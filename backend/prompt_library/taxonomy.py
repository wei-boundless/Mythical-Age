from __future__ import annotations

from typing import Any


PROMPT_LAYERS = {
    "system_contract",
    "runtime_role",
    "agent_role",
    "environment_guidance",
    "tool_guidance",
    "memory_guidance",
    "repair_guidance",
    "utility",
}

PROMPT_VISIBILITIES = {"model_visible", "metadata_only", "locked_contract"}

CONTRACT_PRIORITIES = {
    "core_contract",
    "project_contract",
    "current_user_request",
    "task_contract",
    "observed_fact",
    "runtime_policy",
    "owner_guidance",
    "memory_background",
    "weak_signal",
}

CONFLICT_POLICIES = {
    "override",
    "constrain",
    "factual_correction",
    "scoped_guidance",
    "background_only",
    "advisory",
}


def normalize_contract_priority(value: Any, *, category: str = "", resource_type: str = "") -> str:
    explicit = str(value or "").strip()
    if explicit in CONTRACT_PRIORITIES:
        return explicit
    resource = str(resource_type or "").strip()
    category_value = str(category or "").strip()
    if resource in {"system_foundation", "runtime_contract", "action_schema"} or category_value == "system":
        return "core_contract"
    if category_value in {"agent", "environment", "personality"}:
        return "owner_guidance"
    if category_value == "skill":
        return "owner_guidance"
    if resource == "tool_guidance" or category_value == "tool":
        return "owner_guidance"
    if category_value in {"task", "graph_node"}:
        return "task_contract"
    return "owner_guidance"


def normalize_conflict_policy(value: Any, *, contract_priority: str = "") -> str:
    explicit = str(value or "").strip()
    if explicit in CONFLICT_POLICIES:
        return explicit
    priority = str(contract_priority or "").strip()
    if priority == "core_contract":
        return "override"
    if priority in {"project_contract", "runtime_policy"}:
        return "constrain"
    if priority == "observed_fact":
        return "factual_correction"
    if priority == "memory_background":
        return "background_only"
    if priority == "weak_signal":
        return "advisory"
    return "scoped_guidance"


def normalize_prompt_scope(value: Any, *, owner_kind: str = "", owner_ref: str = "") -> str:
    explicit = str(value or "").strip()
    if explicit:
        return explicit
    kind = str(owner_kind or "").strip()
    ref = str(owner_ref or "").strip()
    if kind and ref:
        return f"{kind}:{ref}"
    if kind:
        return kind
    return "runtime"
