from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.understanding import model_visible_semantic_contract


@dataclass(frozen=True, slots=True)
class ReadonlyPlannerRequest:
    request_id: str
    semantic_contract_ref: str
    semantic_contract: dict[str, Any] = field(default_factory=dict)
    workspace_observations: tuple[dict[str, Any], ...] = ()
    output_schema: dict[str, Any] = field(default_factory=dict)
    role_prompt: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.readonly_planner_request"

    def __post_init__(self) -> None:
        if self.authority != "runtime.readonly_planner_request":
            raise ValueError("ReadonlyPlannerRequest authority must be runtime.readonly_planner_request")
        if not self.request_id:
            raise ValueError("ReadonlyPlannerRequest requires request_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["semantic_contract"] = dict(self.semantic_contract or {})
        payload["workspace_observations"] = [dict(item) for item in self.workspace_observations]
        payload["output_schema"] = dict(self.output_schema or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class ReadonlyVerifierRequest:
    request_id: str
    semantic_contract_ref: str
    evidence_packet_ref: str = ""
    semantic_contract: dict[str, Any] = field(default_factory=dict)
    agent_plan_draft: dict[str, Any] = field(default_factory=dict)
    evidence_packet: dict[str, Any] = field(default_factory=dict)
    deliverable_validation: dict[str, Any] = field(default_factory=dict)
    obligation_validation: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    role_prompt: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.readonly_verifier_request"

    def __post_init__(self) -> None:
        if self.authority != "runtime.readonly_verifier_request":
            raise ValueError("ReadonlyVerifierRequest authority must be runtime.readonly_verifier_request")
        if not self.request_id:
            raise ValueError("ReadonlyVerifierRequest requires request_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["semantic_contract"] = dict(self.semantic_contract or {})
        payload["agent_plan_draft"] = dict(self.agent_plan_draft or {})
        payload["evidence_packet"] = dict(self.evidence_packet or {})
        payload["deliverable_validation"] = dict(self.deliverable_validation or {})
        payload["obligation_validation"] = dict(self.obligation_validation or {})
        payload["output_schema"] = dict(self.output_schema or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def build_readonly_planner_request(
    *,
    task_id: str,
    semantic_contract: dict[str, Any] | None,
    workspace_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> ReadonlyPlannerRequest:
    contract = model_visible_semantic_contract(semantic_contract)
    return ReadonlyPlannerRequest(
        request_id=f"readonly-planner-request:{task_id or 'runtime'}",
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        semantic_contract=contract,
        workspace_observations=tuple(dict(item) for item in list(workspace_observations or []) if isinstance(item, dict)),
        output_schema=_agent_plan_schema(),
        role_prompt=_planner_prompt(),
        diagnostics={
            "request_contract_only": True,
            "model_call_performed": False,
            "readonly": True,
            "expected_response_authority": "runtime.agent_plan_draft",
        },
    )


def build_readonly_verifier_request(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
    agent_plan_draft: dict[str, Any] | None = None,
    deliverable_validation: dict[str, Any] | None = None,
    obligation_validation: dict[str, Any] | None = None,
) -> ReadonlyVerifierRequest:
    contract = model_visible_semantic_contract(semantic_contract)
    evidence = dict(evidence_packet or {})
    return ReadonlyVerifierRequest(
        request_id=f"readonly-verifier-request:{task_run_id or 'runtime'}",
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        evidence_packet_ref=str(evidence.get("packet_id") or ""),
        semantic_contract=contract,
        agent_plan_draft=dict(agent_plan_draft or {}),
        evidence_packet=evidence,
        deliverable_validation=dict(deliverable_validation or {}),
        obligation_validation=dict(obligation_validation or {}),
        output_schema=_verification_review_schema(),
        role_prompt=_verifier_prompt(),
        diagnostics={
            "request_contract_only": True,
            "model_call_performed": False,
            "readonly": True,
            "expected_response_authority": "runtime.verification_review",
        },
    )


def _agent_plan_schema() -> dict[str, Any]:
    return {
        "authority": "runtime.agent_plan_draft",
        "required": ["plan_id", "task_goal_type", "semantic_contract_ref", "steps", "authority"],
        "step_required": ["step_id", "title", "purpose", "evidence_expectations"],
        "step_fields": {
            "required_operations": "list[str]",
            "expected_outputs": "list[str]",
            "contract_refs": "list[str]",
            "may_skip_if": "string",
        },
    }


def _verification_review_schema() -> dict[str, Any]:
    return {
        "authority": "runtime.verification_review",
        "required": ["review_id", "semantic_contract_ref", "passed", "authority"],
        "fields": {
            "blocking_issues": "list[str]",
            "contradictions": "list[str]",
            "limitations": "list[str]",
            "diagnostics": "object",
        },
    }


def _planner_prompt() -> str:
    return "\n".join(
        [
            "你是一名只读任务计划员。",
            "你只根据语义任务合同、用户显式流程和已经存在的真实观察生成可执行计划草稿。",
            "你不修改文件，不运行命令，不宣称已经完成任何执行动作。",
            "每个计划步骤必须说明目的、预期产物、需要的操作类型和证据期望。",
            "用户显式流程和禁令优先于任何默认习惯；如果计划无法覆盖合同，你必须明确写出限制或阻断。",
            "请只输出符合 runtime.agent_plan_draft schema 的结构化结果。",
        ]
    )


def _verifier_prompt() -> str:
    return "\n".join(
        [
            "你是一名只读交付验证员。",
            "你只根据语义任务合同、执行计划、证据包和验证结果判断是否满足交付要求。",
            "你不修改文件，不补写产物，不替实现者完成缺失步骤。",
            "模型自述不是事实证据；只有工具观察、文件读写、命令、浏览器、测试和结构化材料可以作为事实。",
            "如果证据不足、存在无证据声明或合同义务未满足，你必须指出阻断原因。",
            "请只输出符合 runtime.verification_review schema 的结构化结果。",
        ]
    )
