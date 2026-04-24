from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any, Callable

from pdf_agent import PDFCanonicalResult
from query.answer_finalizer import (
    RAGEvidencePack,
    answer_looks_like_snippet_dump,
    build_rag_answer_finalization_messages,
    build_rag_evidence_pack,
    normalize_finalized_answer,
    total_compact_chars,
)
from query.models import QueryExecutionPlan
from query.output_boundary import (
    AssistantOutputResponse,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from query.output_classifier import looks_like_progress_text
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content

logger = logging.getLogger(__name__)


class RuntimeOutputPolicy:
    def __init__(
        self,
        *,
        model_runtime: ModelRuntime,
        stringify_tool_output: Callable[[Any], str],
    ) -> None:
        self.model_runtime = model_runtime
        self._stringify_tool_output = stringify_tool_output

    async def maybe_finalize_rag_output(
        self,
        *,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None,
        output_response: AssistantOutputResponse,
    ) -> AssistantOutputResponse:
        if str(execution.query_understanding.route or "") != "rag":
            return output_response
        if str(getattr(output_response, "finalization_policy", "none") or "none") != "route_required":
            return output_response
        fallback_reason = str(getattr(output_response, "fallback_reason", "") or "")
        preserve_no_receipt_fallback = fallback_reason in {"no_receipt_tool_claim", "no_receipt_query_promise"}
        evidence_pack = build_rag_evidence_pack(
            user_query=execution.message,
            retrieval_results=retrieval_results,
            max_items=3,
        )
        if not self.rag_evidence_pack_can_finalize(evidence_pack):
            return output_response if preserve_no_receipt_fallback else self.fallback_rag_output_response(output_response)
        finalized = await self.rewrite_rag_answer_with_model(evidence_pack=evidence_pack)
        if not finalized:
            return self.fallback_rag_output_response(output_response)
        return replace(
            output_response,
            canonical_answer=finalized,
            selected_channel="answer_candidate",
            selected_source="rag_answer_finalization",
            canonical_state="stable_answer",
            persist_policy="persist_canonical",
            finalization_policy="none",
            fallback_reason="",
        )

    async def rewrite_rag_answer_with_model(
        self,
        *,
        evidence_pack: RAGEvidencePack,
    ) -> str:
        messages = build_rag_answer_finalization_messages(evidence_pack=evidence_pack)
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError:
            return ""
        except Exception:
            logger.exception("RAG answer finalization failed")
            return ""
        content = normalize_finalized_answer(stringify_content(getattr(response, "content", response)))
        if (
            not content
            or contains_internal_protocol(content)
            or self.looks_like_rag_procedural_answer(content)
            or answer_looks_like_snippet_dump(content, evidence_pack)
        ):
            return ""
        return content

    def rag_evidence_pack_can_finalize(self, evidence_pack: RAGEvidencePack | None) -> bool:
        if evidence_pack is None:
            return False
        if len(list(evidence_pack.items or [])) < 2:
            return False
        return total_compact_chars(evidence_pack) >= 60

    def fallback_rag_output_response(self, output_response: AssistantOutputResponse) -> AssistantOutputResponse:
        return replace(
            output_response,
            canonical_answer="已检索到相关资料，但当前模型尚未产出可直接展示的结论。",
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="route_required",
            fallback_reason="rag_missing_answer",
        )

    def maybe_gate_memory_output(
        self,
        *,
        execution: QueryExecutionPlan,
        output_response: AssistantOutputResponse,
    ) -> AssistantOutputResponse:
        if str(execution.query_understanding.route or "") != "memory":
            return output_response
        if str(getattr(output_response, "selected_channel", "") or "") == "fallback_answer":
            return output_response
        if str(getattr(output_response, "canonical_state", "") or "") == "progress_only":
            return self.fallback_memory_output_response(output_response)
        if not self.memory_output_needs_gate(output_response):
            return output_response
        return self.fallback_memory_output_response(output_response)

    def memory_output_needs_gate(self, output_response: AssistantOutputResponse) -> bool:
        selected_source = str(getattr(output_response, "selected_source", "") or "")
        if not selected_source.startswith("segment."):
            return False
        answer = sanitize_visible_assistant_content(
            str(getattr(output_response, "canonical_answer", "") or "")
        ).strip()
        if not answer:
            return False
        if looks_like_progress_text(answer):
            return True
        leak_flags = {str(flag or "").strip() for flag in list(getattr(output_response, "leak_flags", []) or [])}
        if not leak_flags:
            return False
        compact = re.sub(r"\s+", "", answer)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in answer
            for token in (
                "检查",
                "查看",
                "读取",
                "分析",
                "确认",
                "整理",
                "梳理",
                "回顾",
                "回忆",
                "目录结构",
                "知识库",
            )
        )

    def fallback_memory_output_response(self, output_response: AssistantOutputResponse) -> AssistantOutputResponse:
        return replace(
            output_response,
            canonical_answer="当前没有足够稳定的会话内容可直接回答这个问题。",
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason="memory_visible_pollution",
        )

    async def maybe_finalize_pdf_output(
        self,
        *,
        execution: QueryExecutionPlan,
        output_response: AssistantOutputResponse,
    ) -> AssistantOutputResponse:
        canonical = self.extract_pdf_canonical_from_output_response(output_response)
        if canonical is None:
            return output_response
        if str(getattr(output_response, "finalization_policy", "none") or "none") != "route_required":
            return output_response
        if not self.pdf_canonical_can_finalize(canonical):
            return self.fallback_pdf_output_response(output_response, canonical)
        finalized = await self.rewrite_pdf_answer_with_model(
            user_query=execution.message,
            canonical=canonical,
        )
        if not finalized:
            return self.fallback_pdf_output_response(output_response, canonical)
        return replace(
            output_response,
            canonical_answer=finalized,
            selected_channel="answer_candidate",
            selected_source="pdf_answer_finalization",
            canonical_state="stable_answer",
            persist_policy="persist_canonical",
            finalization_policy="none",
            fallback_reason="",
        )

    def extract_pdf_canonical_from_output_response(
        self, output_response: AssistantOutputResponse
    ) -> PDFCanonicalResult | None:
        for item in reversed(list(getattr(output_response, "tool_calls", []) or [])):
            if str(item.get("tool", "") or "") != "pdf_analysis":
                continue
            output = str(item.get("output", "") or "").strip()
            if not output:
                continue
            canonical = PDFCanonicalResult.from_tool_output(output)
            if canonical is not None:
                return canonical
        return None

    def pdf_canonical_can_finalize(self, canonical: PDFCanonicalResult) -> bool:
        if canonical.ok and canonical.summary.strip():
            return True
        return self.pdf_canonical_has_finalizable_evidence(canonical)

    def fallback_pdf_output_response(
        self,
        output_response: AssistantOutputResponse,
        canonical: PDFCanonicalResult,
    ) -> AssistantOutputResponse:
        pages = [int(page) for page in list(canonical.pages or []) if int(page) > 0][:3]
        selected = "、".join(f"P{page}" for page in pages)
        degraded_reason = str(canonical.degraded_reason or "").strip()
        if degraded_reason == "target_page_has_no_stable_text" and selected:
            message = f"已定位到 {selected}，但这一页没有稳定可提取的正文，可能是扫描页、图片页、目录页或空白页。"
            reason = "pdf_target_page_has_no_stable_text"
        elif degraded_reason == "target_page_text_quality_low" and selected:
            message = f"已定位到 {selected}，但页面文本质量不稳定，当前无法可靠给出页级结论。"
            reason = "pdf_target_page_text_quality_low"
        elif degraded_reason == "target_section_not_located":
            message = "已检索这份 PDF，但当前没有稳定定位到你指定的章节或部分。"
            reason = "pdf_target_section_not_located"
        elif degraded_reason == "target_section_not_stably_located":
            message = "已定位到相关章节线索，但章节文本不够稳定，当前无法可靠生成章节摘要。"
            reason = "pdf_target_section_not_stably_located"
        elif degraded_reason == "no_stable_document_evidence":
            message = "已读取这份 PDF，但当前提取到的正文证据不足，暂时不能稳定生成文档结论。"
            reason = "pdf_no_stable_document_evidence"
        elif degraded_reason == "document_summary_text_quality_low":
            message = "已读取这份 PDF，但正文清洗后的文本质量不够稳定，暂时不能可靠总结全文。"
            reason = "pdf_document_summary_text_quality_low"
        elif pages:
            message = f"已读取与当前问题最相关的 PDF 页面：{selected}，但当前还没有形成稳定摘要。"
            reason = "pdf_canonical_missing_summary"
        else:
            message = "已读取这份 PDF，但当前工具尚未形成可直接展示的摘要。"
            reason = "pdf_missing_summary"
        return replace(
            output_response,
            canonical_answer=message,
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="route_required",
            fallback_reason=reason,
        )

    def looks_like_rag_procedural_answer(self, answer: str) -> bool:
        normalized = sanitize_visible_assistant_content(str(answer or "")).strip()
        if not normalized:
            return False
        normalized = re.sub(r"^(?:岩[，,\s]*)+", "", normalized).strip()
        if not normalized:
            return False
        if looks_like_progress_text(normalized):
            return True
        compact = re.sub(r"\s+", "", normalized)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in normalized
            for token in (
                "检索",
                "搜索",
                "查看",
                "检查",
                "读取",
                "分析",
                "确认",
                "整理",
                "改写",
                "根据这些证据",
                "整理答案",
            )
        )

    def looks_like_pdf_procedural_answer(self, answer: str) -> bool:
        normalized = sanitize_visible_assistant_content(str(answer or "")).strip()
        if not normalized:
            return False
        normalized = re.sub(r"^(?:岩[，,\s]*)+", "", normalized).strip()
        if not normalized:
            return False
        if looks_like_progress_text(normalized):
            return True
        compact = re.sub(r"\s+", "", normalized)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in normalized
            for token in (
                "PDF",
                "页面",
                "页",
                "文档",
                "章节",
                "读取",
                "查看",
                "分析",
                "整理",
                "提炼",
                "总结",
            )
        )

    def build_pdf_answer_finalization_messages(
        self,
        *,
        user_query: str,
        canonical: PDFCanonicalResult,
    ) -> list[dict[str, str]]:
        source = str(canonical.source or "当前PDF").strip()
        page_marks = [f"P{int(page)}" for page in list(canonical.pages or []) if int(page) > 0][:6]
        evidence_lines: list[str] = []
        for item in list(canonical.evidence or [])[:4]:
            snippet = " ".join(str(item.snippet or "").split()).strip()
            if not snippet:
                continue
            evidence_lines.append(f"- P{int(item.page_number)}: {snippet[:220]}")
        evidence_block = "\n".join(evidence_lines) if evidence_lines else "- 无额外证据片段"
        page_block = "、".join(page_marks) if page_marks else "未标注"
        summary = canonical.summary.strip()
        degraded_reason = str(canonical.degraded_reason or "").strip()
        system_prompt = (
            "你负责把已经清洗过的 PDF 阅读结果改写成对用户可直接展示的最终回答。"
            "只能依据提供的摘要和证据回答，不要编造，不要输出内部协议、工具名、canonical、evidence 等词。"
            "不要大段摘抄原文；优先直接回应用户任务。"
            "如果用户要求总结、行动建议、解释或对比，请按该任务形态组织答案。"
            "如果提供的页面看起来主要是封面、题名页、目录、版权页或其他非正文，请直接说明这一点，不要硬编正文结论。"
        )
        user_prompt = (
            f"用户问题：{user_query.strip()}\n"
            f"PDF：{source}\n"
            f"相关页面：{page_block}\n"
            f"稳定摘要：{summary or '无'}\n"
            f"当前状态：{canonical.status}\n"
            f"降级原因：{degraded_reason or '无'}\n"
            f"证据片段：\n{evidence_block}\n\n"
            "请直接回答用户，不要解释你的处理过程。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def rewrite_pdf_answer_with_model(
        self,
        *,
        user_query: str,
        canonical: PDFCanonicalResult,
    ) -> str:
        messages = self.build_pdf_answer_finalization_messages(
            user_query=user_query,
            canonical=canonical,
        )
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError:
            return ""
        except Exception:
            logger.exception("PDF answer finalization failed")
            return ""
        content = sanitize_visible_assistant_content(
            stringify_content(getattr(response, "content", response))
        ).strip()
        if (
            not content
            or contains_internal_protocol(content)
            or self.looks_like_pdf_procedural_answer(content)
            or (canonical.summary.strip() and content == canonical.summary.strip())
        ):
            return ""
        return content

    def pdf_tool_result_can_use_model_finalization(self, raw_output: Any, tool_decision: Any) -> bool:
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        if canonical is None:
            return False
        if canonical.ok:
            return True
        return self.pdf_canonical_has_finalizable_evidence(canonical)

    def pdf_canonical_has_finalizable_evidence(self, canonical: PDFCanonicalResult) -> bool:
        if (
            str(canonical.effective_mode or "") == "page"
            and str(canonical.degraded_reason or "") == "target_page_has_no_stable_text"
        ):
            return False
        for item in list(canonical.evidence or [])[:4]:
            snippet = sanitize_visible_assistant_content(str(item.snippet or "")).strip()
            compact = re.sub(r"\s+", "", snippet)
            if len(compact) >= 8:
                return True
        return False

    def pdf_tool_decision_is_persistable(self, raw_output: Any, tool_decision: Any) -> bool:
        if tool_decision is None or str(getattr(tool_decision, "selected_channel", "") or "") == "fallback_answer":
            return False
        canonical = PDFCanonicalResult.from_tool_output(self._stringify_tool_output(raw_output))
        return canonical is not None and canonical.ok

    def merge_summary_key_points(
        self,
        existing: list[str],
        *,
        pdf_path: str = "",
        page: int | None = None,
        pdf_mode: str = "",
        pdf_section: str = "",
        pdf_pages: list[int] | None = None,
        readable_pages: int | None = None,
        usable_pages: int | None = None,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()

        def add(item: str) -> None:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            merged.append(normalized)

        for item in existing:
            add(str(item or ""))
        if page is not None:
            add(f"page={page}")
        if pdf_mode:
            add(f"pdf_mode={pdf_mode}")
        if pdf_section:
            add(f"pdf_section={pdf_section}")
        normalized_pages = [int(page_item) for page_item in list(pdf_pages or []) if int(page_item) > 0]
        if normalized_pages:
            add("pdf_pages=" + ",".join(str(page_item) for page_item in normalized_pages))
        if readable_pages is not None:
            add(f"readable_pages={readable_pages}")
        if usable_pages is not None:
            add(f"usable_pages={usable_pages}")
        if pdf_path:
            add(f"pdf={pdf_path}")
        return merged

    def pdf_task_kind_from_mode(self, mode: str) -> str:
        normalized = self.normalize_pdf_scope(str(mode or ""))
        if normalized == "page":
            return "document_page"
        if normalized == "section":
            return "document_section"
        return "document_read"

    def normalize_pdf_scope(self, mode: str) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized in {"page", "page-read", "page_read"}:
            return "page"
        if normalized in {"section", "section-read", "section_read"}:
            return "section"
        return "document"
