from __future__ import annotations

from execution.model_runtime import ModelRuntimeError, stringify_content
from output_boundary import (
    answer_looks_like_snippet_dump,
    build_rag_answer_finalization_messages,
    normalize_finalized_answer,
)


class RAGEvidenceOutputPolicy:
    """Model-backed answer finalization for evidence-first retrieval."""

    def __init__(self, *, model_runtime) -> None:
        self.model_runtime = model_runtime

    def rag_evidence_pack_can_finalize(self, evidence_pack) -> bool:
        return bool(evidence_pack is not None and list(getattr(evidence_pack, "items", []) or []))

    async def rewrite_rag_answer_with_model(self, *, evidence_pack) -> str:
        if not self.rag_evidence_pack_can_finalize(evidence_pack):
            return ""
        messages = build_rag_answer_finalization_messages(evidence_pack=evidence_pack)
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError:
            return ""
        except Exception:
            return ""
        content = normalize_finalized_answer(stringify_content(getattr(response, "content", response)))
        if not content:
            return ""
        if answer_looks_like_snippet_dump(content, evidence_pack):
            return ""
        return content
