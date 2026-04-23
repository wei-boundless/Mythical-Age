from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SkillDefinition:
    name: str
    title: str
    description: str
    path: str
    allowed_tools: list[str] = field(default_factory=list)
    supported_modalities: list[str] = field(default_factory=list)
    supported_task_kinds: list[str] = field(default_factory=list)
    supported_source_kinds: list[str] = field(default_factory=list)
    capability_tags: list[str] = field(default_factory=list)
    preferred_route: str = "rag"
    forbidden_routes: list[str] = field(default_factory=list)
    routing_hints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    activation_policy: str = "model_visible"
    context_mode: str = "inline"
    route_authority: str = "candidate_only"
    reference_paths: list[str] = field(default_factory=list)


class SkillRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.registry_path = base_dir / "SKILLS_REGISTRY.json"
        self._skills: list[SkillDefinition] = []
        self.reload()

    def reload(self) -> None:
        if not self.registry_path.exists():
            self._skills = []
            return
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            self._skills = []
            return
        skills: list[SkillDefinition] = []
        for item in payload.get("skills", []):
            if not isinstance(item, dict):
                continue
            skills.append(
                SkillDefinition(
                    name=str(item.get("name", "")).strip(),
                    title=str(item.get("title", "")).strip(),
                    description=str(item.get("description", "")).strip(),
                    path=str(item.get("path", "")).strip(),
                    allowed_tools=[str(v) for v in item.get("allowed_tools", []) if str(v).strip()],
                    supported_modalities=[str(v) for v in item.get("supported_modalities", []) if str(v).strip()],
                    supported_task_kinds=[str(v) for v in item.get("supported_task_kinds", []) if str(v).strip()],
                    supported_source_kinds=[str(v) for v in item.get("supported_source_kinds", []) if str(v).strip()],
                    capability_tags=[str(v) for v in item.get("capability_tags", []) if str(v).strip()],
                    preferred_route=str(item.get("preferred_route", "rag") or "rag").strip(),
                    forbidden_routes=[str(v) for v in item.get("forbidden_routes", []) if str(v).strip()],
                    routing_hints=[str(v) for v in item.get("routing_hints", []) if str(v).strip()],
                    examples=[str(v) for v in item.get("examples", []) if str(v).strip()],
                    activation_policy=str(item.get("activation_policy", "model_visible") or "model_visible").strip(),
                    context_mode=str(item.get("context_mode", "inline") or "inline").strip(),
                    route_authority=str(item.get("route_authority", "candidate_only") or "candidate_only").strip(),
                    reference_paths=[str(v) for v in item.get("reference_paths", []) if str(v).strip()],
                )
            )
        self._skills = skills

    @property
    def skills(self) -> list[SkillDefinition]:
        return list(self._skills)

    def get_by_name(self, name: str | None) -> SkillDefinition | None:
        if not name:
            return None
        target = name.strip().lower()
        for skill in self._skills:
            if skill.name.lower() == target:
                return skill
        return None

    def get_for_tool(self, tool_name: str | None) -> SkillDefinition | None:
        if not tool_name:
            return None
        target = tool_name.strip().lower()
        for skill in self._skills:
            if any(tool.lower() == target for tool in skill.allowed_tools):
                return skill
        return None

    def match_for_query(
        self,
        message: str,
        route: str,
        modality: str,
        *,
        task_kind: str | None = None,
        source_kind: str | None = None,
        tool_name: str | None = None,
        candidate_tools: list[str] | None = None,
    ) -> SkillDefinition | None:
        if tool_name:
            tool_skill = self.get_for_tool(tool_name)
            if tool_skill is not None:
                return tool_skill

        normalized = (message or "").strip().lower()
        best_skill: SkillDefinition | None = None
        best_score = float("-inf")

        for skill in self._skills:
            score = 0.0
            if route and route in skill.forbidden_routes:
                score -= 100.0

            if task_kind and task_kind in skill.supported_task_kinds:
                score += 8.0
            if source_kind and source_kind in skill.supported_source_kinds:
                score += 7.0
            if route and skill.preferred_route == route:
                score += 3.0
            if modality and modality in skill.supported_modalities:
                score += 2.0

            if candidate_tools and skill.allowed_tools:
                overlap = set(candidate_tools) & set(skill.allowed_tools)
                score += float(len(overlap)) * 2.5

            for hint in skill.routing_hints:
                if hint and hint.lower() in normalized:
                    score += 2.0
            for example in skill.examples:
                example_lower = example.lower()
                if example_lower and example_lower in normalized:
                    score += 3.0
            for tag in skill.capability_tags:
                if tag and tag.lower() in normalized:
                    score += 1.0

            if score > best_score:
                best_score = score
                best_skill = skill

        if best_skill is not None and best_score > 0:
            return best_skill

        if task_kind in {"knowledge_lookup", "faq_explanation"}:
            return self.get_by_name("rag-skill")
        if route == "rag":
            return self.get_by_name("rag-skill")
        return None

    def format_active_skill_block(self, skill: SkillDefinition | None) -> str | None:
        if skill is None:
            return None
        lines = [
            f"Skill: {skill.title or skill.name}",
            f"Skill ID: {skill.name}",
            f"Preferred Route: {skill.preferred_route}",
            f"Activation Policy: {skill.activation_policy}",
            f"Context Mode: {skill.context_mode}",
            f"Route Authority: {skill.route_authority}",
            f"Description: {skill.description}",
        ]
        if skill.supported_source_kinds:
            lines.append(f"Supported Sources: {', '.join(skill.supported_source_kinds)}")
        if skill.supported_task_kinds:
            lines.append(f"Supported Tasks: {', '.join(skill.supported_task_kinds)}")
        if skill.allowed_tools:
            lines.append(f"Allowed Tools: {', '.join(skill.allowed_tools)}")
        if skill.supported_modalities:
            lines.append(f"Modalities: {', '.join(skill.supported_modalities)}")
        if skill.routing_hints:
            lines.append(f"Routing Hints: {', '.join(skill.routing_hints[:6])}")
        return "\n".join(lines)
