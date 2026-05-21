from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .protocol_boundary import is_internal_protocol_input_key


EXECUTOR_TYPES = {"agent", "human", "tool", "subgraph", "graph_unit"}


@dataclass(frozen=True, slots=True)
class NodeExecutorBinding:
    node_id: str
    default_executor: str = "agent"
    allowed_executors: tuple[str, ...] = ("agent",)
    selected_executor: str = "agent"
    override_policy: str = "before_dispatch"
    agent_profile_id: str = ""
    human_profile_id: str = ""
    tool_binding_id: str = ""
    subgraph_id: str = ""
    interaction_schema_id: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_graph.node_executor_binding"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_executors"] = list(self.allowed_executors)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


@dataclass(frozen=True, slots=True)
class NodeInputItem:
    input_key: str
    source_type: str
    source_node_id: str = ""
    source_edge_id: str = ""
    source_ref: str = ""
    content_type: str = ""
    content_ref: str = ""
    content_preview: str = ""
    required: bool = False
    usage_instruction: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_graph.node_input_item"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class StandardNodeInputPackage:
    package_id: str
    coordination_run_id: str
    node_id: str
    stage_id: str
    activation_id: str
    execution_permit_id: str
    task_instruction: str
    executor_instruction: str
    input_items: tuple[NodeInputItem, ...] = ()
    output_contract: dict[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ("submit_result",)
    handoff_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_graph.standard_node_input_package"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_items"] = [item.to_dict() for item in self.input_items]
        payload["output_contract"] = dict(self.output_contract)
        payload["allowed_actions"] = list(self.allowed_actions)
        payload["handoff_policy"] = dict(self.handoff_policy)
        payload["artifact_policy"] = dict(self.artifact_policy)
        payload["memory_policy"] = dict(self.memory_policy)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


@dataclass(frozen=True, slots=True)
class HumanWorkPacket:
    work_packet_id: str
    package_id: str
    title: str
    role_label: str
    task_brief: str
    material_sections: tuple[dict[str, Any], ...] = ()
    output_form_schema: dict[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    submit_policy: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_graph.human_work_packet"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["material_sections"] = [dict(item) for item in self.material_sections]
        payload["output_form_schema"] = dict(self.output_form_schema)
        payload["allowed_actions"] = list(self.allowed_actions)
        payload["submit_policy"] = dict(self.submit_policy)
        return payload


@dataclass(frozen=True, slots=True)
class StandardNodeResultPackage:
    result_package_id: str
    coordination_run_id: str
    node_id: str
    stage_id: str
    activation_id: str
    execution_permit_id: str
    executor_type: str
    outputs: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    memory_candidates: tuple[dict[str, Any], ...] = ()
    handoff_summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_graph.standard_node_result_package"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outputs"] = dict(self.outputs)
        payload["decisions"] = dict(self.decisions)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["memory_candidates"] = [dict(item) for item in self.memory_candidates]
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def build_node_executor_binding(
    *,
    node_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any] | None = None,
    agent_profile_id: str = "",
) -> NodeExecutorBinding:
    policy = {
        **dict(contract.get("executor_policy") or {}),
        **dict(dict(contract.get("metadata") or {}).get("executor_policy") or {}),
    }
    default_executor = _normalize_executor(policy.get("default_executor") or policy.get("executor") or "agent")
    allowed = tuple(
        dict.fromkeys(
            _normalize_executor(item)
            for item in list(policy.get("allowed_executors") or [default_executor])
            if _normalize_executor(item)
        )
    ) or (default_executor,)
    override = str(dict(explicit_inputs or {}).get("executor_override") or "").strip()
    selected = _normalize_executor(override) if override else default_executor
    diagnostics: dict[str, Any] = {}
    if selected not in allowed:
        diagnostics["executor_override_rejected"] = selected
        selected = default_executor
    return NodeExecutorBinding(
        node_id=node_id,
        default_executor=default_executor,
        allowed_executors=allowed,
        selected_executor=selected,
        override_policy=str(policy.get("override_policy") or "before_dispatch").strip() or "before_dispatch",
        agent_profile_id=str(policy.get("agent_profile_id") or agent_profile_id or "").strip(),
        human_profile_id=str(policy.get("human_profile_id") or "").strip(),
        tool_binding_id=str(policy.get("tool_binding_id") or "").strip(),
        subgraph_id=str(policy.get("subgraph_id") or "").strip(),
        interaction_schema_id=str(policy.get("interaction_schema_id") or "").strip(),
        diagnostics=diagnostics,
    )


