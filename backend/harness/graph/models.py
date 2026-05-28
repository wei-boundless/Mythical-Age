from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


GRAPH_HARNESS_CONFIG_SCHEMA_VERSION = "graph_harness_config.v1"
GRAPH_HARNESS_CONFIG_AUTHORITY = "harness.graph_harness_config"


@dataclass(frozen=True, slots=True)
class GraphHarnessConfig:
    config_id: str
    graph_id: str
    graph_title: str
    publish_version: str
    config_schema_version: str = GRAPH_HARNESS_CONFIG_SCHEMA_VERSION
    authority: str = GRAPH_HARNESS_CONFIG_AUTHORITY
    status: str = "published"
    content_hash: str = ""
    published_at: float = 0.0
    task_environment_id: str = ""
    root_task_ref: str = ""
    control: dict[str, Any] = field(default_factory=dict)
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    loop_frames: tuple[dict[str, Any], ...] = ()
    resources: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    contracts: dict[str, Any] = field(default_factory=dict)
    modules: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority_map: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.authority != GRAPH_HARNESS_CONFIG_AUTHORITY:
            raise ValueError("GraphHarnessConfig authority must be harness.graph_harness_config")
        if self.config_schema_version != GRAPH_HARNESS_CONFIG_SCHEMA_VERSION:
            raise ValueError("unsupported GraphHarnessConfig schema version")
        if not self.config_id:
            raise ValueError("GraphHarnessConfig requires config_id")
        if not self.graph_id:
            raise ValueError("GraphHarnessConfig requires graph_id")
        if self.status not in {"published", "archived"}:
            raise ValueError("GraphHarnessConfig status must be published or archived")

    def content_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("config_id", None)
        payload.pop("content_hash", None)
        payload.pop("published_at", None)
        return payload

    def expected_content_hash(self) -> str:
        return stable_hash(self.content_payload())

    def with_content_identity(self, *, config_id: str = "", published_at: float = 0.0) -> "GraphHarnessConfig":
        payload = self.to_dict()
        payload["content_hash"] = stable_hash(self.content_payload())
        if config_id:
            payload["config_id"] = config_id
        if published_at:
            payload["published_at"] = published_at
        return graph_harness_config_from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [dict(item) for item in self.nodes]
        payload["edges"] = [dict(item) for item in self.edges]
        payload["loop_frames"] = [dict(item) for item in self.loop_frames]
        payload["modules"] = [dict(item) for item in self.modules]
        return payload


