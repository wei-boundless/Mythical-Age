from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from execution.model_runtime import ModelRuntimeError, stringify_content
from output_boundary import (
    answer_looks_like_snippet_dump,
    build_rag_answer_finalization_messages,
    normalize_finalized_answer,
)


@dataclass(frozen=True, slots=True)
class RAGAnswerFinalizationResult:
    status: Literal["finalized", "skipped", "error"]
    answer: str = ""
    degraded_reason_typed: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class RAGEvidenceOutputPolicy:
    """Model-backed answer finalization for evidence-first retrieval."""

    def __init__(self, *, model_runtime) -> None:
        self.model_runtime = model_runtime

    def rag_evidence_pack_can_finalize(self, evidence_pack) -> bool:
        return bool(evidence_pack is not None and list(getattr(evidence_pack, "items", []) or []))

    async def rewrite_rag_answer_with_model(self, *, evidence_pack) -> RAGAnswerFinalizationResult:
        if not self.rag_evidence_pack_can_finalize(evidence_pack):
            return RAGAnswerFinalizationResult(
                status="skipped",
                degraded_reason_typed="missing_evidence_pack",
                diagnostics={"stage": "precondition"},
            )
        messages = build_rag_answer_finalization_messages(evidence_pack=evidence_pack)
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError as exc:
            return RAGAnswerFinalizationResult(
                status="error",
                degraded_reason_typed="rag_finalizer_model_error",
                diagnostics={
                    "stage": "model_invoke",
                    "error_type": exc.code,
                    "provider": exc.provider,
                    "model": exc.model,
                    "detail": exc.detail,
                    "retryable": exc.retryable,
                },
            )
        except Exception as exc:
            return RAGAnswerFinalizationResult(
                status="error",
                degraded_reason_typed="rag_finalizer_runtime_error",
                diagnostics={
                    "stage": "model_invoke",
                    "error_type": exc.__class__.__name__,
                    "detail": str(exc),
                },
            )
        content = normalize_finalized_answer(stringify_content(getattr(response, "content", response)))
        if not content:
            return RAGAnswerFinalizationResult(
                status="skipped",
                degraded_reason_typed="rag_finalizer_empty_output",
                diagnostics={"stage": "normalize_output"},
            )
        if answer_looks_like_snippet_dump(content, evidence_pack):
            return RAGAnswerFinalizationResult(
                status="skipped",
                degraded_reason_typed="rag_finalizer_snippet_dump",
                diagnostics={"stage": "quality_gate"},
            )
        return RAGAnswerFinalizationResult(
            status="finalized",
            answer=content,
            diagnostics={"stage": "completed"},
        )
