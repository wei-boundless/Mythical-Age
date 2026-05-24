from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from task_system.registry.flow_models import TaskDomainRecord
from task_system.registry.flow_registry import TaskFlowRegistry


@dataclass(frozen=True, slots=True)
class TaskDomainBinding:
    binding_id: str
    requested_domain: str
    bound_domain_id: str
    semantic_domain: str
    title: str
    binding_source: str
    playbook_role: str = "mature_working_conventions"
    user_flow_priority: str = "higher_than_domain_playbook"
    forbidden_actions_priority: str = "absolute"
    default_practices: tuple[str, ...] = ()
    validation_practices: tuple[str, ...] = ()
    risk_controls: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_domain_binding"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_domain_binding":
            raise ValueError("TaskDomainBinding authority must be task_system.task_domain_binding")
        if not self.binding_id:
            raise ValueError("TaskDomainBinding requires binding_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["default_practices"] = list(self.default_practices)
        payload["validation_practices"] = list(self.validation_practices)
        payload["risk_controls"] = list(self.risk_controls)
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def bind_task_domain(
    *,
    base_dir: Path,
    task_id: str,
    requested_domain: str,
    task_goal_domain: str = "",
    goal_evidence: dict[str, Any] | None = None,
    forbidden_actions: list[str] | tuple[str, ...] = (),
) -> TaskDomainBinding:
    normalized = _normalize_domain(requested_domain or task_goal_domain)
    registry = TaskFlowRegistry(base_dir)
    domains = registry.list_task_domains()
    record, source = _resolve_domain_record(normalized, domains)
    semantic_domain = normalized or "general"
    bound_domain_id = str(record.domain_id if record is not None else f"domain.{semantic_domain}").strip()
    title = str(record.title if record is not None else f"{semantic_domain}任务域").strip()
    metadata = dict(record.metadata if record is not None else {})
    practices = _default_practices(semantic_domain=semantic_domain, domain_id=bound_domain_id, metadata=metadata)
    validation = _validation_practices(semantic_domain=semantic_domain, domain_id=bound_domain_id, metadata=metadata)
    risks = _risk_controls(semantic_domain=semantic_domain, domain_id=bound_domain_id, metadata=metadata)
    evidence = dict(goal_evidence or {})
    has_user_flow = bool(list(evidence.get("user_provided_flow") or []))
    return TaskDomainBinding(
        binding_id=f"taskdomainbind:{task_id or 'runtime'}:{bound_domain_id}",
        requested_domain=str(requested_domain or task_goal_domain or "").strip(),
        bound_domain_id=bound_domain_id,
        semantic_domain=semantic_domain,
        title=title,
        binding_source=source,
        user_flow_priority="higher_than_domain_playbook" if has_user_flow else "domain_playbook_can_fill_gaps",
        default_practices=tuple(practices),
        validation_practices=tuple(validation),
        risk_controls=tuple(risks),
        diagnostics={
            "matched_record": record.to_dict() if record is not None else {},
            "normalized_domain": normalized,
            "forbidden_actions": [str(item).strip() for item in list(forbidden_actions or []) if str(item).strip()],
            "domain_binding_does_not_decide_goal": True,
            "domain_binding_must_not_override_user_flow": True,
            "domain_binding_must_not_override_forbidden_actions": True,
        },
    )


def _resolve_domain_record(
    normalized: str,
    domains: list[TaskDomainRecord],
) -> tuple[TaskDomainRecord | None, str]:
    if not domains:
        return None, "derived_no_registry_domains"
    exact_id = f"domain.{normalized}" if normalized and not normalized.startswith("domain.") else normalized
    for record in domains:
        if record.domain_id == exact_id:
            return record, "domain_id"
    if normalized == "development":
        for record in domains:
            if record.domain_id in {"domain.development", "domain.custom_4"} or "开发" in record.title:
                return record, "development_alias"
    if normalized in {"writing", "writing_modular_novel"}:
        for record in domains:
            if record.domain_id in {"domain.writing", "domain.writing_modular_novel"}:
                return record, "writing_alias"
    for record in domains:
        if record.domain_id == "domain.general":
            return record, "general_fallback"
    return None, "derived_fallback"


def _default_practices(*, semantic_domain: str, domain_id: str, metadata: dict[str, Any]) -> list[str]:
    configured = _metadata_list(metadata, "default_practices")
    if configured:
        return configured
    if semantic_domain in {"development", "custom_4"} or "development" in domain_id:
        return [
            "先观察真实代码和项目结构",
            "按用户明确流程推进",
            "保持变更范围受控",
            "真实修改后再汇报结果",
        ]
    if semantic_domain in {"writing", "writing_modular_novel"}:
        return [
            "先确认创作目标和材料边界",
            "保持设定一致性",
            "区分评审、规划和代写职责",
        ]
    return ["按用户目标和显式约束选择最小充分行动"]


def _validation_practices(*, semantic_domain: str, domain_id: str, metadata: dict[str, Any]) -> list[str]:
    configured = _metadata_list(metadata, "validation_practices")
    if configured:
        return configured
    if semantic_domain in {"development", "custom_4"} or "development" in domain_id:
        return [
            "能运行测试时运行相关测试",
            "无法验证时明确说明限制",
            "不得声称未发生的构建、测试或浏览器验证",
        ]
    if semantic_domain in {"writing", "writing_modular_novel"}:
        return ["检查设定一致性、章节目标和输出边界"]
    return ["最终回答必须说明依据或限制"]


def _risk_controls(*, semantic_domain: str, domain_id: str, metadata: dict[str, Any]) -> list[str]:
    configured = _metadata_list(metadata, "risk_controls")
    if configured:
        return configured
    if semantic_domain in {"development", "custom_4"} or "development" in domain_id:
        return [
            "用户禁令优先于开发默认流程",
            "不要用兼容借口保留无用旧代码",
            "不要用假结果绕过测试",
        ]
    return ["用户显式禁令优先于任务域习惯"]


def _metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    return [str(item).strip() for item in list(metadata.get(key) or []) if str(item).strip()]


def _normalize_domain(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("domain."):
        raw = raw.removeprefix("domain.")
    aliases = {
        "dev": "development",
        "code": "development",
        "coding": "development",
        "开发": "development",
        "开发任务": "development",
        "document": "document",
        "docs": "document",
        "writing_modular_novel": "writing_modular_novel",
    }
    return aliases.get(raw, raw or "general")
