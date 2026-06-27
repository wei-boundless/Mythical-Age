from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AssistantOutputBoundary": ("harness.runtime.output_boundary.boundary", "AssistantOutputBoundary"),
    "CanonicalFinalTextDecision": ("harness.runtime.output_boundary.boundary", "CanonicalFinalTextDecision"),
    "OutputCandidate": ("harness.runtime.output_boundary.output_models", "OutputCandidate"),
    "OutputDecision": ("harness.runtime.output_boundary.output_models", "OutputDecision"),
    "RAGEvidenceItem": ("harness.runtime.output_boundary.rag_finalizer", "RAGEvidenceItem"),
    "RAGEvidencePack": ("harness.runtime.output_boundary.rag_finalizer", "RAGEvidencePack"),
    "ToolVisibleOutputEnvelope": ("harness.runtime.output_boundary.output_models", "ToolVisibleOutputEnvelope"),
    "answer_looks_like_snippet_dump": ("harness.runtime.output_boundary.rag_finalizer", "answer_looks_like_snippet_dump"),
    "build_output_decision": ("harness.runtime.output_boundary.classifier", "build_output_decision"),
    "build_rag_answer_finalization_messages": ("harness.runtime.output_boundary.rag_finalizer", "build_rag_answer_finalization_messages"),
    "build_rag_evidence_pack": ("harness.runtime.output_boundary.rag_finalizer", "build_rag_evidence_pack"),
    "canonical_output_decision_for_final_text": ("harness.runtime.output_boundary.boundary", "canonical_output_decision_for_final_text"),
    "classify_output_candidate": ("harness.runtime.output_boundary.classifier", "classify_output_candidate"),
    "contains_inline_pseudo_tool_call": ("harness.runtime.output_boundary.boundary", "contains_inline_pseudo_tool_call"),
    "contains_internal_protocol": ("harness.runtime.output_boundary.boundary", "contains_internal_protocol"),
    "contains_runtime_protocol_disclosure": ("harness.runtime.output_boundary.boundary", "contains_runtime_protocol_disclosure"),
    "could_be_internal_protocol_prefix": ("harness.runtime.output_boundary.boundary", "could_be_internal_protocol_prefix"),
    "looks_like_procedural_promise_text": ("harness.runtime.output_boundary.classifier", "looks_like_procedural_promise_text"),
    "looks_like_progress_text": ("harness.runtime.output_boundary.classifier", "looks_like_progress_text"),
    "looks_like_tool_claim_without_receipt": ("harness.runtime.output_boundary.classifier", "looks_like_tool_claim_without_receipt"),
    "normalize_finalized_answer": ("harness.runtime.output_boundary.rag_finalizer", "normalize_finalized_answer"),
    "sanitize_visible_assistant_content": ("harness.runtime.output_boundary.boundary", "sanitize_visible_assistant_content"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
