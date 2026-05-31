from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.contracts.contract_definition_models import (
    AcceptanceRule,
    ArtifactRequirement,
    ContractField,
    ContractSpec,
    ContextVisibilityPolicy,
    FailurePolicy,
    HandoffPolicy,
)


@dataclass(frozen=True, slots=True)
class WritingContractFamily:
    family_id: str
    title_zh: str
    purpose: str
    contract_kind: str
    default_artifact_type: str = ""
    output_key: str = ""
    relation_ids: tuple[str, ...] = ()
    configurable_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["relation_ids"] = list(self.relation_ids)
        payload["configurable_fields"] = list(self.configurable_fields)
        payload["metadata"] = dict(self.metadata)
        return payload


WRITING_CONTRACT_FAMILIES: tuple[WritingContractFamily, ...] = (
    WritingContractFamily(
        "writing.draft_artifact",
        "写作草稿产物",
        "写手节点交付章节、设定、细纲、提案等可追踪草稿产物。",
        "workflow_step",
        "draft",
        "artifact_ref",
        ("writing.draft_to_review", "writing.revision_to_review"),
        ("artifact_type", "writing_stage", "artifact_title", "quality_bar"),
    ),
    WritingContractFamily(
        "writing.review_verdict",
        "审核裁决",
        "审核节点输出通过、返修、驳回、问题清单和返修要求。",
        "acceptance",
        "review_verdict",
        "verdict",
        ("writing.review_pass_to_commit", "writing.review_revise_to_writer", "writing.review_reject_to_human"),
        ("artifact_type", "verdict_key", "pass_value", "revise_value", "reject_value", "quality_bar"),
    ),
    WritingContractFamily(
        "writing.revision_request",
        "返修请求",
        "把审核意见、原产物引用和返修要求交还给写手或返修节点。",
        "edge_handoff",
        "revision_request",
        "revision_request",
        ("writing.review_revise_to_writer",),
        ("artifact_type", "max_revision_attempts", "carry_fields"),
    ),
    WritingContractFamily(
        "writing.commit_receipt",
        "通过后提交回执",
        "审核通过后记录正式提交的产物、来源裁决和可见性。",
        "workflow_step",
        "commit_receipt",
        "commit_receipt",
        ("writing.review_pass_to_commit",),
        ("artifact_type", "commit_target", "visibility_policy"),
    ),
    WritingContractFamily(
        "writing.memory_update",
        "写作记忆更新",
        "把已审核通过的设定、章节摘要、人物状态或连续性信息写入正式记忆。",
        "workflow_step",
        "memory_update",
        "memory_candidate_ref",
        ("memory.write_candidate", "memory.commit_after_review"),
        ("repository_id", "collection_id", "record_kind", "source_output_key", "approval_source_node_id"),
    ),
)


def list_writing_contract_families() -> tuple[WritingContractFamily, ...]:
    return WRITING_CONTRACT_FAMILIES


def get_writing_contract_family(family_id: str) -> WritingContractFamily | None:
    target = str(family_id or "").strip()
    return next((item for item in WRITING_CONTRACT_FAMILIES if item.family_id == target), None) if target else None


def writing_contract_family_catalog() -> dict[str, Any]:
    families = [item.to_dict() for item in WRITING_CONTRACT_FAMILIES]
    return {
        "authority": "task_system.writing_contract_families",
        "families": families,
        "summary": {
            "contract_family_count": len(families),
            "writing_contract_family_count": len(families),
        },
    }


def resolve_writing_contract(family_id: str, overrides: dict[str, Any] | None = None) -> ContractSpec:
    family = get_writing_contract_family(family_id)
    if family is None:
        raise ValueError(f"Unknown writing contract family: {family_id}")
    overrides = dict(overrides or {})
    artifact_type = _identifier(overrides.get("artifact_type"), family.default_artifact_type or "artifact")
    writing_stage = _text(overrides.get("writing_stage"), artifact_type)
    contract_id = _text(overrides.get("contract_id"), f"contract.{family.family_id}.{artifact_type}")
    quality_bar = _text(overrides.get("quality_bar"), "必须满足当前任务质量标准，并保留可追踪引用。")
    metadata = {
        "generated_from_family": True,
        "contract_family_id": family.family_id,
        "contract_family_title_zh": family.title_zh,
        "artifact_type": artifact_type,
        "writing_stage": writing_stage,
        "relation_ids": list(family.relation_ids),
        "overrides": overrides,
        **dict(family.metadata),
    }
    builders = {
        "writing.draft_artifact": _draft_artifact_contract,
        "writing.review_verdict": _review_verdict_contract,
        "writing.revision_request": _revision_request_contract,
        "writing.commit_receipt": _commit_receipt_contract,
        "writing.memory_update": _memory_update_contract,
    }
    return builders[family.family_id](
        family,
        contract_id=contract_id,
        artifact_type=artifact_type,
        writing_stage=writing_stage,
        quality_bar=quality_bar,
        overrides=overrides,
        metadata=metadata,
    )


