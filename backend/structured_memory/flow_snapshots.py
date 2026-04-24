from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from .dialogue_state import DialogueState
from .models import utc_now_iso
from .text_utils import normalize_storage_text


@dataclass(slots=True)
class FlowSnapshot:
    snapshot_id: str
    flow_id: str
    flow_type: str
    status: str = "suspended"
    goal: str = ""
    binding_kind: str = ""
    binding_identity: str = ""
    binding_owner_task_id: str = ""
    key_slots: dict[str, str] = field(default_factory=dict)
    recent_results: list[str] = field(default_factory=list)
    resume_hints: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "FlowSnapshot":
        key_slots_payload = payload.get("key_slots", {})
        return cls(
            snapshot_id=str(payload.get("snapshot_id", "") or ""),
            flow_id=str(payload.get("flow_id", "") or ""),
            flow_type=str(payload.get("flow_type", "") or ""),
            status=str(payload.get("status", "suspended") or "suspended"),
            goal=str(payload.get("goal", "") or ""),
            binding_kind=str(payload.get("binding_kind", "") or ""),
            binding_identity=str(payload.get("binding_identity", "") or ""),
            binding_owner_task_id=str(payload.get("binding_owner_task_id", "") or ""),
            key_slots={
                str(key): str(value)
                for key, value in dict(key_slots_payload or {}).items()
                if str(value).strip()
            }
            if isinstance(key_slots_payload, dict)
            else {},
            recent_results=[
                str(item)
                for item in list(payload.get("recent_results", []) or [])
                if str(item).strip()
            ],
            resume_hints=[
                str(item)
                for item in list(payload.get("resume_hints", []) or [])
                if str(item).strip()
            ],
            updated_at=str(payload.get("updated_at", "") or utc_now_iso()),
        )


class FlowSnapshotManager:
    def __init__(self, session_dir: str | Path, *, max_snapshots: int = 8) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.session_dir / "flow_snapshots.json"
        self.max_snapshots = max(1, max_snapshots)

    def load(self) -> list[FlowSnapshot]:
        if not self.snapshot_path.exists():
            return []
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [
            FlowSnapshot.from_dict(item)
            for item in payload
            if isinstance(item, dict)
        ]

    def overwrite(self, snapshots: list[FlowSnapshot]) -> None:
        payload = json.dumps(
            [snapshot.to_dict() for snapshot in snapshots[: self.max_snapshots]],
            ensure_ascii=False,
            indent=2,
        )
        self.snapshot_path.write_text(payload, encoding="utf-8")

    def update_for_transition(
        self,
        previous_state: DialogueState,
        next_state: DialogueState,
    ) -> list[FlowSnapshot]:
        snapshots = [
            snapshot
            for snapshot in self.load()
            if snapshot.flow_id != next_state.flow_state.flow_id
        ]

        if self._should_snapshot(previous_state, next_state):
            snapshots.insert(0, self._snapshot_from_state(previous_state))

        deduped: list[FlowSnapshot] = []
        seen_flow_ids: set[str] = set()
        for snapshot in snapshots:
            if not snapshot.flow_id or snapshot.flow_id in seen_flow_ids:
                continue
            seen_flow_ids.add(snapshot.flow_id)
            deduped.append(snapshot)

        self.overwrite(deduped)
        return deduped[: self.max_snapshots]

    def _should_snapshot(
        self,
        previous_state: DialogueState,
        next_state: DialogueState,
    ) -> bool:
        previous_goal = previous_state.active_goal.strip()
        if not previous_goal:
            return False
        if previous_state.flow_state.flow_id == next_state.flow_state.flow_id:
            return False
        if previous_state.flow_state.flow_type == "general_problem_solving_flow" and not previous_state.current_task_state:
            return False
        return True

    def _snapshot_from_state(self, state: DialogueState) -> FlowSnapshot:
        key_slots = {
            label: value
            for label, value in {
                "active_pdf": state.context_slots.active_pdf,
                "active_dataset": state.context_slots.active_dataset,
                "active_entity": state.context_slots.active_entity,
                "active_rule": state.context_slots.active_rule,
            }.items()
            if normalize_storage_text(value).strip()
        }
        resume_hints = list(state.next_step[:1]) or list(state.warm_context[:2])
        binding_kind = str(state.context_slots.active_binding_kind or "").strip()
        binding_identity = str(state.context_slots.active_binding_identity or "").strip()
        binding_owner_task_id = str(state.context_slots.active_binding_owner_task_id or "").strip()
        return FlowSnapshot(
            snapshot_id=f"snap:{state.flow_state.flow_id}:{utc_now_iso()}",
            flow_id=state.flow_state.flow_id,
            flow_type=state.flow_state.flow_type,
            status="suspended",
            goal=state.active_goal,
            binding_kind=binding_kind,
            binding_identity=binding_identity,
            binding_owner_task_id=binding_owner_task_id,
            key_slots=key_slots,
            recent_results=list((getattr(state, "current_result_refs", None) or state.key_results)[:2]),
            resume_hints=[
                normalize_storage_text(item)
                for item in resume_hints
                if normalize_storage_text(item).strip()
            ][:2],
            updated_at=utc_now_iso(),
        )
