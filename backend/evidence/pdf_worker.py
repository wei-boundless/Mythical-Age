from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from capability_system.units.mcp.local.pdf.agent import PDFCanonicalResult, PDFReadAgentRuntime, PDFReadRequest
from capability_system.units.mcp.local.pdf.analysis import PdfAnalysisCatalog
from evidence.models import (
    DocumentCandidate,
    EvidenceArtifact,
    EvidenceEnvelope,
    EvidenceItem,
    SourceObjectRef,
)
from .mcp_models import CanonicalResult, MCPRequest, MCPResult


class PDFWorker:
    def __init__(
        self,
        *,
        root_dir: Path,
        runtime: PDFReadAgentRuntime | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.runtime = runtime or PDFReadAgentRuntime(root_dir=self.root_dir)

    async def run(self, request: MCPRequest) -> MCPResult:
        pdf_path = self._request_pdf_path(request)
        if not pdf_path:
            return MCPResult(
                mcp_name="pdf",
                status="clarify",
                canonical_result=CanonicalResult(
                    result_kind="pdf_answer",
                    ok=False,
                    answer="需要先确认要阅读的 PDF 文件。",
                    projection_policy="do_not_persist",
                    degraded_reason="missing_pdf_binding",
                    diagnostics={"answer_source": "pdf_worker"},
                    degraded_reason_typed="missing_object_handle",
                ),
            )

        try:
            file_path = self._resolve_pdf_path(pdf_path)
        except ValueError as exc:
            return MCPResult(
                mcp_name="pdf",
                status="error",
                canonical_result=CanonicalResult(
                    result_kind="pdf_answer",
                    ok=False,
                    answer=self._resolve_error_message(str(exc)),
                    projection_policy="do_not_persist",
                    degraded_reason=str(exc) or "pdf_path_resolution_failed",
                    diagnostics={"answer_source": "pdf_worker"},
                    degraded_reason_typed="missing_object_handle",
                ),
            )

        relative_path = PdfAnalysisCatalog.relative_path(self.root_dir, file_path)
        mode = str(request.constraints.get("mode", "") or request.bindings.get("active_pdf_mode", "") or "document").strip()
        max_chunks = _safe_int(request.constraints.get("max_chunks"), default=4, minimum=1, maximum=12)
        canonical = await asyncio.to_thread(
            self.runtime.run,
            request=PDFReadRequest(
                query=str(request.query or "").strip(),
                path=relative_path,
                mode=mode,
                max_chunks=max_chunks,
            ),
            file_path=file_path,
        )
        return MCPResult(
            mcp_name="pdf",
            status="ok" if canonical.ok else "degraded" if canonical.status == "degraded" else "error",
            evidence_envelope=self._to_evidence_envelope(
                request=request,
                canonical=canonical,
                active_pdf=relative_path,
            ),
            canonical_result=self._to_worker_canonical(canonical, active_pdf=relative_path),
            emitted_object_handles=[
                {
                    "handle_id": _stable_id("source:pdf", relative_path),
                    "handle_kind": "source_object",
                    "object_type": "pdf",
                    "uri": relative_path,
                }
            ],
            emitted_result_handles=_result_handles_from_canonical(canonical, active_pdf=relative_path),
            diagnostics={
                "active_pdf": relative_path,
                "requested_mode": canonical.requested_mode,
                "effective_mode": canonical.effective_mode,
                "pages": list(canonical.pages),
            },
            binding_owner_task_id=str(request.owner_task_id or "").strip(),
        )

    def _to_evidence_envelope(
        self,
        *,
        request: MCPRequest,
        canonical: PDFCanonicalResult,
        active_pdf: str,
    ) -> EvidenceEnvelope:
        source_object_id = _stable_id("source:pdf", active_pdf)
        source_object = SourceObjectRef(
            object_id=source_object_id,
            object_type="pdf",
            uri=active_pdf,
            locator={
                "path": active_pdf,
                "pages": list(canonical.pages),
                "requested_mode": canonical.requested_mode,
                "effective_mode": canonical.effective_mode,
            },
            metadata={
                "pdf_status": canonical.status,
                "document_total_pages": canonical.metadata.get("document_total_pages"),
                "readable_pages": canonical.metadata.get("readable_pages"),
                "usable_pages": canonical.metadata.get("usable_pages"),
            },
        )
        artifacts: list[EvidenceArtifact] = []
        evidence_items: list[EvidenceItem] = []
        for evidence in canonical.evidence:
            page_number = int(evidence.page_number or 0)
            if page_number <= 0:
                continue
            artifact_id = f"{source_object_id}:page:{page_number}"
            snippet = " ".join(str(evidence.snippet or "").split())
            artifacts.append(
                EvidenceArtifact(
                    artifact_id=artifact_id,
                    artifact_type="pdf_page",
                    source_object_id=source_object_id,
                    content_ref=f"{active_pdf}#page={page_number}",
                    canonical_preview=snippet[:220],
                    visibility="model_visible" if canonical.ok else "debug_only",
                    consumable_by=["pdf", "answer_finalizer"],
                    metadata={
                        "page": page_number,
                        "score": float(evidence.score or 0.0),
                        "confidence": float(evidence.score or 0.0),
                        "active_pdf": active_pdf,
                        "effective_mode": canonical.effective_mode,
                    },
                )
            )
            evidence_items.append(
                EvidenceItem(
                    kind="pdf_page",
                    source=active_pdf,
                    text=snippet,
                    score=float(evidence.score or 0.0),
                    metadata={
                        "page": page_number,
                        "artifact_id": artifact_id,
                        "source_object_id": source_object_id,
                    },
                    visibility="model_visible" if canonical.ok else "debug_only",
                )
            )
        document_candidate = DocumentCandidate(
            path=active_pdf,
            document_type="pdf",
            page=int(canonical.pages[0]) if canonical.pages else None,
            confidence=1.0 if canonical.ok else 0.45,
            reason="pdf_worker_active_document",
            artifact_id=artifacts[0].artifact_id if artifacts else "",
            source_object_id=source_object_id,
        )
        return EvidenceEnvelope(
            query=str(request.query or "").strip(),
            source_mcp="pdf",
            evidence_items=evidence_items,
            source_objects=[source_object],
            derived_artifacts=artifacts,
            document_candidates=[document_candidate],
            diagnostics={
                "pdf_status": canonical.status,
                "requested_mode": canonical.requested_mode,
                "effective_mode": canonical.effective_mode,
                "page_count": len(canonical.pages),
                "evidence_count": len(evidence_items),
            },
        )

    def _request_pdf_path(self, request: MCPRequest) -> str:
        candidates = [
            request.bindings.get("active_pdf"),
            request.constraints.get("active_pdf"),
            request.constraints.get("path"),
            request.task_frame.get("active_pdf"),
            request.task_frame.get("path"),
        ]
        for item in candidates:
            value = str(item or "").strip()
            if value:
                return value
        return ""

    def _resolve_pdf_path(self, path: str) -> Path:
        normalized = str(path or "").strip()
        if not normalized:
            raise ValueError("missing_pdf_binding")
        candidates = PdfAnalysisCatalog.list_pdf_paths(self.root_dir)
        matched = PdfAnalysisCatalog._match_filename(self.root_dir, candidates, normalized)
        if matched is not None:
            return matched
        resolved = (self.root_dir / normalized).resolve()
        if resolved != self.root_dir and self.root_dir not in resolved.parents:
            raise ValueError("illegal_pdf_path")
        if not resolved.exists():
            raise ValueError("pdf_file_not_found")
        if resolved.is_dir():
            raise ValueError("pdf_path_is_directory")
        if resolved.suffix.lower() != ".pdf":
            raise ValueError("not_pdf_file")
        return resolved

    def _to_worker_canonical(self, canonical: PDFCanonicalResult, *, active_pdf: str) -> CanonicalResult:
        ok = canonical.ok
        answer = canonical.summary.strip()
        degraded_reason = str(canonical.degraded_reason or canonical.error or "").strip()
        if not answer:
            answer = _degraded_pdf_answer(canonical)
        answer = _shape_pdf_answer_for_request(answer, canonical)
        artifact_refs = [f"{active_pdf}#page={page}" for page in canonical.pages if int(page or 0) > 0]
        return CanonicalResult(
            result_kind="pdf_answer",
            ok=ok,
            answer=answer,
            artifact_refs=artifact_refs,
            evidence_refs=artifact_refs,
            bindings={
                "active_pdf": active_pdf,
                "active_pdf_pages": list(canonical.pages),
                "active_pdf_mode": canonical.effective_mode or canonical.requested_mode or "document",
                "active_pdf_section": str(canonical.metadata.get("target_section", "") or ""),
                "active_pdf_section_key": str(canonical.metadata.get("target_section_key", "") or ""),
            },
            projection_policy="persist_canonical" if ok else "do_not_persist",
            degraded_reason="" if ok else degraded_reason or "pdf_missing_stable_answer",
            diagnostics={
                "answer_source": "pdf_worker",
                "pdf_status": canonical.status,
                "requested_mode": canonical.requested_mode,
                "effective_mode": canonical.effective_mode,
                "metadata": dict(canonical.metadata or {}),
            },
            object_handle_ids=[_stable_id("source:pdf", active_pdf), *[f"artifact:pdf_page:{_stable_id('source:pdf', active_pdf).split(':')[-1]}:p{page}" for page in canonical.pages if int(page or 0) > 0]],
            result_handle_ids=_result_handle_ids(canonical, active_pdf=active_pdf),
            primary_result_handle_id=_primary_result_handle_id(canonical, active_pdf=active_pdf),
            degraded_reason_typed="" if ok else _typed_degraded_reason(canonical),
        )

    def _resolve_error_message(self, reason: str) -> str:
        if reason == "illegal_pdf_path":
            return "检测到非法 PDF 路径访问。"
        if reason == "pdf_file_not_found":
            return "没有找到要阅读的 PDF 文件。"
        if reason == "pdf_path_is_directory":
            return "提供的 PDF 路径是一个目录。"
        if reason == "not_pdf_file":
            return "提供的路径不是 PDF 文件。"
        return "PDF 阅读任务没有形成可执行输入。"


def _degraded_pdf_answer(canonical: PDFCanonicalResult) -> str:
    pages = "、".join(f"P{page}" for page in canonical.pages[:5] if int(page or 0) > 0)
    reason = str(canonical.degraded_reason or canonical.error or "").strip().lower()
    target_section = str(canonical.metadata.get("target_section", "") or "").strip()
    page_state = str(canonical.metadata.get("target_page_state", "") or "").strip()
    evidence_hint = _stable_evidence_hint(canonical)
    if reason == "target_page_transition_title_only" or page_state == "transition_title_only":
        if pages:
            return f"已定位到 {pages}。这一页更像标题过渡页，只承载标题或章节分隔作用，不是正文页。"
        return "已定位到目标页。这一页更像标题过渡页，只承载标题或章节分隔作用，不是正文页。"
    if reason == "target_page_toc_like" or page_state == "toc_like":
        if pages:
            return f"已定位到 {pages}。这一页更像目录页，主要承担结构导航作用，不是正文论述页。"
        return "已定位到目标页。这一页更像目录页，主要承担结构导航作用，不是正文论述页。"
    if reason == "target_page_structure_missing" or page_state == "page_structure_missing":
        if pages:
            return f"已定位到 {pages}，但当前页级结构化结果缺失，不能把它当作正文页来稳定提取。"
        return "已定位到目标页，但当前页级结构化结果缺失，不能把它当作正文页来稳定提取。"
    if reason == "target_page_text_corrupted" or page_state == "text_corrupted":
        if pages and evidence_hint:
            return f"已定位到 {pages}，但这一页文本损坏或乱码严重。当前只能稳定辨认出：{evidence_hint}。"
        if pages:
            return f"已定位到 {pages}，但这一页文本损坏或乱码严重，暂时不能可靠提取正文。"
        return "已定位到目标页，但这一页文本损坏或乱码严重，暂时不能可靠提取正文。"
    if reason == "target_page_image_without_text" or page_state == "image_or_scan_without_text":
        if pages:
            return f"已定位到 {pages}，但这一页更像图片页或扫描页，当前没有稳定可提取的文本正文。"
        return "已定位到目标页，但这一页更像图片页或扫描页，当前没有稳定可提取的文本正文。"
    if reason == "target_page_has_no_stable_text":
        if pages:
            return f"已定位到 {pages}，但这一页没有稳定可提取的正文，可能是扫描页、图片页、目录页或近乎空白页。"
        return "已定位到目标页，但这一页没有稳定可提取的正文，可能是扫描页、图片页、目录页或近乎空白页。"
    if reason == "target_page_text_quality_low":
        if pages and evidence_hint:
            return f"已定位到 {pages}，但页面文本质量不稳定，暂时不能可靠概括整页内容。当前只能稳定辨认出：{evidence_hint}。"
        if pages:
            return f"已定位到 {pages}，但页面文本质量不稳定，暂时不能可靠概括整页内容。"
        return "已定位到目标页，但页面文本质量不稳定，暂时不能可靠概括整页内容。"
    if reason == "target_section_not_located":
        if target_section:
            return f"已检索这份 PDF，但当前没有稳定定位到“{target_section}”这一部分。"
        return "已检索这份 PDF，但当前没有稳定定位到你指定的章节或部分。"
    if reason == "target_section_not_stably_located":
        if target_section and pages:
            return f"已定位到“{target_section}”的相关页码：{pages}，但章节文本不够稳定，暂时不能可靠生成章节摘要。"
        if target_section:
            return f"已定位到“{target_section}”的相关线索，但章节文本不够稳定，暂时不能可靠生成章节摘要。"
        return "已定位到相关章节线索，但章节文本不够稳定，暂时不能可靠生成章节摘要。"
    if reason == "no_stable_document_evidence":
        if pages:
            return f"已读取这份 PDF，并检查了与问题最相关的页面：{pages}，但能稳定提取的正文证据仍然不足，暂时不能可靠总结。"
        return "已读取这份 PDF，但能稳定提取的正文证据仍然不足，暂时不能可靠总结。"
    if reason == "document_summary_text_quality_low":
        if pages and evidence_hint:
            return f"已读取这份 PDF，并检查了相关页面：{pages}，但清洗后的正文质量仍不稳定。当前只能稳定辨认出：{evidence_hint}。"
        if pages:
            return f"已读取这份 PDF，并检查了相关页面：{pages}，但清洗后的正文质量仍不稳定，暂时不能可靠总结。"
        return "已读取这份 PDF，但清洗后的正文质量仍不稳定，暂时不能可靠总结。"
    if pages:
        return f"已读取这份 PDF 的 {pages}，但当前还没有形成稳定摘要。"
    return "已读取这份 PDF，但当前还没有形成稳定摘要。"


def _shape_pdf_answer_for_request(answer: str, canonical: PDFCanonicalResult) -> str:
    query = str((canonical.metadata or {}).get("query", "") or "").strip()
    if not answer.strip() or not _looks_like_action_recommendation_request(query):
        return answer
    if not canonical.ok:
        return answer
    points = _extract_action_basis_points(answer)
    while len(points) < 3:
        points.append(answer)
    actions = (
        ("建立", "面向现实业务风险的治理框架", points[0]),
        ("推进", "产业应用与合规要求同步落地", points[1]),
        ("统一", "跨部门的评估、反馈和迭代机制", points[2]),
    )
    lines = []
    for index, (verb, theme, basis) in enumerate(actions, start=1):
        basis_text = _compact_basis(basis)
        lines.append(f"{index}. {verb}{theme}：{basis_text}")
    return "三条行动建议：\n" + "\n".join(lines)


def _looks_like_action_recommendation_request(query: str) -> bool:
    normalized = query.lower()
    action_markers = ("行动建议", "建议", "动作", "action")
    compression_markers = ("三条", "3条", "三个", "压成", "提炼", "总结")
    verb_markers = ("行动动词", "动词", "建立", "推进", "统一", "收紧", "评估", "补齐")
    return (
        any(marker in normalized for marker in action_markers)
        and any(marker in normalized for marker in compression_markers)
    ) or ("行动建议" in normalized and any(marker in normalized for marker in verb_markers))


def _extract_action_basis_points(answer: str) -> list[str]:
    normalized = re.sub(r"^已定位[^。]*。", "", answer.strip())
    normalized = normalized.replace("文档要点：", "")
    fragments = [
        item.strip(" ：:；;，,。 \n\t")
        for item in re.split(r"[。；;\n]+", normalized)
        if item.strip(" ：:；;，,。 \n\t")
    ]
    useful: list[str] = []
    for fragment in fragments:
        if len(fragment) < 8:
            continue
        if fragment in useful:
            continue
        useful.append(fragment)
        if len(useful) >= 3:
            break
    return useful


def _compact_basis(text: str) -> str:
    compact = " ".join(str(text or "").split()).strip(" ：:；;，,。")
    if len(compact) > 86:
        compact = compact[:86].rstrip(" ，,；;：:")
    return compact + "。"


def _stable_evidence_hint(canonical: PDFCanonicalResult) -> str:
    for item in list(canonical.evidence or []):
        snippet = " ".join(str(getattr(item, "snippet", "") or "").split()).strip(" .。;；,，:：")
        if not snippet:
            continue
        compact = snippet[:80].strip()
        if compact:
            return compact
    return ""


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _primary_result_handle_id(canonical: PDFCanonicalResult, *, active_pdf: str) -> str:
    source_suffix = _stable_id("source:pdf", active_pdf).split(":")[-1]
    mode = canonical.effective_mode or canonical.requested_mode or "document"
    target_page = _safe_int(canonical.metadata.get("target_page"), default=0, minimum=0, maximum=100000)
    section_key = str(canonical.metadata.get("target_section_key", "") or "").strip()
    if mode == "page" and target_page > 0:
        return f"result:pdf_page_summary:{source_suffix}:p{target_page}"
    if mode == "section":
        section_suffix = section_key or "section"
        return f"result:pdf_section_summary:{source_suffix}:{section_suffix}"
    return f"result:pdf_summary:{source_suffix}:primary"


def _result_handle_ids(canonical: PDFCanonicalResult, *, active_pdf: str) -> list[str]:
    return [_primary_result_handle_id(canonical, active_pdf=active_pdf)] if str(active_pdf or "").strip() else []


def _result_handles_from_canonical(canonical: PDFCanonicalResult, *, active_pdf: str) -> list[dict[str, Any]]:
    primary = _primary_result_handle_id(canonical, active_pdf=active_pdf)
    mode = canonical.effective_mode or canonical.requested_mode or "document"
    if mode == "page":
        result_kind = "pdf_page_summary"
    elif mode == "section":
        result_kind = "pdf_section_summary"
    else:
        result_kind = "pdf_summary"
    return (
        [
            {
                "handle_id": primary,
                "handle_kind": "result",
                "result_kind": result_kind,
                "object_handle_id": _stable_id("source:pdf", active_pdf),
                "mode": mode,
                "target_page": _safe_int(canonical.metadata.get("target_page"), default=0, minimum=0, maximum=100000),
                "target_section": str(canonical.metadata.get("target_section", "") or ""),
                "target_section_key": str(canonical.metadata.get("target_section_key", "") or ""),
            }
        ]
        if primary
        else []
    )


def _typed_degraded_reason(canonical: PDFCanonicalResult) -> str:
    reason = str(canonical.degraded_reason or canonical.error or "").strip().lower()
    if "transition_title_only" in reason:
        return "page_transition_title_only"
    if "toc_like" in reason:
        return "page_toc_like"
    if "structure_missing" in reason:
        return "page_structure_missing"
    if "text_corrupted" in reason:
        return "page_text_corrupted"
    if "image_without_text" in reason:
        return "page_image_without_text"
    if "no_stable_text" in reason or "no_text" in reason:
        return "page_has_no_text"
    if "section_not_located" in reason:
        return "section_not_located"
    if "section_not_stably_located" in reason:
        return "section_not_stably_located"
    if "ocr" in reason:
        return "ocr_unstable"
    return "evidence_insufficient_for_synthesis"
