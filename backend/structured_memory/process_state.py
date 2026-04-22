from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from .models import utc_now_iso


@dataclass(slots=True)
class TurnUnderstanding:
    role: str
    turn_type: str
    excerpt: str
    intent: str = "general"
    modality: str = "general"
    target_object: str = ""
    flow_hint: str = "general"
    constraints: list[str] = field(default_factory=list)


DialogueTurn = TurnUnderstanding


@dataclass(slots=True)
class FlowState:
    flow_id: str = "general:active"
    flow_type: str = "general_problem_solving_flow"
    status: str = "active"
    confidence: float = 0.0


@dataclass(slots=True)
class TaskState:
    current_step: str = ""
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    next_step: str = ""


@dataclass(slots=True)
class ContextSlots:
    active_pdf: str = ""
    active_dataset: str = ""
    active_binding_kind: str = ""
    active_binding_identity: str = ""
    active_binding_owner_task_id: str = ""
    active_entity: str = ""
    active_rule: str = ""


@dataclass(slots=True)
class ProcessState:
    version: int = 2
    updated_at: str = field(default_factory=utc_now_iso)
    session_title: str = "Ongoing session"
    active_goal: str = ""
    active_goal_turn_type: str = "unknown"
    last_turn_type: str = "unknown"
    flow_state: FlowState = field(default_factory=FlowState)
    task_state: TaskState = field(default_factory=TaskState)
    context_slots: ContextSlots = field(default_factory=ContextSlots)
    current_task_state: list[str] = field(default_factory=list)
    warm_context: list[str] = field(default_factory=list)
    key_user_requests: list[str] = field(default_factory=list)
    files_and_functions: list[str] = field(default_factory=list)
    conventions_and_constraints: list[str] = field(default_factory=list)
    errors_and_corrections: list[str] = field(default_factory=list)
    decisions_and_learnings: list[str] = field(default_factory=list)
    key_results: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    next_step: list[str] = field(default_factory=list)
    worklog: list[str] = field(default_factory=list)
    turn_trace: list[TurnUnderstanding] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["turn_trace"] = [asdict(item) for item in self.turn_trace]
        payload["flow_state"] = asdict(self.flow_state)
        payload["task_state"] = asdict(self.task_state)
        payload["context_slots"] = asdict(self.context_slots)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProcessState":
        turn_trace = [
            TurnUnderstanding(
                role=str(item.get("role", "")),
                turn_type=str(item.get("turn_type", "unknown")),
                excerpt=str(item.get("excerpt", "")),
                intent=str(item.get("intent", "general")),
                modality=str(item.get("modality", "general")),
                target_object=str(item.get("target_object", "")),
                flow_hint=str(item.get("flow_hint", "general")),
                constraints=[
                    str(value)
                    for value in list(item.get("constraints", []) or [])
                    if str(value).strip()
                ],
            )
            for item in list(payload.get("turn_trace", []) or [])
            if isinstance(item, dict)
        ]
        flow_payload = payload.get("flow_state", {})
        task_payload = payload.get("task_state", {})
        slots_payload = payload.get("context_slots", {})

        flow_state = (
            FlowState(
                flow_id=str(getattr(flow_payload, "get", lambda *_: "general:active")("flow_id", "general:active")),
                flow_type=str(
                    getattr(flow_payload, "get", lambda *_: "general_problem_solving_flow")(
                        "flow_type",
                        "general_problem_solving_flow",
                    )
                ),
                status=str(getattr(flow_payload, "get", lambda *_: "active")("status", "active")),
                confidence=float(getattr(flow_payload, "get", lambda *_: 0.0)("confidence", 0.0) or 0.0),
            )
            if isinstance(flow_payload, dict)
            else FlowState()
        )

        task_state = (
            TaskState(
                current_step=str(getattr(task_payload, "get", lambda *_: "")("current_step", "")),
                completed_steps=[
                    str(item)
                    for item in list(getattr(task_payload, "get", lambda *_: [])("completed_steps", []) or [])
                    if str(item).strip()
                ],
                pending_steps=[
                    str(item)
                    for item in list(getattr(task_payload, "get", lambda *_: [])("pending_steps", []) or [])
                    if str(item).strip()
                ],
                next_step=str(getattr(task_payload, "get", lambda *_: "")("next_step", "")),
            )
            if isinstance(task_payload, dict)
            else TaskState()
        )

        context_slots = (
            ContextSlots(
                active_pdf=str(getattr(slots_payload, "get", lambda *_: "")("active_pdf", "")),
                active_dataset=str(getattr(slots_payload, "get", lambda *_: "")("active_dataset", "")),
                active_binding_kind=str(getattr(slots_payload, "get", lambda *_: "")("active_binding_kind", "")),
                active_binding_identity=str(getattr(slots_payload, "get", lambda *_: "")("active_binding_identity", "")),
                active_binding_owner_task_id=str(
                    getattr(slots_payload, "get", lambda *_: "")("active_binding_owner_task_id", "")
                ),
                active_entity=str(getattr(slots_payload, "get", lambda *_: "")("active_entity", "")),
                active_rule=str(getattr(slots_payload, "get", lambda *_: "")("active_rule", "")),
            )
            if isinstance(slots_payload, dict)
            else ContextSlots()
        )

        return cls(
            version=int(payload.get("version", 1) or 1),
            updated_at=str(payload.get("updated_at", "") or utc_now_iso()),
            session_title=str(payload.get("session_title", "Ongoing session") or "Ongoing session"),
            active_goal=str(payload.get("active_goal", "") or ""),
            active_goal_turn_type=str(payload.get("active_goal_turn_type", "unknown") or "unknown"),
            last_turn_type=str(payload.get("last_turn_type", "unknown") or "unknown"),
            flow_state=flow_state,
            task_state=task_state,
            context_slots=context_slots,
            current_task_state=[
                str(item)
                for item in list(payload.get("current_task_state", []) or [])
                if str(item).strip()
            ],
            warm_context=[
                str(item)
                for item in list(payload.get("warm_context", []) or [])
                if str(item).strip()
            ],
            key_user_requests=[
                str(item)
                for item in list(payload.get("key_user_requests", []) or [])
                if str(item).strip()
            ],
            files_and_functions=[
                str(item)
                for item in list(payload.get("files_and_functions", []) or [])
                if str(item).strip()
            ],
            conventions_and_constraints=[
                str(item)
                for item in list(
                    payload.get("conventions_and_constraints", payload.get("workflow_and_constraints", [])) or []
                )
                if str(item).strip()
            ],
            errors_and_corrections=[
                str(item)
                for item in list(payload.get("errors_and_corrections", []) or [])
                if str(item).strip()
            ],
            decisions_and_learnings=[
                str(item)
                for item in list(payload.get("decisions_and_learnings", []) or [])
                if str(item).strip()
            ],
            key_results=[
                str(item)
                for item in list(payload.get("key_results", []) or [])
                if str(item).strip()
            ],
            risk_flags=[
                str(item)
                for item in list(payload.get("risk_flags", []) or [])
                if str(item).strip()
            ],
            risk_notes=[
                str(item)
                for item in list(payload.get("risk_notes", []) or [])
                if str(item).strip()
            ],
            next_step=[
                str(item)
                for item in list(payload.get("next_step", []) or [])
                if str(item).strip()
            ],
            worklog=[str(item) for item in list(payload.get("worklog", []) or []) if str(item).strip()],
            turn_trace=turn_trace,
        )


class ProcessStateManager:
    def __init__(self, session_dir: str | Path) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.process_state_path = self.session_dir / "process_state.json"
        self.state_mirror_path = self.session_dir / "state.json"

    def load(self) -> ProcessState:
        for candidate in (self.process_state_path, self.state_mirror_path):
            state = self._load_from_path(candidate)
            if state is not None:
                return state
        return ProcessState()

    def overwrite(self, state: ProcessState) -> None:
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        self.process_state_path.write_text(payload, encoding="utf-8")
        self.state_mirror_path.write_text(payload, encoding="utf-8")

    def _load_from_path(self, path: Path) -> ProcessState | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return ProcessState.from_dict(payload)


DialogueState = ProcessState
DialogueStateManager = ProcessStateManager