def build_standard_node_input_package(
    *,
    coordination_run_id: str,
    stage_id: str,
    node_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
    dispatch_context: dict[str, Any],
    memory_snapshot: dict[str, Any],
    artifact_context_packet: dict[str, Any],
    revision_packet: dict[str, Any],
    handoff_packets: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> StandardNodeInputPackage:
    activation_id = str(dispatch_context.get("activation_id") or "")
    permit_id = str(dispatch_context.get("execution_permit_id") or "")
    input_items: list[NodeInputItem] = []
    input_items.extend(_explicit_input_items(explicit_inputs))
    input_items.extend(_memory_input_items(memory_snapshot))
    input_items.extend(_artifact_input_items(artifact_context_packet))
    input_items.extend(_revision_input_items(revision_packet))
    input_items.extend(_handoff_input_items(handoff_packets))
    required_inputs = {str(item).strip() for item in list(contract.get("required_inputs") or []) if str(item).strip()}
    output_mappings = [dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)]
    package_seed = {
        "coordination_run_id": coordination_run_id,
        "stage_id": stage_id,
        "node_id": node_id,
        "activation_id": activation_id,
        "permit_id": permit_id,
        "input_items": [item.to_dict() for item in input_items],
    }
    return StandardNodeInputPackage(
        package_id=f"nodeinput:{_short_hash(package_seed)}",
        coordination_run_id=coordination_run_id,
        node_id=node_id,
        stage_id=stage_id,
        activation_id=activation_id,
        execution_permit_id=permit_id,
        task_instruction=_task_instruction(contract=contract, node_id=node_id),
        executor_instruction=_executor_instruction(contract=contract),
        input_items=tuple(input_items),
        output_contract={
            "output_contract_id": str(contract.get("output_contract_id") or ""),
            "required_output_keys": [
                str(item.get("output_key") or "").strip()
                for item in output_mappings
                if str(item.get("output_key") or "").strip() and item.get("required") is not False
            ],
            "output_mappings": output_mappings,
        },
        allowed_actions=_allowed_actions(contract),
        handoff_policy={"input_bindings": [dict(item) for item in list(contract.get("input_bindings") or []) if isinstance(item, dict)]},
        artifact_policy=dict(contract.get("artifact_policy") or {}),
        memory_policy={
            "read": dict(contract.get("memory_read_policy") or {}),
            "write": dict(contract.get("memory_writeback_policy") or {}),
            "dynamic_read": dict(contract.get("dynamic_memory_read_policy") or {}),
        },
        diagnostics={
            "required_inputs": sorted(required_inputs),
            "missing_required_input_keys": sorted(required_inputs - {item.input_key for item in input_items}),
        },
    )


