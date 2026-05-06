from __future__ import annotations

import hashlib

from soul.agent_prompt_bundle import build_agent_prompt_bundle
from soul.contracts import PromptSection, SoulProjectionRequest, SoulRuntimeView
from soul.prompt_assembly import build_prompt_manifest
from soul.registry import CORE_PATH, SoulRegistry, read_text


class SoulProjectionBuilder:
    """Build static soul/projection prompt bundles for soul-side management and preview."""

    def __init__(self, registry: SoulRegistry):
        self.registry = registry

    def build(self, request: SoulProjectionRequest) -> dict[str, object]:
        profile = self.registry.get_profile(request.soul_id)
        if profile is None or not profile.enabled:
            raise KeyError(request.soul_id)

        seed_content = read_text(self.registry.base_dir / profile.seed_path)
        sections = self._sections(profile.seed_path, seed_content, request)
        runtime_tool_views = [item for item in request.tool_views if item.runtime_executable]
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

    def _sections(
        self,
        seed_path: str,
        seed_content: str,
        request: SoulProjectionRequest,
    ) -> tuple[PromptSection, ...]:
        skill_lines = [f"- {item.title} (`{item.skill_id}`): {item.capability_summary}" for item in request.skill_views]
        runtime_tool_views = [item for item in request.tool_views if item.runtime_executable]
        tool_lines = [
            (
                f"- {item.title} (`{item.tool_id}`): {item.capability_summary}；"
                f"decision={item.policy_decision}"
            )
            for item in runtime_tool_views
        ]
        role_view_content = (
            f"当前 TaskMode: {request.task_mode}\n"
            f"当前 RoleType: {request.role_type}\n"
            f"当前 AgentProfile: {request.agent_profile_id}\n"
            "投影只约束本次任务的关注点、角色姿态和输出形态。"
        )
        projection_identity = str(request.identity_anchor or "").strip()
        if projection_identity:
            role_view_content = f"{projection_identity}\n\n{role_view_content}"
        return (
            PromptSection(
                section_id="identity_view",
                title="灵魂基础身份",
                source_type="soul_seed",
                source_id=seed_path,
                owner_layer="soul",
                cache_scope="static",
                visible_to_model=True,
                content=_strip_identity_anchor(seed_content).strip(),
                source_refs=(seed_path,),
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
                content=request.usage_summary,
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
                content=role_view_content,
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

    def _projection_id(self, request: SoulProjectionRequest) -> str:
        raw = (
            f"{request.task_id}:{request.soul_id}:{request.role_type}:"
            f"{request.task_mode}:{request.agent_profile_id}:{request.projection_name}:"
            f"{request.usage_summary}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _strip_identity_anchor(content: str) -> str:
    lines = content.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and ("身份锚点" in stripped or "Identity Anchor" in stripped):
            skipping = True
            continue
        if skipping and stripped.startswith("## "):
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip()
