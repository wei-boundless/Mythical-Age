from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from prompt_library import assemble_runtime_prompt_sections
from soul.agent_prompt_bundle import build_agent_prompt_bundle
from soul.contracts import SoulProjectionRequest, SoulRuntimeView
from soul.prompt_assembly import build_prompt_manifest

from .view_mapping import (
    soul_skill_view_from_skill_runtime_view,
    soul_tool_view_from_resource_runtime_view,
)


class SoulRuntimeAssemblyBuilder:
    """Build runtime-facing soul identity artifacts for orchestration consumption."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def build_runtime_view(
        self,
        *,
        task_prompt_contract: Any,
        projection_requirement: Any,
        skill_views: list[Any],
        resource_views: list[Any],
        soul_id: str = "runtime",
        agent_profile_id: str = "runtime_agent",
        use_shared_contract: bool = True,
    ) -> dict[str, Any]:
        contract = task_prompt_contract.to_dict() if hasattr(task_prompt_contract, "to_dict") else dict(task_prompt_contract)
        projection = projection_requirement.to_dict() if hasattr(projection_requirement, "to_dict") else dict(projection_requirement)
        soul_skill_views = tuple(soul_skill_view_from_skill_runtime_view(item) for item in skill_views)
        soul_tool_views = tuple(soul_tool_view_from_resource_runtime_view(item) for item in resource_views)
        request = SoulProjectionRequest(
            task_id=str(contract.get("task_id") or ""),
            soul_id=soul_id,
            identity_anchor=str(projection.get("identity_anchor") or ""),
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
            use_shared_contract=use_shared_contract,
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
                "prompt_section_owner": "PromptLibrary",
                "projection_owner": "SoulRuntimeProjection",
                "authorization_owner": "ResourcePolicy",
            },
        )
        projection_id = str(projection.get("projection_id") or "").strip()
        if not projection_id:
            projection_id = hashlib.sha1(
                f"{request.task_id}:{request.role_type}:{request.task_mode}:runtime".encode("utf-8")
            ).hexdigest()[:16]
        metadata = contract.get("metadata", {}) if isinstance(contract.get("metadata"), dict) else {}
        interaction_mode = str(
            dict(metadata.get("prompt_selection_context") or {}).get("interaction_mode")
            or dict(metadata.get("mode_policy") or {}).get("interaction_mode")
            or projection.get("interaction_mode")
            or ""
        ).strip()
        manifest = build_prompt_manifest(
            request.task_id,
            projection_id,
            runtime_view,
            interaction_mode=interaction_mode,
            metadata={
                "interaction_mode": interaction_mode,
                "agent_id": str(metadata.get("agent_id") or "agent:runtime"),
            },
        )
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

    def _runtime_sections(self, **payload: Any):
        return assemble_runtime_prompt_sections(base_dir=self.base_dir, **payload)


def build_soul_runtime_view(
    *,
    task_prompt_contract: Any,
    projection_requirement: Any,
    skill_views: list[Any],
    resource_views: list[Any],
    soul_id: str = "runtime",
    agent_profile_id: str = "runtime_agent",
    use_shared_contract: bool = True,
    base_dir: Path | str = ".",
) -> dict[str, Any]:
    return SoulRuntimeAssemblyBuilder(Path(base_dir)).build_runtime_view(
        task_prompt_contract=task_prompt_contract,
        projection_requirement=projection_requirement,
        skill_views=skill_views,
        resource_views=resource_views,
        soul_id=soul_id,
        agent_profile_id=agent_profile_id,
        use_shared_contract=use_shared_contract,
    )
