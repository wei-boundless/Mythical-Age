from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from context_system.compaction.compactor import CompactResult
    from memory_system.storage.models import Message

PressureLevel = Literal["normal", "warning", "microcompact", "full_compact"]
ContextLedgerSource = Literal["memory_candidate", "retrieval_evidence"]
ContextLedgerDecision = Literal["include", "drop"]


def hash_context_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_context_sections(sections: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    return {
        str(name): tuple(hash_context_text(item) for item in list(items or []) if str(item).strip())
        for name, items in dict(sections or {}).items()
    }


def hash_context_section_package(sections: dict[str, list[str]]) -> str:
    normalized = {
        str(name): [str(item or "").replace("\r\n", "\n").replace("\r", "\n").strip() for item in list(items or [])]
        for name, items in dict(sections or {}).items()
    }
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True, frozen=True)
class SealedContextLedgerEntry:
    entry_id: str
    source_kind: ContextLedgerSource
    target_section: str
    decision: ContextLedgerDecision
    reason: str
    candidate_id: str = ""
    memory_layer: str = ""
    source: str = ""
    content_ref: str = ""
    rendered_sha256: str = ""
    token_estimate: int = 0
    requires_verification_before_use: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "context_policy.ledger_entry"

    def __post_init__(self) -> None:
        if self.authority != "context_policy.ledger_entry":
            raise ValueError("SealedContextLedgerEntry cannot carry runtime authority")
        if self.decision == "include" and not self.rendered_sha256:
            raise ValueError("included context ledger entries require rendered_sha256")
        if self.source_kind == "memory_candidate" and not self.candidate_id:
            raise ValueError("memory candidate ledger entries require candidate_id")
        if not self.target_section:
            raise ValueError("context ledger entries require target_section")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "source_kind": self.source_kind,
            "target_section": self.target_section,
            "decision": self.decision,
            "reason": self.reason,
            "candidate_id": self.candidate_id,
            "memory_layer": self.memory_layer,
            "source": self.source,
            "content_ref": self.content_ref,
            "rendered_sha256": self.rendered_sha256,
            "token_estimate": self.token_estimate,
            "requires_verification_before_use": self.requires_verification_before_use,
            "metadata": dict(self.metadata),
            "authority": self.authority,
        }


@dataclass(slots=True, frozen=True)
class SealedContextReceipt:
    receipt_id: str
    memory_runtime_view_ref: str
    package_sha256: str
    section_item_hashes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    included_entries: tuple[SealedContextLedgerEntry, ...] = ()
    dropped_entries: tuple[SealedContextLedgerEntry, ...] = ()
    read_only: bool = True
    authority: str = "context_policy.sealed_receipt"

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError("SealedContextReceipt must remain read_only")
        if self.authority != "context_policy.sealed_receipt":
            raise ValueError("SealedContextReceipt cannot carry runtime authority")
        if not self.receipt_id:
            raise ValueError("SealedContextReceipt requires receipt_id")
        if not self.memory_runtime_view_ref:
            raise ValueError("SealedContextReceipt requires memory_runtime_view_ref")
        object.__setattr__(
            self,
            "section_item_hashes",
            {
                str(name): tuple(str(item) for item in list(items or ()))
                for name, items in dict(self.section_item_hashes or {}).items()
            },
        )
        object.__setattr__(self, "included_entries", tuple(self.included_entries or ()))
        object.__setattr__(self, "dropped_entries", tuple(self.dropped_entries or ()))
        for entry in (*self.included_entries, *self.dropped_entries):
            if entry.authority != "context_policy.ledger_entry":
                raise ValueError("SealedContextReceipt can only contain policy ledger entries")
        for entry in self.included_entries:
            if entry.decision != "include":
                raise ValueError("included_entries can only contain include decisions")
        for entry in self.dropped_entries:
            if entry.decision != "drop":
                raise ValueError("dropped_entries can only contain drop decisions")

    @property
    def included_candidate_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.candidate_id
            for entry in self.included_entries
            if entry.source_kind == "memory_candidate" and entry.candidate_id
        )

    @property
    def dropped_candidate_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.candidate_id
            for entry in self.dropped_entries
            if entry.source_kind == "memory_candidate" and entry.candidate_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "memory_runtime_view_ref": self.memory_runtime_view_ref,
            "package_sha256": self.package_sha256,
            "section_item_hashes": {name: list(items) for name, items in self.section_item_hashes.items()},
            "included_entries": [entry.to_dict() for entry in self.included_entries],
            "dropped_entries": [entry.to_dict() for entry in self.dropped_entries],
            "included_candidate_ids": list(self.included_candidate_ids),
            "dropped_candidate_ids": list(self.dropped_candidate_ids),
            "read_only": self.read_only,
            "authority": self.authority,
        }


