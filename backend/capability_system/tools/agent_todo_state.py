from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class AgentTodoStateStore:
    def __init__(self, runtime_state_root: str | Path) -> None:
        self.state_dir = Path(runtime_state_root).resolve() / "agent_todo"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def read(self, *, session_id: str, task_id: str) -> dict[str, Any]:
        path = self._state_path(session_id=session_id, task_id=task_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write(self, *, session_id: str, task_id: str, payload: dict[str, Any]) -> None:
        self._state_path(session_id=session_id, task_id=task_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _state_path(self, *, session_id: str, task_id: str) -> Path:
        return self.state_dir / f"{safe_todo_state_key(session_id)}__{safe_todo_state_key(task_id)}.json"


def agent_todo_state_store_from_backend_dir(base_dir: str | Path) -> AgentTodoStateStore:
    from project_layout import ProjectLayout

    return AgentTodoStateStore(ProjectLayout.from_backend_dir(base_dir).runtime_state_dir)


def agent_todo_state_store_from_root(root_dir: str | Path) -> AgentTodoStateStore:
    from project_layout import ProjectLayout

    resolved = Path(root_dir).resolve()
    if resolved.name == "runtime_state" and resolved.parent.name == "storage":
        return AgentTodoStateStore(resolved)
    return AgentTodoStateStore(ProjectLayout.from_backend_dir(resolved).runtime_state_dir)


def normalize_todo_items(*, items: Any = None) -> list[dict[str, Any]]:
    raw_items = list(items or [])
    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            normalized.append(dict(item))
            continue
        model_dump = getattr(item, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                normalized.append(dict(dumped))
    return normalized


def todo_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(payload.get("items") or []) if isinstance(item, dict)]


def build_todo_plan(*, session_id: str, task_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    now = time.time()
    normalized: list[dict[str, Any]] = []
    active_item_id = ""
    for index, raw in enumerate(items):
        content = str(raw.get("content") or raw.get("title") or "").strip()
        if not content:
            continue
        todo_id = str(raw.get("todo_id") or _todo_id(content, index))
        status = str(raw.get("status") or "pending").strip()
        if status not in {"pending", "in_progress", "completed"}:
            status = "pending"
        if status == "in_progress":
            if active_item_id:
                status = "pending"
            else:
                active_item_id = todo_id
        item = {
            "todo_id": todo_id,
            "content": content,
            "active_form": str(raw.get("active_form") or content),
            "status": status,
            "notes": str(raw.get("notes") or ""),
            "evidence_expectations": [str(item) for item in list(raw.get("evidence_expectations") or []) if str(item).strip()],
            "contract_refs": [str(item) for item in list(raw.get("contract_refs") or []) if str(item).strip()],
            "updated_at": float(raw.get("updated_at") or now),
        }
        _copy_optional_string_field(item, raw, "owner_agent_id", aliases=("assigned_agent_id",))
        _copy_optional_string_field(item, raw, "scope")
        _copy_optional_string_field(item, raw, "subagent_run_ref")
        _copy_optional_string_field(item, raw, "handoff_goal")
        _copy_optional_string_field(item, raw, "parallel_group")
        depends_on = [str(value).strip() for value in list(raw.get("depends_on") or []) if str(value).strip()]
        if depends_on:
            item["depends_on"] = depends_on
        normalized.append(item)
    return {
        "plan_id": f"agent-todo:{safe_todo_state_key(session_id)}:{safe_todo_state_key(task_id)}",
        "session_id": session_id,
        "task_id": task_id,
        "active_item_id": active_item_id,
        "completion_ready": bool(normalized and all(item["status"] == "completed" for item in normalized)),
        "items": normalized,
        "diagnostics": {"item_count": len(normalized), "updated_at": now},
        "authority": "agent.todo_plan",
    }


def update_todo_plan(
    current: dict[str, Any],
    *,
    session_id: str,
    task_id: str,
    operation: str,
    items: list[dict[str, Any]],
    todo_id: str,
    status: str,
    notes: str,
) -> dict[str, Any]:
    existing = todo_items(current)
    op = str(operation or "replace").strip()
    target_id = str(todo_id or "").strip()
    if op == "replace":
        next_items = items
    elif op == "append":
        next_items = [*existing, *items]
    elif op == "clear":
        next_items = []
    elif op in {"start", "complete", "update_status", "remove"}:
        if not target_id:
            raise ValueError(f"{op} requires todo_id")
        found = False
        next_items = []
        for item in existing:
            current_id = str(item.get("todo_id") or "").strip()
            if current_id != target_id:
                if op == "start" and item.get("status") == "in_progress":
                    item = {**item, "status": "pending"}
                next_items.append(item)
                continue
            found = True
            if op == "remove":
                continue
            if op == "start":
                item = {**item, "status": "in_progress"}
            elif op == "complete":
                item = {**item, "status": "completed"}
            elif op == "update_status":
                item = {**item, "status": status or item.get("status") or "pending"}
            if notes:
                item = {**item, "notes": notes}
            next_items.append(item)
        if not found:
            raise ValueError(f"todo_id not found: {target_id}")
    else:
        raise ValueError(f"unsupported todo operation: {op}")
    return build_todo_plan(session_id=session_id, task_id=task_id, items=next_items)


def render_todo_tool_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "plan_id": plan["plan_id"],
        "active_item_id": plan["active_item_id"],
        "completion_ready": plan["completion_ready"],
        "items": plan["items"],
        "diagnostics": plan["diagnostics"],
    }


def safe_todo_state_key(value: str) -> str:
    result = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))
    return result.strip("_")[:80] or "runtime"


def _copy_optional_string_field(target: dict[str, Any], source: dict[str, Any], key: str, *, aliases: tuple[str, ...] = ()) -> None:
    for field in (key, *aliases):
        value = str(source.get(field) or "").strip()
        if value:
            target[key] = value
            return


def _todo_id(content: str, index: int) -> str:
    digest = hashlib.sha1(f"{index}:{content}".encode("utf-8")).hexdigest()[:8]
    return f"todo:{index + 1}:{digest}"
