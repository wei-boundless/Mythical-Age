from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


TODO_STATUSES = {"pending", "in_progress", "completed"}


@dataclass(frozen=True, slots=True)
class AgentTodoItem:
    todo_id: str
    content: str
    active_form: str = ""
    status: str = "pending"
    evidence_expectations: tuple[str, ...] = ()
    contract_refs: tuple[str, ...] = ()
    notes: str = ""
    authority: str = "runtime.agent_todo_item"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_todo_item":
            raise ValueError("AgentTodoItem authority must be runtime.agent_todo_item")
        if not self.todo_id:
            raise ValueError("AgentTodoItem requires todo_id")
        if self.status not in TODO_STATUSES:
            raise ValueError(f"Invalid AgentTodoItem status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_expectations"] = list(self.evidence_expectations)
        payload["contract_refs"] = list(self.contract_refs)
        return payload


@dataclass(frozen=True, slots=True)
class AgentTodoPlan:
    plan_id: str
    session_id: str
    task_id: str
    items: tuple[AgentTodoItem, ...] = ()
    active_item_id: str = ""
    coverage_refs: tuple[str, ...] = ()
    completion_ready: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_todo_plan"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_todo_plan":
            raise ValueError("AgentTodoPlan authority must be runtime.agent_todo_plan")
        if not self.plan_id:
            raise ValueError("AgentTodoPlan requires plan_id")
        in_progress = [item.todo_id for item in self.items if item.status == "in_progress"]
        if len(in_progress) > 1:
            raise ValueError("AgentTodoPlan allows at most one in_progress item")
        if self.active_item_id and self.active_item_id not in {item.todo_id for item in self.items}:
            raise ValueError("AgentTodoPlan active_item_id must refer to an item")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        payload["coverage_refs"] = list(self.coverage_refs)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_agent_todo_plan(
    *,
    session_id: str,
    task_id: str,
    items: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    coverage_refs: list[str] | tuple[str, ...] | None = None,
) -> AgentTodoPlan:
    todo_items = tuple(_todo_item_from_payload(index=index, payload=payload) for index, payload in enumerate(items or [], start=1))
    active = next((item.todo_id for item in todo_items if item.status == "in_progress"), "")
    completion_ready = bool(todo_items) and all(item.status == "completed" for item in todo_items)
    return AgentTodoPlan(
        plan_id=f"agent-todo:{session_id or 'session'}:{task_id or 'runtime'}",
        session_id=str(session_id or ""),
        task_id=str(task_id or ""),
        items=todo_items,
        active_item_id=active,
        coverage_refs=tuple(str(item).strip() for item in list(coverage_refs or []) if str(item).strip()),
        completion_ready=completion_ready,
        diagnostics={
            "item_count": len(todo_items),
            "pending_count": len([item for item in todo_items if item.status == "pending"]),
            "completed_count": len([item for item in todo_items if item.status == "completed"]),
        },
    )


