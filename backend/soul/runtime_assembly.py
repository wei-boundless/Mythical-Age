from __future__ import annotations

import hashlib
from typing import Any

from soul.agent_prompt_bundle import build_agent_prompt_bundle
from soul.contracts import PromptSection, SoulProjectionRequest, SoulRuntimeView, SoulToolView
from soul.prompt_assembly import build_prompt_manifest

from .view_mapping import (
    soul_skill_view_from_skill_runtime_view,
    soul_tool_view_from_resource_runtime_view,
)


class SoulRuntimeAssemblyBuilder:
    """Build runtime-facing soul identity artifacts for orchestration consumption."""

    def build_runtime_view(
        self,
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
            usage_summary=str(contract.get("projection_section") or ""),
            memory_policy_summary="",
            output_contract_summary=str(contract.get("output_section") or ""),
        )
        sections = self._runtime_sections(
            contract=contract,
            projection=projection,
            request=request,
            soul_skill_views=soul_skill_views,
            soul_tool_views=soul_tool_views,
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

    def _runtime_sections(
        self,
        *,
        contract: dict[str, Any],
        projection: dict[str, Any],
        request: SoulProjectionRequest,
        soul_skill_views: tuple[Any, ...],
        soul_tool_views: tuple[SoulToolView, ...],
    ) -> tuple[PromptSection, ...]:
        resource_content = _resource_projection_content(soul_tool_views)
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
                section_id="workflow_section",
                title="工作流",
                source_type="task_workflow",
                source_id="task_prompt_contract.workflow_section",
                owner_layer="task",
                cache_scope="dynamic",
                visible_to_model=True,
                content=str(contract.get("workflow_section") or ""),
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
        return tuple(
            section
            for section in candidate_sections
            if section.visible_to_model and section.content.strip()
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
    return SoulRuntimeAssemblyBuilder().build_runtime_view(
        task_prompt_contract=task_prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_views,
        resource_views=resource_views,
        soul_id=soul_id,
        agent_profile_id=agent_profile_id,
    )


def _resource_projection_content(tool_views: tuple[SoulToolView, ...]) -> str:
    lines = []
    for item in [view for view in tool_views if view.runtime_executable]:
        lines.append(f"- {item.title} (`{item.tool_id}`): decision={item.policy_decision}")
    return "\n".join(line for line in lines if line)
