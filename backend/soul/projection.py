from __future__ import annotations

import hashlib

from soul.contracts import PromptSection, SoulProjectionRequest, SoulRuntimeView
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
        tool_lines = [
            f"- {item.title} (`{item.tool_id}`): {item.capability_summary}；授权：{'是' if item.authorized else '否'}"
            for item in request.tool_views
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
                    "灵魂投影只改变承载方式，不扩大工具、记忆或调度权限。"
                ),
            ),
            PromptSection(
                section_id="skill_view",
                title="Skills 可见摘要",
                source_type="skill_contract",
                source_id="projection_request.skill_views",
                owner_layer="skill",
                cache_scope="semi-static",
                visible_to_model=True,
                content="\n".join(skill_lines) if skill_lines else "当前预览没有注入额外 skill。灵魂仍具备基础对话能力。",
            ),
            PromptSection(
                section_id="tool_view",
                title="Tools 可见摘要",
                source_type="tool_contract",
                source_id="projection_request.tool_views",
                owner_layer="resource_policy",
                cache_scope="semi-static",
                visible_to_model=True,
                content="\n".join(tool_lines) if tool_lines else "当前预览没有注入可见 tool；工具授权仍由 ResourcePolicy 决定。",
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
            ),
        )
        runtime_view = SoulRuntimeView(
            soul_id=profile.soul_id,
            role_type=request.role_type,
            task_mode=request.task_mode,
            sections=sections,
            visible_skill_ids=tuple(item.skill_id for item in request.skill_views),
            visible_tool_ids=tuple(item.tool_id for item in request.tool_views if item.authorized),
            trace={
                "projection_owner": "SoulProjectionBuilder",
                "authorization_owner": "ResourcePolicy",
                "profile_source": profile.source,
            },
        )
        projection_id = self._projection_id(request)
        manifest = build_prompt_manifest(request.task_id, projection_id, runtime_view)
        return {
            "projection_id": projection_id,
            "runtime_view": runtime_view.to_dict(),
            "prompt_manifest": manifest.to_dict(),
            "profile": profile.to_dict(),
        }

    def _projection_id(self, request: SoulProjectionRequest) -> str:
        raw = (
            f"{request.task_id}:{request.soul_id}:{request.role_type}:"
            f"{request.task_mode}:{request.agent_profile_id}:{request.projection_name}:"
            f"{request.task_contract_summary}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
