from __future__ import annotations

from dataclasses import asdict, dataclass
import time
import uuid
from typing import Any, Literal


AgentInvocationKind = Literal["single_turn", "task_run", "subagent", "background"]


@dataclass(frozen=True, slots=True)
class AgentRunScope:
    session_id: str
    agent_run_id: str
    run_cell_id: str
    invocation_kind: AgentInvocationKind
    parent_agent_run_id: str = ""
    turn_id: str = ""
    turn_run_id: str = ""
    task_run_id: str = ""
    created_at: float = 0.0
    authority: str = "harness.runtime.agent_scope"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.agent_scope":
            raise ValueError("AgentRunScope authority must be harness.runtime.agent_scope")
        if not self.session_id:
            raise ValueError("AgentRunScope requires session_id")
        if not self.agent_run_id:
            raise ValueError("AgentRunScope requires agent_run_id")
        if not self.run_cell_id:
            raise ValueError("AgentRunScope requires run_cell_id")
        if self.invocation_kind not in {"single_turn", "task_run", "subagent", "background"}:
            raise ValueError(f"Unsupported agent invocation kind: {self.invocation_kind}")
        if self.invocation_kind == "task_run" and not self.task_run_id:
            raise ValueError("task_run AgentRunScope requires task_run_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_agent_run_scope(
    *,
    session_id: str,
    invocation_kind: AgentInvocationKind,
    task_run_id: str = "",
    turn_id: str = "",
    turn_run_id: str = "",
    parent_agent_run_id: str = "",
    agent_run_id: str = "",
    run_cell_id: str = "",
    created_at: float | None = None,
) -> AgentRunScope:
    normalized_session_id = str(session_id or "").strip()
    normalized_kind = str(invocation_kind or "").strip() or "task_run"
    now = time.time() if created_at is None else float(created_at or 0.0)
    agent_id = str(agent_run_id or "").strip() or _runtime_id("agentrun", normalized_kind, task_run_id or turn_id)
    cell_id = str(run_cell_id or "").strip() or _runtime_id("runcell", normalized_kind, task_run_id or turn_id)
    return AgentRunScope(
        session_id=normalized_session_id,
        agent_run_id=agent_id,
        run_cell_id=cell_id,
        invocation_kind=normalized_kind,  # type: ignore[arg-type]
        parent_agent_run_id=str(parent_agent_run_id or "").strip(),
        turn_id=str(turn_id or "").strip(),
        turn_run_id=str(turn_run_id or "").strip(),
        task_run_id=str(task_run_id or "").strip(),
        created_at=now,
    )


def agent_scope_from_task_run(
    task_run: Any,
    *,
    agent_run_id: str = "",
    run_cell_id: str = "",
    parent_agent_run_id: str = "",
    created_at: float | None = None,
) -> AgentRunScope:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    return build_agent_run_scope(
        session_id=str(getattr(task_run, "session_id", "") or ""),
        invocation_kind="task_run",
        task_run_id=str(getattr(task_run, "task_run_id", "") or ""),
        turn_id=str(diagnostics.get("latest_interaction_turn_id") or ""),
        parent_agent_run_id=parent_agent_run_id,
        agent_run_id=agent_run_id,
        run_cell_id=run_cell_id,
        created_at=created_at,
    )


def scope_matches(scope: AgentRunScope | dict[str, Any], *, agent_run_id: str = "", run_cell_id: str = "") -> bool:
    payload = scope.to_dict() if isinstance(scope, AgentRunScope) else dict(scope or {})
    if agent_run_id and str(payload.get("agent_run_id") or "") != str(agent_run_id):
        return False
    if run_cell_id and str(payload.get("run_cell_id") or "") != str(run_cell_id):
        return False
    return True


def _runtime_id(prefix: str, kind: str, semantic_ref: str = "") -> str:
    semantic = "".join(ch if ch.isalnum() or ch in {"-", "_", ":"} else "_" for ch in str(semantic_ref or "")).strip("_")
    suffix = uuid.uuid4().hex[:12]
    if semantic:
        return f"{prefix}:{kind}:{semantic}:{suffix}"
    return f"{prefix}:{kind}:{suffix}"