def _field(
    field_id: str,
    title_zh: str,
    field_type: str = "string",
    *,
    required: bool = False,
    source_hint: str = "upstream_output",
    description: str = "",
) -> ContractField:
    return ContractField(
        field_id=field_id,
        title_zh=title_zh,
        field_type=field_type,
        required=required,
        description=description,
        source_hint=source_hint,
    )


def _rule(rule_id: str, title_zh: str, target_field: str, criteria: str, rule_type: str = "required_field_present") -> AcceptanceRule:
    return AcceptanceRule(
        rule_id=rule_id,
        title_zh=title_zh,
        rule_type=rule_type,
        target_field=target_field,
        criteria=criteria,
    )


def _common_contract(
    family: WritingContractFamily,
    *,
    contract_id: str,
    artifact_type: str,
    writing_stage: str,
    description: str,
    input_fields: tuple[ContractField, ...],
    output_fields: tuple[ContractField, ...],
    acceptance_rules: tuple[AcceptanceRule, ...],
    metadata: dict[str, Any],
    title_suffix_zh: str,
    title_suffix_en: str,
    artifact_requirements: tuple[ArtifactRequirement, ...] = (),
    retry_allowed: bool = False,
    escalate_to: str = "coordinator",
) -> ContractSpec:
    return ContractSpec(
        contract_id=contract_id,
        title_zh=f"{writing_stage}{title_suffix_zh}",
        title_en=f"{artifact_type} {title_suffix_en}",
        contract_kind=family.contract_kind,
        description=description,
        input_fields=input_fields,
        output_fields=output_fields,
        artifact_requirements=artifact_requirements,
        acceptance_rules=acceptance_rules,
        context_visibility_policy=ContextVisibilityPolicy(upstream_outputs="summary", artifact_access="refs_only"),
        handoff_policy=HandoffPolicy(handoff_mode="structured_packet", include_artifact_refs=True, ack_required=True),
        failure_policy=FailurePolicy(failure_mode="fail_closed", retry_allowed=retry_allowed, retry_limit=1 if retry_allowed else 0, escalate_to=escalate_to),
        metadata=metadata,
    )


def _draft_artifact_contract(
    family: WritingContractFamily,
    *,
    contract_id: str,
    artifact_type: str,
    writing_stage: str,
    quality_bar: str,
    overrides: dict[str, Any],
    metadata: dict[str, Any],
) -> ContractSpec:
    return _common_contract(
        family,
        contract_id=contract_id,
        artifact_type=artifact_type,
        writing_stage=writing_stage,
        title_suffix_zh="草稿产物",
        title_suffix_en="draft artifact",
        description=f"写手节点必须交付 {writing_stage} 的可追踪草稿产物。{quality_bar}",
        input_fields=(
            _field("upstream_packet", "上游交接包", "object", source_hint="upstream_output", description="目标、约束、资料引用和审核要求。"),
            _field("memory_context", "已提交记忆上下文", "object", source_hint="runtime_context", description="运行时读取的正式记忆快照。"),
        ),
        output_fields=(
            _field("artifact_refs", "产物引用集合", "array", required=True, source_hint="artifact"),
            _field("artifact_ref", f"{writing_stage}产物引用", "artifact_ref", required=True, source_hint="artifact"),
            _field("artifact_summary", "产物摘要", description="给审核员或下游节点使用的简短摘要。"),
            _field("memory_candidates", "候选记忆", "array", description="需要审核后才可进入正式记忆的候选条目。"),
        ),
        artifact_requirements=(
            ArtifactRequirement(
                requirement_id=f"{artifact_type}_artifact_required",
                title_zh=f"{writing_stage}产物必须存在",
                artifact_type=artifact_type,
                required=True,
                description="必须写入产物库并返回引用。",
                storage_policy="artifact_ref",
            ),
        ),
        acceptance_rules=(
            _rule("artifact_refs_present", "产物引用必须存在", "artifact_refs", "至少返回一个可追踪产物引用。", "artifact_exists"),
            _rule("primary_artifact_ref_present", "主产物引用必须存在", "artifact_ref", "写作节点必须声明主要产物引用。"),
        ),
        retry_allowed=True,
        metadata=metadata,
    )


