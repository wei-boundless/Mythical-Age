from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from ..registry.agent_registry import AgentRegistry
from ..identity import agent_id_aliases, normalize_agent_id, normalize_agent_id_sequence
from .runtime_profile_models import AgentRuntimeProfile
from ..models.model_profile_models import contains_raw_secret, parse_agent_model_profile
from orchestration.runtime_lane_registry import normalize_runtime_lane_sequence
from .runtime_mode_config import (
    DEFAULT_RUNTIME_MODE,
    CUSTOM_MODE,
    PROFESSIONAL_MODE,
    ROLE_MODE,
    STANDARD_MODE,
    modes_for_runtime_lanes_or_custom,
    normalize_default_runtime_mode,
    normalize_runtime_modes,
    runtime_lanes_for_modes,
)


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).orchestration_dir


def _profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "agent_runtime_profiles.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_removed_health_runtime_profile(payload: dict[str, Any]) -> bool:
    metadata = dict(payload.get("metadata") or {})
    profile_id = str(payload.get("agent_profile_id") or "").strip()
    agent_id = normalize_agent_id(str(payload.get("agent_id") or ""))
    return (
        agent_id == "agent:3"
        and (
            profile_id == "health_maintainer_agent"
            or str(metadata.get("runtime_template_id") or "").strip() == "builtin.system.health_manager"
        )
    )


