from __future__ import annotations

import hashlib
from typing import Any

from soul.agent_prompt_bundle import build_agent_prompt_bundle
from soul.contracts import (
    PromptSection,
    SoulProjectionRequest,
    SoulRuntimeView,
    SoulSkillView,
    SoulToolView,
)
from soul.prompt_assembly import build_prompt_manifest
from soul.registry import CORE_PATH, SoulRegistry, read_text


class SoulProjectionBuilder:
    def __init__(self, registry: SoulRegistry):
        self.registry = registry

    def build(self, request: SoulProjectionRequest) -> dict[str, object]:
        profile = self.registry.get_profile(request.soul_id)
        if profile is None or not profile.enabled:
            raise KeyError(request.soul_id)

        seed_content = read_text(self.registry.base_dir / profile.seed_path)
        skill_lines = [f"- {item.title} (`{item.skill_id}`): {item.capability_summary}" for item in request.skill_views]
        runtime_tool_views = [item for item in request.tool_views if item.runtime_executable]
        tool_lines = [
            (
                f"- {item.title} (`{item.tool_id}`): {item.capability_summary}；"
                f"decision={item.policy_decision}"
            )
            for item in runtime_tool_views
        ]
        sections = (
            PromptSection(
                section_id="identity_view",
                title="灵魂身份",
                source_type="soul_seed",
                source_id=profile.seed_path,
                owner_layer="soul",
                cache_scope="static",
                visible_to_model=True,
                content=seed_content.strip(),
                source_refs=(profile.seed_path,),
            ),
            PromptSection(
                section_id="static_common_rules",
                title="静态共同准则",
                source_type="core",
                source_id=CORE_PATH,
                owner_layer="soul_core",
                cache_scope="static",
                visible_to_model=True,
                content=read_text(self.registry.base_dir / CORE_PATH).strip() or "当前未配置静态共同准则。",
                source_refs=(CORE_PATH,),
            ),
            PromptSection(
                section_id="dynamic_task_contract",
                title="动态任务契约",
                source_type="task_contract",
                source_id=request.task_id,
                owner_layer="task",
                cache_scope="dynamic",
                visible_to_model=True,
                content=request.task_contract_summary,
                source_refs=(request.task_id,),
            ),
            PromptSection(
                section_id="role_view",
                title="当前投影职责",
                source_type="task_contract",
                source_id=request.task_id,
                owner_layer="task",
                cache_scope="dynamic",
                visible_to_model=True,
                content=(
                    f"当前 TaskMode: {request.task_mode}\n"
                    f"当前 RoleType: {request.role_type}\n"
                    f"当前 AgentProfile: {request.agent_profile_id}\n"
                    "投影只约束本次任务的关注点、角色姿态和输出形态。"
                ),
                source_refs=(request.task_id,),
            ),
            PromptSection(
                section_id="skill_view",
                title="Skills 可见摘要",
                source_type="skill_contract",
                source_id="projection_request.skill_views",
                owner_layer="skill",
                cache_scope="semi-static",
                visible_to_model=True,
                content="\n".join(skill_lines) if skill_lines else "",
                source_refs=tuple(item.skill_id for item in request.skill_views),
            ),
            PromptSection(
                section_id="tool_view",
                title="Tools 可见摘要",
                source_type="resource_policy",
                source_id="projection_request.tool_views",
                owner_layer="resource_policy",
                cache_scope="dynamic",
                visible_to_model=True,
                content="\n".join(tool_lines) if tool_lines else "",
                source_refs=tuple(item.tool_id for item in runtime_tool_views),
            ),
            PromptSection(
                section_id="memory_output_view",
                title="记忆与输出边界",
                source_type="memory_policy",
                source_id=request.task_id,
                owner_layer="runtime",
                cache_scope="dynamic",
                visible_to_model=True,
                content=f"{request.memory_policy_summary}\n{request.output_contract_summary}",
                source_refs=(request.task_id,),
            ),
        )
        runtime_view = SoulRuntimeView(
            soul_id=profile.soul_id,
            role_type=request.role_type,
            task_mode=request.task_mode,
            sections=sections,
            visible_skill_ids=tuple(item.skill_id for item in request.skill_views),
            visible_tool_ids=tuple(item.tool_id for item in runtime_tool_views),
            trace={
                "projection_owner": "SoulProjectionBuilder",
                "authorization_owner": "ResourcePolicy",
                "profile_source": profile.source,
            },
        )
        projection_id = self._projection_id(request)
        manifest = build_prompt_manifest(request.task_id, projection_id, runtime_view)
        bundle = build_agent_prompt_bundle(
            agent_id=f"agent:{request.agent_profile_id}",
            agent_profile_id=request.agent_profile_id,
            task_id=request.task_id,
            projection_id=projection_id,
            runtime_view=runtime_view,
            prompt_manifest=manifest,
            refs={
                "prompt_manifest_ref": manifest.manifest_id,
                "task_prompt_contract_ref": request.task_id,
                "authorization_owner": runtime_view.authorization_owner,
            },
        )
        return {
            "projection_id": projection_id,
            "runtime_view": runtime_view.to_dict(),
            "prompt_manifest": manifest.to_dict(),
            "agent_prompt_bundle": bundle.to_dict(),
            "profile": profile.to_dict(),
        }

    def _projection_id(self, request: SoulProjectionRequest) -> str:
        raw = (
            f"{request.task_id}:{request.soul_id}:{request.role_type}:"
            f"{request.task_mode}:{request.agent_profile_id}:{request.projection_name}:"
            f"{request.task_contract_summary}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def soul_tool_view_from_resource_runtime_view(resource_view: Any) -> SoulToolView:
    data = resource_view.to_dict() if hasattr(resource_view, "to_dict") else dict(resource_view)
    return SoulToolView(
        tool_id=str(data.get("resource_id") or ""),
        title=str(data.get("title") or data.get("resource_id") or ""),
        capability_summary=str(data.get("capability_summary") or ""),
        input_schema_summary=str(data.get("input_contract_ref") or ""),
        output_schema_summary=str(data.get("output_contract_ref") or ""),
        risk_summary=str(data.get("risk_summary") or ""),
        authorized=bool(data.get("authorized", False)),
        authorization_owner=str(data.get("authorization_owner") or "ResourcePolicy"),
        requires_approval=bool(data.get("requires_approval", False)),
        available_to_model=bool(data.get("available_to_model", False)),
        runtime_executable=bool(data.get("runtime_executable", False)),
        denied_reason=str(data.get("denied_reason") or ""),
        policy_decision=str(data.get("policy_decision") or "unknown"),
    )


def soul_skill_view_from_skill_runtime_view(skill_view: Any) -> SoulSkillView:
    data = skill_view.to_dict() if hasattr(skill_view, "to_dict") else dict(skill_view)
    return SoulSkillView(
        skill_id=str(data.get("skill_id") or ""),
        title=str(data.get("title") or data.get("skill_id") or ""),
        capability_summary=str(data.get("method_summary") or ""),
        input_boundary=str(data.get("input_boundary") or ""),
        output_boundary=str(data.get("output_boundary") or ""),
        forbidden_uses=", ".join(list(data.get("forbidden_uses") or [])),
        current_task_reason=str(data.get("task_reason") or ""),
    )


def build_soul_runtime_view(
    *,
    task_prompt_contract: Any,
    projection_requirement: Any,
    skill_views: list[Any],
    resource_views: list[Any],
    soul_id: str = "runtime",
    agent_profile_id: str = "runtime_agent",
) -> dict[str, Any]:
    contract = task_prompt_contract.to_dict() if hasattr(task_prompt_contract, "to_dict") else dict(task_prompt_contract)
    projection = projection_requirement.to_dict() if hasattr(projection_requirement, "to_dict") else dict(projection_requirement)
    soul_skill_views = tuple(soul_skill_view_from_skill_runtime_view(item) for item in skill_views)
    soul_tool_views = tuple(soul_tool_view_from_resource_runtime_view(item) for item in resource_views)
    request = SoulProjectionRequest(
        task_id=str(contract.get("task_id") or ""),
        soul_id=soul_id,
        role_type=str(projection.get("role_type") or "runtime"),
        task_mode=str(contract.get("definition_id") or "runtime"),
        agent_profile_id=agent_profile_id,
        projection_name="runtime",
        skill_views=soul_skill_views,
        tool_views=soul_tool_views,
        task_contract_summary=str(contract.get("task_section") or ""),
        memory_policy_summary="",
        output_contract_summary=str(contract.get("output_section") or ""),
    )
    resource_content = _resource_projection_content(contract, soul_tool_views)
    resource_policy_ref = str(contract.get("metadata", {}).get("resource_policy_ref") or "")
    candidate_sections = [
        PromptSection(
            section_id="task_section",
            title="任务契约",
            source_type="task_contract",
            source_id=request.task_id,
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("task_section") or ""),
            source_refs=(str(contract.get("contract_id") or request.task_id),),
        ),
        PromptSection(
            section_id="method_section",
            title="方法摘要",
            source_type="skill_runtime_view",
            source_id="task_prompt_contract.method_section",
            owner_layer="skill",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("method_section") or ""),
            source_refs=tuple(item.skill_id for item in soul_skill_views),
        ),
        PromptSection(
            section_id="projection_section",
            title="投影姿态",
            source_type="projection_requirement",
            source_id=request.task_id,
            owner_layer="projection",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("projection_section") or ""),
            source_refs=(str(projection.get("task_id") or request.task_id),),
        ),
        PromptSection(
            section_id="output_section",
            title="输出边界",
            source_type="task_contract",
            source_id=request.task_id,
            owner_layer="task",
            cache_scope="dynamic",
            visible_to_model=True,
            content=str(contract.get("output_section") or ""),
            source_refs=(str(contract.get("contract_id") or request.task_id),),
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
    sections = tuple(
        section
        for section in candidate_sections
        if section.visible_to_model and section.content.strip()
    )
    runtime_view = SoulRuntimeView(
        soul_id=request.soul_id,
        role_type=request.role_type,
        task_mode=request.task_mode,
        sections=sections,
        visible_skill_ids=tuple(item.skill_id for item in soul_skill_views),
        visible_tool_ids=tuple(item.tool_id for item in soul_tool_views if item.runtime_executable),
        authorization_owner="ResourcePolicy",
        trace={
            "projection_owner": "SoulRuntimeProjection",
            "authorization_owner": "ResourcePolicy",
        },
    )
    projection_id = hashlib.sha1(
        f"{request.task_id}:{request.role_type}:{request.task_mode}:runtime".encode("utf-8")
    ).hexdigest()[:16]
    manifest = build_prompt_manifest(request.task_id, projection_id, runtime_view)
    metadata = contract.get("metadata", {}) if isinstance(contract.get("metadata"), dict) else {}
    bundle = build_agent_prompt_bundle(
        agent_id=str(metadata.get("agent_id") or "agent:runtime"),
        agent_profile_id=request.agent_profile_id,
        task_id=request.task_id,
        task_run_id=str(metadata.get("task_run_id") or ""),
        projection_id=projection_id,
        runtime_view=runtime_view,
        prompt_manifest=manifest,
        refs={
            "prompt_manifest_ref": manifest.manifest_id,
            "task_prompt_contract_ref": str(contract.get("contract_id") or ""),
            "binding_ref": str(contract.get("binding_id") or ""),
            "authorization_owner": runtime_view.authorization_owner,
        },
    )
    return {
        "projection_request": request.to_dict(),
        "runtime_view": runtime_view.to_dict(),
        "prompt_manifest": manifest.to_dict(),
        "agent_prompt_bundle": bundle.to_dict(),
        "projection_id": projection_id,
    }


def _resource_projection_content(contract: dict[str, Any], tool_views: tuple[SoulToolView, ...]) -> str:
    lines = []
    for item in [view for view in tool_views if view.runtime_executable]:
        lines.append(
            (
                f"- {item.title} (`{item.tool_id}`): "
                f"decision={item.policy_decision}"
            )
        )
    return "\n".join(line for line in lines if line)
