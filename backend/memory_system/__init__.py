from __future__ import annotations

__all__ = [
    "ConversationMemorySnapshot",
    "ConversationMemoryStoreAdapter",
    "DurableMemoryLayer",
    "DurableMemoryType",
    "FormalMemoryCollection",
    "FormalMemoryReadLog",
    "FormalMemoryRecord",
    "FormalMemoryRecordVersion",
    "FormalMemoryRepository",
    "FormalMemoryService",
    "FormalMemoryStore",
    "FormalMemoryTransaction",
    "LongTermMemoryRecord",
    "LongTermMemoryStoreAdapter",
    "MemoryNote",
    "MemoryCommitRecord",
    "MemoryCompactionResult",
    "MemoryContextCandidate",
    "MemoryFacade",
    "MemoryHeader",
    "MemoryMaintenanceReceipt",
    "MemoryMaintenanceRequest",
    "MemoryMaintenanceResult",
    "MemoryRequest",
    "MemoryRuntimeView",
    "MemoryScopePolicy",
    "MemoryBundle",
    "MemoryBundleService",
    "Message",
    "MemoryRequestService",
    "MemoryWriteCandidate",
    "WorkingMemoryHandoffTransaction",
    "WorkingMemoryItem",
    "WorkingMemoryPolicyProfile",
    "WorkingMemoryQuery",
    "WorkingMemoryReadLog",
    "WorkingMemoryPolicyDenied",
    "WorkingMemoryService",
    "WorkingMemoryStore",
    "WorkingMemoryTemporalEdge",
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
    "TurnUnderstanding",
    "build_memory_compaction_result",
    "build_memory_bundle",
    "build_memory_request",
    "build_memory_runtime_view",
    "build_memory_scope_policy",
    "format_memory_manifest",
    "load_memory_header",
    "load_static_context",
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
    if name in {"DurableMemoryLayer"}:
        from .durable import DurableMemoryLayer

        return DurableMemoryLayer
    if name in {"MemoryBundleService"}:
        from .bundle_service import MemoryBundleService

        return MemoryBundleService
    if name in {
        "FormalMemoryCollection",
        "FormalMemoryReadLog",
        "FormalMemoryRecord",
        "FormalMemoryRecordVersion",
        "FormalMemoryRepository",
        "FormalMemoryTransaction",
    }:
        from .formal_memory_models import (
            FormalMemoryCollection,
            FormalMemoryReadLog,
            FormalMemoryRecord,
            FormalMemoryRecordVersion,
            FormalMemoryRepository,
            FormalMemoryTransaction,
        )

        return {
            "FormalMemoryCollection": FormalMemoryCollection,
            "FormalMemoryReadLog": FormalMemoryReadLog,
            "FormalMemoryRecord": FormalMemoryRecord,
            "FormalMemoryRecordVersion": FormalMemoryRecordVersion,
            "FormalMemoryRepository": FormalMemoryRepository,
            "FormalMemoryTransaction": FormalMemoryTransaction,
        }[name]
    if name in {"FormalMemoryService"}:
        from .formal_memory_service import FormalMemoryService

        return FormalMemoryService
    if name in {"FormalMemoryStore"}:
        from .formal_memory_store import FormalMemoryStore

        return FormalMemoryStore
    if name in {"MemoryFacade"}:
        from .facade import MemoryFacade

        return MemoryFacade
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
    if name in {
        "MemoryMaintenanceReceipt",
        "MemoryMaintenanceRequest",
        "MemoryMaintenanceResult",
    }:
        from .maintenance_agent import MemoryMaintenanceAgent
        from .maintenance_coordinator import MemoryMaintenanceCoordinator
        from .maintenance_models import MemoryMaintenanceReceipt, MemoryMaintenanceRequest, MemoryMaintenanceResult

        return {
            "MemoryMaintenanceReceipt": MemoryMaintenanceReceipt,
            "MemoryMaintenanceRequest": MemoryMaintenanceRequest,
            "MemoryMaintenanceResult": MemoryMaintenanceResult,
        }[name]
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
        from .compat_types import (
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
    if name in {"MemoryRequestService"}:
        from .request_service import MemoryRequestService

        return MemoryRequestService
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
        "build_memory_request",
        "build_memory_scope_policy",
        "build_memory_bundle",
    }:
        from .supply import (
            MemoryBundle,
            MemoryRequest,
            MemoryScopePolicy,
            build_memory_bundle,
            build_memory_request,
            build_memory_scope_policy,
        )

        return {
            "MemoryRequest": MemoryRequest,
            "MemoryScopePolicy": MemoryScopePolicy,
            "MemoryBundle": MemoryBundle,
            "build_memory_request": build_memory_request,
            "build_memory_scope_policy": build_memory_scope_policy,
            "build_memory_bundle": build_memory_bundle,
        }[name]
    if name in {"SessionMemoryLayer"}:
        from .session import SessionMemoryLayer

        return SessionMemoryLayer
    if name in {"StateMemoryStoreAdapter"}:
        from .state_memory import StateMemoryStoreAdapter

        return StateMemoryStoreAdapter
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
    raise AttributeError(f"module 'memory_system' has no attribute {name!r}")
