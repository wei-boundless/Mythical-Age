from __future__ import annotations

__all__ = [
    "ConversationMemorySnapshot",
    "ConversationMemoryStoreAdapter",
    "DurableAdmissionDecision",
    "DurableAdmissionPolicy",
    "DurableCandidateDraft",
    "DurableExtractionBundle",
    "DurableMemoryLayer",
    "DurableMemoryType",
    "DurableMutationPlan",
    "DurableMutationPlanner",
    "DurableStoreWriter",
    "DurableWriteExtractorAgent",
    "LongTermMemoryRecord",
    "LongTermMemoryStoreAdapter",
    "MemoryNote",
    "MemoryCommitRecord",
    "MemoryCompactionResult",
    "MemoryContextCandidate",
    "MemoryFacade",
    "MemoryGateDecision",
    "MemoryGovernance",
    "MemoryHeader",
    "MemoryMessageAdapter",
    "MemoryReadAgent",
    "MemoryRecallRequest",
    "MemoryRecallResult",
    "MemoryRecallSelection",
    "MemoryRequest",
    "MemoryRuntimeView",
    "MemoryScopePolicy",
    "MemoryBundle",
    "MemoryBundleService",
    "Message",
    "MemoryWritebackProposal",
    "MemoryRequestService",
    "MemoryWritebackBuilderService",
    "MemoryWriteCandidate",
    "MemoryWritebackService",
    "WorkingMemoryHandoffTransaction",
    "WorkingMemoryItem",
    "WorkingMemoryPolicyProfile",
    "WorkingMemoryQuery",
    "WorkingMemoryReadLog",
    "WorkingMemoryPolicyDenied",
    "WorkingMemoryService",
    "WorkingMemoryStore",
    "WorkingMemoryTemporalEdge",
    "DurableMemoryGovernanceService",
    "SessionMemoryLayer",
    "StateMemoryFileRef",
    "StateMemoryRestoreCandidate",
    "StateMemorySnapshot",
    "StateMemoryStoreAdapter",
    "StaticContextBundle",
    "StaticContextEntry",
    "StaticContextSection",
    "ContextSlots",
    "FlowState",
    "ProcessState",
    "SessionMemoryManager",
    "TaskState",
    "TaskDurableMemoryItem",
    "TaskDurableMemoryNamespace",
    "TaskDurableMemoryQuery",
    "TaskDurableMemoryService",
    "TaskDurableMemoryStore",
    "TurnUnderstanding",
    "build_blocked_memory_gate",
    "build_memory_compaction_result",
    "build_memory_bundle",
    "build_memory_request",
    "build_memory_runtime_view",
    "build_memory_scope_policy",
    "build_memory_writeback_proposal",
    "format_memory_manifest",
    "load_memory_header",
    "load_static_context",
    "normalize_memory_write_statement",
    "scan_memory_headers",
    "utc_now_iso",
]


