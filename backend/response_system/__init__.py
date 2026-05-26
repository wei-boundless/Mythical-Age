from __future__ import annotations

from response_system.assembly.answer_assembler import AnswerAssembler
from response_system.boundary.boundary import (
    AssistantOutputBoundary,
    contains_inline_pseudo_tool_call,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from response_system.classification.classifier import (
    build_output_decision,
    classify_output_candidate,
    looks_like_procedural_promise_text,
    looks_like_progress_text,
    looks_like_tool_claim_without_receipt,
)
from response_system.finalization.answer_finalizer import (
    RAGEvidenceItem,
    RAGEvidencePack,
    answer_looks_like_snippet_dump,
    build_rag_answer_finalization_messages,
    build_rag_evidence_pack,
    normalize_finalized_answer,
)
from response_system.models.answer_models import AnswerAssemblyPlan, AnswerSegment, StyleConstraints
from response_system.models.output_models import OutputCandidate, OutputDecision, ToolResultEnvelope

__all__ = [
    "AnswerAssembler",
    "AnswerAssemblyPlan",
    "AnswerSegment",
    "AssistantOutputBoundary",
    "OutputCandidate",
    "OutputDecision",
    "RAGEvidenceItem",
    "RAGEvidencePack",
    "StyleConstraints",
    "ToolResultEnvelope",
    "answer_looks_like_snippet_dump",
    "build_output_decision",
    "build_rag_answer_finalization_messages",
    "build_rag_evidence_pack",
    "build_tool_result_envelope",
    "classify_output_candidate",
    "contains_inline_pseudo_tool_call",
    "contains_internal_protocol",
    "looks_like_procedural_promise_text",
    "looks_like_progress_text",
    "looks_like_tool_claim_without_receipt",
    "normalize_finalized_answer",
    "sanitize_visible_assistant_content",
]


def build_tool_result_envelope(*args, **kwargs):
    from response_system.tool_outputs.tool_output_adapter import build_tool_result_envelope as _build_tool_result_envelope

    return _build_tool_result_envelope(*args, **kwargs)