def default_agent_runtime_profiles() -> tuple[AgentRuntimeProfile, ...]:
    return (
        AgentRuntimeProfile(
            agent_profile_id="main_interactive_agent",
            agent_id="agent:0",
            enabled_runtime_modes=(ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE, CUSTOM_MODE),
            default_runtime_mode=STANDARD_MODE,
            allowed_runtime_lanes=(
                "full_interactive",
                "game_delivery",
                "role_interaction",
                "standard_task",
                "professional_task",
            ),
            allowed_operations=(
                "op.model_response",
                "op.read_file",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.read_structured_file",
                "op.search_files",
                "op.search_text",
                "op.git_status",
                "op.git_diff",
                "op.git_log",
                "op.git_show",
                "op.web_search",
                "op.fetch_url",
                "op.memory_read",
                "op.delegate_to_agent",
                "op.mcp_retrieval",
                "op.mcp_pdf",
                "op.mcp_structured_data",
                "op.write_file",
                "op.edit_file",
                "op.shell",
            ),
            blocked_operations=("op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate"),
            allowed_context_sections=("conversation", "state", "task", "projection", "tool", "runtime_contracts"),
            use_shared_contract=True,
            can_delegate_to_agents=True,
            allowed_delegate_agent_ids=("agent:rag_analyst", "agent:pdf_reader", "agent:table_analyst", "agent:web_researcher"),
            max_delegate_calls_per_turn=1,
            delegate_context_policy="summary_and_refs_only",
            lifecycle_policy="system_builtin",
            metadata={"runtime_template_id": "builtin.main.default"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="memory_system_agent",
            agent_id="agent:1",
            allowed_runtime_lanes=("memory_trace_read", "session_memory_maintenance", "durable_memory_extraction", "memory_candidate_review"),
            allowed_operations=("op.model_response", "op.memory_read", "op.memory_write_candidate"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.agent_bounded", "op.delegate_to_agent", "op.web_search"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate", "session_memory_write_candidate", "durable_memory_write_candidate"),
            allowed_context_sections=("task", "runtime_trace", "memory_runtime_view", "prompt_manifest", "runtime_contracts"),
            use_shared_contract=True,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "memory_system", "manager_kind": "memory", "runtime_template_id": "builtin.system.memory_manager"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="config_system_agent",
            agent_id="agent:2",
            allowed_runtime_lanes=("config_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "config_system", "manager_kind": "config", "runtime_template_id": "builtin.system.config_manager"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="task_management_agent",
            agent_id="agent:4",
            allowed_runtime_lanes=("task_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "task_management_system", "manager_kind": "task", "runtime_template_id": "builtin.system.task_manager"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="capability_system_agent",
            agent_id="agent:5",
            allowed_runtime_lanes=("capability_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "capability_system", "manager_kind": "capability", "runtime_template_id": "builtin.system.capability_manager"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="rag_analysis_agent",
            agent_id="agent:rag_analyst",
            allowed_runtime_lanes=("retrieval_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.mcp_retrieval", "op.memory_read"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            use_shared_contract=True,
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"worker_kind": "rag_analysis", "delegation_kind": "evidence_lookup", "runtime_template_id": "builtin.specialist.rag_analyst"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="pdf_analysis_agent",
            agent_id="agent:pdf_reader",
            allowed_runtime_lanes=("pdf_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.mcp_pdf", "op.read_file"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            use_shared_contract=True,
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"worker_kind": "pdf_analysis", "delegation_kind": "pdf_reading", "runtime_template_id": "builtin.specialist.pdf_reader"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="structured_data_analysis_agent",
            agent_id="agent:table_analyst",
            allowed_runtime_lanes=("structured_data_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.mcp_structured_data", "op.read_structured_file", "op.read_file"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            use_shared_contract=True,
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"worker_kind": "structured_data_analysis", "delegation_kind": "table_analysis", "runtime_template_id": "builtin.specialist.table_analyst"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="web_research_agent",
            agent_id="agent:web_researcher",
            allowed_runtime_lanes=("web_research_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.web_search", "op.fetch_url"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            use_shared_contract=True,
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "web_research",
                "delegation_kind": "web_research",
                "delegation_kinds": ("web_research", "external_web_lookup", "current_information_lookup", "official_source_lookup"),
                "runtime_template_id": "builtin.specialist.web_researcher",
            },
        ),
    )

def _profile_from_dict(payload: dict[str, Any]) -> AgentRuntimeProfile:
    normalized_agent_id = normalize_agent_id(str(payload.get("agent_id") or ""))
    metadata = dict(payload.get("metadata") or {})
    allow_unregistered_lanes = bool(metadata.get("allow_unregistered_runtime_lanes", False))
    explicit_modes = normalize_runtime_modes(
        payload.get("enabled_runtime_modes") or metadata.get("enabled_runtime_modes"),
        fallback=(),
    )
    if not explicit_modes:
        explicit_modes = modes_for_runtime_lanes_or_custom(payload.get("allowed_runtime_lanes"))
    default_runtime_mode = normalize_default_runtime_mode(
        payload.get("default_runtime_mode") or metadata.get("default_runtime_mode") or DEFAULT_RUNTIME_MODE,
        explicit_modes,
    )
    mode_lanes = runtime_lanes_for_modes(explicit_modes)
    raw_runtime_lanes = list(payload.get("allowed_runtime_lanes") or []) if CUSTOM_MODE in explicit_modes else []
    allowed_runtime_lanes = normalize_runtime_lane_sequence(
        [*mode_lanes, *raw_runtime_lanes],
        allow_unregistered=allow_unregistered_lanes,
        allow_system_only=True,
    )
    allowed_operations = tuple(str(item) for item in list(payload.get("allowed_operations") or []) if str(item))
    blocked_operations = _without_allowed_operations(
        tuple(str(item) for item in list(payload.get("blocked_operations") or []) if str(item)),
        allowed_operations=allowed_operations,
    )
    return AgentRuntimeProfile(
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        agent_id=normalized_agent_id,
        enabled_runtime_modes=explicit_modes,
        default_runtime_mode=default_runtime_mode,
        allowed_runtime_lanes=allowed_runtime_lanes,
        allowed_operations=allowed_operations,
        blocked_operations=blocked_operations,
        allowed_memory_scopes=tuple(_normalize_memory_scopes(normalized_agent_id, payload.get("allowed_memory_scopes"))),
        allowed_context_sections=tuple(str(item) for item in list(payload.get("allowed_context_sections") or []) if str(item)),
        use_shared_contract=bool(payload.get("use_shared_contract", True)),
        can_delegate_to_agents=bool(payload.get("can_delegate_to_agents", False)),
        allowed_delegate_agent_ids=normalize_agent_id_sequence(
            str(item) for item in list(payload.get("allowed_delegate_agent_ids") or []) if str(item)
        ),
        max_delegate_calls_per_turn=max(0, int(payload.get("max_delegate_calls_per_turn", 1) or 0)),
        delegate_context_policy=str(payload.get("delegate_context_policy") or "summary_and_refs_only"),
        approval_policy=str(payload.get("approval_policy") or "default"),
        trace_policy=str(payload.get("trace_policy") or "runtime_event_log"),
        lifecycle_policy=str(payload.get("lifecycle_policy") or "orchestration_managed"),
        model_profile=parse_agent_model_profile(payload.get("model_profile")),
        metadata=metadata,
    )


def _infer_runtime_template_id(agent_id: str, payload: dict[str, Any]) -> str:
    metadata = dict(payload.get("metadata") or {})
    explicit = str(metadata.get("runtime_template_id") or payload.get("runtime_template_id") or "").strip()
    if explicit:
        return explicit
    task_family = str(metadata.get("task_family") or "").strip()
    source_refs = [str(item).strip() for item in list(metadata.get("source_task_graph_refs") or []) if str(item).strip()]
    return ""


class AgentRuntimeRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.path = _profiles_path(self.base_dir)

    def list_profiles(self) -> list[AgentRuntimeProfile]:
        default_payload = [item.to_dict() for item in default_agent_runtime_profiles()]
        default_by_agent = {str(item.get("agent_id") or ""): item for item in default_payload}
        payload = _read_json(
            self.path,
            {"profiles": default_payload},
        )
        stored_profiles = [
            _migrate_profile_payload(item)
            for item in list(payload.get("profiles") or [])
            if isinstance(item, dict) and not _is_removed_health_runtime_profile(item)
        ]
        default_agent_ids = set(default_by_agent)
        live_agent_ids = {agent.agent_id for agent in self.agent_registry.list_agents()}
        merged_payload = (
            default_payload
            if not self.path.exists()
            else _merge_items_by_key(
                default_payload,
                [
                    item
                    for item in stored_profiles
                    if str(item.get("agent_id") or "").strip() in live_agent_ids
                    or str(item.get("agent_id") or "").strip() in default_agent_ids
                ],
                key="agent_id",
            )
        )
        profiles = [
            _profile_from_dict(_enforce_system_builtin_profile_payload(item, default_by_agent=default_by_agent))
            for item in merged_payload
        ]
        normalized = [item.to_dict() for item in profiles]
        if payload.get("profiles") != normalized:
            _write_json(self.path, {"profiles": normalized})
        return profiles

    def get_profile(self, agent_id: str) -> AgentRuntimeProfile | None:
        target = normalize_agent_id(agent_id)
        aliases = set(agent_id_aliases(target))
        return next((item for item in self.list_profiles() if item.agent_id in aliases), None)

    def upsert_profile(
        self,
        *,
        agent_id: str,
        agent_profile_id: str = "",
        enabled_runtime_modes: tuple[str, ...] = (),
        default_runtime_mode: str = "",
        allowed_runtime_lanes: tuple[str, ...] = (),
        allowed_operations: tuple[str, ...] = (),
        blocked_operations: tuple[str, ...] = (),
        allowed_memory_scopes: tuple[str, ...] = (),
        allowed_context_sections: tuple[str, ...] = (),
        use_shared_contract: bool = True,
        can_delegate_to_agents: bool = False,
        allowed_delegate_agent_ids: tuple[str, ...] = (),
        max_delegate_calls_per_turn: int = 1,
        delegate_context_policy: str = "summary_and_refs_only",
        approval_policy: str = "default",
        trace_policy: str = "runtime_event_log",
        lifecycle_policy: str = "orchestration_managed",
        model_profile: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRuntimeProfile:
        target = normalize_agent_id(agent_id)
        if not target.startswith("agent:"):
            raise ValueError("agent_id must start with agent:")
        if self.agent_registry.get_agent(target) is None:
            raise ValueError("unknown agent")
        if contains_raw_secret(model_profile):
            raise ValueError("model_profile must use credential_ref instead of raw secrets")
        current = self.get_profile(target)
        metadata_payload = dict(metadata or {})
        metadata_payload.pop("custom_runtime_modes", None)
        normalized_modes = normalize_runtime_modes(
            enabled_runtime_modes or metadata_payload.get("enabled_runtime_modes") or (current.enabled_runtime_modes if current else ()),
            fallback=(),
        )
        if not normalized_modes and allowed_runtime_lanes:
            normalized_modes = modes_for_runtime_lanes_or_custom(allowed_runtime_lanes)
        normalized_default_mode = normalize_default_runtime_mode(
            default_runtime_mode or metadata_payload.get("default_runtime_mode") or (current.default_runtime_mode if current else DEFAULT_RUNTIME_MODE),
            normalized_modes,
        )
        metadata_payload.pop("enabled_runtime_modes", None)
        metadata_payload.pop("default_runtime_mode", None)
        mode_runtime_lanes = runtime_lanes_for_modes(normalized_modes)
        manual_runtime_lanes = allowed_runtime_lanes if CUSTOM_MODE in normalized_modes else ()
        normalized_runtime_lanes = normalize_runtime_lane_sequence(
            (*mode_runtime_lanes, *manual_runtime_lanes),
            allow_unregistered=bool(metadata_payload.get("allow_unregistered_runtime_lanes", False)),
            allow_system_only=True,
        )
        profile = AgentRuntimeProfile(
            agent_profile_id=str(agent_profile_id or (current.agent_profile_id if current else f"{target.removeprefix('agent:').replace(':', '_')}_runtime")).strip(),
            agent_id=target,
            enabled_runtime_modes=normalized_modes,
            default_runtime_mode=normalized_default_mode,
            allowed_runtime_lanes=normalized_runtime_lanes,
            allowed_operations=tuple(str(item).strip() for item in allowed_operations if str(item).strip()),
            blocked_operations=tuple(str(item).strip() for item in blocked_operations if str(item).strip()),
            allowed_memory_scopes=tuple(_normalize_memory_scopes(target, allowed_memory_scopes)),
            allowed_context_sections=tuple(str(item).strip() for item in allowed_context_sections if str(item).strip()),
            use_shared_contract=bool(use_shared_contract),
            can_delegate_to_agents=bool(can_delegate_to_agents),
            allowed_delegate_agent_ids=normalize_agent_id_sequence(
                str(item).strip() for item in allowed_delegate_agent_ids if str(item).strip()
            ),
            max_delegate_calls_per_turn=max(0, int(max_delegate_calls_per_turn or 0)),
            delegate_context_policy=str(delegate_context_policy or "summary_and_refs_only").strip() or "summary_and_refs_only",
            approval_policy=str(approval_policy or "default").strip() or "default",
            trace_policy=str(trace_policy or "runtime_event_log").strip() or "runtime_event_log",
            lifecycle_policy=str(lifecycle_policy or "orchestration_managed").strip() or "orchestration_managed",
            model_profile=parse_agent_model_profile(model_profile if model_profile is not None else (current.model_profile.to_dict() if current else {})),
            metadata=metadata_payload,
        )
        profiles = [item for item in self.list_profiles() if item.agent_id != target]
        profiles.append(profile)
        _write_json(self.path, {"profiles": [item.to_dict() for item in profiles]})
        return profile

    def delete_profile(self, agent_id: str) -> None:
        target = str(agent_id or "").strip()
        if not target:
            return
        profiles = [item for item in self.list_profiles() if item.agent_id != target]
        _write_json(self.path, {"profiles": [item.to_dict() for item in profiles]})

    def build_catalog(self) -> dict[str, Any]:
        agents = self.agent_registry.list_agents()
        profiles = self.list_profiles()
        profile_by_agent = {item.agent_id: item for item in profiles}
        runtime_templates: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            template_id = profile.runtime_template_id
            if not template_id:
                continue
            bucket = runtime_templates.setdefault(
                template_id,
                {
                    "runtime_template_id": template_id,
                    "agent_ids": [],
                    "profile_ids": [],
                    "lifecycle_policies": set(),
                },
            )
            bucket["agent_ids"].append(profile.agent_id)
            bucket["profile_ids"].append(profile.agent_profile_id)
            bucket["lifecycle_policies"].add(profile.lifecycle_policy)
        return {
            "authority": "orchestration.agent_runtime_registry",
            "agents": [
                {
                    **agent.to_dict(),
                    "runtime_profile": profile_by_agent.get(agent.agent_id).to_dict() if profile_by_agent.get(agent.agent_id) else {},
                }
                for agent in agents
            ],
            "profiles": [item.to_dict() for item in profiles],
            "runtime_templates": [
                {
                    "runtime_template_id": template_id,
                    "agent_ids": sorted(list(dict.fromkeys(bucket["agent_ids"]))),
                    "profile_ids": sorted(list(dict.fromkeys(bucket["profile_ids"]))),
                    "lifecycle_policies": sorted(bucket["lifecycle_policies"]),
                    "agent_count": len(set(bucket["agent_ids"])),
                }
                for template_id, bucket in sorted(runtime_templates.items())
            ],
            "summary": {
                "agent_count": len(agents),
                "runtime_profile_count": len(profiles),
                "profile_missing_count": sum(1 for agent in agents if agent.agent_id not in profile_by_agent),
                "main_agent_count": sum(1 for item in agents if item.profile_type == "main_agent"),
                "builtin_agent_count": sum(1 for item in agents if item.profile_type == "builtin_agent"),
                "custom_agent_count": sum(1 for item in agents if item.profile_type == "custom_agent"),
                "system_manager_agent_count": sum(1 for item in agents if item.builtin_kind == "system_manager"),
                "delegation_enabled_agent_count": sum(1 for item in agents if item.delegation_enabled),
                "runtime_template_count": len(runtime_templates),
            },
        }


def _merge_items_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in default_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    for item in stored_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    return list(merged.values())


def _migrate_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["agent_id"] = normalize_agent_id(str(payload.get("agent_id") or ""))
    next_payload["allowed_delegate_agent_ids"] = list(
        normalize_agent_id_sequence(
            str(item) for item in list(payload.get("allowed_delegate_agent_ids") or []) if str(item)
        )
    )
    next_payload["allowed_memory_scopes"] = _normalize_memory_scopes(
        next_payload["agent_id"],
        payload.get("allowed_memory_scopes"),
    )
    metadata = dict(payload.get("metadata") or {})
    metadata.pop("legacy_agent_id", None)
    metadata.pop("allowed_task_modes", None)
    metadata.pop("custom_runtime_modes", None)
    enabled_runtime_modes = normalize_runtime_modes(
        payload.get("enabled_runtime_modes") or metadata.pop("enabled_runtime_modes", None),
        fallback=(),
    )
    if not enabled_runtime_modes:
        enabled_runtime_modes = modes_for_runtime_lanes_or_custom(payload.get("allowed_runtime_lanes"))
    next_payload["enabled_runtime_modes"] = list(enabled_runtime_modes)
    next_payload["default_runtime_mode"] = normalize_default_runtime_mode(
        payload.get("default_runtime_mode") or metadata.pop("default_runtime_mode", None) or DEFAULT_RUNTIME_MODE,
        enabled_runtime_modes,
    )
    runtime_template_id = _infer_runtime_template_id(next_payload["agent_id"], {**next_payload, "metadata": metadata})
    if runtime_template_id:
        metadata["runtime_template_id"] = runtime_template_id
    next_payload["allowed_runtime_lanes"] = list(
        normalize_runtime_lane_sequence(
            [
                *runtime_lanes_for_modes(enabled_runtime_modes),
                *(list(payload.get("allowed_runtime_lanes") or []) if CUSTOM_MODE in enabled_runtime_modes else []),
            ],
            allow_unregistered=bool(metadata.get("allow_unregistered_runtime_lanes", False)),
            allow_system_only=True,
        )
    )
    next_payload["metadata"] = metadata
    next_payload["model_profile"] = parse_agent_model_profile(
        payload.get("model_profile") or metadata.pop("model_profile", {})
    ).to_dict()
    next_payload.pop("allowed_task_modes", None)
    next_payload.pop("allowed_delegate_agent_categories", None)
    next_payload.pop("output_contracts", None)
    return next_payload


def _enforce_system_builtin_profile_payload(
    payload: dict[str, Any],
    *,
    default_by_agent: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "").strip()
    default_payload = default_by_agent.get(agent_id)
    if not default_payload:
        return payload
    enforced = dict(default_payload)
    enforced.update(payload)
    enforced["agent_id"] = agent_id
    for key in (
        "enabled_runtime_modes",
        "allowed_runtime_lanes",
        "allowed_operations",
        "blocked_operations",
        "allowed_memory_scopes",
        "allowed_context_sections",
        "allowed_delegate_agent_ids",
    ):
        enforced[key] = _merge_sequence_field(
            default_payload.get(key),
            payload.get(key),
        )
    enforced["allowed_memory_scopes"] = _normalize_memory_scopes(
        agent_id,
        enforced.get("allowed_memory_scopes"),
    )
    enforced["blocked_operations"] = _without_allowed_operations(
        enforced.get("blocked_operations"),
        allowed_operations=enforced.get("allowed_operations"),
    )
    enforced["metadata"] = {
        **dict(payload.get("metadata") or {}),
        **{
            key: value
            for key, value in dict(default_payload.get("metadata") or {}).items()
            if key in {"system_key", "manager_kind", "runtime_template_id"}
        },
    }
    return enforced


def _merge_sequence_field(default_value: Any, payload_value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for source in (default_value, payload_value):
        for item in list(source or []):
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_memory_scopes(agent_id: str, scopes: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in list(scopes or []):
        value = str(item or "").strip()
        if value in {"conversation_read_write", "state_read_write"}:
            continue
        if not value or value in seen:
            continue
        if agent_id != "agent:1" and value in {"session_memory_write_candidate", "durable_memory_write_candidate"}:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _without_allowed_operations(blocked_operations: Any, *, allowed_operations: Any) -> tuple[str, ...]:
    allowed = {str(item or "").strip() for item in list(allowed_operations or []) if str(item or "").strip()}
    result: list[str] = []
    seen: set[str] = set()
    for item in list(blocked_operations or []):
        value = str(item or "").strip()
        if not value or value in allowed or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
