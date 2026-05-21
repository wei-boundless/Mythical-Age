from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from task_system.contracts.contract_definition_models import (
    ACCEPTANCE_RULE_SEVERITY_OPTIONS,
    ACCEPTANCE_RULE_TYPE_OPTIONS,
    CONTRACT_FIELD_SOURCE_HINT_OPTIONS,
    CONTRACT_FIELD_TYPE_OPTIONS,
    CONTRACT_FIELD_VISIBILITY_OPTIONS,
    CONTRACT_KIND_OPTIONS,
    AcceptanceRule,
    ArtifactRequirement,
    ContextVisibilityPolicy,
    ContractField,
    ContractSpec,
    ContractValidationIssue,
    FailurePolicy,
    HandoffPolicy,
    HumanGatePolicy,
    RuntimeRequirement,
)


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).tasks_dir


def _contract_specs_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "contract_specs.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_contract_specs() -> tuple[ContractSpec, ...]:
    return (
        ContractSpec(
            contract_id="contract.user_request.basic",
            title_zh="用户任务请求",
            title_en="Basic User Request",
            contract_kind="global_task",
            description="定义用户发起任务时最小可用的目标、约束与上下文输入。",
            input_fields=(
                ContractField(
                    field_id="goal",
                    title_zh="任务目标",
                    field_type="string",
                    required=True,
                    description="用户希望 Agent 完成的核心目标。",
                    source_hint="user_input",
                ),
                ContractField(
                    field_id="constraints",
                    title_zh="任务约束",
                    field_type="array",
                    required=False,
                    description="用户明确提出的边界、偏好或禁止事项。",
                    source_hint="user_input",
                ),
            ),
            output_fields=(
                ContractField(
                    field_id="normalized_goal",
                    title_zh="规范化目标",
                    field_type="string",
                    required=True,
                    description="运行前整理后的任务目标。",
                    source_hint="system",
                ),
            ),
            acceptance_rules=(
                AcceptanceRule(
                    rule_id="goal_present",
                    title_zh="目标必须存在",
                    rule_type="required_field_present",
                    severity="error",
                    target_field="goal",
                    criteria="用户任务请求必须能提取出明确目标。",
                ),
            ),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.agent_output.markdown",
            title_zh="Agent Markdown 输出",
            title_en="Agent Markdown Output",
            contract_kind="final_output",
            description="定义单 Agent 或主 Agent 面向用户输出的 Markdown 文本结构。",
            output_fields=(
                ContractField(
                    field_id="answer_markdown",
                    title_zh="Markdown 回答",
                    field_type="string",
                    required=True,
                    description="可直接展示给用户的最终回答。",
                    source_hint="upstream_output",
                ),
                ContractField(
                    field_id="verification_notes",
                    title_zh="验证说明",
                    field_type="array",
                    required=False,
                    description="执行或验证过程中产生的关键说明。",
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            acceptance_rules=(
                AcceptanceRule(
                    rule_id="answer_present",
                    title_zh="回答必须存在",
                    rule_type="required_field_present",
                    severity="error",
                    target_field="answer_markdown",
                    criteria="最终输出不能为空。",
                ),
            ),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.artifact_refs.bundle",
            title_zh="产物引用包",
            title_en="Artifact Reference Bundle",
            contract_kind="workflow_step",
            description="定义节点或步骤交付文件、报告、截图等产物时的引用集合。",
            output_fields=(
                ContractField(
                    field_id="artifact_refs",
                    title_zh="产物引用",
                    field_type="array",
                    required=True,
                    description="运行产生的产物引用列表，不直接内联大文件内容。",
                    source_hint="artifact",
                ),
            ),
            artifact_requirements=(
                ArtifactRequirement(
                    requirement_id="artifact_refs_required",
                    title_zh="至少一个产物引用",
                    artifact_type="artifact_ref",
                    required=True,
                    description="需要交付可追踪的产物引用。",
                ),
            ),
            acceptance_rules=(
                AcceptanceRule(
                    rule_id="artifact_refs_present",
                    title_zh="产物引用必须存在",
                    rule_type="artifact_exists",
                    severity="error",
                    target_field="artifact_refs",
                    criteria="产物引用列表至少包含一个有效引用。",
                ),
            ),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.error_report.basic",
            title_zh="基础错误报告",
            title_en="Basic Error Report",
            contract_kind="failure",
            description="定义 Agent 或 Runtime 失败时上报给协调者或主 Agent 的错误信息。",
            output_fields=(
                ContractField(
                    field_id="error_code",
                    title_zh="错误代码",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="error_summary",
                    title_zh="错误摘要",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                ),
                ContractField(
                    field_id="recoverable",
                    title_zh="是否可恢复",
                    field_type="boolean",
                    required=False,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            failure_policy=FailurePolicy(failure_mode="fail_closed", retry_allowed=False, escalate_to="coordinator"),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.human_review.decision",
            title_zh="人工审核决策",
            title_en="Human Review Decision",
            contract_kind="human_gate",
            description="定义需要人工确认时的审核结论、意见和放行状态。",
            input_fields=(
                ContractField(
                    field_id="review_target_ref",
                    title_zh="审核对象引用",
                    field_type="result_ref",
                    required=True,
                    source_hint="runtime_context",
                ),
            ),
            output_fields=(
                ContractField(
                    field_id="decision",
                    title_zh="审核结论",
                    field_type="string",
                    required=True,
                    source_hint="manual_review",
                ),
                ContractField(
                    field_id="review_notes",
                    title_zh="审核意见",
                    field_type="string",
                    required=False,
                    source_hint="manual_review",
                ),
            ),
            human_gate_policy=HumanGatePolicy(
                required=True,
                gate_type="manual_approval",
                reviewer_role="human_operator",
            ),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.taskgraph.monitor.decision",
            title_zh="TaskGraph 监测决策包",
            title_en="TaskGraph Monitor Decision Packet",
            contract_kind="workflow_step",
            description="定义后台监测节点对任务图运行态做出的结构化观察、判断和建议控制动作。",
            input_fields=(
                ContractField(
                    field_id="monitor_snapshot",
                    title_zh="监测快照",
                    field_type="object",
                    required=True,
                    description="来自 task_graph.run_monitor 的运行态快照摘要。",
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            output_fields=(
                ContractField(
                    field_id="decision_id",
                    title_zh="决策 ID",
                    field_type="string",
                    required=True,
                    source_hint="system",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="action",
                    title_zh="建议动作",
                    field_type="string",
                    required=True,
                    description="no_action、notify、request_user_decision、resume、restart、pause 或 escalate。旧记录中的 request_human_review 等价于 request_user_decision。",
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="severity",
                    title_zh="严重级别",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="summary",
                    title_zh="决策摘要",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                ),
                ContractField(
                    field_id="recommended_control",
                    title_zh="建议控制入口",
                    field_type="object",
                    required=False,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="run_interaction_request",
                    title_zh="运行交互请求",
                    field_type="object",
                    required=False,
                    description="当需要用户处理提醒、续跑、重试、暂停或人工确认时，向统一运行交互窗口投递的请求。",
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            acceptance_rules=(
                AcceptanceRule(
                    rule_id="monitor_action_present",
                    title_zh="必须给出建议动作",
                    rule_type="required_field_present",
                    severity="error",
                    target_field="action",
                    criteria="监测节点必须产出一个明确的 action。",
                ),
            ),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.taskgraph.monitor.snapshot",
            title_zh="TaskGraph 监测快照",
            title_en="TaskGraph Monitor Snapshot",
            contract_kind="runtime",
            description="定义后台监测节点读取的任务图运行态快照摘要，来源必须是 task_graph.run_monitor。",
            output_fields=(
                ContractField(
                    field_id="task_run_id",
                    title_zh="TaskRun ID",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="coordination_run_id",
                    title_zh="CoordinationRun ID",
                    field_type="string",
                    required=False,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="runtime",
                    title_zh="运行状态",
                    field_type="object",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="state",
                    title_zh="节点状态",
                    field_type="object",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="blocker",
                    title_zh="阻塞信息",
                    field_type="object",
                    required=False,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            metadata={"default_seed": True},
        ),
        ContractSpec(
            contract_id="contract.taskgraph.run_interaction.request",
            title_zh="TaskGraph 运行交互请求",
            title_en="TaskGraph Run Interaction Request",
            contract_kind="human_gate",
            description="定义监测节点、人工门控节点或运行控制节点向统一运行交互窗口发出的结构化请求。",
            input_fields=(
                ContractField(
                    field_id="monitor_decision",
                    title_zh="监测决策",
                    field_type="object",
                    required=False,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            output_fields=(
                ContractField(
                    field_id="request_id",
                    title_zh="请求 ID",
                    field_type="string",
                    required=True,
                    source_hint="system",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="action",
                    title_zh="建议动作",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="reason",
                    title_zh="触发原因",
                    field_type="string",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
                ContractField(
                    field_id="decision_options",
                    title_zh="用户决策选项",
                    field_type="array",
                    required=True,
                    source_hint="runtime_context",
                    visibility="human_only",
                ),
                ContractField(
                    field_id="safe_state_refs",
                    title_zh="安全状态引用",
                    field_type="object",
                    required=True,
                    source_hint="runtime_context",
                    visibility="monitor_visible",
                ),
            ),
            human_gate_policy=HumanGatePolicy(
                required=True,
                gate_type="run_interaction",
                reviewer_role="human_operator",
            ),
            metadata={"default_seed": True},
        ),
    )


class TaskContractRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def _read_stored_specs(self) -> list[ContractSpec]:
        payload = _read_json(_contract_specs_path(self.base_dir), {"contract_specs": []})
        specs: list[ContractSpec] = []
        for item in list(payload.get("contract_specs") or []):
            if isinstance(item, dict):
                specs.append(ContractSpec.from_dict(item))
        return specs

    def _write_stored_specs(self, specs: list[ContractSpec]) -> None:
        _write_json(
            _contract_specs_path(self.base_dir),
            {"contract_specs": [item.to_dict() for item in sorted(specs, key=lambda spec: spec.contract_id)]},
        )

    def list_contract_specs(self) -> list[ContractSpec]:
        merged: dict[str, ContractSpec] = {item.contract_id: item for item in default_contract_specs()}
        for spec in self._read_stored_specs():
            if spec.contract_id:
                merged[spec.contract_id] = spec
        return sorted(merged.values(), key=lambda item: (item.contract_kind, item.title_zh, item.contract_id))

    def get_contract_spec(self, contract_id: str) -> ContractSpec | None:
        target = str(contract_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list_contract_specs() if item.contract_id == target), None)

    def upsert_contract_spec(self, spec: ContractSpec | dict[str, Any]) -> ContractSpec:
        normalized = spec if isinstance(spec, ContractSpec) else ContractSpec.from_dict(dict(spec))
        issues = self.validate_contract_spec(normalized)
        blocking = [item for item in issues if item.severity == "error"]
        if blocking:
            raise ValueError("; ".join(item.message or item.reason for item in blocking))

        stored = [item for item in self._read_stored_specs() if item.contract_id != normalized.contract_id]
        stored.append(normalized)
        self._write_stored_specs(stored)
        return normalized

    def delete_contract_spec(self, contract_id: str) -> dict[str, Any]:
        target = str(contract_id or "").strip()
        if not target:
            raise ValueError("contract_id is required")
        before = self._read_stored_specs()
        after = [item for item in before if item.contract_id != target]
        if len(before) == len(after):
            raise ValueError(f"ContractSpec not found in editable storage: {target}")
        self._write_stored_specs(after)
        return {"contract_id": target, "deleted": True}

    def validate_contract_spec(self, spec: ContractSpec) -> list[ContractValidationIssue]:
        issues: list[ContractValidationIssue] = []

        def add(field: str, reason: str, message: str, *, severity: str = "error") -> None:
            issues.append(
                ContractValidationIssue(
                    contract_id=spec.contract_id,
                    field=field,
                    reason=reason,
                    severity=severity,
                    message=message,
                )
            )

        if not spec.contract_id:
            add("contract_id", "required", "契约 ID 不能为空。")
        if not spec.title_zh:
            add("title_zh", "required", "契约必须提供中文名称。")
        if spec.contract_kind not in CONTRACT_KIND_OPTIONS:
            add("contract_kind", "not_allowed", f"契约类型不在允许范围内：{spec.contract_kind}")

        for group_name, fields in (("input_fields", spec.input_fields), ("output_fields", spec.output_fields)):
            seen_field_ids: set[str] = set()
            for item in fields:
                prefix = f"{group_name}.{item.field_id or '<empty>'}"
                if not item.field_id:
                    add(group_name, "field_id_required", "字段必须提供 field_id。")
                elif item.field_id in seen_field_ids:
                    add(prefix, "duplicate_field_id", f"字段 ID 重复：{item.field_id}")
                seen_field_ids.add(item.field_id)
                if not item.title_zh:
                    add(prefix, "title_zh_required", f"字段 {item.field_id} 必须提供中文名称。")
                if item.field_type not in CONTRACT_FIELD_TYPE_OPTIONS:
                    add(prefix, "field_type_not_allowed", f"字段类型不在允许范围内：{item.field_type}")
                if item.source_hint not in CONTRACT_FIELD_SOURCE_HINT_OPTIONS:
                    add(prefix, "source_hint_not_allowed", f"字段来源不在允许范围内：{item.source_hint}")
                if item.visibility not in CONTRACT_FIELD_VISIBILITY_OPTIONS:
                    add(prefix, "visibility_not_allowed", f"字段可见性不在允许范围内：{item.visibility}")

        seen_rule_ids: set[str] = set()
        for rule in spec.acceptance_rules:
            prefix = f"acceptance_rules.{rule.rule_id or '<empty>'}"
            if not rule.rule_id:
                add("acceptance_rules", "rule_id_required", "验收规则必须提供 rule_id。")
            elif rule.rule_id in seen_rule_ids:
                add(prefix, "duplicate_rule_id", f"验收规则 ID 重复：{rule.rule_id}")
            seen_rule_ids.add(rule.rule_id)
            if not rule.title_zh:
                add(prefix, "title_zh_required", f"验收规则 {rule.rule_id} 必须提供中文名称。")
            if rule.rule_type not in ACCEPTANCE_RULE_TYPE_OPTIONS:
                add(prefix, "rule_type_not_allowed", f"验收规则类型不在允许范围内：{rule.rule_type}")
            if rule.severity not in ACCEPTANCE_RULE_SEVERITY_OPTIONS:
                add(prefix, "severity_not_allowed", f"验收规则级别不在允许范围内：{rule.severity}")

        for requirement in spec.artifact_requirements:
            prefix = f"artifact_requirements.{requirement.requirement_id or '<empty>'}"
            if not requirement.requirement_id:
                add("artifact_requirements", "requirement_id_required", "产物要求必须提供 requirement_id。")
            if not requirement.title_zh:
                add(prefix, "title_zh_required", "产物要求必须提供中文名称。")

        for requirement in spec.runtime_requirements:
            prefix = f"runtime_requirements.{requirement.requirement_id or '<empty>'}"
            if not requirement.requirement_id:
                add("runtime_requirements", "requirement_id_required", "Runtime 要求必须提供 requirement_id。")
            if not requirement.title_zh:
                add(prefix, "title_zh_required", "Runtime 要求必须提供中文名称。")

        return issues

    def validate_all(self) -> list[ContractValidationIssue]:
        return [issue for spec in self.list_contract_specs() for issue in self.validate_contract_spec(spec)]

    def build_catalog(self) -> dict[str, Any]:
        specs = self.list_contract_specs()
        issues = self.validate_all()
        return {
            "authority": "task_system.contract_management",
            "contract_specs": [item.to_dict() for item in specs],
            "contract_kind_options": list(CONTRACT_KIND_OPTIONS),
            "field_type_options": list(CONTRACT_FIELD_TYPE_OPTIONS),
            "source_hint_options": list(CONTRACT_FIELD_SOURCE_HINT_OPTIONS),
            "visibility_options": list(CONTRACT_FIELD_VISIBILITY_OPTIONS),
            "acceptance_rule_type_options": list(ACCEPTANCE_RULE_TYPE_OPTIONS),
            "validation_issues": [item.to_dict() for item in issues],
            "summary": {
                "contract_spec_count": len(specs),
                "enabled_contract_spec_count": sum(1 for item in specs if item.enabled),
                "validation_issue_count": len(issues),
            },
        }
