from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .ids import (
    build_assembly_contract_id,
    build_execution_permit_id,
    build_execution_result_id,
    build_node_result_envelope_id,
    build_work_order_id,
    safe_id,
    stable_hash,
)


def _dict_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _tuple_of_str(values: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in list(values or []) if str(item).strip())


def _tuple_of_dict(values: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(values or []) if isinstance(item, dict))


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkOrder:
    work_order_id: str
    work_kind: str
    task_ref: str
    executor_type: str = "agent"
    coordination_run_id: str = ""
    thread_id: str = ""
    root_task_run_id: str = ""
    stage_id: str = ""
    node_id: str = ""
    agent_id: str = ""
    agent_profile_id: str = ""
    runtime_lane: str = ""
    message: str = ""
    explicit_inputs: dict[str, Any] = field(default_factory=dict)
    input_package: dict[str, Any] = field(default_factory=dict)
    graph_state: dict[str, Any] = field(default_factory=dict)
    executor_binding: dict[str, Any] = field(default_factory=dict)
    current_turn_context: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    stream_policy: dict[str, Any] = field(default_factory=dict)
    artifact_root: str = ""
    artifact_targets: tuple[dict[str, Any], ...] = ()
    output_contract_id: str = ""
    expected_outputs: tuple[dict[str, Any], ...] = ()
    working_memory_refs: tuple[str, ...] = ()
    dispatch_context: dict[str, Any] = field(default_factory=dict)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    artifact_context_packet: dict[str, Any] = field(default_factory=dict)
    revision_packet: dict[str, Any] = field(default_factory=dict)
    handoff_packet_refs: tuple[str, ...] = ()
    timeline_result_policy: dict[str, Any] = field(default_factory=dict)
    human_work_packet: dict[str, Any] = field(default_factory=dict)
    a2a_payload: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    authority: str = "runtime.agent_assembly.work_order"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_assembly.work_order":
            raise ValueError("WorkOrder authority must be runtime.agent_assembly.work_order")
        if not self.work_kind:
            raise ValueError("WorkOrder requires work_kind")
        if not self.task_ref:
            raise ValueError("WorkOrder requires task_ref")
        if not self.work_order_id:
            object.__setattr__(self, "work_order_id", build_work_order_id(self.work_kind, self.identity_payload()))
        if not self.thread_id:
            object.__setattr__(self, "thread_id", self.coordination_run_id or self.work_order_id)
        if not self.node_id:
            object.__setattr__(self, "node_id", self.stage_id or self.work_order_id)
        if not self.message:
            if self.work_kind == "direct":
                object.__setattr__(self, "message", "请继续执行当前用户任务。")
            else:
                object.__setattr__(self, "message", f"继续执行任务图节点：{self.node_id}。")
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", self._build_idempotency_key())

    def identity_payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind,
            "task_ref": self.task_ref,
            "executor_type": self.executor_type,
            "coordination_run_id": self.coordination_run_id,
            "thread_id": self.thread_id,
            "root_task_run_id": self.root_task_run_id,
            "stage_id": self.stage_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "runtime_lane": self.runtime_lane,
            "explicit_inputs": dict(self.explicit_inputs),
            "input_package": dict(self.input_package),
            "executor_binding": dict(self.executor_binding),
            "dispatch_context": dict(self.dispatch_context),
        }

    def _build_idempotency_key(self) -> str:
        dispatch_event_id = str(self.dispatch_context.get("dispatch_event_id") or "").strip()
        if dispatch_event_id:
            return f"{self.coordination_run_id}:{self.node_id}:dispatch:{dispatch_event_id}"
        clock_seq = str(self.dispatch_context.get("clock_seq") or "").strip()
        if clock_seq:
            return f"{self.coordination_run_id}:{self.node_id}:clock:{clock_seq}:{stable_hash(self.explicit_inputs)}"
        return f"{self.coordination_run_id}:{self.node_id}:{stable_hash(self.explicit_inputs)}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["explicit_inputs"] = dict(self.explicit_inputs)
        payload["input_package"] = dict(self.input_package)
        payload["graph_state"] = dict(self.graph_state)
        payload["executor_binding"] = dict(self.executor_binding)
        payload["current_turn_context"] = dict(self.current_turn_context)
        payload["artifact_policy"] = dict(self.artifact_policy)
        payload["stream_policy"] = dict(self.stream_policy)
        payload["artifact_root"] = self.artifact_root
        payload["artifact_targets"] = [dict(item) for item in self.artifact_targets]
        payload["expected_outputs"] = [dict(item) for item in self.expected_outputs]
        payload["working_memory_refs"] = list(self.working_memory_refs)
        payload["dispatch_context"] = dict(self.dispatch_context)
        payload["memory_snapshot"] = dict(self.memory_snapshot)
        payload["artifact_context_packet"] = dict(self.artifact_context_packet)
        payload["revision_packet"] = dict(self.revision_packet)
        payload["handoff_packet_refs"] = list(self.handoff_packet_refs)
        payload["timeline_result_policy"] = dict(self.timeline_result_policy)
        payload["human_work_packet"] = dict(self.human_work_packet)
        payload["a2a_payload"] = dict(self.a2a_payload)
        payload["runtime_assembly"] = dict(self.runtime_assembly)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkOrder":
        return cls(
            work_order_id=str(payload.get("work_order_id") or payload.get("request_id") or ""),
            work_kind=str(payload.get("work_kind") or payload.get("work_order_kind") or ("direct" if not payload.get("stage_id") else "node")),
            task_ref=str(payload.get("task_ref") or payload.get("next_task_ref") or ""),
            executor_type=str(payload.get("executor_type") or dict(payload.get("executor_binding") or {}).get("selected_executor") or "agent"),
            coordination_run_id=str(payload.get("coordination_run_id") or ""),
            thread_id=str(payload.get("thread_id") or payload.get("coordination_run_id") or ""),
            root_task_run_id=str(payload.get("root_task_run_id") or ""),
            stage_id=str(payload.get("stage_id") or ""),
            node_id=str(payload.get("node_id") or payload.get("stage_id") or ""),
            agent_id=str(payload.get("agent_id") or ""),
            agent_profile_id=str(payload.get("agent_profile_id") or ""),
            runtime_lane=str(payload.get("runtime_lane") or ""),
            message=str(payload.get("message") or ""),
            explicit_inputs=_dict_payload(payload.get("explicit_inputs")),
            input_package=_dict_payload(payload.get("input_package") or payload.get("standard_input_package")),
            graph_state=_dict_payload(payload.get("graph_state")),
            executor_binding=_dict_payload(payload.get("executor_binding")),
            current_turn_context=_dict_payload(payload.get("current_turn_context")),
            artifact_policy=_dict_payload(payload.get("artifact_policy")),
            stream_policy=_dict_payload(payload.get("stream_policy")),
            artifact_root=str(payload.get("artifact_root") or ""),
            artifact_targets=_tuple_of_dict(payload.get("artifact_targets")),
            output_contract_id=str(payload.get("output_contract_id") or ""),
            expected_outputs=_tuple_of_dict(payload.get("expected_outputs")),
            working_memory_refs=_tuple_of_str(payload.get("working_memory_refs")),
            dispatch_context=_dict_payload(payload.get("dispatch_context")),
            memory_snapshot=_dict_payload(payload.get("memory_snapshot")),
            artifact_context_packet=_dict_payload(payload.get("artifact_context_packet")),
            revision_packet=_dict_payload(payload.get("revision_packet")),
            handoff_packet_refs=_tuple_of_str(payload.get("handoff_packet_refs")),
            timeline_result_policy=_dict_payload(payload.get("timeline_result_policy")),
            human_work_packet=_dict_payload(payload.get("human_work_packet")),
            a2a_payload=_dict_payload(payload.get("a2a_payload")),
            runtime_assembly=_dict_payload(payload.get("runtime_assembly")),
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectWorkOrder(WorkOrder):
    work_kind: str = "direct"
    authority: str = "runtime.agent_assembly.work_order"

    def __post_init__(self) -> None:
        WorkOrder.__post_init__(self)
        if self.work_kind != "direct":
            object.__setattr__(self, "work_kind", "direct")


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeWorkOrder(WorkOrder):
    work_kind: str = "node"
    authority: str = "runtime.agent_assembly.work_order"

    def __post_init__(self) -> None:
        WorkOrder.__post_init__(self)
        if self.work_kind != "node":
            object.__setattr__(self, "work_kind", "node")


@dataclass(frozen=True, slots=True, kw_only=True)
class HumanWorkOrder(WorkOrder):
    work_kind: str = "human"
    executor_type: str = "human"
    authority: str = "runtime.agent_assembly.work_order"

    def __post_init__(self) -> None:
        WorkOrder.__post_init__(self)
        if self.work_kind != "human":
            object.__setattr__(self, "work_kind", "human")
        if self.executor_type != "human":
            object.__setattr__(self, "executor_type", "human")


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphModuleWorkOrder(WorkOrder):
    work_kind: str = "graph_module"
    executor_type: str = "graph_module"
    authority: str = "runtime.agent_assembly.work_order"

    def __post_init__(self) -> None:
        WorkOrder.__post_init__(self)
        if self.work_kind != "graph_module":
            object.__setattr__(self, "work_kind", "graph_module")
        if self.executor_type != "graph_module":
            object.__setattr__(self, "executor_type", "graph_module")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssemblyPort:
    port_id: str
    port_kind: str
    mode: str = "input"
    required: bool = True
    ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryAssemblyBinding:
    read_scope: dict[str, Any] = field(default_factory=dict)
    write_scope: dict[str, Any] = field(default_factory=dict)
    snapshot_ref: str = ""
    durable_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityAssemblyBinding:
    allowed_operations: tuple[str, ...] = ()
    visible_tools: tuple[str, ...] = ()
    dispatchable_tools: tuple[str, ...] = ()
    mcp_routes: tuple[str, ...] = ()
    delegated_agent_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_operations"] = list(self.allowed_operations)
        payload["visible_tools"] = list(self.visible_tools)
        payload["dispatchable_tools"] = list(self.dispatchable_tools)
        payload["mcp_routes"] = list(self.mcp_routes)
        payload["delegated_agent_ids"] = list(self.delegated_agent_ids)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class RolePromptBinding:
    role_prompt_id: str = ""
    role_name: str = ""
    role_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputBoundaryBinding:
    boundary_id: str = ""
    selected_channel: str = ""
    canonical_state: str = ""
    persist_policy: str = ""
    finalization_policy: str = ""
    fallback_reason: str = ""
    leak_flags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["leak_flags"] = list(self.leak_flags)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptAssemblyContract:
    prompt_id: str
    role_name: str
    role_summary: str
    instruction_text: str
    visible_sections: tuple[AssemblyPort, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["visible_sections"] = [item.to_dict() for item in self.visible_sections]
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["required_outputs"] = list(self.required_outputs)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentAssemblyContract:
    assembly_id: str
    work_order_id: str
    work_kind: str
    task_ref: str
    executor_type: str = "agent"
    coordination_run_id: str = ""
    thread_id: str = ""
    root_task_run_id: str = ""
    stage_id: str = ""
    node_id: str = ""
    agent_id: str = ""
    agent_profile_id: str = ""
    runtime_lane: str = ""
    model_profile_id: str = ""
    prompt_assembly: PromptAssemblyContract | None = None
    memory_binding: MemoryAssemblyBinding = field(default_factory=MemoryAssemblyBinding)
    capability_binding: CapabilityAssemblyBinding = field(default_factory=CapabilityAssemblyBinding)
    role_prompt_binding: RolePromptBinding = field(default_factory=RolePromptBinding)
    output_boundary: OutputBoundaryBinding = field(default_factory=OutputBoundaryBinding)
    ports: tuple[AssemblyPort, ...] = ()
    execution_contract_ref: str = ""
    current_turn_context: dict[str, Any] = field(default_factory=dict)
    work_order: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    stream_policy: dict[str, Any] = field(default_factory=dict)
    dispatch_context: dict[str, Any] = field(default_factory=dict)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    artifact_context_packet: dict[str, Any] = field(default_factory=dict)
    revision_packet: dict[str, Any] = field(default_factory=dict)
    human_work_packet: dict[str, Any] = field(default_factory=dict)
    a2a_payload: dict[str, Any] = field(default_factory=dict)
    executor_binding: dict[str, Any] = field(default_factory=dict)
    graph_state: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)
    model_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.contract"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_assembly.contract":
            raise ValueError("AgentAssemblyContract authority must be runtime.agent_assembly.contract")
        if not self.assembly_id:
            object.__setattr__(self, "assembly_id", build_assembly_contract_id(self.work_order_id or self.work_kind, self.identity_payload()))
        if not self.work_order_id:
            raise ValueError("AgentAssemblyContract requires work_order_id")
        if not self.work_kind:
            raise ValueError("AgentAssemblyContract requires work_kind")
        if not self.task_ref:
            raise ValueError("AgentAssemblyContract requires task_ref")
        if not self.agent_id:
            raise ValueError("AgentAssemblyContract requires agent_id")
        if not self.agent_profile_id:
            raise ValueError("AgentAssemblyContract requires agent_profile_id")
        if not self.prompt_assembly:
            object.__setattr__(self, "prompt_assembly", PromptAssemblyContract(
                prompt_id=f"prompt:{safe_id(self.assembly_id)}",
                role_name="执行代理",
                role_summary="你负责完成当前工作要求并交付可验证结果。",
                instruction_text="你是一名执行代理。你只负责完成当前工作要求，不扩展无关内容。",
            ))
        if not self.execution_contract_ref:
            object.__setattr__(self, "execution_contract_ref", self.assembly_id)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "work_kind": self.work_kind,
            "task_ref": self.task_ref,
            "executor_type": self.executor_type,
            "coordination_run_id": self.coordination_run_id,
            "thread_id": self.thread_id,
            "root_task_run_id": self.root_task_run_id,
            "stage_id": self.stage_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "runtime_lane": self.runtime_lane,
            "model_profile_id": self.model_profile_id,
            "memory_binding": self.memory_binding.to_dict(),
            "capability_binding": self.capability_binding.to_dict(),
            "role_prompt_binding": self.role_prompt_binding.to_dict(),
            "output_boundary": self.output_boundary.to_dict(),
            "ports": [port.to_dict() for port in self.ports],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prompt_assembly"] = self.prompt_assembly.to_dict() if self.prompt_assembly is not None else None
        payload["memory_binding"] = self.memory_binding.to_dict()
        payload["capability_binding"] = self.capability_binding.to_dict()
        payload["role_prompt_binding"] = self.role_prompt_binding.to_dict()
        payload["output_boundary"] = self.output_boundary.to_dict()
        payload["ports"] = [port.to_dict() for port in self.ports]
        payload["current_turn_context"] = dict(self.current_turn_context)
        payload["work_order"] = dict(self.work_order)
        payload["artifact_policy"] = dict(self.artifact_policy)
        payload["stream_policy"] = dict(self.stream_policy)
        payload["dispatch_context"] = dict(self.dispatch_context)
        payload["memory_snapshot"] = dict(self.memory_snapshot)
        payload["artifact_context_packet"] = dict(self.artifact_context_packet)
        payload["revision_packet"] = dict(self.revision_packet)
        payload["human_work_packet"] = dict(self.human_work_packet)
        payload["a2a_payload"] = dict(self.a2a_payload)
        payload["executor_binding"] = dict(self.executor_binding)
        payload["graph_state"] = dict(self.graph_state)
        payload["runtime_assembly"] = dict(self.runtime_assembly)
        payload["model_context"] = dict(self.model_context)
        payload["metadata"] = dict(self.metadata)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPermit:
    permit_id: str
    assembly_id: str
    work_order_id: str
    executor_type: str = "agent"
    agent_id: str = ""
    agent_profile_id: str = ""
    allowed_operations: tuple[str, ...] = ()
    visible_tools: tuple[str, ...] = ()
    dispatchable_tools: tuple[str, ...] = ()
    mcp_routes: tuple[str, ...] = ()
    delegated_agent_ids: tuple[str, ...] = ()
    sandbox_mode: str = ""
    approval_state: str = ""
    operation_gate_ref: str = ""
    tool_gate_ref: str = ""
    model_visible_tool_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.execution_permit"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_assembly.execution_permit":
            raise ValueError("ExecutionPermit authority must be runtime.agent_assembly.execution_permit")
        if not self.permit_id:
            object.__setattr__(self, "permit_id", build_execution_permit_id(self.assembly_id or self.work_order_id, self.identity_payload()))
        if not self.assembly_id:
            raise ValueError("ExecutionPermit requires assembly_id")
        if not self.work_order_id:
            raise ValueError("ExecutionPermit requires work_order_id")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "work_order_id": self.work_order_id,
            "executor_type": self.executor_type,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "allowed_operations": list(self.allowed_operations),
            "visible_tools": list(self.visible_tools),
            "dispatchable_tools": list(self.dispatchable_tools),
            "mcp_routes": list(self.mcp_routes),
            "delegated_agent_ids": list(self.delegated_agent_ids),
            "sandbox_mode": self.sandbox_mode,
            "approval_state": self.approval_state,
            "operation_gate_ref": self.operation_gate_ref,
            "tool_gate_ref": self.tool_gate_ref,
            "model_visible_tool_refs": list(self.model_visible_tool_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_operations"] = list(self.allowed_operations)
        payload["visible_tools"] = list(self.visible_tools)
        payload["dispatchable_tools"] = list(self.dispatchable_tools)
        payload["mcp_routes"] = list(self.mcp_routes)
        payload["delegated_agent_ids"] = list(self.delegated_agent_ids)
        payload["model_visible_tool_refs"] = list(self.model_visible_tool_refs)
        payload["diagnostics"] = dict(self.diagnostics)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentInvocation:
    invocation_id: str
    work_order_id: str
    assembly_id: str
    task_ref: str
    executor_type: str = "agent"
    agent_id: str = ""
    agent_profile_id: str = ""
    runtime_lane: str = ""
    work_order: dict[str, Any] = field(default_factory=dict)
    assembly_contract: dict[str, Any] = field(default_factory=dict)
    execution_permit: dict[str, Any] = field(default_factory=dict)
    runtime_control: dict[str, Any] = field(default_factory=dict)
    model_context: dict[str, Any] = field(default_factory=dict)
    task_selection: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.invocation"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_assembly.invocation":
            raise ValueError("AgentInvocation authority must be runtime.agent_assembly.invocation")
        if not self.work_order_id:
            raise ValueError("AgentInvocation requires work_order_id")
        if not self.assembly_id:
            raise ValueError("AgentInvocation requires assembly_id")
        if not self.task_ref:
            raise ValueError("AgentInvocation requires task_ref")
        if not self.invocation_id:
            object.__setattr__(
                self,
                "invocation_id",
                f"agent-invocation:{stable_hash(self.identity_payload())}",
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "assembly_id": self.assembly_id,
            "task_ref": self.task_ref,
            "executor_type": self.executor_type,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "runtime_lane": self.runtime_lane,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["work_order"] = dict(self.work_order)
        payload["assembly_contract"] = dict(self.assembly_contract)
        payload["execution_permit"] = dict(self.execution_permit)
        payload["runtime_control"] = dict(self.runtime_control)
        payload["model_context"] = dict(self.model_context)
        payload["current_turn_context"] = dict(self.model_context)
        payload["task_selection"] = dict(self.task_selection)
        payload["diagnostics"] = dict(self.diagnostics)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionResult:
    execution_result_id: str
    assembly_id: str
    work_order_id: str
    executor_type: str = "agent"
    content: str = ""
    answer_channel: str = ""
    answer_source: str = ""
    answer_canonical_state: str = ""
    answer_persist_policy: str = ""
    answer_finalization_policy: str = ""
    answer_fallback_reason: str = ""
    answer_leak_flags: tuple[str, ...] = ()
    status: str = "completed"
    result_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    task_summary_refs: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.execution_result"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_assembly.execution_result":
            raise ValueError("ExecutionResult authority must be runtime.agent_assembly.execution_result")
        if not self.execution_result_id:
            object.__setattr__(self, "execution_result_id", build_execution_result_id(self.assembly_id or self.work_order_id, self.identity_payload()))
        if not self.assembly_id:
            raise ValueError("ExecutionResult requires assembly_id")
        if not self.work_order_id:
            raise ValueError("ExecutionResult requires work_order_id")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "work_order_id": self.work_order_id,
            "executor_type": self.executor_type,
            "content": self.content,
            "answer_channel": self.answer_channel,
            "answer_source": self.answer_source,
            "status": self.status,
            "result_refs": list(self.result_refs),
            "artifact_refs": list(self.artifact_refs),
            "output_refs": list(self.output_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["answer_leak_flags"] = list(self.answer_leak_flags)
        payload["result_refs"] = list(self.result_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["output_refs"] = list(self.output_refs)
        payload["task_summary_refs"] = [dict(item) for item in self.task_summary_refs]
        payload["diagnostics"] = dict(self.diagnostics)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeResultEnvelope:
    envelope_id: str
    coordination_run_id: str
    work_order_id: str
    assembly_id: str
    node_id: str
    stage_id: str = ""
    task_ref: str = ""
    executor_type: str = "agent"
    accepted: bool = True
    status: str = "completed"
    result_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    final_content: str = ""
    execution_result: ExecutionResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.node_result_envelope"

    def __post_init__(self) -> None:
        if self.authority != "runtime.agent_assembly.node_result_envelope":
            raise ValueError("NodeResultEnvelope authority must be runtime.agent_assembly.node_result_envelope")
        if not self.envelope_id:
            object.__setattr__(self, "envelope_id", build_node_result_envelope_id(self.coordination_run_id or self.node_id, self.node_id, self.identity_payload()))
        if not self.coordination_run_id:
            raise ValueError("NodeResultEnvelope requires coordination_run_id")
        if not self.work_order_id:
            raise ValueError("NodeResultEnvelope requires work_order_id")
        if not self.assembly_id:
            raise ValueError("NodeResultEnvelope requires assembly_id")
        if not self.node_id:
            raise ValueError("NodeResultEnvelope requires node_id")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "coordination_run_id": self.coordination_run_id,
            "work_order_id": self.work_order_id,
            "assembly_id": self.assembly_id,
            "node_id": self.node_id,
            "stage_id": self.stage_id,
            "task_ref": self.task_ref,
            "executor_type": self.executor_type,
            "accepted": self.accepted,
            "status": self.status,
            "result_refs": list(self.result_refs),
            "artifact_refs": list(self.artifact_refs),
            "output_refs": list(self.output_refs),
            "final_content": self.final_content,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result_refs"] = list(self.result_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["output_refs"] = list(self.output_refs)
        payload["execution_result"] = self.execution_result.to_dict() if self.execution_result is not None else None
        payload["diagnostics"] = dict(self.diagnostics)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphModuleInvocationContract:
    invocation_id: str
    kind: str
    work_order_id: str
    assembly_id: str
    executor_type: str = "graph_module"
    target_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.graph_module_invocation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphModuleResultEnvelope:
    result_id: str
    invocation_id: str
    kind: str
    work_order_id: str
    assembly_id: str
    status: str = "completed"
    content: str = ""
    result_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.agent_assembly.graph_module_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result_refs"] = list(self.result_refs)
        payload["artifact_refs"] = list(self.artifact_refs)
        payload["diagnostics"] = dict(self.diagnostics)
        payload["metadata"] = dict(self.metadata)
        return payload


