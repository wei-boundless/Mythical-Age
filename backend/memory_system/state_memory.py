from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from structured_memory.session_memory import SessionMemoryManager

from .contracts import (
    MemoryContextCandidate,
    StateMemoryRestoreCandidate,
    StateMemorySnapshot,
)


class StateMemoryStoreAdapter:
    """Read-only adapter over the current process-state storage.

    This is the first landing layer for the new StateMemory boundary. It wraps
    existing `process_state.json` / `flow_snapshots.json` material into
    candidate-only contracts without changing the old storage format.
    """

    def __init__(self, session_root: str | Path) -> None:
        self.session_root = Path(session_root)
        self.session_root.mkdir(parents=True, exist_ok=True)

    def manager(self, session_id: str) -> SessionMemoryManager:
        root = self.session_root.resolve()
        target = (root / _safe_session_id(session_id)).resolve()
        if target == root or root not in target.parents:
            raise ValueError("Invalid session_id")
        return SessionMemoryManager(target)

    def load_snapshot(self, session_id: str) -> StateMemorySnapshot:
        manager = self.manager(session_id)
        state = manager.load_state()
        slots = getattr(state, "context_slots", None)
        flow_state = getattr(state, "flow_state", None)
        task_state = getattr(state, "task_state", None)
        context_slots = _object_to_dict(slots)
        active_handles = {
            key: value
            for key, value in {
                "active_object_handle_id": context_slots.get("active_object_handle_id", ""),
                "active_result_handle_id": context_slots.get("active_result_handle_id", ""),
                "active_subset_handle_id": context_slots.get("active_subset_handle_id", ""),
            }.items()
            if _clean(value)
        }
        return StateMemorySnapshot(
            session_id=_safe_session_id(session_id),
            active_goal=_clean(getattr(state, "active_goal", "")),
            flow_state=_object_to_dict(flow_state),
            task_state=_object_to_dict(task_state),
            context_slots=context_slots,
            active_handles={key: _clean(value) for key, value in active_handles.items()},
            operation_refs=tuple(_clean(item) for item in getattr(state, "current_result_refs", []) or [] if _clean(item)),
            next_step=tuple(_clean(item) for item in getattr(state, "next_step", []) or [] if _clean(item)),
            updated_at=_clean(getattr(state, "updated_at", "")),
            source="structured_memory.process_state",
        )

    def restore_candidates(self, session_id: str) -> tuple[StateMemoryRestoreCandidate, ...]:
        snapshot = self.load_snapshot(session_id)
        return self.restore_candidates_from_snapshot(snapshot)

    def restore_candidates_from_snapshot(
        self,
        snapshot: StateMemorySnapshot,
    ) -> tuple[StateMemoryRestoreCandidate, ...]:
        candidates: list[StateMemoryRestoreCandidate] = []
        slots = dict(snapshot.context_slots)

        for key, owner_key in (
            ("committed_pdf", "committed_pdf_owner_task_id"),
            ("committed_dataset", "committed_dataset_owner_task_id"),
            ("active_pdf", "active_binding_owner_task_id"),
            ("active_dataset", "active_binding_owner_task_id"),
            ("active_entity", "active_binding_owner_task_id"),
            ("active_rule", "active_binding_owner_task_id"),
        ):
            value = _clean(slots.get(key))
            if not value:
                continue
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:context_slot:{key}",
                    restore_kind="context_slot",
                    value=value,
                    source=f"{snapshot.source}.context_slots.{key}",
                    owner_task_id=_clean(slots.get(owner_key)),
                    observed_at=snapshot.updated_at,
                    confidence=0.72 if key.startswith("committed_") else 0.55,
                    metadata={"slot_name": key},
                )
            )

        binding_kind = _clean(slots.get("active_binding_kind"))
        binding_identity = _clean(slots.get("active_binding_identity"))
        if binding_kind and binding_identity:
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:active_binding",
                    restore_kind="active_binding",
                    value={"kind": binding_kind, "identity": binding_identity},
                    source=f"{snapshot.source}.context_slots.active_binding",
                    owner_task_id=_clean(slots.get("active_binding_owner_task_id")),
                    observed_at=snapshot.updated_at,
                    confidence=0.68,
                )
            )

        for key, value in snapshot.active_handles.items():
            clean_value = _clean(value)
            if not clean_value:
                continue
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:handle:{key}",
                    restore_kind="result_handle",
                    value=clean_value,
                    source=f"{snapshot.source}.context_slots.{key}",
                    owner_task_id=_clean(slots.get("active_binding_owner_task_id")),
                    observed_at=snapshot.updated_at,
                    confidence=0.64,
                    metadata={"handle_name": key},
                )
            )

        if snapshot.flow_state:
            flow_id = _clean(snapshot.flow_state.get("flow_id"))
            if flow_id:
                candidates.append(
                    StateMemoryRestoreCandidate(
                        candidate_id=f"state-restore:{snapshot.session_id}:flow:{flow_id}",
                        restore_kind="flow_state",
                        value=dict(snapshot.flow_state),
                        source=f"{snapshot.source}.flow_state",
                        observed_at=snapshot.updated_at,
                        confidence=float(snapshot.flow_state.get("confidence") or 0.0),
                    )
                )

        if snapshot.task_state:
            has_task_state = any(_clean(value) for value in snapshot.task_state.values())
            if has_task_state:
                candidates.append(
                    StateMemoryRestoreCandidate(
                        candidate_id=f"state-restore:{snapshot.session_id}:task_state",
                        restore_kind="task_state",
                        value=dict(snapshot.task_state),
                        source=f"{snapshot.source}.task_state",
                        observed_at=snapshot.updated_at,
                        confidence=0.6,
                    )
                )

        return tuple(candidates)

    def context_candidates(self, session_id: str) -> tuple[MemoryContextCandidate, ...]:
        snapshot = self.load_snapshot(session_id)
        preview_parts = []
        if snapshot.active_goal:
            preview_parts.append(f"active_goal: {snapshot.active_goal}")
        if snapshot.next_step:
            preview_parts.append(f"next_step: {'; '.join(snapshot.next_step[:2])}")
        for key in ("committed_pdf", "committed_dataset", "active_pdf", "active_dataset"):
            value = _clean(snapshot.context_slots.get(key))
            if value:
                preview_parts.append(f"{key}: {value}")
        for key, value in snapshot.active_handles.items():
            if value:
                preview_parts.append(f"{key}: {value}")
        preview = "\n".join(preview_parts).strip()
        if not preview:
            return ()
        return (
            MemoryContextCandidate(
                candidate_id=f"memory-context:{snapshot.session_id}:state:snapshot",
                memory_layer="state",
                source=snapshot.source,
                content_ref=f"state-memory:{snapshot.session_id}",
                rendered_preview=preview,
                relevance=0.8,
                confidence=0.68,
                staleness="session_scoped",
                token_estimate=max(1, len(preview) // 4),
                budget_class="preferred",
                requires_verification_before_use=False,
                metadata={
                    "restore_candidate_count": len(self.restore_candidates_from_snapshot(snapshot)),
                    "updated_at": snapshot.updated_at,
                },
            ),
        )


def _safe_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    return value or "default"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _object_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
    else:
        try:
            payload = asdict(value)
        except TypeError:
            payload = {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): item
        for key, item in payload.items()
        if item not in ("", [], {}, None)
    }