def _review_verdict_contract(
    family: WritingContractFamily,
    *,
    contract_id: str,
    artifact_type: str,
    writing_stage: str,
    quality_bar: str,
    overrides: dict[str, Any],
    metadata: dict[str, Any],
) -> ContractSpec:
    verdict_key = _identifier(overrides.get("verdict_key"), "verdict")
    return _common_contract(
        family,
        contract_id=contract_id,
        artifact_type=artifact_type,
        writing_stage=writing_stage,
        title_suffix_zh="审核裁决",
        title_suffix_en="review verdict",
        description=f"审核节点必须裁决 {writing_stage} 是否可通过、返修或驳回。{quality_bar}",
        input_fields=(
            _field("review_target_ref", "审核对象引用", "artifact_ref", required=True, source_hint="artifact"),
            _field("quality_criteria", "审核标准", description="当前阶段的质量门、读者目标和禁止事项。"),
        ),
        output_fields=(
            _field(verdict_key, "审核结论", required=True, description="必须是 pass、revise、reject 或项目配置的等价裁决值。"),
            _field("issues", "问题清单", "array", description="未通过时必须给出具体、可执行的问题清单。"),
            _field("revision_request", "返修要求", "object", description="给写手的返修目标、范围和验收标准。"),
            _field("approved_artifact_ref", "通过产物引用", "artifact_ref", source_hint="artifact"),
            _field("memory_commit_allowed", "允许写入记忆", "boolean"),
        ),
        acceptance_rules=(
            _rule("verdict_present", "审核结论必须存在", verdict_key, "审核节点必须输出明确裁决。"),
        ),
        retry_allowed=False,
        metadata={**metadata, "verdict_key": verdict_key},
    )


def _revision_request_contract(
    family: WritingContractFamily,
    *,
    contract_id: str,
    artifact_type: str,
    writing_stage: str,
    quality_bar: str,
    overrides: dict[str, Any],
    metadata: dict[str, Any],
) -> ContractSpec:
    return _common_contract(
        family,
        contract_id=contract_id,
        artifact_type=artifact_type,
        writing_stage=writing_stage,
        title_suffix_zh="返修请求",
        title_suffix_en="revision request",
        description="审核未通过时，把原产物、审核意见和返修标准交还给写手或返修者。",
        input_fields=(
            _field("review_verdict", "审核裁决", "object", required=True),
            _field("previous_artifact_ref", "原产物引用", "artifact_ref", required=True, source_hint="artifact"),
        ),
        output_fields=(
            _field("revision_request", "返修请求", "object", required=True),
            _field("carry_artifact_refs", "携带产物引用", "array", required=True, source_hint="artifact"),
        ),
        acceptance_rules=(
            _rule("revision_request_present", "返修要求必须存在", "revision_request", "返修边必须携带明确返修要求。"),
            _rule("previous_artifact_ref_present", "原产物引用必须存在", "previous_artifact_ref", "返修者必须能定位原产物。"),
        ),
        metadata=metadata,
    )


def _commit_receipt_contract(
    family: WritingContractFamily,
    *,
    contract_id: str,
    artifact_type: str,
    writing_stage: str,
    quality_bar: str,
    overrides: dict[str, Any],
    metadata: dict[str, Any],
) -> ContractSpec:
    return _common_contract(
        family,
        contract_id=contract_id,
        artifact_type=artifact_type,
        writing_stage=writing_stage,
        title_suffix_zh="提交回执",
        title_suffix_en="commit receipt",
        description="审核通过后记录正式提交结果，供下游节点和运行审计追踪。",
        input_fields=(
            _field("approved_artifact_ref", "通过产物引用", "artifact_ref", required=True, source_hint="artifact"),
            _field("review_verdict", "审核裁决", "object", required=True),
        ),
        output_fields=(
            _field("commit_receipt", "提交回执", "object", required=True, source_hint="runtime_context"),
            _field("committed_artifact_ref", "正式产物引用", "artifact_ref", source_hint="artifact"),
        ),
        acceptance_rules=(
            _rule("commit_receipt_present", "提交回执必须存在", "commit_receipt", "通过后的提交动作必须可追踪。"),
        ),
        metadata=metadata,
    )


def _memory_update_contract(
    family: WritingContractFamily,
    *,
    contract_id: str,
    artifact_type: str,
    writing_stage: str,
    quality_bar: str,
    overrides: dict[str, Any],
    metadata: dict[str, Any],
) -> ContractSpec:
    return _common_contract(
        family,
        contract_id=contract_id,
        artifact_type=artifact_type,
        writing_stage=writing_stage,
        title_suffix_zh="记忆更新",
        title_suffix_en="memory update",
        description="把经过审核的写作资料转为候选记忆，并在通过后提交到正式记忆库。",
        input_fields=(
            _field("source_artifact_ref", "来源产物引用", "artifact_ref", required=True, source_hint="artifact"),
            _field("approval_verdict", "审核裁决", "object"),
        ),
        output_fields=(
            _field("memory_candidate_ref", "候选记忆引用", "result_ref", required=True, source_hint="runtime_context"),
            _field("memory_commit_receipt", "记忆提交回执", "object", source_hint="runtime_context"),
        ),
        acceptance_rules=(
            _rule("memory_candidate_present", "候选记忆引用必须存在", "memory_candidate_ref", "写入正式记忆前必须先形成候选记录。"),
        ),
        metadata=metadata,
    )


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _identifier(value: Any, fallback: str) -> str:
    raw = _text(value, fallback)
    return "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in raw).strip("._-") or fallback
