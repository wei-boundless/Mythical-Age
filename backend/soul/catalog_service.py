from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog_store import SoulCatalogStore
from .contracts import (
    CommonContractPrompt,
    SoulCard,
    SoulManifestation,
    SoulModeProfile,
    SoulResourceCatalog,
    SoulStory,
    SoulWorld,
    WorkPrompt,
)
from .registry import CORE_PATH, BUILTIN_PROFILES, BUILTIN_SOUL_NAMES, SoulRegistry, read_text


class SoulCatalogService:
    """Build the formal soul resource catalog consumed by backend and future frontend."""

    def __init__(self, base_dir: Path, *, registry: SoulRegistry | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.registry = registry or SoulRegistry(self.base_dir)
        self.store = SoulCatalogStore(self.base_dir)

    def build_catalog(self) -> SoulResourceCatalog:
        profiles = self.registry.profiles(include_disabled=True)
        active_soul_id = self.registry.active_soul_id()
        worlds = [self._world_from_payload(item) for item in self.store.ensure_bucket("worlds", self._default_worlds())]
        stories = [self._story_from_payload(item) for item in self.store.ensure_bucket("stories", self._default_stories())]
        work_prompts = [
            self._work_prompt_from_payload(item)
            for item in self.store.ensure_bucket("work_prompts", self._default_work_prompts())
        ]
        system_contracts = [self._system_contract()]
        common_contracts = [
            self._common_contract_from_payload(item)
            for item in self.store.ensure_bucket("common_contracts", self._default_common_contracts())
        ]
        manifestations = [
            self._manifestation_from_payload(item)
            for item in self.store.ensure_bucket("manifestations", self._default_manifestations())
        ]
        cards = [
            self._card_from_payload(item)
            for item in self.store.ensure_bucket("cards", self._default_cards())
            if str(item.get("soul_id") or "") in profiles
        ]
        return SoulResourceCatalog(
            active_soul_id=active_soul_id,
            worlds=tuple(worlds),
            stories=tuple(stories),
            cards=tuple(cards),
            work_prompts=tuple(work_prompts),
            system_contracts=tuple(system_contracts),
            common_contracts=tuple(common_contracts),
            manifestations=tuple(manifestations),
            modes=tuple(default_mode_profiles()),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.build_catalog().to_dict()

    def _default_worlds(self) -> list[dict[str, Any]]:
        return [
            {
                "world_id": "world.default",
                "title": "现实世界",
                "summary": "真实任务、共同契约与无角色执行投影的工作空间。",
                "content": "这里承载现实任务所需的共同契约、工作指令和专业执行投影。它不启用洪荒叙事，也不要求灵魂扮演，只帮助用户把目标、证据、工具和验收边界整理清楚。",
                "source_ref": "soul/worlds/catalog.json",
                "metadata": {"system_default": True, "theme": "reality"},
            }
        ]

    def _default_stories(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for soul_id, name in BUILTIN_SOUL_NAMES.items():
            profile = BUILTIN_PROFILES[soul_id]
            items.append(
                {
                    "story_id": f"story.{soul_id}.default",
                    "soul_id": soul_id,
                    "title": f"{name}默认灵魂故事",
                    "summary": str(profile.get("description") or ""),
                    "content": str(profile.get("background") or profile.get("description") or ""),
                    "world_id": "world.default",
                    "source_ref": f"soul/agent_core/seeds/{soul_id}.md",
                    "metadata": {"system_default": True},
                }
            )
        return items

    def _default_cards(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for soul_id, name in BUILTIN_SOUL_NAMES.items():
            profile = BUILTIN_PROFILES[soul_id]
            items.append(
                {
                    "soul_id": soul_id,
                    "name": name,
                    "display_name": name,
                    "story_id": f"story.{soul_id}.default",
                    "world_id": "world.default",
                    "manifestation_id": f"manifestation.{soul_id}.default",
                    "default_work_prompt_id": "work_prompt.default",
                    "description": str(profile.get("description") or ""),
                    "source": "builtin",
                    "enabled": True,
                    "tags": list(profile.get("preferred_task_modes") or ()),
                    "metadata": {"system_default": True},
                }
            )
        return items

    def _default_work_prompts(self) -> list[dict[str, Any]]:
        return [
            {
                "prompt_id": "work_prompt.default",
                "title": "默认工作指令",
                "content": "你是一名执行当前任务的工作 Agent。你只关注用户目标、任务契约、可用资源和验收要求。你不进行灵魂扮演，不引用背景世界，不用故事设定解释工作行为。",
                "source_ref": "soul/work_prompts/catalog.json",
                "task_mode": "work_mode",
                "role_type": "worker",
                "metadata": {"system_default": True, "world_id": "world.default"},
            }
        ]

    def _default_common_contracts(self) -> list[dict[str, Any]]:
        return [
            {
                "prompt_id": "common_contract.default",
                "title": "默认用户共同契约",
                "content": (
                    "## 工作偏好\n\n"
                    "- 优先按用户当前真实目标推进，不把内部流程名称当作用户目标。\n"
                    "- 需要行动时先确认关键边界，再给出可执行结果。\n"
                    "- 表达要清楚、直接、有人味；不要为了显得完整而堆叠无关内容。\n\n"
                    "## 项目约定\n\n"
                    "- Agent prompt 应写成角色职责、工作边界、可执行任务和裁决标准。\n"
                    "- 当项目要求真实验证时，交付前需要说明验证方式和结果。"
                ),
                "source_ref": "soul/common_contracts/catalog.json",
                "version": "v2",
                "cache_scope": "static",
                "contract_layer": "user_common",
                "editable": True,
            }
        ]

    def _default_manifestations(self) -> list[dict[str, Any]]:
        return [
            {
                "manifestation_id": f"manifestation.{soul_id}.default",
                "soul_id": soul_id,
                "display_name": name,
                "avatar_ref": f"/souls/{soul_id}.png",
                "portrait_ref": f"/souls/{soul_id}.png",
                "model_ref": "",
                "state": "idle",
                "metadata": {"system_default": True, "display_only": True},
            }
            for soul_id, name in BUILTIN_SOUL_NAMES.items()
        ]

    @staticmethod
    def _world_from_payload(payload: dict[str, Any]) -> SoulWorld:
        return SoulWorld(
            world_id=str(payload.get("world_id") or ""),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            content=str(payload.get("content") or ""),
            source_ref=str(payload.get("source_ref") or ""),
            version=str(payload.get("version") or "v1"),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _story_from_payload(payload: dict[str, Any]) -> SoulStory:
        return SoulStory(
            story_id=str(payload.get("story_id") or ""),
            soul_id=str(payload.get("soul_id") or ""),
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            content=str(payload.get("content") or ""),
            world_id=str(payload.get("world_id") or ""),
            source_ref=str(payload.get("source_ref") or ""),
            version=str(payload.get("version") or "v1"),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _work_prompt_from_payload(payload: dict[str, Any]) -> WorkPrompt:
        return WorkPrompt(
            prompt_id=str(payload.get("prompt_id") or ""),
            title=str(payload.get("title") or ""),
            content=str(payload.get("content") or ""),
            source_ref=str(payload.get("source_ref") or ""),
            task_mode=str(payload.get("task_mode") or "work_mode"),
            role_type=str(payload.get("role_type") or ""),
            version=str(payload.get("version") or "v1"),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _common_contract_from_payload(payload: dict[str, Any]) -> CommonContractPrompt:
        return CommonContractPrompt(
            prompt_id=str(payload.get("prompt_id") or ""),
            title=str(payload.get("title") or ""),
            content=str(payload.get("content") or ""),
            source_ref=str(payload.get("source_ref") or ""),
            version=str(payload.get("version") or "v1"),
            cache_scope=str(payload.get("cache_scope") or "static"),
            contract_layer=str(payload.get("contract_layer") or "user_common"),
            editable=bool(payload.get("editable", True)),
            authority=str(payload.get("authority") or "soul.common_contract"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _system_contract(self) -> CommonContractPrompt:
        content = read_text(self.base_dir / CORE_PATH).strip()
        return CommonContractPrompt(
            prompt_id="system_contract.core",
            title="系统硬契约",
            content=content or "遵守事实、执行、权限、测试和输出底线。",
            source_ref=CORE_PATH,
            version="v2",
            cache_scope="static",
            contract_layer="protected_system",
            editable=False,
            authority="soul.protected_system_contract",
            metadata={
                "protected": True,
                "user_edit_bucket": False,
                "runtime_required": True,
            },
        )

    @staticmethod
    def _manifestation_from_payload(payload: dict[str, Any]) -> SoulManifestation:
        return SoulManifestation(
            manifestation_id=str(payload.get("manifestation_id") or ""),
            soul_id=str(payload.get("soul_id") or ""),
            display_name=str(payload.get("display_name") or ""),
            avatar_ref=str(payload.get("avatar_ref") or ""),
            portrait_ref=str(payload.get("portrait_ref") or ""),
            model_ref=str(payload.get("model_ref") or ""),
            state=str(payload.get("state") or "idle"),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _card_from_payload(payload: dict[str, Any]) -> SoulCard:
        return SoulCard(
            soul_id=str(payload.get("soul_id") or ""),
            name=str(payload.get("name") or ""),
            display_name=str(payload.get("display_name") or payload.get("name") or ""),
            story_id=str(payload.get("story_id") or ""),
            world_id=str(payload.get("world_id") or ""),
            manifestation_id=str(payload.get("manifestation_id") or ""),
            default_work_prompt_id=str(payload.get("default_work_prompt_id") or ""),
            description=str(payload.get("description") or ""),
            source=str(payload.get("source") or "builtin"),
            enabled=bool(payload.get("enabled", True)),
            tags=tuple(str(item) for item in list(payload.get("tags") or []) if str(item).strip()),
            metadata=dict(payload.get("metadata") or {}),
        )


def default_mode_profiles() -> list[SoulModeProfile]:
    return [
        SoulModeProfile(
            mode="role_mode",
            title="角色模式",
            section_order=("protected_system_rules", "shared_common_contract", "world", "story"),
            includes_world=True,
            includes_story=True,
            includes_work_prompt=False,
            description="用于带背景、带灵魂体验的对话与陪伴场景。",
        ),
        SoulModeProfile(
            mode="standard_mode",
            title="标准模式",
            section_order=("protected_system_rules", "shared_common_contract", "story"),
            includes_world=False,
            includes_story=True,
            includes_work_prompt=False,
            description="用于保留灵魂表达但不渲染背景世界的常规任务。",
        ),
        SoulModeProfile(
            mode="work_mode",
            title="工作模式",
            section_order=("protected_system_rules", "shared_common_contract", "task_contract", "work_prompt"),
            includes_world=False,
            includes_story=False,
            includes_work_prompt=True,
            description="用于纯执行任务，不进行灵魂扮演。",
        ),
    ]