@dataclass(slots=True)
class ContextBudget:
    total: int = 0
    reserved_output: int = 0
    available_context: int = 0
    static: int = 0
    active_process: int = 0
    hot_truth: int = 0
    warm_snapshots: int = 0
    durable: int = 0
    retrieval: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class ContextPackage:
    pressure_level: PressureLevel = "normal"
    budget: ContextBudget = field(default_factory=ContextBudget)
    sections: dict[str, list[str]] = field(default_factory=dict)
    model_visible_sections: dict[str, list[str]] = field(default_factory=dict)
    debug_sections: dict[str, list[str]] = field(default_factory=dict)
    selected_sections: list[str] = field(default_factory=list)
    debug_selected_sections: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    dropped_items: list[str] = field(default_factory=list)
    rebuild_reason: str = "unknown"
    compaction_strategy: str = "none"
    compaction_decisions: list[str] = field(default_factory=list)
    token_accounting: dict[str, int] = field(default_factory=dict)
    sealed_receipt: SealedContextReceipt | None = None

    def __post_init__(self) -> None:
        if not self.model_visible_sections and self.sections:
            self.model_visible_sections = self._copy_sections(self.sections)
        if not self.sections and self.model_visible_sections:
            self.sections = self._copy_sections(self.model_visible_sections)
        if not self.debug_sections:
            self.debug_sections = self._copy_sections(self.model_visible_sections)
        if not self.selected_sections:
            self.selected_sections = self._selected_from(self.model_visible_sections)
        if not self.debug_selected_sections:
            self.debug_selected_sections = self._selected_from(self.debug_sections)

    def sections_for(self, mode: Literal["model", "debug"] = "model") -> dict[str, list[str]]:
        return self.debug_sections if mode == "debug" else self.model_visible_sections

    def _copy_sections(self, sections: dict[str, list[str]]) -> dict[str, list[str]]:
        return {name: list(items) for name, items in sections.items()}

    def _selected_from(self, sections: dict[str, list[str]]) -> list[str]:
        return [name for name, items in sections.items() if items]

    def to_dict(self) -> dict[str, object]:
        return {
            "pressure_level": self.pressure_level,
            "budget": self.budget.to_dict(),
            "sections": self.sections,
            "model_visible_sections": self.model_visible_sections,
            "debug_sections": self.debug_sections,
            "selected_sections": self.selected_sections,
            "debug_selected_sections": self.debug_selected_sections,
            "dropped_sections": self.dropped_sections,
            "dropped_items": self.dropped_items,
            "rebuild_reason": self.rebuild_reason,
            "compaction_strategy": self.compaction_strategy,
            "compaction_decisions": self.compaction_decisions,
            "token_accounting": self.token_accounting,
            "sealed_receipt": self.sealed_receipt.to_dict() if self.sealed_receipt is not None else None,
        }


@dataclass(slots=True)
class ContextControllerResult:
    messages: list[Message]
    package: ContextPackage
    compact_result: CompactResult



