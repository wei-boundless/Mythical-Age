from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library.personality_prompts import DEFAULT_PERSONALITY_PROMPT_REF


@dataclass(frozen=True, slots=True)
class PersonalityPromptSelection:
    selected_personality_ref: str = DEFAULT_PERSONALITY_PROMPT_REF
    personality_prompt_refs: tuple[str, ...] = (DEFAULT_PERSONALITY_PROMPT_REF,)
    selection_source: str = "default"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.personality_prompt_controller"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["personality_prompt_refs"] = list(self.personality_prompt_refs)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def select_personality_prompt(
    *,
    runtime_contract: dict[str, Any] | None = None,
    agent_runtime_profile: Any | None = None,
    default_personality_ref: str = DEFAULT_PERSONALITY_PROMPT_REF,
) -> PersonalityPromptSelection:
    contract = dict(runtime_contract or {})
    profile_metadata = dict(getattr(agent_runtime_profile, "metadata", {}) or {})
    default_ref = _first_string(
        default_personality_ref,
        profile_metadata.get("default_personality_prompt_ref"),
        DEFAULT_PERSONALITY_PROMPT_REF,
    )
    selected_ref, source = _selected_personality_ref(contract=contract, profile_metadata=profile_metadata)
    if not selected_ref:
        selected_ref = default_ref
        source = "default"
    refs = _dedupe_strings((selected_ref,))
    return PersonalityPromptSelection(
        selected_personality_ref=selected_ref,
        personality_prompt_refs=refs,
        selection_source=source,
        diagnostics={
            "selection_source": source,
            "default_personality_ref": default_ref,
            "selected_personality_ref": selected_ref,
            "model_may_switch_personality": False,
            "authority_scope": "identity_and_style_only",
        },
    )


def _selected_personality_ref(
    *,
    contract: dict[str, Any],
    profile_metadata: dict[str, Any],
) -> tuple[str, str]:
    direct = _first_string(
        contract.get("personality_prompt_ref"),
        contract.get("personality_ref"),
    )
    if direct:
        return direct, "runtime_contract"
    personality = dict(contract.get("personality") or {}) if isinstance(contract.get("personality"), dict) else {}
    nested = _first_string(
        personality.get("prompt_ref"),
        personality.get("personality_prompt_ref"),
        personality.get("ref"),
    )
    if nested:
        return nested, "runtime_contract.personality"
    profile_ref = _first_string(profile_metadata.get("personality_prompt_ref"))
    if profile_ref:
        return profile_ref, "agent_profile_metadata"
    return "", ""


def _first_string(*values: Any) -> str:
    for value in values:
        item = str(value or "").strip()
        if item:
            return item
    return ""


def _dedupe_strings(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
