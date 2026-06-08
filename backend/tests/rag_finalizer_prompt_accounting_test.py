from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evidence.output_policy import RAGEvidenceOutputPolicy
from runtime.output_boundary import build_rag_evidence_pack


def test_rag_finalizer_uses_scoped_segment_plan() -> None:
    runtime = _CapturingRuntime()
    evidence_pack = build_rag_evidence_pack(
        user_query="项目当前缓存情况如何？",
        retrieval_results=[
            {
                "source": "knowledge/cache.md",
                "text": "DeepSeek prompt cache 在稳定前缀重复时会提高命中率，这段证据用于验证最终回答整理。",
            }
        ],
    )

    result = asyncio.run(
        RAGEvidenceOutputPolicy(model_runtime=runtime).rewrite_rag_answer_with_model(
            evidence_pack=evidence_pack,
        )
    )

    context = runtime.accounting_context
    assert result.status == "finalized"
    assert context["cache_metric_scope"] == "rag_finalizer"
    assert context["call_purpose"] == "utility.rag_answer_finalizer"
    assert context["segment_plan"]["segments"]
    assert context["prompt_manifest"]["cache_metric_scope"] == "rag_finalizer"
    assert context["prompt_manifest"]["primary_prompt_ref"] == "utility.finalizer.rag_answer"
    assert context["prompt_manifest"]["prompt_refs"] == ["utility.finalizer.rag_answer"]
    assert context["segment_plan"]["segments"][0]["source_ref"] == "utility.finalizer.rag_answer"


class _CapturingRuntime:
    def __init__(self) -> None:
        self.accounting_context: dict[str, Any] = {}

    async def invoke_messages(self, _messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.accounting_context = dict(kwargs.get("accounting_context") or {})
        return SimpleNamespace(content="基于当前检索证据，只能确认稳定前缀重复时缓存命中率会提高。")
