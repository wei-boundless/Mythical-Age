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
from .projection_store import load_projection_store
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
                "title": "默认无背景世界",
                "summary": "不注入额外世界观，仅保留灵魂卡片自身说明。",
                "content": "这是默认无背景世界。它只表示当前灵魂不绑定额外世界观，不参与纯工作模式。",
                "source_ref": "soul/worlds/catalog.json",
                "metadata": {"system_default": True},
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
        projection_by_soul = self._default_projection_by_soul()
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
                    "default_projection_id": projection_by_soul.get(soul_id, f"{soul_id}__primary"),
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
                "title": "默认纯工作 prompt",
                "content": "你是一名执行当前任务的工作 Agent。你只关注用户目标、任务契约、可用资源和验收要求。你不进行灵魂扮演，不引用背景世界，不用故事设定解释工作行为。",
                "source_ref": "soul/work_prompts/catalog.json",
                "task_mode": "work_mode",
                "role_type": "worker",
                "metadata": {"system_default": True},
            }
        ]

    def _default_common_contracts(self) -> list[dict[str, Any]]:
        content = read_text(self.base_dir / CORE_PATH).strip()
        return [
            {
                "prompt_id": "common_contract.default",
                "title": "默认共同契约",
                "content": content or "遵守用户当前目标、事实边界、执行义务和输出要求。",
                "source_ref": CORE_PATH,
                "version": "v1",
                "cache_scope": "static",
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

    def _default_projection_by_soul(self) -> dict[str, str]:
        result: dict[str, str] = {}
        store = load_projection_store(self.base_dir)
        for card in list(store.get("cards") or []):
            if not isinstance(card, dict):
                continue
            soul_id = str(card.get("soul_id") or "").strip().lower()
            projection_id = str(card.get("projection_id") or "").strip()
            if soul_id and projection_id and soul_id not in result:
                result[soul_id] = projection_id
        return result

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
            default_projection_id=str(payload.get("default_projection_id") or ""),
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
            section_order=("common_contract", "world", "story", "projection"),
            includes_world=True,
            includes_story=True,
            includes_work_prompt=False,
            description="用于带背景、带灵魂体验的对话与陪伴场景。",
        ),
        SoulModeProfile(
            mode="standard_mode",
            title="标准模式",
            section_order=("common_contract", "story", "projection"),
            includes_world=False,
            includes_story=True,
            includes_work_prompt=False,
            description="用于保留灵魂表达但不渲染背景世界的常规任务。",
        ),
        SoulModeProfile(
            mode="work_mode",
            title="工作模式",
            section_order=("common_contract", "task_contract", "work_prompt"),
            includes_world=False,
            includes_story=False,
            includes_work_prompt=True,
            description="用于纯执行任务，不进行灵魂扮演。",
        ),
    ]
