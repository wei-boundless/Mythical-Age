from __future__ import annotations

from pathlib import Path
from typing import Any


def assemble_runtime_prompt_sections(
    *,
    base_dir: Path,
    contract: dict[str, Any],
    projection: dict[str, Any] | None = None,
    request: Any,
    soul_skill_views: tuple[Any, ...],
    soul_tool_views: tuple[Any, ...],
    use_shared_contract: bool,
) -> tuple[Any, ...]:
    """Build model-facing runtime sections from a prompt contract.

    The prompt library owns task prompt section shaping. Soul runtime assembly
    only wraps the resulting sections into its existing runtime view contract.
    """
    from soul.contracts import PromptSection
    from soul.registry import CORE_PATH, read_text

    metadata = dict(contract.get("metadata") or {})
    prompt_selection_context = dict(metadata.get("prompt_selection_context") or {})
    interaction_mode = str(
        prompt_selection_context.get("interaction_mode")
        or dict(metadata.get("mode_policy") or {}).get("interaction_mode")
        or ""
    ).strip()
    shared_contract = _load_shared_contract(base_dir)
    resource_content = _resource_projection_content(soul_tool_views)
    resource_policy_ref = str(metadata.get("resource_policy_ref") or "")
    node_prompt = _node_prompt_source(
        contract=contract,
        metadata=metadata,
        request=request,
    )
    candidate_sections = [
        PromptSection(
            section_id="protected_system_rules",
            title="系统硬契约",
            source_type="protected_system_contract",
            source_id=CORE_PATH,
            owner_layer="system_contract",
            cache_scope="static",
            visible_to_model=True,
            content=read_text(Path(base_dir) / CORE_PATH).strip() or "当前未配置系统硬契约。",
            source_refs=(CORE_PATH,),
        ),
        PromptSection(
            section_id="shared_common_contract",
            title="用户共同契约",
            source_type="common_contract",
            source_id=str(shared_contract.get("prompt_id") or "common_contract.default"),
            owner_layer="common_contract",
            cache_scope=str(shared_contract.get("cache_scope") or "static"),
            visible_to_model=use_shared_contract,
            content=str(shared_contract.get("content") or ""),
            source_refs=(str(shared_contract.get("source_ref") or "soul/common_contracts/catalog.json"),),
        ),
        PromptSection(
            section_id="task_section",
            title="任务契约",
            source_type="task_contract",
            source_id=str(getattr(request, "task_id", "") or contract.get("task_id") or ""),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("task_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="semantic_task_section",
            title="语义任务契约",
            source_type="task_requirement_contract",
            source_id=_semantic_contract_source_id(contract=contract, request=request),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("semantic_task_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="goal_understanding_section",
            title="目标理解",
            source_type="goal_understanding_contract",
            source_id=_goal_hypothesis_source_id(contract),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("goal_understanding_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="task_goal_role_prompt_section",
            title="任务目标职责",
            source_type="task_goal_role_prompt",
            source_id=_task_goal_prompt_source_id(contract),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("task_goal_role_prompt_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="node_professional_prompt_section",
            title="节点专业职责",
            source_type=node_prompt["source_type"],
            source_id=node_prompt["source_id"],
            owner_layer="task",
            cache_scope=node_prompt["cache_scope"],
            visible_to_model=True,
            content=str(contract.get("node_professional_prompt_section") or ""),
            source_refs=tuple(node_prompt["source_refs"]),
        ),
        PromptSection(
            section_id="professional_profile_section",
            title="专业职责",
            source_type="professional_prompt_profile",
            source_id=_professional_profile_source_id(contract),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("professional_profile_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="agent_plan_section",
            title="执行计划草案",
            source_type="agent_plan_draft",
            source_id=_agent_plan_source_id(contract),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("agent_plan_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="plan_coverage_section",
            title="计划覆盖审查",
            source_type="plan_coverage_review",
            source_id=_plan_coverage_source_id(contract),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("plan_coverage_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="completion_judgment_section",
            title="完成裁决",
            source_type="completion_judgment",
            source_id=_completion_judgment_source_id(contract),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("completion_judgment_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
        PromptSection(
            section_id="workflow_section",
            title="工作流",
            source_type="task_workflow",
            source_id="task_prompt_contract.workflow_section",
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("workflow_section") or ""),
            source_refs=tuple(str(getattr(item, "skill_id", "") or "") for item in soul_skill_views if str(getattr(item, "skill_id", "") or "")),
        ),
        PromptSection(
            section_id="skill_catalog_section",
            title="候选 Skills",
            source_type="skill_candidate_catalog",
            source_id="task_prompt_contract.skill_catalog_section",
            owner_layer="capability",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("skill_catalog_section") or ""),
            source_refs=(),
            candidate_refs=tuple(
                str(getattr(item, "skill_id", "") or "")
                for item in soul_skill_views
                if str(getattr(item, "skill_id", "") or "")
            ),
        ),
        PromptSection(
            section_id="skill_detail_section",
            title="已激活 Skill 说明",
            source_type="skill_activation_detail",
            source_id="task_prompt_contract.skill_detail_section",
            owner_layer="capability",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("skill_detail_section") or ""),
            source_refs=tuple(str(item).strip() for item in list(metadata.get("skill_detail_source_refs") or []) if str(item).strip()),
            candidate_refs=tuple(str(item).strip() for item in list(metadata.get("activated_skill_ids") or []) if str(item).strip()),
        ),
        PromptSection(
            section_id="output_section",
            title="输出边界",
            source_type="task_contract",
            source_id=str(getattr(request, "task_id", "") or contract.get("task_id") or ""),
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("output_section") or ""),
            source_refs=(str(contract.get("contract_id") or getattr(request, "task_id", "")),),
        ),
    ]
    if resource_content:
        candidate_sections.append(
            PromptSection(
                section_id="tool_view",
                title="Tools 可见摘要",
                source_type="resource_policy",
                source_id=resource_policy_ref or "resource_policy",
                owner_layer="resource_policy",
                cache_scope="dynamic",
                visible_to_model=True,
                content=resource_content,
                source_refs=(resource_policy_ref,) if resource_policy_ref else (),
            )
        )
    guardrail_content = str(contract.get("guardrail_section") or "")
    if guardrail_content:
        candidate_sections.append(
            PromptSection(
                section_id="guardrail_section",
                title="护栏",
                source_type="task_binding",
                source_id=str(contract.get("binding_id") or ""),
                owner_layer="task",
                cache_scope="dynamic",
                visible_to_model=True,
                content=guardrail_content,
                source_refs=(str(contract.get("binding_id") or ""),),
            )
        )
    return tuple(section for section in candidate_sections if section.visible_to_model and section.content.strip())


def _load_shared_contract(base_dir: Path) -> dict[str, Any]:
    from soul.catalog_store import SoulCatalogStore
    from soul.catalog_service import SoulCatalogService

    items = SoulCatalogStore(base_dir).load_bucket("common_contracts")
    if not items:
        items = SoulCatalogService(base_dir)._default_common_contracts()
    for item in items:
        content = str(dict(item).get("content") or "").strip()
        if content:
            return dict(item)
    return {}


def _node_prompt_source(
    *,
    contract: dict[str, Any],
    metadata: dict[str, Any],
    request: Any,
) -> dict[str, Any]:
    node_prompt_resource = (
        dict(metadata.get("node_professional_prompt_resource") or {})
        if isinstance(metadata.get("node_professional_prompt_resource"), dict)
        else {}
    )
    prompt_plan_item = _selected_plan_item(metadata, section_id="node_professional_prompt_section")
    task_id = str(getattr(request, "task_id", "") or contract.get("task_id") or "")
    source_id = str(
        node_prompt_resource.get("resource_id")
        or prompt_plan_item.get("resource_id")
        or metadata.get("task_workflow_id")
        or task_id
    )
    source_type = (
        "prompt_library_resource"
        if str(node_prompt_resource.get("resource_id") or prompt_plan_item.get("resource_id") or "").strip()
        else "task_workflow_prompt"
    )
    source_refs = tuple(
        item
        for item in (
            str(node_prompt_resource.get("source_ref") or "").strip(),
            str(prompt_plan_item.get("source_ref") or "").strip(),
            str(node_prompt_resource.get("workflow_id") or "").strip(),
        )
        if item
    ) or (str(metadata.get("task_workflow_id") or task_id),)
    return {
        "source_id": source_id,
        "source_type": source_type,
        "source_refs": source_refs,
        "cache_scope": str(node_prompt_resource.get("cache_scope") or "dynamic"),
    }


def _selected_plan_item(metadata: dict[str, Any], *, section_id: str) -> dict[str, Any]:
    plan = metadata.get("prompt_assembly_plan")
    if not isinstance(plan, dict):
        return {}
    for item in list(plan.get("selected") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("section_id") or "") == section_id and not str(item.get("resource_id") or "").startswith("builtin:"):
            return dict(item)
    return {}


def _semantic_contract_source_id(*, contract: dict[str, Any], request: Any) -> str:
    metadata = dict(contract.get("metadata") or {})
    semantic_contract = metadata.get("task_requirement_contract")
    if isinstance(semantic_contract, dict):
        return str(semantic_contract.get("contract_id") or getattr(request, "task_id", "") or contract.get("task_id") or "")
    return str(getattr(request, "task_id", "") or contract.get("task_id") or "")


def _professional_profile_source_id(contract: dict[str, Any]) -> str:
    metadata = dict(contract.get("metadata") or {})
    professional_profile = metadata.get("professional_profile")
    if isinstance(professional_profile, dict):
        return str(professional_profile.get("profile_id") or "")
    return ""


def _goal_hypothesis_source_id(contract: dict[str, Any]) -> str:
    metadata = dict(contract.get("metadata") or {})
    hypothesis = metadata.get("goal_hypothesis_set")
    if isinstance(hypothesis, dict):
        return str(hypothesis.get("hypothesis_set_id") or "")
    return ""


def _task_goal_prompt_source_id(contract: dict[str, Any]) -> str:
    metadata = dict(contract.get("metadata") or {})
    resource = metadata.get("task_goal_prompt_resource")
    if isinstance(resource, dict):
        return str(resource.get("resource_id") or "")
    return ""


def _agent_plan_source_id(contract: dict[str, Any]) -> str:
    metadata = dict(contract.get("metadata") or {})
    plan = metadata.get("agent_plan_draft")
    if isinstance(plan, dict):
        plan_id = str(plan.get("plan_id") or "")
        if plan_id:
            return plan_id
    requirement = metadata.get("agent_plan_requirement")
    if isinstance(requirement, dict):
        return str(requirement.get("requirement_id") or "")
    return ""


def _plan_coverage_source_id(contract: dict[str, Any]) -> str:
    metadata = dict(contract.get("metadata") or {})
    review = metadata.get("plan_coverage_review")
    if isinstance(review, dict):
        return str(review.get("review_id") or "")
    return ""


def _completion_judgment_source_id(contract: dict[str, Any]) -> str:
    metadata = dict(contract.get("metadata") or {})
    judgment = metadata.get("completion_judgment")
    if isinstance(judgment, dict):
        return str(judgment.get("judgment_id") or "")
    return ""


def _resource_projection_content(tool_views: tuple[Any, ...]) -> str:
    lines = []
    for item in [view for view in tool_views if bool(getattr(view, "runtime_executable", False))]:
        lines.append(
            f"- {getattr(item, 'title', '')} (`{getattr(item, 'tool_id', '')}`): "
            f"decision={getattr(item, 'policy_decision', '')}"
        )
    return "\n".join(line for line in lines if line)