def render_human_work_packet(
    *,
    input_package: StandardNodeInputPackage,
    executor_binding: NodeExecutorBinding,
    contract: dict[str, Any],
) -> HumanWorkPacket:
    title = str(contract.get("title") or input_package.node_id or "节点执行").strip()
    role = str(contract.get("role") or executor_binding.human_profile_id or "人工执行者").strip()
    sections_by_type: dict[str, list[dict[str, Any]]] = {}
    for item in input_package.input_items:
        sections_by_type.setdefault(item.source_type, []).append(item.to_dict())
    sections = [
        {
            "section_id": source_type,
            "title": _source_type_title(source_type),
            "items": items,
        }
        for source_type, items in sections_by_type.items()
    ]
    return HumanWorkPacket(
        work_packet_id=f"humanwork:{_short_hash({'package_id': input_package.package_id, 'executor': executor_binding.to_dict()})}",
        package_id=input_package.package_id,
        title=f"代替节点执行：{title}",
        role_label=role,
        task_brief=input_package.task_instruction,
        material_sections=tuple(sections),
        output_form_schema={
            "output_contract": dict(input_package.output_contract),
            "fields": [
                {
                    "field_id": key,
                    "label": key,
                    "input_type": "textarea",
                    "required": True,
                }
                for key in list(input_package.output_contract.get("required_output_keys") or [])
            ],
            "decision_actions": list(input_package.allowed_actions),
        },
        allowed_actions=input_package.allowed_actions,
        submit_policy={
            "submit_as": "standard_node_result_package",
            "requires_activation_id": input_package.activation_id,
            "requires_execution_permit_id": input_package.execution_permit_id,
        },
    )


