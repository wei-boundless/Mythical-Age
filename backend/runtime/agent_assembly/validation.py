from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .boundary import CONTROL_CONTEXT_KEYS
from .models import AgentInvocation, AgentAssemblyContract, ExecutionPermit, WorkOrder


@dataclass(frozen=True, slots=True, kw_only=True)
class AssemblyValidationIssue:
    code: str
    message: str
    severity: str = "error"
    field_name: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class AssemblyValidationReport:
    passed: bool
    issues: tuple[AssemblyValidationIssue, ...] = ()
    authority: str = "runtime.agent_assembly.validation"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [item.to_dict() for item in self.issues]
        return payload


def validate_work_order(work_order: WorkOrder) -> AssemblyValidationReport:
    issues: list[AssemblyValidationIssue] = []
    if not str(work_order.work_kind or "").strip():
        issues.append(_issue("missing_work_kind", "工作单缺少 work_kind", field_name="work_kind"))
    if not str(work_order.task_ref or "").strip():
        issues.append(_issue("missing_task_ref", "工作单缺少 task_ref", field_name="task_ref"))
    if not str(work_order.executor_type or "").strip():
        issues.append(_issue("missing_executor_type", "工作单缺少 executor_type", field_name="executor_type"))
    if work_order.work_kind in {"node", "human", "subruntime"} and not str(work_order.node_id or work_order.stage_id or "").strip():
        issues.append(_issue("missing_node_id", "节点工作单缺少 node_id 或 stage_id", field_name="node_id"))
    return AssemblyValidationReport(passed=not issues, issues=tuple(issues))


def validate_assembly_contract(contract: AgentAssemblyContract) -> AssemblyValidationReport:
    issues: list[AssemblyValidationIssue] = []
    if not str(contract.work_order_id or "").strip():
        issues.append(_issue("missing_work_order_id", "组装契约缺少 work_order_id", field_name="work_order_id"))
    if not str(contract.task_ref or "").strip():
        issues.append(_issue("missing_task_ref", "组装契约缺少 task_ref", field_name="task_ref"))
    if not str(contract.agent_id or "").strip():
        issues.append(_issue("missing_agent_id", "组装契约缺少 agent_id", field_name="agent_id"))
    if not str(contract.agent_profile_id or "").strip():
        issues.append(_issue("missing_agent_profile_id", "组装契约缺少 agent_profile_id", field_name="agent_profile_id"))
    if not contract.prompt_assembly:
        issues.append(_issue("missing_prompt_assembly", "组装契约缺少 prompt_assembly", field_name="prompt_assembly"))
    if not contract.ports:
        issues.append(_issue("missing_ports", "组装契约缺少 ports", field_name="ports"))
    if contract.executor_type == "agent" and not (
        contract.capability_binding.allowed_operations
        or contract.capability_binding.visible_tools
        or contract.output_boundary.selected_channel
        or (contract.prompt_assembly and contract.prompt_assembly.instruction_text.strip())
    ):
        issues.append(_issue("empty_capability_binding", "组装契约缺少可执行能力或输出契约", field_name="capability_binding"))
    return AssemblyValidationReport(passed=not issues, issues=tuple(issues))


def validate_execution_permit(permit: ExecutionPermit) -> AssemblyValidationReport:
    issues: list[AssemblyValidationIssue] = []
    if not str(permit.assembly_id or "").strip():
        issues.append(_issue("missing_assembly_id", "执行许可缺少 assembly_id", field_name="assembly_id"))
    if not str(permit.work_order_id or "").strip():
        issues.append(_issue("missing_work_order_id", "执行许可缺少 work_order_id", field_name="work_order_id"))
    if not permit.allowed_operations and not permit.visible_tools and permit.executor_type == "agent":
        issues.append(_issue("empty_permit_scope", "执行许可没有任何可见或可执行能力", field_name="allowed_operations"))
    return AssemblyValidationReport(passed=not issues, issues=tuple(issues))


def validate_agent_invocation(invocation: AgentInvocation) -> AssemblyValidationReport:
    issues: list[AssemblyValidationIssue] = []
    if not str(invocation.work_order_id or "").strip():
        issues.append(_issue("missing_work_order_id", "AgentInvocation 缺少 work_order_id", field_name="work_order_id"))
    if not str(invocation.assembly_id or "").strip():
        issues.append(_issue("missing_assembly_id", "AgentInvocation 缺少 assembly_id", field_name="assembly_id"))
    if not invocation.assembly_contract:
        issues.append(_issue("missing_assembly_contract", "AgentInvocation 缺少 assembly_contract", field_name="assembly_contract"))
    if not invocation.execution_permit and invocation.executor_type == "agent":
        issues.append(_issue("missing_execution_permit", "AgentInvocation 缺少 execution_permit", field_name="execution_permit"))
    leaked_keys = sorted(key for key in dict(invocation.model_context or {}) if key in CONTROL_CONTEXT_KEYS)
    if leaked_keys:
        issues.append(
            _issue(
                "model_context_control_leak",
                "AgentInvocation model_context 泄露 runtime control 字段",
                field_name="model_context",
                leaked_keys=leaked_keys,
            )
        )
    permit_agent = str(dict(invocation.execution_permit or {}).get("agent_id") or "").strip()
    if permit_agent and invocation.agent_id and permit_agent != invocation.agent_id:
        issues.append(
            _issue(
                "permit_agent_mismatch",
                "AgentInvocation execution_permit 与 assembly agent_id 不一致",
                field_name="execution_permit.agent_id",
                permit_agent_id=permit_agent,
                invocation_agent_id=invocation.agent_id,
            )
        )
    return AssemblyValidationReport(passed=not issues, issues=tuple(issues))


def _issue(code: str, message: str, *, field_name: str = "", **context: Any) -> AssemblyValidationIssue:
    return AssemblyValidationIssue(code=code, message=message, field_name=field_name, context=dict(context))
