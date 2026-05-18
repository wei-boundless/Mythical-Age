from __future__ import annotations

__all__ = [
    "ConsolidationConfig",
    "ConsolidationReport",
    "ConsolidationScheduler",
    "DialogueState",
    "DialogueStateManager",
    "DialogueTurn",
    "DurableMemoryConsolidator",
    "ExactMemoryMatch",
    "FlowSnapshot",
    "FlowSnapshotManager",
    "MemoryManager",
    "MemoryNote",
    "Message",
    "ProcessState",
    "ProcessStateEngine",
    "ProcessStateManager",
    "ReconciledTurnUnderstanding",
    "ReconciliationDecision",
    "SessionMemoryManager",
    "SessionUnderstandingProcessor",
    "TurnUnderstandingAnalyzer",
    "TurnUnderstandingSnapshot",
    "UnderstandingReconciler",
    "ActiveUnderstanding",
    "find_exact_memory_matches",
    "format_frontmatter",
    "parse_frontmatter",
]


def __getattr__(name: str):
    if name in {"ConsolidationConfig", "ConsolidationScheduler"}:
        from .consolidation_scheduler import ConsolidationConfig, ConsolidationScheduler

        return {
            "ConsolidationConfig": ConsolidationConfig,
            "ConsolidationScheduler": ConsolidationScheduler,
        }[name]
    if name in {"ConsolidationReport", "DurableMemoryConsolidator"}:
        from .consolidation import ConsolidationReport, DurableMemoryConsolidator

        return {
            "ConsolidationReport": ConsolidationReport,
            "DurableMemoryConsolidator": DurableMemoryConsolidator,
        }[name]
    if name in {"DialogueState", "DialogueStateManager", "DialogueTurn"}:
        from .process_state import DialogueState, DialogueStateManager, DialogueTurn

        return {
            "DialogueState": DialogueState,
            "DialogueStateManager": DialogueStateManager,
            "DialogueTurn": DialogueTurn,
        }[name]
    if name in {"ExactMemoryMatch", "find_exact_memory_matches"}:
        from .exact_lookup import ExactMemoryMatch, find_exact_memory_matches

        return {
            "ExactMemoryMatch": ExactMemoryMatch,
            "find_exact_memory_matches": find_exact_memory_matches,
        }[name]
    if name in {"FlowSnapshot", "FlowSnapshotManager"}:
        from .flow_snapshots import FlowSnapshot, FlowSnapshotManager

        return {
            "FlowSnapshot": FlowSnapshot,
            "FlowSnapshotManager": FlowSnapshotManager,
        }[name]
    if name in {"format_frontmatter", "parse_frontmatter"}:
        from .frontmatter import format_frontmatter, parse_frontmatter

        return {
            "format_frontmatter": format_frontmatter,
            "parse_frontmatter": parse_frontmatter,
        }[name]
    if name == "MemoryManager":
        from .memory_manager import MemoryManager

        return MemoryManager
    if name in {"Message", "MemoryNote"}:
        from .models import Message, MemoryNote

        return {
            "Message": Message,
            "MemoryNote": MemoryNote,
        }[name]
    if name == "ProcessStateEngine":
        from .process_engine import ProcessStateEngine

        return ProcessStateEngine
    if name in {"ProcessState", "ProcessStateManager"}:
        from .process_state import ProcessState, ProcessStateManager

        return {
            "ProcessState": ProcessState,
            "ProcessStateManager": ProcessStateManager,
        }[name]
    if name == "SessionMemoryManager":
        from .session_memory import SessionMemoryManager

        return SessionMemoryManager
    if name == "SessionUnderstandingProcessor":
        from .session_processor import SessionUnderstandingProcessor

        return SessionUnderstandingProcessor
    if name in {"ActiveUnderstanding", "TurnUnderstandingAnalyzer", "TurnUnderstandingSnapshot"}:
        from .turn_understanding import ActiveUnderstanding, TurnUnderstandingAnalyzer, TurnUnderstandingSnapshot

        return {
            "ActiveUnderstanding": ActiveUnderstanding,
            "TurnUnderstandingAnalyzer": TurnUnderstandingAnalyzer,
            "TurnUnderstandingSnapshot": TurnUnderstandingSnapshot,
        }[name]
    if name in {"ReconciledTurnUnderstanding", "ReconciliationDecision", "UnderstandingReconciler"}:
        from .understanding_reconciliation import (
            ReconciledTurnUnderstanding,
            ReconciliationDecision,
            UnderstandingReconciler,
        )

        return {
            "ReconciledTurnUnderstanding": ReconciledTurnUnderstanding,
            "ReconciliationDecision": ReconciliationDecision,
            "UnderstandingReconciler": UnderstandingReconciler,
        }[name]
    raise AttributeError(f"module 'structured_memory' has no attribute {name!r}")
