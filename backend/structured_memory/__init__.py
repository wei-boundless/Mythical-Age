from __future__ import annotations

from .consolidation import ConsolidationReport, DurableMemoryConsolidator
from .consolidation_scheduler import ConsolidationConfig, ConsolidationScheduler
from .dialogue_state import DialogueState, DialogueStateManager, DialogueTurn
from .exact_lookup import ExactMemoryMatch, find_exact_memory_matches
from .extraction_scheduler import ExtractionConfig, ExtractionScheduler
from .extractor import MemoryExtractor
from .flow_snapshots import FlowSnapshot, FlowSnapshotManager
from .frontmatter import format_frontmatter, parse_frontmatter
from .memory_manager import MemoryManager
from .models import Message, MemoryNote
from .process_engine import ProcessStateEngine
from .process_state import ProcessState, ProcessStateManager
from .session_memory import SessionMemoryManager
from .session_processor import SessionUnderstandingProcessor
from .team_memory import TeamMemoryManager
from .turn_understanding import ActiveUnderstanding, TurnUnderstandingAnalyzer, TurnUnderstandingSnapshot
from .understanding_reconciliation import (
    ReconciledTurnUnderstanding,
    ReconciliationDecision,
    UnderstandingReconciler,
)

__all__ = [
    "CompactResult",
    "ConsolidationConfig",
    "ConsolidationReport",
    "ConsolidationScheduler",
    "ContextCompactor",
    "DialogueState",
    "DialogueStateManager",
    "DialogueTurn",
    "DurableMemoryConsolidator",
    "ExtractionConfig",
    "ExtractionScheduler",
    "ExactMemoryMatch",
    "FlowSnapshot",
    "FlowSnapshotManager",
    "format_frontmatter",
    "find_exact_memory_matches",
    "MemoryExtractor",
    "MemoryManager",
    "MemoryNote",
    "Message",
    "parse_frontmatter",
    "ActiveUnderstanding",
    "ProcessState",
    "ProcessStateEngine",
    "ProcessStateManager",
    "ReconciledTurnUnderstanding",
    "ReconciliationDecision",
    "SessionMemoryManager",
    "SessionUnderstandingProcessor",
    "TeamMemoryManager",
    "TurnUnderstandingAnalyzer",
    "TurnUnderstandingSnapshot",
    "UnderstandingReconciler",
]


def __getattr__(name: str):
    if name in {"CompactResult", "ContextCompactor"}:
        from .compact import CompactResult, ContextCompactor

        return {
            "CompactResult": CompactResult,
            "ContextCompactor": ContextCompactor,
        }[name]
    raise AttributeError(f"module 'structured_memory' has no attribute {name!r}")
