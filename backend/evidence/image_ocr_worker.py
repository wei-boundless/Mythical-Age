from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import re
from pathlib import Path
from typing import Any

from capability_system.capabilities.attachments import SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES
from config import runtime_config
from evidence.models import BindingCandidate, EvidenceArtifact, EvidenceEnvelope, EvidenceItem, SourceObjectRef
from .mcp_models import CanonicalResult, MCPRequest, MCPResult


class ImageOCRWorker:
    def __init__(self, *, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir).resolve()
        self._engine: Any | None = None

    async def run(self, request: MCPRequest) -> MCPResult:
        path = _request_attachment_path(request)
        if not path:
            return _error_result("missing_attachment_binding", "No image attachment path was provided.")

        config = runtime_config.get_image_ocr_config()
        timeout_seconds = int(config.get("timeout_seconds") or 60)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(self._extract_text, path, config=config, constraints=dict(request.constraints or {})),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return _error_result("image_ocr_timeout", "Image OCR timed out.")
        except _ImageOCRError as exc:
            return _error_result(exc.code, str(exc), diagnostics=exc.to_dict())

        text = str(payload["text"]).strip()
        relative_path = str(payload["path"])
        source_object_id = _stable_id("source:image_attachment", relative_path)
        artifact_id = f"{source_object_id}:ocr_text"
        result_handle_id = f"result:image_ocr_text:{source_object_id.rsplit(':', 1)[-1]}:primary"
        ok = bool(text)
        artifact = EvidenceArtifact(
            artifact_id=artifact_id,
            artifact_type="ocr_text",
            source_object_id=source_object_id,
            content_ref=f"{relative_path}#ocr",
            canonical_preview=text[:220],
            visibility="model_visible" if ok else "debug_only",
            consumable_by=["image_ocr", "answer_finalizer"],
            metadata={
                "provider": payload["provider"],
                "language": payload["language"],
                "text_chars": len(text),
                "limitations": list(payload["limitations"]),
            },
        )
        envelope = EvidenceEnvelope(
            query=str(request.query or "").strip(),
            source_mcp="image_ocr",
            evidence_items=[
                EvidenceItem(
                    kind="ocr_text",
                    source=relative_path,
                    text=text,
                    score=float(payload.get("confidence") or 0.0),
                    metadata={"artifact_id": artifact_id, "source_object_id": source_object_id},
                    visibility="model_visible",
                )
            ] if ok else [],
            source_objects=[
                SourceObjectRef(
                    object_id=source_object_id,
                    object_type="image_attachment",
                    uri=relative_path,
                    locator={"path": relative_path},
                    metadata={"size_bytes": payload["size_bytes"], "provider": payload["provider"]},
                )
            ],
            derived_artifacts=[artifact],
            answer_candidates=[text] if ok else [],
            diagnostics={"limitations": list(payload["limitations"]), "line_count": len(payload["lines"])},
        )
        canonical = CanonicalResult(
            result_kind="image_ocr_text",
            ok=ok,
            answer=text,
            evidence_refs=[artifact_id] if ok else [],
            artifact_refs=[artifact_id],
            bindings={"active_attachment": relative_path},
            projection_policy="persist_canonical" if ok else "do_not_persist",
            degraded_reason="" if ok else "ocr_returned_no_text",
            diagnostics={
                "answer_source": "image_ocr_worker",
                "provider": payload["provider"],
                "language": payload["language"],
                "limitations": list(payload["limitations"]),
            },
            object_handle_ids=[source_object_id],
            result_handle_ids=[result_handle_id],
            primary_result_handle_id=result_handle_id,
            degraded_reason_typed="" if ok else "ocr_returned_no_text",
        )
        return MCPResult(
            mcp_name="image_ocr",
            status="ok" if ok else "degraded",
            evidence_envelope=envelope,
            artifact_updates=[artifact],
            canonical_result=canonical,
            binding_candidates=[
                BindingCandidate(
                    candidate_id=f"cand:attachment:{source_object_id.rsplit(':', 1)[-1]}",
                    kind="attachment",
                    identity=relative_path,
                    display_label=relative_path,
                    source_mcp="image_ocr",
                    artifact_id=artifact_id,
                    confidence=1.0 if ok else 0.2,
                    evidence_refs=[artifact_id],
                )
            ],
            emitted_object_handles=[
                {
                    "handle_id": source_object_id,
                    "handle_kind": "source_object",
                    "object_type": "image_attachment",
                    "uri": relative_path,
                }
            ],
            emitted_result_handles=[
                {
                    "handle_id": result_handle_id,
                    "handle_kind": "result",
                    "result_kind": "image_ocr_text",
                    "object_handle_id": source_object_id,
                    "artifact_id": artifact_id,
                }
            ],
            diagnostics={"payload": payload},
            binding_owner_task_id=str(request.owner_task_id or "").strip(),
        )

    def _extract_text(self, path: str, *, config: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        if not bool(config.get("enabled", True)):
            raise _ImageOCRError("Image OCR is disabled by runtime configuration.", code="image_ocr_disabled")
        provider = str(config.get("provider") or "rapidocr").strip().lower()
        if provider != "rapidocr":
            raise _ImageOCRError(f"Unsupported image OCR provider: {provider}", code="unsupported_image_ocr_provider")
        file_path = _resolve_attachment_path(self.root_dir, path)
        if file_path.suffix.lower() not in SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES:
            raise _ImageOCRError("Unsupported attachment image suffix.", code="unsupported_attachment_suffix")
        if not file_path.is_file():
            raise _ImageOCRError("Attachment file does not exist.", code="attachment_not_found")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            output = self._rapidocr()(str(file_path))
        lines = _ocr_lines(output)
        scores = _ocr_scores(output)
        text = _normalize_ocr_text("\n".join(lines))
        max_chars = _max_text_chars(constraints.get("max_text_chars") or config.get("max_text_chars"))
        limitations: list[str] = []
        if len(text) > max_chars:
            text = text[:max_chars]
            limitations.append("ocr_text_truncated")
        if not text:
            limitations.append("ocr_returned_no_text")
        return {
            "path": file_path.relative_to(self.root_dir).as_posix(),
            "provider": provider,
            "language": str(constraints.get("language") or config.get("default_language") or "chi_sim+eng"),
            "text": text,
            "lines": lines,
            "confidence": _average_score(scores),
            "size_bytes": file_path.stat().st_size,
            "limitations": limitations,
        }

    def _rapidocr(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import RapidOCR  # type: ignore
            except ImportError as exc:
                raise _ImageOCRError("RapidOCR is not installed.", code="rapidocr_unavailable") from exc
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self._engine = RapidOCR()
        return self._engine


def _request_attachment_path(request: MCPRequest) -> str:
    for value in (
        request.bindings.get("active_attachment"),
        request.constraints.get("path"),
        request.constraints.get("attachment_path"),
        request.target_handle_id,
    ):
        text = str(value or "").replace("\\", "/").strip()
        if text:
            return text
    return ""


def _resolve_attachment_path(root_dir: Path, path: str) -> Path:
    raw = Path(str(path or "").replace("\\", "/").strip())
    file_path = raw.resolve() if raw.is_absolute() else (root_dir / raw).resolve()
    try:
        file_path.relative_to(root_dir)
    except ValueError as exc:
        raise _ImageOCRError("Attachment path traversal detected.", code="attachment_path_traversal") from exc
    return file_path


def _error_result(code: str, message: str, *, diagnostics: dict[str, Any] | None = None) -> MCPResult:
    return MCPResult(
        mcp_name="image_ocr",
        status="error",
        canonical_result=CanonicalResult(
            result_kind="image_ocr_text",
            ok=False,
            answer="",
            projection_policy="do_not_persist",
            degraded_reason=message,
            diagnostics={"answer_source": "image_ocr_worker", **dict(diagnostics or {})},
            degraded_reason_typed=code,
        ),
        diagnostics={"structured_error": {"code": code, "message": message, **dict(diagnostics or {})}},
    )


def _ocr_lines(output: Any) -> list[str]:
    direct = getattr(output, "txts", None)
    if direct is not None:
        return [str(item or "").strip() for item in tuple(direct or ()) if str(item or "").strip()]
    lines: list[str] = []
    for item in list(output or []):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = str(item[1] or "").strip()
            if text:
                lines.append(text)
    return lines


def _ocr_scores(output: Any) -> list[float]:
    direct = getattr(output, "scores", None)
    if direct is not None:
        return [float(item or 0.0) for item in tuple(direct or ())]
    scores: list[float] = []
    for item in list(output or []):
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            try:
                scores.append(float(item[2] or 0.0))
            except (TypeError, ValueError):
                continue
    return scores


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _normalize_ocr_text(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _max_text_chars(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 12_000
    return max(1, min(parsed, 120_000))


def _average_score(scores: list[float]) -> float | None:
    values = [float(item) for item in scores if float(item or 0.0) > 0]
    return sum(values) / len(values) if values else None


class _ImageOCRError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}
