__all__ = [
    "DurableAdmissionPolicy",
    "DurableAdmissionDecision",
    "DurableCandidateDraft",
    "DurableMemoryType",
    "DurableMemoryLayer",
    "DurableExtractionBundle",
    "DurableMutationPlanner",
    "DurableMutationPlan",
    "DurableStoreWriter",
    "DurableWriteExtractorAgent",
    "MemoryHeader",
    "MemoryContextLayer",
    "MemoryFacade",
    "MemoryMessageAdapter",
    "MemoryReadAgent",
    "MemoryRecallRequest",
    "MemoryRecallResult",
    "MemoryRecallSelection",
    "SessionMemoryLayer",
    "StaticContextBundle",
    "StaticContextSection",
    "format_memory_manifest",
    "load_static_context",
    "scan_memory_headers",
]


def __getattr__(name: str):
    if name == "DurableAdmissionPolicy":
        from memory.admission_policy import DurableAdmissionPolicy

        return DurableAdmissionPolicy
    if name in {"MemoryHeader", "format_memory_manifest", "scan_memory_headers"}:
        from memory.manifest_scan import MemoryHeader, format_memory_manifest, scan_memory_headers

        return {
            "MemoryHeader": MemoryHeader,
            "format_memory_manifest": format_memory_manifest,
            "scan_memory_headers": scan_memory_headers,
        }[name]
    if name in {"DurableMutationPlanner"}:
        from memory.mutation_planner import DurableMutationPlanner

        return DurableMutationPlanner
    if name in {"MemoryReadAgent"}:
        from memory.read_agent import MemoryReadAgent

        return MemoryReadAgent
    if name in {"MemoryRecallRequest", "MemoryRecallResult", "MemoryRecallSelection"}:
        from memory.read_models import MemoryRecallRequest, MemoryRecallResult, MemoryRecallSelection

        return {
            "MemoryRecallRequest": MemoryRecallRequest,
            "MemoryRecallResult": MemoryRecallResult,
            "MemoryRecallSelection": MemoryRecallSelection,
        }[name]
    if name in {"MemoryContextLayer"}:
        from memory.context import MemoryContextLayer

        return MemoryContextLayer
    if name in {"DurableMemoryLayer"}:
        from memory.durable import DurableMemoryLayer

        return DurableMemoryLayer
    if name in {"MemoryFacade"}:
        from memory.facade import MemoryFacade

        return MemoryFacade
    if name in {"MemoryMessageAdapter"}:
        from memory.messages import MemoryMessageAdapter

        return MemoryMessageAdapter
    if name in {"DurableMemoryType", "StaticContextBundle", "StaticContextSection"}:
        from memory.models import DurableMemoryType, StaticContextBundle, StaticContextSection

        return {
            "DurableMemoryType": DurableMemoryType,
            "StaticContextBundle": StaticContextBundle,
            "StaticContextSection": StaticContextSection,
        }[name]
    if name in {"SessionMemoryLayer"}:
        from memory.session import SessionMemoryLayer

        return SessionMemoryLayer
    if name in {"load_static_context"}:
        from memory.static_loader import load_static_context

        return load_static_context
    if name in {
        "DurableAdmissionDecision",
        "DurableCandidateDraft",
        "DurableExtractionBundle",
        "DurableMutationPlan",
    }:
        from memory.write_models import (
            DurableAdmissionDecision,
            DurableCandidateDraft,
            DurableExtractionBundle,
            DurableMutationPlan,
        )

        return {
            "DurableAdmissionDecision": DurableAdmissionDecision,
            "DurableCandidateDraft": DurableCandidateDraft,
            "DurableExtractionBundle": DurableExtractionBundle,
            "DurableMutationPlan": DurableMutationPlan,
        }[name]
    if name in {"DurableStoreWriter"}:
        from memory.store_writer import DurableStoreWriter

        return DurableStoreWriter
    if name in {"DurableWriteExtractorAgent"}:
        from memory.write_agent import DurableWriteExtractorAgent

        return DurableWriteExtractorAgent
    raise AttributeError(f"module 'memory' has no attribute {name!r}")
