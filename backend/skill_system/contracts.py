from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_SKILL_OUTPUT_RULE = (
    "Directly answer the user-facing task. Do not describe internal tool calls, routing policy, or protocol."
)

VALID_ACTIVATION_POLICIES = {"model_visible", "manual", "disabled"}
VALID_CONTEXT_MODES = {"inline", "isolated", "summary_only"}
VALID_ROUTE_AUTHORITIES = {"candidate_only", "preferred", "required"}


def normalize_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [normalize_string(item) for item in value if normalize_string(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


@dataclass(slots=True)
class SkillPromptContract:
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def normalized(self) -> "SkillRuntimeContract":
        activation_policy = self.activation_policy if self.activation_policy in VALID_ACTIVATION_POLICIES else "model_visible"
        context_mode = self.context_mode if self.context_mode in VALID_CONTEXT_MODES else "inline"
        route_authority = self.route_authority if self.route_authority in VALID_ROUTE_AUTHORITIES else "candidate_only"
        return SkillRuntimeContract(
            name=normalize_string(self.name),
            title=normalize_string(self.title),
            description=normalize_string(self.description),
            path=normalize_string(self.path),
            allowed_tools=normalize_string_list(self.allowed_tools),
            supported_modalities=normalize_string_list(self.supported_modalities),
            supported_task_kinds=normalize_string_list(self.supported_task_kinds),
            supported_source_kinds=normalize_string_list(self.supported_source_kinds),
            capability_tags=normalize_string_list(self.capability_tags),
            preferred_route=normalize_string(self.preferred_route, "rag") or "rag",
            forbidden_routes=normalize_string_list(self.forbidden_routes),
            routing_hints=normalize_string_list(self.routing_hints),
            examples=normalize_string_list(self.examples),
            activation_policy=activation_policy,
            context_mode=context_mode,
            route_authority=route_authority,
            reference_paths=normalize_string_list(self.reference_paths),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("name is required")
        if not self.title:
            errors.append("title is required")
        if not self.description:
            errors.append("description is required")
        if not self.path:
            errors.append("path is required")
        if self.activation_policy not in VALID_ACTIVATION_POLICIES:
            errors.append(f"activation_policy must be one of {sorted(VALID_ACTIVATION_POLICIES)}")
        if self.context_mode not in VALID_CONTEXT_MODES:
            errors.append(f"context_mode must be one of {sorted(VALID_CONTEXT_MODES)}")
        if self.route_authority not in VALID_ROUTE_AUTHORITIES:
            errors.append(f"route_authority must be one of {sorted(VALID_ROUTE_AUTHORITIES)}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SkillContract:
    runtime: SkillRuntimeContract
    prompt: SkillPromptContract
    body: str = ""
    validation_errors: list[str] = field(default_factory=list)

    @classmethod
    def from_runtime(cls, runtime: SkillRuntimeContract, *, body: str = "", use_when: str = "") -> "SkillContract":
        normalized = runtime.normalized()
        prompt = SkillPromptContract(
            name=normalized.name,
            title=normalized.title,
            capability=normalized.description,
            use_when=use_when,
        )
        return cls(
            runtime=normalized,
            prompt=prompt,
            body=body,
            validation_errors=normalized.validate(),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SkillContract":
        runtime_payload = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else payload
        prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else payload.get("prompt_view")
        runtime = SkillRuntimeContract(
            name=normalize_string(runtime_payload.get("name")),
            title=normalize_string(runtime_payload.get("title")),
            description=normalize_string(runtime_payload.get("description")),
            path=normalize_string(runtime_payload.get("path")),
            allowed_tools=normalize_string_list(runtime_payload.get("allowed_tools")),
            supported_modalities=normalize_string_list(runtime_payload.get("supported_modalities")),
            supported_task_kinds=normalize_string_list(runtime_payload.get("supported_task_kinds")),
            supported_source_kinds=normalize_string_list(runtime_payload.get("supported_source_kinds")),
            capability_tags=normalize_string_list(runtime_payload.get("capability_tags")),
            preferred_route=normalize_string(runtime_payload.get("preferred_route"), "rag") or "rag",
            forbidden_routes=normalize_string_list(runtime_payload.get("forbidden_routes")),
            routing_hints=normalize_string_list(runtime_payload.get("routing_hints")),
            examples=normalize_string_list(runtime_payload.get("examples")),
            activation_policy=normalize_string(runtime_payload.get("activation_policy"), "model_visible") or "model_visible",
            context_mode=normalize_string(runtime_payload.get("context_mode"), "inline") or "inline",
            route_authority=normalize_string(runtime_payload.get("route_authority"), "candidate_only") or "candidate_only",
            reference_paths=normalize_string_list(runtime_payload.get("reference_paths")),
        ).normalized()
        if isinstance(prompt_payload, dict):
            prompt = SkillPromptContract(
                name=normalize_string(prompt_payload.get("name"), runtime.name) or runtime.name,
                title=normalize_string(prompt_payload.get("title"), runtime.title) or runtime.title,
                capability=normalize_string(
                    prompt_payload.get("capability") or prompt_payload.get("description"),
                    runtime.description,
                ) or runtime.description,
                use_when=normalize_string(prompt_payload.get("use_when")),
                output_rule=normalize_string(prompt_payload.get("output_rule"), DEFAULT_SKILL_OUTPUT_RULE) or DEFAULT_SKILL_OUTPUT_RULE,
            )
        else:
            prompt = SkillPromptContract(runtime.name, runtime.title, runtime.description)
        return cls(
            runtime=runtime,
            prompt=prompt,
            body=normalize_string(payload.get("body")),
            validation_errors=runtime.validate(),
        )

    def to_registry_record(self) -> dict[str, Any]:
        return {
            "schema_version": 3,
            **self.runtime.to_dict(),
            "runtime": self.runtime.to_dict(),
            "prompt": self.prompt.to_dict(),
            "validation_errors": list(self.validation_errors),
        }
