from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(slots=True, frozen=True)
class SoulProfile:
    soul_id: str
    name: str
    display_name: str
    source: str
    version: str
    enabled: bool
    seed_path: str
    description: str
    background: str = ""
    personality_traits: tuple[str, ...] = ()
    expression_style: tuple[str, ...] = ()
    preferred_role_types: tuple[str, ...] = ()
    preferred_task_modes: tuple[str, ...] = ()
    collaboration_tendencies: tuple[str, ...] = ()
    memory_preferences: tuple[str, ...] = ()
    risk_biases: tuple[str, ...] = ()
    guardrails: tuple[str, ...] = ()
    portrait: str | None = None
    validation_errors: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(slots=True, frozen=True)
class SoulRole:
    role_id: str
    soul_id: str
    role_type: str
    agent_profile_id: str
    task_mode: str
    expected_artifact: str = "answer"
    allowed_skills: tuple[str, ...] = ()
    visible_tools: tuple[str, ...] = ()
    handoff_target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SoulSkillView:
    skill_id: str
    title: str
    capability_summary: str
    use_when: str = ""
    input_boundary: str = ""
    output_boundary: str = ""
    forbidden_uses: str = ""
    current_task_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SoulToolView:
    tool_id: str
    title: str
    capability_summary: str
    input_schema_summary: str = ""
    output_schema_summary: str = ""
    risk_summary: str = ""
    authorized: bool = False
    authorization_owner: str = "ResourcePolicy"
    requires_approval: bool = False
    available_to_model: bool = False
    runtime_executable: bool = False
    denied_reason: str = ""
    policy_decision: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SoulProjectionRequest:
    task_id: str
    soul_id: str
    role_type: str
    task_mode: str
    agent_profile_id: str
    projection_name: str = ""
    projection_prompt: str = ""
    skill_views: tuple[SoulSkillView, ...] = ()
    tool_views: tuple[SoulToolView, ...] = ()
    usage_summary: str = "可被任务系统选用的灵魂投影资源。"
    memory_policy_summary: str = "当前运行阶段不授予记忆写回权。"
    output_contract_summary: str = "输出当前灵魂运行时视图。"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skill_views"] = [item.to_dict() for item in self.skill_views]
        payload["tool_views"] = [item.to_dict() for item in self.tool_views]
        return payload


@dataclass(slots=True, frozen=True)
class PromptSection:
    section_id: str
    title: str
    source_type: str
    source_id: str
    owner_layer: str
    cache_scope: str
    visible_to_model: bool
    content: str
    source_refs: tuple[str, ...] = ()
    candidate_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = list(self.source_refs)
        payload["candidate_refs"] = list(self.candidate_refs)
        payload["chars"] = len(self.content)
        return payload


@dataclass(slots=True, frozen=True)
class SoulRuntimeView:
    soul_id: str
    role_type: str
    task_mode: str
    sections: tuple[PromptSection, ...]
    visible_skill_ids: tuple[str, ...]
    visible_tool_ids: tuple[str, ...]
    authorization_owner: str = "ResourcePolicy"
    trace: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "soul_id": self.soul_id,
            "role_type": self.role_type,
            "task_mode": self.task_mode,
            "sections": [section.to_dict() for section in self.sections],
            "visible_skill_ids": list(self.visible_skill_ids),
            "visible_tool_ids": list(self.visible_tool_ids),
            "authorization_owner": self.authorization_owner,
            "trace": dict(self.trace),
        }


@dataclass(slots=True, frozen=True)
class CommonContractPrompt:
    prompt_id: str
    title: str
    content: str
    source_ref: str
    version: str = "v1"
    cache_scope: str = "static"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chars"] = len(self.content)
        return payload


@dataclass(slots=True, frozen=True)
class SoulTemplatePrompt:
    prompt_id: str
    soul_id: str
    title: str
    content: str
    source_ref: str
    version: str = "v1"
    cache_scope: str = "static"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chars"] = len(self.content)
        return payload


@dataclass(slots=True, frozen=True)
class PromptSectionManifest:
    section_id: str
    source_type: str
    source_id: str
    owner_layer: str
    cache_scope: str
    visible_to_model: bool
    chars: int
    source_refs: tuple[str, ...] = ()
    candidate_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_refs"] = list(self.source_refs)
        payload["candidate_refs"] = list(self.candidate_refs)
        return payload


@dataclass(slots=True, frozen=True)
class SoulPromptManifest:
    manifest_id: str
    task_id: str
    soul_id: str
    projection_id: str
    sections: tuple[PromptSectionManifest, ...]
    prompt_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "task_id": self.task_id,
            "soul_id": self.soul_id,
            "projection_id": self.projection_id,
            "sections": [section.to_dict() for section in self.sections],
            "prompt_hash": self.prompt_hash,
        }


@dataclass(slots=True, frozen=True)
class AgentPromptBundle:
    bundle_id: str
    agent_id: str
    agent_profile_id: str
    task_id: str
    task_run_id: str
    soul_id: str
    projection_id: str
    sections: tuple[PromptSection, ...]
    prompt_manifest: SoulPromptManifest
    cache_plan: Mapping[str, str] = field(default_factory=dict)
    refs: Mapping[str, str] = field(default_factory=dict)
    authority: str = "soul.agent_prompt_bundle"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "agent_id": self.agent_id,
            "agent_profile_id": self.agent_profile_id,
            "task_id": self.task_id,
            "task_run_id": self.task_run_id,
            "soul_id": self.soul_id,
            "projection_id": self.projection_id,
            "sections": [section.to_dict() for section in self.sections],
            "prompt_manifest": self.prompt_manifest.to_dict(),
            "cache_plan": dict(self.cache_plan),
            "refs": dict(self.refs),
            "authority": self.authority,
        }