def build_standard_node_result_package(
    *,
    request_payload: dict[str, Any],
    event: dict[str, Any],
    outputs: dict[str, Any],
    artifact_refs: list[str] | tuple[str, ...],
    memory_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> StandardNodeResultPackage:
    standard_input = dict(request_payload.get("standard_input_package") or {})
    dispatch = dict(request_payload.get("dispatch_context") or {})
    diagnostics = dict(event.get("diagnostics") or {})
    decisions = {
        key: diagnostics.get(key)
        for key in ("verdict", "review_verdict", "decision", "commit_decision", "allow_commit")
        if key in diagnostics
    }
    handoff_summary = str(
        diagnostics.get("handoff_summary")
        or diagnostics.get("summary")
        or dict(outputs or {}).get("handoff_summary")
        or ""
    )
    payload_seed = {
        "request_id": str(request_payload.get("request_id") or ""),
        "event": {
            "task_run_id": str(event.get("task_run_id") or ""),
            "task_result_ref": str(event.get("task_result_ref") or ""),
            "agent_run_result_ref": str(event.get("agent_run_result_ref") or ""),
        },
    }
    return StandardNodeResultPackage(
        result_package_id=f"noderesult:{_short_hash(payload_seed)}",
        coordination_run_id=str(request_payload.get("coordination_run_id") or ""),
        node_id=str(request_payload.get("node_id") or ""),
        stage_id=str(request_payload.get("stage_id") or ""),
        activation_id=str(standard_input.get("activation_id") or dispatch.get("activation_id") or ""),
        execution_permit_id=str(standard_input.get("execution_permit_id") or dispatch.get("execution_permit_id") or ""),
        executor_type=str(request_payload.get("executor_type") or dict(request_payload.get("executor_binding") or {}).get("selected_executor") or "agent"),
        outputs=dict(outputs or {}),
        decisions={key: value for key, value in decisions.items() if value not in (None, "")},
        artifact_refs=tuple(str(item) for item in list(artifact_refs or []) if str(item)),
        memory_candidates=tuple(dict(item) for item in list(memory_candidates or []) if isinstance(item, dict)),
        handoff_summary=handoff_summary,
        diagnostics={
            "source_request_id": str(request_payload.get("request_id") or ""),
            "source_event_request_id": str(event.get("request_id") or ""),
            "accepted": bool(event.get("accepted") is True),
        },
    )


def _explicit_input_items(explicit_inputs: dict[str, Any]) -> list[NodeInputItem]:
    return [
        NodeInputItem(
            input_key=str(key),
            source_type="explicit",
            source_ref=f"explicit:{key}",
            content_type=_content_type(value),
            content_preview=_preview(value),
            required=False,
            usage_instruction="用户或上游运行显式传入的任务参数。",
            metadata={"value": value},
        )
        for key, value in sorted(dict(explicit_inputs or {}).items(), key=lambda item: str(item[0]))
        if not is_internal_protocol_input_key(str(key))
    ]


def _memory_input_items(memory_snapshot: dict[str, Any]) -> list[NodeInputItem]:
    records = [dict(item) for item in list(memory_snapshot.get("resolved_records") or []) if isinstance(item, dict)]
    refs = [str(item) for item in list(memory_snapshot.get("resolved_record_refs") or []) if str(item)]
    if not records and not refs:
        return []
    items: list[NodeInputItem] = []
    read_edges = [str(item) for item in list(memory_snapshot.get("read_edge_ids") or []) if str(item)]
    for index, record in enumerate(records):
        ref = str(record.get("version_id") or record.get("record_id") or record.get("work_memory_id") or (refs[index] if index < len(refs) else ""))
        items.append(
            NodeInputItem(
                input_key=str(record.get("collection") or record.get("collection_id") or f"memory_{index + 1}"),
                source_type="memory",
                source_edge_id=read_edges[0] if read_edges else "",
                source_ref=ref,
                content_type="memory_record",
                content_ref=ref,
                content_preview=_preview(record),
                required=True,
                usage_instruction=str(record.get("usage_instruction") or "作为本节点运行的定向记忆约束使用。"),
                metadata=record,
            )
        )
    if not items:
        items.append(
            NodeInputItem(
                input_key="memory_snapshot",
                source_type="memory",
                source_edge_id=read_edges[0] if read_edges else "",
                source_ref=str(memory_snapshot.get("snapshot_id") or ""),
                content_type="memory_snapshot",
                content_ref=str(memory_snapshot.get("snapshot_id") or ""),
                content_preview=", ".join(refs[:8]),
                required=True,
                usage_instruction="按记忆读边读取到的记录集合。",
                metadata={"resolved_record_refs": refs},
            )
        )
    return items


def _artifact_input_items(packet: dict[str, Any]) -> list[NodeInputItem]:
    refs = [str(item) for item in list(packet.get("artifact_refs") or []) if str(item)]
    edge_ids = [str(item) for item in list(packet.get("edge_ids") or []) if str(item)]
    source_nodes = [str(item) for item in list(packet.get("source_node_ids") or []) if str(item)]
    expanded = {str(key): str(value) for key, value in dict(packet.get("expanded_text_by_input_key") or {}).items() if str(key)}
    items: list[NodeInputItem] = []
    for key, text in expanded.items():
        items.append(
            NodeInputItem(
                input_key=key,
                source_type="artifact",
                source_node_id=source_nodes[0] if source_nodes else "",
                source_edge_id=edge_ids[0] if edge_ids else "",
                source_ref=str(packet.get("packet_id") or ""),
                content_type="artifact_text",
                content_ref=refs[0] if refs else "",
                content_preview=_preview(text),
                required=True,
                usage_instruction="作为边映射指定的产物上下文使用。",
                metadata={"artifact_refs": refs, "text": text, "expanded_by_runtime": True},
            )
        )
    for index, ref in enumerate(refs):
        text = _read_artifact_ref_text(ref)
        items.append(
            NodeInputItem(
                input_key=f"artifact_{index + 1}",
                source_type="artifact",
                source_node_id=source_nodes[0] if source_nodes else "",
                source_edge_id=edge_ids[0] if edge_ids else "",
                source_ref=str(packet.get("packet_id") or ""),
                content_type="artifact_text" if text else "artifact_ref",
                content_ref=ref,
                content_preview=_preview(text) if text else ref,
                required=not bool(expanded),
                usage_instruction="作为上游产物引用使用。",
                metadata={
                    "packet_id": str(packet.get("packet_id") or ""),
                    "artifact_ref": ref,
                    **({"text": text} if text else {}),
                    "expanded_by_runtime": bool(text),
                },
            )
        )
    return items


def _revision_input_items(packet: dict[str, Any]) -> list[NodeInputItem]:
    if not packet:
        return []
    return [
        NodeInputItem(
            input_key="revision_instruction",
            source_type="revision",
            source_node_id=str(packet.get("review_node_id") or packet.get("review_stage_id") or ""),
            source_edge_id=str(packet.get("revision_edge_id") or ""),
            source_ref=str(packet.get("revision_packet_id") or ""),
            content_type="revision_packet",
            content_ref=str(packet.get("revision_packet_id") or ""),
            content_preview=_preview(packet),
            required=True,
            usage_instruction="作为返修或重试的约束输入，必须处理其中列出的 required_changes。",
            metadata=packet,
        )
    ]


def _handoff_input_items(packets: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[NodeInputItem]:
    items: list[NodeInputItem] = []
    for index, packet in enumerate(packets):
        payload = dict(packet)
        items.append(
            NodeInputItem(
                input_key=str(payload.get("target_input_key") or payload.get("payload_contract_id") or f"handoff_{index + 1}"),
                source_type="upstream_result",
                source_node_id=str(payload.get("source_node_id") or ""),
                source_edge_id=str(payload.get("edge_id") or ""),
                source_ref=str(payload.get("source_result_record_id") or payload.get("packet_id") or ""),
                content_type="handoff_packet",
                content_ref=str(payload.get("packet_id") or ""),
                content_preview=str(payload.get("summary") or "")[:600],
                required=bool(payload.get("ack_required", True) is not False),
                usage_instruction=str(payload.get("usage_instruction") or "作为上游节点交接材料使用。"),
                metadata=payload,
            )
        )
    return items


def _task_instruction(*, contract: dict[str, Any], node_id: str) -> str:
    title = str(contract.get("title") or node_id).strip()
    role = str(contract.get("role") or "").strip()
    if role:
        return f"执行节点“{title}”。你的节点职责是：{role}。"
    return f"执行节点“{title}”。请严格依据输入包完成本节点输出契约。"


def _executor_instruction(*, contract: dict[str, Any]) -> str:
    instruction = str(dict(contract.get("executor_policy") or {}).get("instruction") or "").strip()
    if instruction:
        return instruction
    return "只使用本节点输入包中的材料完成输出契约，不要猜测未提供的上下文。"


def _allowed_actions(contract: dict[str, Any]) -> tuple[str, ...]:
    policy = dict(contract.get("executor_policy") or {})
    actions = [str(item).strip() for item in list(policy.get("allowed_actions") or []) if str(item).strip()]
    if actions:
        return tuple(dict.fromkeys(actions))
    review_policy = dict(contract.get("review_gate_policy") or {})
    if review_policy:
        return ("pass", "revise", "reject", "submit_result")
    return ("submit_result",)


def _source_type_title(source_type: str) -> str:
    return {
        "explicit": "任务参数",
        "memory": "定向记忆",
        "artifact": "产物材料",
        "revision": "返修要求",
        "upstream_result": "上游交接",
    }.get(source_type, source_type or "输入材料")


def _normalize_executor(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"ai", "model", "agent_runtime"}:
        text = "agent"
    if text in {"manual", "user", "operator"}:
        text = "human"
    if text in {"nested_graph", "graphunit", "graph-unit"}:
        text = "graph_unit"
    return text if text in EXECUTOR_TYPES else ""


def _content_type(value: Any) -> str:
    if isinstance(value, str):
        return "text"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _preview(value: Any, *, max_chars: int = 600) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = " ".join(text.split())
    return text[:max_chars]


def _read_artifact_ref_text(ref: str) -> str:
    raw = str(ref or "").strip()
    if not raw.startswith("artifact:"):
        return ""
    rel = raw[len("artifact:") :]
    candidates = [Path(rel)]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / rel)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def _short_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