def __getattr__(name: str):
    if name in {
        "ConversationMemorySnapshot",
        "LongTermMemoryRecord",
        "MemoryCommitRecord",
        "MemoryContextCandidate",
        "MemoryWriteCandidate",
        "StateMemoryFileRef",
        "StateMemoryRestoreCandidate",
        "StateMemorySnapshot",
    }:
        from .contracts import (
            ConversationMemorySnapshot,
            LongTermMemoryRecord,
            MemoryCommitRecord,
            MemoryContextCandidate,
            MemoryWriteCandidate,
            StateMemoryFileRef,
            StateMemoryRestoreCandidate,
            StateMemorySnapshot,
        )

        return {
            "ConversationMemorySnapshot": ConversationMemorySnapshot,
            "LongTermMemoryRecord": LongTermMemoryRecord,
            "MemoryCommitRecord": MemoryCommitRecord,
            "MemoryContextCandidate": MemoryContextCandidate,
            "MemoryWriteCandidate": MemoryWriteCandidate,
            "StateMemoryFileRef": StateMemoryFileRef,
            "StateMemoryRestoreCandidate": StateMemoryRestoreCandidate,
            "StateMemorySnapshot": StateMemorySnapshot,
        }[name]
    if name == "ConversationMemoryStoreAdapter":
        from .conversation_memory import ConversationMemoryStoreAdapter

        return ConversationMemoryStoreAdapter
    if name in {"MemoryCompactionResult", "build_memory_compaction_result"}:
        from .compaction import MemoryCompactionResult, build_memory_compaction_result

        return {
            "MemoryCompactionResult": MemoryCompactionResult,
            "build_memory_compaction_result": build_memory_compaction_result,
        }[name]
    if name in {"DurableAdmissionPolicy"}:
        from .admission_policy import DurableAdmissionPolicy

        return DurableAdmissionPolicy
    if name in {"DurableMemoryLayer"}:
        from .durable import DurableMemoryLayer

        return DurableMemoryLayer
    if name in {"MemoryBundleService"}:
        from .bundle_service import MemoryBundleService

        return MemoryBundleService
    if name in {"DurableMemoryGovernanceService"}:
        from .governance_service import DurableMemoryGovernanceService

        return DurableMemoryGovernanceService
    if name in {"MemoryFacade"}:
        from .facade import MemoryFacade

        return MemoryFacade
    if name in {"MemoryGateDecision", "build_blocked_memory_gate"}:
        from .gate import MemoryGateDecision, build_blocked_memory_gate

        return {
            "MemoryGateDecision": MemoryGateDecision,
            "build_blocked_memory_gate": build_blocked_memory_gate,
        }[name]
    if name in {"MemoryGovernance"}:
        from .governance import MemoryGovernance

        return MemoryGovernance
    if name in {"LongTermMemoryStoreAdapter"}:
        from .long_term_memory import LongTermMemoryStoreAdapter

        return LongTermMemoryStoreAdapter
    if name in {"MemoryHeader", "format_memory_manifest", "load_memory_header", "scan_memory_headers"}:
        from .manifest_scan import MemoryHeader, format_memory_manifest, load_memory_header, scan_memory_headers

        return {
            "MemoryHeader": MemoryHeader,
            "format_memory_manifest": format_memory_manifest,
            "load_memory_header": load_memory_header,
            "scan_memory_headers": scan_memory_headers,
        }[name]
    if name in {"MemoryMessageAdapter"}:
        from .messages import MemoryMessageAdapter

        return MemoryMessageAdapter
    if name in {
        "ContextSlots",
        "FlowState",
        "MemoryNote",
        "Message",
        "ProcessState",
        "SessionMemoryManager",
        "TaskState",
        "TurnUnderstanding",
        "utc_now_iso",
    }:
        from .legacy_types import (
            ContextSlots,
            FlowState,
            MemoryNote,
            Message,
            ProcessState,
            SessionMemoryManager,
            TaskState,
            TurnUnderstanding,
            utc_now_iso,
        )

        return {
            "ContextSlots": ContextSlots,
            "FlowState": FlowState,
            "MemoryNote": MemoryNote,
            "Message": Message,
            "ProcessState": ProcessState,
            "SessionMemoryManager": SessionMemoryManager,
            "TaskState": TaskState,
            "TurnUnderstanding": TurnUnderstanding,
            "utc_now_iso": utc_now_iso,
        }[name]
    if name in {"DurableMemoryType", "StaticContextBundle", "StaticContextEntry", "StaticContextSection"}:
        from .models import DurableMemoryType, StaticContextBundle, StaticContextEntry, StaticContextSection

        return {
            "DurableMemoryType": DurableMemoryType,
            "StaticContextBundle": StaticContextBundle,
            "StaticContextEntry": StaticContextEntry,
            "StaticContextSection": StaticContextSection,
        }[name]
    if name in {"DurableMutationPlanner"}:
        from .mutation_planner import DurableMutationPlanner

        return DurableMutationPlanner
    if name in {"MemoryReadAgent"}:
        from .read_agent import MemoryReadAgent

        return MemoryReadAgent
    if name in {"MemoryRequestService"}:
        from .request_service import MemoryRequestService

        return MemoryRequestService
    if name in {"MemoryRecallRequest", "MemoryRecallResult", "MemoryRecallSelection"}:
        from .read_models import MemoryRecallRequest, MemoryRecallResult, MemoryRecallSelection

        return {
            "MemoryRecallRequest": MemoryRecallRequest,
            "MemoryRecallResult": MemoryRecallResult,
            "MemoryRecallSelection": MemoryRecallSelection,
        }[name]
    if name in {"MemoryRuntimeView", "build_memory_runtime_view"}:
        from .runtime_view import MemoryRuntimeView, build_memory_runtime_view

        return {
            "MemoryRuntimeView": MemoryRuntimeView,
            "build_memory_runtime_view": build_memory_runtime_view,
        }[name]
    if name in {
        "MemoryRequest",
        "MemoryScopePolicy",
        "MemoryBundle",
        "MemoryWritebackProposal",
        "build_memory_request",
        "build_memory_scope_policy",
        "build_memory_bundle",
        "build_memory_writeback_proposal",
    }:
        from .supply import (
            MemoryBundle,
            MemoryRequest,
            MemoryScopePolicy,
            MemoryWritebackProposal,
            build_memory_bundle,
            build_memory_request,
            build_memory_scope_policy,
            build_memory_writeback_proposal,
        )

        return {
            "MemoryRequest": MemoryRequest,
            "MemoryScopePolicy": MemoryScopePolicy,
            "MemoryBundle": MemoryBundle,
            "MemoryWritebackProposal": MemoryWritebackProposal,
            "build_memory_request": build_memory_request,
            "build_memory_scope_policy": build_memory_scope_policy,
            "build_memory_bundle": build_memory_bundle,
            "build_memory_writeback_proposal": build_memory_writeback_proposal,
        }[name]
    if name in {"SessionMemoryLayer"}:
        from .session import SessionMemoryLayer

        return SessionMemoryLayer
    if name in {"StateMemoryStoreAdapter"}:
        from .state_memory import StateMemoryStoreAdapter

        return StateMemoryStoreAdapter
    if name in {"TaskDurableMemoryItem", "TaskDurableMemoryNamespace", "TaskDurableMemoryQuery"}:
        from .task_durable_memory_models import (
            TaskDurableMemoryItem,
            TaskDurableMemoryNamespace,
            TaskDurableMemoryQuery,
        )

        return {
            "TaskDurableMemoryItem": TaskDurableMemoryItem,
            "TaskDurableMemoryNamespace": TaskDurableMemoryNamespace,
            "TaskDurableMemoryQuery": TaskDurableMemoryQuery,
        }[name]
    if name in {"TaskDurableMemoryService"}:
        from .task_durable_memory_service import TaskDurableMemoryService

        return TaskDurableMemoryService
    if name in {"TaskDurableMemoryStore"}:
        from .task_durable_memory_store import TaskDurableMemoryStore

        return TaskDurableMemoryStore
    if name in {
        "WorkingMemoryHandoffTransaction",
        "WorkingMemoryItem",
        "WorkingMemoryPolicyProfile",
        "WorkingMemoryQuery",
        "WorkingMemoryReadLog",
        "WorkingMemoryTemporalEdge",
    }:
        from .working_memory_models import (
            WorkingMemoryHandoffTransaction,
            WorkingMemoryItem,
            WorkingMemoryPolicyProfile,
            WorkingMemoryQuery,
            WorkingMemoryReadLog,
            WorkingMemoryTemporalEdge,
        )

        return {
            "WorkingMemoryHandoffTransaction": WorkingMemoryHandoffTransaction,
            "WorkingMemoryItem": WorkingMemoryItem,
            "WorkingMemoryPolicyProfile": WorkingMemoryPolicyProfile,
            "WorkingMemoryQuery": WorkingMemoryQuery,
            "WorkingMemoryReadLog": WorkingMemoryReadLog,
            "WorkingMemoryTemporalEdge": WorkingMemoryTemporalEdge,
        }[name]
    if name in {"WorkingMemoryPolicyDenied", "WorkingMemoryService"}:
        from .working_memory_service import WorkingMemoryPolicyDenied, WorkingMemoryService

        return {"WorkingMemoryPolicyDenied": WorkingMemoryPolicyDenied, "WorkingMemoryService": WorkingMemoryService}[name]
    if name in {"WorkingMemoryFinalizer", "WorkingMemoryFinalizationResult"}:
        from .working_memory_finalizer import WorkingMemoryFinalizationResult, WorkingMemoryFinalizer

        return {
            "WorkingMemoryFinalizer": WorkingMemoryFinalizer,
            "WorkingMemoryFinalizationResult": WorkingMemoryFinalizationResult,
        }[name]
    if name in {"WorkingMemoryStore"}:
        from .working_memory_store import WorkingMemoryStore

        return WorkingMemoryStore
    if name in {"load_static_context"}:
        from .static_loader import load_static_context

        return load_static_context
    if name in {"DurableStoreWriter"}:
        from .store_writer import DurableStoreWriter

        return DurableStoreWriter
    if name in {"DurableWriteExtractorAgent"}:
        from .write_agent import DurableWriteExtractorAgent

        return DurableWriteExtractorAgent
    if name in {
        "DurableAdmissionDecision",
        "DurableCandidateDraft",
        "DurableExtractionBundle",
        "DurableMutationPlan",
    }:
        from .write_models import (
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
    if name in {"MemoryWritebackService", "normalize_memory_write_statement"}:
        from .writeback import MemoryWritebackService, normalize_memory_write_statement

        return {
            "MemoryWritebackService": MemoryWritebackService,
            "normalize_memory_write_statement": normalize_memory_write_statement,
        }[name]
    if name in {"MemoryWritebackBuilderService"}:
        from .writeback_service import MemoryWritebackBuilderService

        return MemoryWritebackBuilderService
    raise AttributeError(f"module 'memory_system' has no attribute {name!r}")
