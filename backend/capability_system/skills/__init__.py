from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "CapabilitySkillPaths": (".paths", "CapabilitySkillPaths"),
    "SkillContract": (".contracts", "SkillContract"),
    "SkillDefinition": (".registry", "SkillDefinition"),
    "SkillPromptContract": (".contracts", "SkillPromptContract"),
    "SkillPromptView": (".registry", "SkillPromptView"),
    "SkillRegistry": (".registry", "SkillRegistry"),
    "SkillRuntimeContract": (".contracts", "SkillRuntimeContract"),
    "refresh_snapshot": (".scanner", "refresh_snapshot"),
    "scan_skills": (".scanner", "scan_skills"),
    "set_skill_prompt_view": (".authoring", "set_skill_prompt_view"),
    "skill_operation_ids_from_runtime": (".operation_requirements", "skill_operation_ids_from_runtime"),
    "skill_operation_ids_from_skill": (".operation_requirements", "skill_operation_ids_from_skill"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
