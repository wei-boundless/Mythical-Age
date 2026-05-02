from __future__ import annotations

from typing import Any


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


def __getattr__(name: str) -> Any:
    if name == "AnswerAssembler":
        from output_boundary.answer_assembler import AnswerAssembler

        return AnswerAssembler
    if name in {"AnswerAssemblyPlan", "AnswerSegment", "StyleConstraints"}:
        from output_boundary.answer_models import AnswerAssemblyPlan, AnswerSegment, StyleConstraints

        return {
            "AnswerAssemblyPlan": AnswerAssemblyPlan,
            "AnswerSegment": AnswerSegment,
            "StyleConstraints": StyleConstraints,
        }[name]
    if name in {
        "RAGEvidenceItem",
        "RAGEvidencePack",
        "answer_looks_like_snippet_dump",
        "build_rag_answer_finalization_messages",
        "build_rag_evidence_pack",
        "normalize_finalized_answer",
    }:
        from output_boundary.answer_finalizer import (
            RAGEvidenceItem,
            RAGEvidencePack,
            answer_looks_like_snippet_dump,
            build_rag_answer_finalization_messages,
            build_rag_evidence_pack,
            normalize_finalized_answer,
        )

        return {
            "RAGEvidenceItem": RAGEvidenceItem,
            "RAGEvidencePack": RAGEvidencePack,
            "answer_looks_like_snippet_dump": answer_looks_like_snippet_dump,
            "build_rag_answer_finalization_messages": build_rag_answer_finalization_messages,
            "build_rag_evidence_pack": build_rag_evidence_pack,
            "normalize_finalized_answer": normalize_finalized_answer,
        }[name]
    if name in {
        "AssistantOutputBoundary",
        "contains_inline_pseudo_tool_call",
        "contains_internal_protocol",
        "sanitize_visible_assistant_content",
    }:
        from output_boundary.boundary import (
            AssistantOutputBoundary,
            contains_inline_pseudo_tool_call,
            contains_internal_protocol,
            sanitize_visible_assistant_content,
        )

        return {
            "AssistantOutputBoundary": AssistantOutputBoundary,
            "contains_inline_pseudo_tool_call": contains_inline_pseudo_tool_call,
            "contains_internal_protocol": contains_internal_protocol,
            "sanitize_visible_assistant_content": sanitize_visible_assistant_content,
        }[name]
    if name in {
        "build_output_decision",
        "classify_output_candidate",
        "looks_like_procedural_promise_text",
        "looks_like_progress_text",
        "looks_like_tool_claim_without_receipt",
    }:
        from output_boundary.classifier import (
            build_output_decision,
            classify_output_candidate,
            looks_like_procedural_promise_text,
            looks_like_progress_text,
            looks_like_tool_claim_without_receipt,
        )

        return {
            "build_output_decision": build_output_decision,
            "classify_output_candidate": classify_output_candidate,
            "looks_like_procedural_promise_text": looks_like_procedural_promise_text,
            "looks_like_progress_text": looks_like_progress_text,
            "looks_like_tool_claim_without_receipt": looks_like_tool_claim_without_receipt,
        }[name]
    if name in {"OutputCandidate", "OutputDecision", "ToolResultEnvelope"}:
        from output_boundary.models import OutputCandidate, OutputDecision, ToolResultEnvelope

        return {
            "OutputCandidate": OutputCandidate,
            "OutputDecision": OutputDecision,
            "ToolResultEnvelope": ToolResultEnvelope,
        }[name]
    if name == "build_tool_result_envelope":
        from output_boundary.tool_output_adapter import build_tool_result_envelope

        return build_tool_result_envelope
    raise AttributeError(name)
