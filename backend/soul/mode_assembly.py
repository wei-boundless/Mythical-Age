from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .catalog_service import SoulCatalogService


@dataclass(slots=True, frozen=True)
class SoulModeSection:
    section_id: str
    title: str
    owner_layer: str
    source_id: str
    content: str
    visible_to_model: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chars"] = len(self.content)
        return payload


@dataclass(slots=True, frozen=True)
class SoulModeAssembly:
    mode: str
    soul_id: str
    projection_id: str
    work_prompt_id: str
    sections: tuple[SoulModeSection, ...]
    trace: dict[str, str] = field(default_factory=dict)
    authority: str = "soul.mode_assembly"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "soul_id": self.soul_id,
            "projection_id": self.projection_id,
            "work_prompt_id": self.work_prompt_id,
            "sections": [item.to_dict() for item in self.sections],
            "trace": dict(self.trace),
            "authority": self.authority,
        }


class SoulModeAssemblyService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.catalog_service = SoulCatalogService(self.base_dir)

    def preview(
        self,
        *,
        mode: str,
        soul_id: str,
        projection_id: str = "",
        work_prompt_id: str = "",
        task_contract: str = "",
    ) -> SoulModeAssembly:
        catalog = self.catalog_service.to_dict()
        mode_profile = self._find_one(catalog["modes"], "mode", mode)
        if not mode_profile:
            raise KeyError(f"Unknown soul mode: {mode}")
        card = self._find_one(catalog["cards"], "soul_id", soul_id)
        if not card:
            raise KeyError(f"Unknown soul: {soul_id}")

        resolved_projection_id = projection_id or str(card.get("default_projection_id") or "")
        resolved_work_prompt_id = work_prompt_id or str(card.get("default_work_prompt_id") or "work_prompt.default")
        sections: list[SoulModeSection] = []

        common_contract = self._first(catalog["common_contracts"])
        if common_contract:
            sections.append(
                SoulModeSection(
                    section_id="common_contract",
                    title="共同契约",
                    owner_layer="common_contract",
                    source_id=str(common_contract.get("prompt_id") or ""),
                    content=str(common_contract.get("content") or ""),
                )
            )

        if mode == "role_mode":
            world = self._find_one(catalog["worlds"], "world_id", str(card.get("world_id") or ""))
            if world:
                sections.append(
                    SoulModeSection(
                        section_id="world",
                        title="背景世界",
                        owner_layer="world",
                        source_id=str(world.get("world_id") or ""),
                        content=str(world.get("content") or world.get("summary") or ""),
                    )
                )

        if mode in {"role_mode", "standard_mode"}:
            story = self._find_one(catalog["stories"], "story_id", str(card.get("story_id") or ""))
            if story:
                sections.append(
                    SoulModeSection(
                        section_id="story",
                        title="灵魂本体",
                        owner_layer="story",
                        source_id=str(story.get("story_id") or ""),
                        content=str(story.get("content") or story.get("summary") or ""),
                    )
                )
            if resolved_projection_id:
                sections.append(
                    SoulModeSection(
                        section_id="projection",
                        title="工作投影",
                        owner_layer="projection",
                        source_id=resolved_projection_id,
                        content=f"使用工作投影：{resolved_projection_id}",
                    )
                )

        if mode == "work_mode":
            if task_contract:
                sections.append(
                    SoulModeSection(
                        section_id="task_contract",
                        title="任务契约",
                        owner_layer="task",
                        source_id="preview.task_contract",
                        content=task_contract,
                    )
                )
            work_prompt = self._find_one(catalog["work_prompts"], "prompt_id", resolved_work_prompt_id)
            if work_prompt:
                sections.append(
                    SoulModeSection(
                        section_id="work_prompt",
                        title="工作 prompt",
                        owner_layer="work_prompt",
                        source_id=str(work_prompt.get("prompt_id") or ""),
                        content=str(work_prompt.get("content") or ""),
                    )
                )

        return SoulModeAssembly(
            mode=mode,
            soul_id=soul_id,
            projection_id=resolved_projection_id if mode != "work_mode" else "",
            work_prompt_id=resolved_work_prompt_id if mode == "work_mode" else "",
            sections=tuple(section for section in sections if section.content.strip()),
            trace={
                "includes_world": str(bool(mode_profile.get("includes_world"))).lower(),
                "includes_story": str(bool(mode_profile.get("includes_story"))).lower(),
                "includes_work_prompt": str(bool(mode_profile.get("includes_work_prompt"))).lower(),
            },
        )

    @staticmethod
    def _find_one(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
        target = str(value or "")
        return next((item for item in items if str(item.get(key) or "") == target), {})

    @staticmethod
    def _first(items: list[dict[str, Any]]) -> dict[str, Any]:
        return dict(items[0]) if items else {}
