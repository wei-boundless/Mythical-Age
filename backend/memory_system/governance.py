from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_layout import durable_memory_layout_from_backend_dir
from structured_memory.models import utc_now_iso

from .contracts import MemoryCommitAction, MemoryCommitLayer, MemoryCommitRecord


class MemoryGovernance:
    """Manual/governance memory commit audit boundary."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.log_dir = durable_memory_layout_from_backend_dir(self.base_dir).meta_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "governance_log.jsonl"

    def record(
        self,
        *,
        action: MemoryCommitAction,
        commit_layer: MemoryCommitLayer = "long_term",
        target_refs: tuple[str, ...] | list[str] = (),
        created_ref: str = "",
        reason: str = "",
        actor: str = "memory_governance_ui",
        allowed: bool = True,
        source_candidate_refs: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> MemoryCommitRecord:
        ts = utc_now_iso()
        record = MemoryCommitRecord(
            record_id=f"memory-commit:{commit_layer}:{action}:{_safe_stamp(ts)}",
            commit_layer=commit_layer,
            action=action,
            target_refs=tuple(str(item) for item in target_refs if str(item).strip()),
            created_ref=str(created_ref or ""),
            reason=str(reason or ""),
            actor=str(actor or "memory_governance"),
            allowed=bool(allowed),
            source_candidate_refs=tuple(str(item) for item in source_candidate_refs if str(item).strip()),
            metadata={"ts": ts, **dict(metadata or {})},
        )
        self.append(record)
        return record

    def record_blocked_legacy_call(
        self,
        *,
        target_refs: tuple[str, ...] | list[str] = (),
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryCommitRecord:
        return self.record(
            action="legacy_blocked",
            commit_layer="governance_log",
            target_refs=target_refs,
            reason=reason,
            actor="runtime_compatibility_guard",
            allowed=False,
            metadata=metadata,
        )

    def append(self, record: MemoryCommitRecord) -> None:
        payload = record.to_dict()
        # Preserve the old log keys so the existing UI can keep reading this
        # file while the new commit record shape rolls in.
        payload.setdefault("ts", dict(record.metadata).get("ts", ""))
        payload.setdefault("filenames", list(record.target_refs))
        payload.setdefault("created", record.created_ref)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _safe_stamp(value: str) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())[:14] or "record"