@dataclass(frozen=True, slots=True)
class GraphRuntimeEnvelope:
    envelope_id: str
    graph_run_id: str
    task_run_id: str
    session_id: str
    config_id: str
    config_hash: str
    graph_id: str
    initial_inputs: dict[str, Any] = field(default_factory=dict)
    runtime_services_ref: str = ""
    permission_scope: dict[str, Any] = field(default_factory=dict)
    file_scope: dict[str, Any] = field(default_factory=dict)
    memory_scope: dict[str, Any] = field(default_factory=dict)
    sandbox_scope: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_runtime_envelope"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GraphLoopState:
    state_id: str
    graph_run_id: str
    task_run_id: str
    session_id: str
    config_id: str
    config_hash: str
    graph_id: str
    status: str = "created"
    node_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    edge_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    ready_node_ids: tuple[str, ...] = ()
    running_node_ids: tuple[str, ...] = ()
    completed_node_ids: tuple[str, ...] = ()
    failed_node_ids: tuple[str, ...] = ()
    blocked_node_ids: tuple[str, ...] = ()
    active_work_orders: dict[str, str] = field(default_factory=dict)
    result_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    event_cursor: int = -1
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.graph_loop_state"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ready_node_ids"] = list(self.ready_node_ids)
        payload["running_node_ids"] = list(self.running_node_ids)
        payload["completed_node_ids"] = list(self.completed_node_ids)
        payload["failed_node_ids"] = list(self.failed_node_ids)
        payload["blocked_node_ids"] = list(self.blocked_node_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphLoopState":
        return cls(
            state_id=str(payload.get("state_id") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            config_id=str(payload.get("config_id") or ""),
            config_hash=str(payload.get("config_hash") or ""),
            graph_id=str(payload.get("graph_id") or ""),
            status=str(payload.get("status") or "created"),
            node_states={str(key): dict(value) for key, value in dict(payload.get("node_states") or {}).items()},
            edge_states={str(key): dict(value) for key, value in dict(payload.get("edge_states") or {}).items()},
            ready_node_ids=tuple(str(item) for item in list(payload.get("ready_node_ids") or []) if str(item)),
            running_node_ids=tuple(str(item) for item in list(payload.get("running_node_ids") or []) if str(item)),
            completed_node_ids=tuple(str(item) for item in list(payload.get("completed_node_ids") or []) if str(item)),
            failed_node_ids=tuple(str(item) for item in list(payload.get("failed_node_ids") or []) if str(item)),
            blocked_node_ids=tuple(str(item) for item in list(payload.get("blocked_node_ids") or []) if str(item)),
            active_work_orders={str(key): str(value) for key, value in dict(payload.get("active_work_orders") or {}).items()},
            result_index={str(key): dict(value) for key, value in dict(payload.get("result_index") or {}).items()},
            event_cursor=int(payload.get("event_cursor") or -1),
            terminal_reason=str(payload.get("terminal_reason") or ""),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "harness.graph_loop_state"),
        )


@dataclass(frozen=True, slots=True)
class NodeResultEnvelope:
    result_id: str
    graph_run_id: str
    task_run_id: str
    node_id: str
    work_order_id: str
    executor_type: str = "agent"
    status: str = "completed"
    outputs: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    memory_candidates: tuple[dict[str, Any], ...] = ()
    handoff_summary: str = ""
    error: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_node_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["memory_candidates"] = [dict(item) for item in self.memory_candidates]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NodeResultEnvelope":
        return cls(
            result_id=str(payload.get("result_id") or ""),
            graph_run_id=str(payload.get("graph_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            work_order_id=str(payload.get("work_order_id") or ""),
            executor_type=str(payload.get("executor_type") or "agent"),
            status=str(payload.get("status") or "completed"),
            outputs=dict(payload.get("outputs") or {}),
            decisions=dict(payload.get("decisions") or {}),
            artifact_refs=tuple(str(item) for item in list(payload.get("artifact_refs") or []) if str(item)),
            memory_candidates=tuple(dict(item) for item in list(payload.get("memory_candidates") or []) if isinstance(item, dict)),
            handoff_summary=str(payload.get("handoff_summary") or ""),
            error=dict(payload.get("error") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
            created_at=float(payload.get("created_at") or 0.0),
            authority=str(payload.get("authority") or "harness.graph_node_result_envelope"),
        )


@dataclass(frozen=True, slots=True)
class GraphResultEnvelope:
    result_id: str
    graph_run_id: str
    task_run_id: str
    graph_id: str
    config_id: str
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    node_result_refs: tuple[str, ...] = ()
    terminal_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "harness.graph_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["node_result_refs"] = list(self.node_result_refs)
        return payload


def graph_harness_config_from_dict(payload: dict[str, Any]) -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id=str(payload.get("config_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        graph_title=str(payload.get("graph_title") or payload.get("title") or ""),
        publish_version=str(payload.get("publish_version") or "published"),
        config_schema_version=str(payload.get("config_schema_version") or GRAPH_HARNESS_CONFIG_SCHEMA_VERSION),
        authority=str(payload.get("authority") or GRAPH_HARNESS_CONFIG_AUTHORITY),
        status=str(payload.get("status") or "published"),
        content_hash=str(payload.get("content_hash") or ""),
        published_at=float(payload.get("published_at") or 0.0),
        task_environment_id=str(payload.get("task_environment_id") or ""),
        root_task_ref=str(payload.get("root_task_ref") or ""),
        control=dict(payload.get("control") or {}),
        nodes=tuple(dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)),
        edges=tuple(dict(item) for item in list(payload.get("edges") or []) if isinstance(item, dict)),
        loop_frames=tuple(dict(item) for item in list(payload.get("loop_frames") or []) if isinstance(item, dict)),
        resources=dict(payload.get("resources") or {}),
        memory=dict(payload.get("memory") or {}),
        artifacts=dict(payload.get("artifacts") or {}),
        permissions=dict(payload.get("permissions") or {}),
        tools=dict(payload.get("tools") or {}),
        agents=dict(payload.get("agents") or {}),
        contracts=dict(payload.get("contracts") or {}),
        modules=tuple(dict(item) for item in list(payload.get("modules") or []) if isinstance(item, dict)),
        diagnostics=dict(payload.get("diagnostics") or {}),
        authority_map=dict(payload.get("authority_map") or {}),
        source_refs=dict(payload.get("source_refs") or {}),
    )


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_id(value: str, *, limit: int = 120) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "")).strip("_")
    return (safe or "graph")[:limit]