def initialize_agent_todo_plan(
    *,
    root_dir: Path,
    session_id: str,
    task_id: str,
    task_run_id: str = "",
    coverage_refs: list[str] | tuple[str, ...] | None = None,
) -> AgentTodoPlan:
    plan = build_agent_todo_plan(
        session_id=session_id,
        task_id=task_id,
        items=[],
        coverage_refs=coverage_refs,
    )
    payload = plan.to_dict()
    payload["diagnostics"] = {
        **dict(payload.get("diagnostics") or {}),
        "initialized_by": "task_run_start",
        "task_run_id": str(task_run_id or ""),
        "agent_owned_progress": True,
        "lifecycle_admission_source": False,
    }
    path = agent_todo_state_path(root_dir=root_dir, session_id=session_id, task_id=task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return AgentTodoPlan(
        plan_id=plan.plan_id,
        session_id=plan.session_id,
        task_id=plan.task_id,
        items=plan.items,
        active_item_id=plan.active_item_id,
        coverage_refs=plan.coverage_refs,
        completion_ready=plan.completion_ready,
        diagnostics=dict(payload["diagnostics"]),
    )


def agent_todo_state_path(*, root_dir: Path, session_id: str, task_id: str) -> Path:
    return Path(root_dir).resolve() / ".tmp" / "agent_todo" / f"{_safe_key(session_id or 'default')}__{_safe_key(task_id or 'runtime')}.json"


def update_agent_todo_plan(
    current: dict[str, Any] | None,
    *,
    session_id: str,
    task_id: str,
    operation: str,
    items: list[dict[str, Any]] | None = None,
    todo_id: str = "",
    status: str = "",
    notes: str = "",
) -> AgentTodoPlan:
    existing_items = [dict(item) for item in list(dict(current or {}).get("items") or []) if isinstance(item, dict)]
    normalized_operation = str(operation or "").strip().lower() or "replace"
    if normalized_operation == "replace":
        return build_agent_todo_plan(session_id=session_id, task_id=task_id, items=items or [])
    if normalized_operation == "append":
        return build_agent_todo_plan(session_id=session_id, task_id=task_id, items=[*existing_items, *list(items or [])])
    if normalized_operation == "clear":
        return build_agent_todo_plan(session_id=session_id, task_id=task_id, items=[])
    if normalized_operation in {"update_status", "complete", "start"}:
        target = str(todo_id or "").strip()
        target_status = _target_status(normalized_operation, status)
        if not target:
            raise ValueError("todo_id is required for status updates")
        updated: list[dict[str, Any]] = []
        found = False
        for item in existing_items:
            candidate = dict(item)
            if str(candidate.get("todo_id") or "") == target:
                candidate["status"] = target_status
                if notes:
                    candidate["notes"] = notes
                found = True
            elif target_status == "in_progress" and str(candidate.get("status") or "") == "in_progress":
                candidate["status"] = "pending"
            updated.append(candidate)
        if not found:
            raise LookupError("todo_id not found")
        return build_agent_todo_plan(session_id=session_id, task_id=task_id, items=updated)
    if normalized_operation == "remove":
        target = str(todo_id or "").strip()
        if not target:
            raise ValueError("todo_id is required for remove")
        updated = [item for item in existing_items if str(item.get("todo_id") or "") != target]
        return build_agent_todo_plan(session_id=session_id, task_id=task_id, items=updated)
    raise ValueError(f"Unsupported todo operation: {operation}")


def _target_status(operation: str, status: str) -> str:
    if operation == "complete":
        return "completed"
    if operation == "start":
        return "in_progress"
    target = str(status or "").strip()
    if target not in TODO_STATUSES:
        raise ValueError(f"Invalid todo status: {status}")
    return target


def _todo_item_from_payload(*, index: int, payload: dict[str, Any]) -> AgentTodoItem:
    item = dict(payload or {})
    todo_id = str(item.get("todo_id") or item.get("id") or f"todo-{index}").strip()
    content = str(item.get("content") or item.get("title") or item.get("subject") or "").strip()
    if not content:
        raise ValueError("AgentTodoItem requires content")
    status = str(item.get("status") or "pending").strip()
    if status not in TODO_STATUSES:
        raise ValueError(f"Invalid todo status: {status}")
    return AgentTodoItem(
        todo_id=todo_id,
        content=content,
        active_form=str(item.get("active_form") or item.get("activeForm") or "").strip(),
        status=status,
        evidence_expectations=tuple(
            str(value).strip()
            for value in list(item.get("evidence_expectations") or item.get("evidenceExpectations") or [])
            if str(value).strip()
        ),
        contract_refs=tuple(
            str(value).strip()
            for value in list(item.get("contract_refs") or item.get("contractRefs") or [])
            if str(value).strip()
        ),
        notes=str(item.get("notes") or "").strip(),
    )


def _safe_key(value: str) -> str:
    result = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))
    return result.strip("_")[:80] or "runtime"


