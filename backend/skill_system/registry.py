from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_SKILL_OUTPUT_RULE = (
    "Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol."
)


@dataclass(slots=True)
class SkillPromptView:
    name: str
    title: str
    capability: str
    use_when: str = ""
    output_rule: str = DEFAULT_SKILL_OUTPUT_RULE

    def render_block(self) -> str:
        lines = [
            f"Skill: {self.title or self.name}",
            f"Capability: {self.capability}",
        ]
        if self.use_when:
            lines.append(f"Use When: {self.use_when}")
        lines.append(f"Output Rule: {self.output_rule}")
        return "\n".join(lines)


@dataclass(slots=True)
class SkillRuntimeContract:
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


@dataclass(slots=True)
class SkillDefinition:
    runtime: SkillRuntimeContract
    prompt_view: SkillPromptView

    def __getattr__(self, attr: str):
        return getattr(self.runtime, attr)

    def render_prompt_block(self) -> str:
        return self.prompt_view.render_block()

    def allowed_tool_scope(self) -> list[str]:
        return list(self.runtime.allowed_tools)

    @classmethod
    def from_payload(cls, item: dict[str, object]) -> "SkillDefinition":
        runtime = SkillRuntimeContract(
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
        prompt_view = SkillPromptView(
            name=runtime.name,
            title=runtime.title,
            capability=runtime.description,
            use_when=_build_skill_use_when(runtime),
        )
        return cls(runtime=runtime, prompt_view=prompt_view)


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
            skills.append(SkillDefinition.from_payload(item))
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
            if modality and modality in skill.supported_modalities:
                score += 2.0

            if candidate_tools and skill.allowed_tools:
                overlap = set(candidate_tools) & set(skill.allowed_tools)
                score += float(len(overlap)) * 2.5

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
        return skill.render_prompt_block()


def _build_skill_use_when(skill: SkillRuntimeContract) -> str:
    source_kinds = set(skill.supported_source_kinds)
    modalities = set(skill.supported_modalities)
    task_kinds = set(skill.supported_task_kinds)

    if "knowledge_base" in source_kinds:
        return "Use for local knowledge-base lookup, factual explanation, and questions that should be answered from local materials."
    if "document" in source_kinds or "pdf" in modalities or "document" in modalities:
        return "Use for reading local documents or PDFs, including whole-document, section-level, and page-level questions."
    if "dataset" in source_kinds or modalities & {"table", "spreadsheet", "csv", "json"}:
        return "Use for structured data questions such as filtering, ranking, grouping, summary statistics, and record lookup."
    if "external_web" in source_kinds or modalities & {"realtime", "web", "finance"}:
        return "Use when the user needs current external information, real-time lookup, or official web sources."
    if "workflow" in source_kinds or "workflow_lesson_capture" in task_kinds:
        return "Use for workflow reflection and reusable lesson capture after a failed-then-corrected attempt."
    return ""
