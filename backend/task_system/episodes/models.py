from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EpisodeStatus = Literal["scheduled", "running", "waiting_tool", "waiting_user", "interrupted", "completed", "failed", "aborted"]
EpisodeResultStatus = Literal["completed", "partial", "blocked", "failed", "aborted"]


@dataclass(frozen=True, slots=True)
class AgentExecutionEpisode:
    episode_id: str
    task_environment_id: str
    task_instance_id: str
    agent_id: str
    agent_profile_id: str
    invocation_kind: str
    caller_kind: str
    status: EpisodeStatus = "scheduled"
    graph_binding_id: str = ""
    input_context_package_id: str = ""
    lease_id: str = ""
    runtime_trace_ref: str = ""
    terminal_reason: str = ""
    continuation_hint: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.agent_execution_episode"

    def __post_init__(self) -> None:
        if self.authority != "task_system.agent_execution_episode":
            raise ValueError("AgentExecutionEpisode authority must be task_system.agent_execution_episode")
        _require_text(self.episode_id, "AgentExecutionEpisode requires episode_id")
        _require_text(self.task_environment_id, "AgentExecutionEpisode requires task_environment_id")
        _require_text(self.task_instance_id, "AgentExecutionEpisode requires task_instance_id")
        _require_text(self.agent_id, "AgentExecutionEpisode requires agent_id")
        _require_text(self.agent_profile_id, "AgentExecutionEpisode requires agent_profile_id")
        _require_text(self.invocation_kind, "AgentExecutionEpisode requires invocation_kind")
        _require_text(self.caller_kind, "AgentExecutionEpisode requires caller_kind")
        if self.status == "completed" and not self.ended_at:
            raise ValueError("completed AgentExecutionEpisode requires ended_at")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentExecutionEpisode":
        data = dict(payload or {})
        return cls(
            episode_id=str(data.get("episode_id") or ""),
            task_environment_id=str(data.get("task_environment_id") or ""),
            task_instance_id=str(data.get("task_instance_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            agent_profile_id=str(data.get("agent_profile_id") or ""),
            invocation_kind=str(data.get("invocation_kind") or ""),
            caller_kind=str(data.get("caller_kind") or ""),
            status=str(data.get("status") or "scheduled"),  # type: ignore[arg-type]
            graph_binding_id=str(data.get("graph_binding_id") or ""),
            input_context_package_id=str(data.get("input_context_package_id") or ""),
            lease_id=str(data.get("lease_id") or ""),
            runtime_trace_ref=str(data.get("runtime_trace_ref") or ""),
            terminal_reason=str(data.get("terminal_reason") or ""),
            continuation_hint=str(data.get("continuation_hint") or ""),
            started_at=_float(data.get("started_at")),
            ended_at=_float(data.get("ended_at")),
            diagnostics=dict(data.get("diagnostics") or {}),
            authority=str(data.get("authority") or "task_system.agent_execution_episode"),
        )


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    result_id: str
    episode_id: str
    task_environment_id: str
    status: EpisodeResultStatus
    summary: str = ""
    work_product_candidates: tuple[dict[str, Any], ...] = ()
    state_update_proposals: tuple[dict[str, Any], ...] = ()
    plan_patch: dict[str, Any] = field(default_factory=dict)
    todo_patch: dict[str, Any] = field(default_factory=dict)
    memory_candidates: tuple[dict[str, Any], ...] = ()
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    blocker: str = ""
    continuation_hint: str = ""
    output_contract_version: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.episode_result"

    def __post_init__(self) -> None:
        if self.authority != "task_system.episode_result":
            raise ValueError("EpisodeResult authority must be task_system.episode_result")
        _require_text(self.result_id, "EpisodeResult requires result_id")
        _require_text(self.episode_id, "EpisodeResult requires episode_id")
        _require_text(self.task_environment_id, "EpisodeResult requires task_environment_id")
        if self.status == "blocked" and not self.blocker:
            raise ValueError("blocked EpisodeResult requires blocker")
        if self.status in {"completed", "partial"} and not (
            self.summary
            or self.work_product_candidates
            or self.state_update_proposals
            or self.plan_patch
            or self.todo_patch
            or self.artifact_refs
            or self.evidence_refs
        ):
            raise ValueError("EpisodeResult completion requires summary, products, proposals, patches, artifacts, or evidence")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["work_product_candidates"] = [dict(item) for item in self.work_product_candidates]
        payload["state_update_proposals"] = [dict(item) for item in self.state_update_proposals]
        payload["memory_candidates"] = [dict(item) for item in self.memory_candidates]
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["evidence_refs"] = list(self.evidence_refs)
        return _drop_empty(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EpisodeResult":
        data = dict(payload or {})
        return cls(
            result_id=str(data.get("result_id") or ""),
            episode_id=str(data.get("episode_id") or ""),
            task_environment_id=str(data.get("task_environment_id") or ""),
            status=str(data.get("status") or "failed"),  # type: ignore[arg-type]
            summary=str(data.get("summary") or ""),
            work_product_candidates=tuple(dict(item) for item in list(data.get("work_product_candidates") or []) if isinstance(item, dict)),
            state_update_proposals=tuple(dict(item) for item in list(data.get("state_update_proposals") or []) if isinstance(item, dict)),
            plan_patch=dict(data.get("plan_patch") or {}),
            todo_patch=dict(data.get("todo_patch") or {}),
            memory_candidates=tuple(dict(item) for item in list(data.get("memory_candidates") or []) if isinstance(item, dict)),
            artifact_refs=_tuple_of_strings(data.get("artifact_refs")),
            evidence_refs=_tuple_of_strings(data.get("evidence_refs")),
            blocker=str(data.get("blocker") or ""),
            continuation_hint=str(data.get("continuation_hint") or ""),
            output_contract_version=str(data.get("output_contract_version") or ""),
            diagnostics=dict(data.get("diagnostics") or {}),
            authority=str(data.get("authority") or "task_system.episode_result"),
        )


def _require_text(value: str, message: str) -> None:
    if not str(value or "").strip():
        raise ValueError(message)


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
