from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .agent_registry import AgentRegistry
from .agent_identity import agent_id_aliases, normalize_agent_id, normalize_agent_id_sequence
from .agent_runtime_models import AgentRuntimeProfile


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


def default_agent_runtime_profiles() -> tuple[AgentRuntimeProfile, ...]:
    return (
        AgentRuntimeProfile(
            agent_profile_id="main_interactive_agent",
            agent_id="agent:0",
            allowed_task_modes=("general_task", "memory_recall"),
            allowed_runtime_lanes=("full_interactive", "task_dispatch", "final_integration", "game_delivery"),
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
            allowed_memory_scopes=("conversation_read_write", "state_read_write", "long_term_candidate"),
            allowed_context_sections=("conversation", "state", "task", "projection", "tool", "runtime_contracts"),
            use_shared_contract=True,
            output_contracts=(),
            can_delegate_to_agents=True,
            allowed_delegate_agent_ids=("agent:rag_analyst", "agent:pdf_reader", "agent:table_analyst", "agent:web_researcher"),
            allowed_delegate_agent_categories=("worker_sub_agent",),
            max_delegate_calls_per_turn=1,
            delegate_context_policy="summary_and_refs_only",
            lifecycle_policy="system_builtin",
        ),
        AgentRuntimeProfile(
            agent_profile_id="health_maintainer_agent",
            agent_id="agent:3",
            allowed_task_modes=(
                "issue_triage",
                "trace_analysis",
                "case_draft",
                "fix_verification",
            ),
            allowed_runtime_lanes=(
                "health_issue_read",
                "health_trace_read",
                "prompt_trace_read",
                "memory_trace_read",
                "runtime_trace_read",
                "assertion_trace_read",
                "case_draft_candidate",
                "fix_verification_candidate",
            ),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text", "op.memory_read"),
            blocked_operations=(
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
                "op.agent_bounded",
            ),
            allowed_memory_scopes=("issue_local_readonly", "health_trace_readonly"),
            allowed_context_sections=("task", "health_issue", "runtime_trace", "prompt_manifest", "memory_runtime_view", "assertions", "runtime_contracts"),
            use_shared_contract=True,
            output_contracts=(
                "HealthTriageResult",
                "HealthTraceAnalysis",
                "HealthCaseDraftProposal",
                "HealthFixVerificationProposal",
            ),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "health_system", "manager_kind": "health"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="permission_system_agent",
            agent_id="agent:1",
            allowed_task_modes=(),
            allowed_runtime_lanes=("permission_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            output_contracts=(),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "permission_system", "manager_kind": "permission"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="config_system_agent",
            agent_id="agent:2",
            allowed_task_modes=(),
            allowed_runtime_lanes=("config_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            output_contracts=(),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "config_system", "manager_kind": "config"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="task_management_agent",
            agent_id="agent:4",
            allowed_task_modes=(),
            allowed_runtime_lanes=("task_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            output_contracts=(),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "task_management_system", "manager_kind": "task"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="capability_system_agent",
            agent_id="agent:5",
            allowed_task_modes=(),
            allowed_runtime_lanes=("capability_trace_read",),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.agent_bounded"),
            allowed_memory_scopes=("state_readonly",),
            allowed_context_sections=("task", "runtime_trace", "runtime_contracts"),
            use_shared_contract=True,
            output_contracts=(),
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"system_key": "capability_system", "manager_kind": "capability"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="rag_analysis_agent",
            agent_id="agent:rag_analyst",
            allowed_task_modes=("knowledge_retrieval", "information_search", "evidence_lookup"),
            allowed_runtime_lanes=("retrieval_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.mcp_retrieval", "op.memory_read"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            use_shared_contract=True,
            output_contracts=("EvidenceLookupResult", "RetrievalSummary"),
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"worker_kind": "rag_analysis", "delegation_kind": "evidence_lookup"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="pdf_analysis_agent",
            agent_id="agent:pdf_reader",
            allowed_task_modes=("pdf_analysis", "document_reading", "evidence_lookup"),
            allowed_runtime_lanes=("pdf_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.mcp_pdf", "op.read_file"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            use_shared_contract=True,
            output_contracts=("PdfAnalysisResult", "DocumentEvidenceSummary"),
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"worker_kind": "pdf_analysis", "delegation_kind": "pdf_reading"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="structured_data_analysis_agent",
            agent_id="agent:table_analyst",
            allowed_task_modes=("structured_data_analysis", "table_analysis", "evidence_lookup"),
            allowed_runtime_lanes=("structured_data_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.mcp_structured_data", "op.read_structured_file", "op.read_file"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            use_shared_contract=True,
            output_contracts=("StructuredDataAnalysisResult", "TableEvidenceSummary"),
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={"worker_kind": "structured_data_analysis", "delegation_kind": "table_analysis"},
        ),
        AgentRuntimeProfile(
            agent_profile_id="web_research_agent",
            agent_id="agent:web_researcher",
            allowed_task_modes=("web_research", "information_search", "current_information_lookup", "evidence_lookup"),
            allowed_runtime_lanes=("web_research_delegate", "readonly_exploration"),
            allowed_operations=("op.model_response", "op.web_search", "op.fetch_url"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate", "op.delegate_to_agent"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            use_shared_contract=True,
            output_contracts=("WebEvidenceResearchResult", "ExternalSourceEvidenceSummary"),
            can_delegate_to_agents=False,
            approval_policy="read_only_first",
            lifecycle_policy="system_builtin",
            metadata={
                "worker_kind": "web_research",
                "delegation_kind": "web_research",
                "delegation_kinds": ("web_research", "external_web_lookup", "current_information_lookup", "official_source_lookup"),
            },
        ),
    )


def _profile_from_dict(payload: dict[str, Any]) -> AgentRuntimeProfile:
    normalized_agent_id = normalize_agent_id(str(payload.get("agent_id") or ""))
    return AgentRuntimeProfile(
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        agent_id=normalized_agent_id,
        allowed_task_modes=tuple(str(item) for item in list(payload.get("allowed_task_modes") or []) if str(item)),
        allowed_runtime_lanes=tuple(str(item) for item in list(payload.get("allowed_runtime_lanes") or []) if str(item)),
        allowed_operations=tuple(str(item) for item in list(payload.get("allowed_operations") or []) if str(item)),
        blocked_operations=tuple(str(item) for item in list(payload.get("blocked_operations") or []) if str(item)),
        allowed_memory_scopes=tuple(str(item) for item in list(payload.get("allowed_memory_scopes") or []) if str(item)),
        allowed_context_sections=tuple(str(item) for item in list(payload.get("allowed_context_sections") or []) if str(item)),
        use_shared_contract=bool(payload.get("use_shared_contract", True)),
        output_contracts=tuple(str(item) for item in list(payload.get("output_contracts") or []) if str(item)),
        can_delegate_to_agents=bool(payload.get("can_delegate_to_agents", False)),
        allowed_delegate_agent_ids=normalize_agent_id_sequence(
            str(item) for item in list(payload.get("allowed_delegate_agent_ids") or []) if str(item)
        ),
        allowed_delegate_agent_categories=tuple(
            str(item) for item in list(payload.get("allowed_delegate_agent_categories") or ["worker_sub_agent"]) if str(item)
        ),
        max_delegate_calls_per_turn=max(0, int(payload.get("max_delegate_calls_per_turn", 1) or 0)),
        delegate_context_policy=str(payload.get("delegate_context_policy") or "summary_and_refs_only"),
        approval_policy=str(payload.get("approval_policy") or "default"),
        trace_policy=str(payload.get("trace_policy") or "runtime_event_log"),
        lifecycle_policy=str(payload.get("lifecycle_policy") or "orchestration_managed"),
        metadata=dict(payload.get("metadata") or {}),
    )


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
        stored_profiles = [_migrate_profile_payload(item) for item in list(payload.get("profiles") or []) if isinstance(item, dict)]
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
        allowed_task_modes: tuple[str, ...] = (),
        allowed_runtime_lanes: tuple[str, ...] = (),
        allowed_operations: tuple[str, ...] = (),
        blocked_operations: tuple[str, ...] = (),
        allowed_memory_scopes: tuple[str, ...] = (),
        allowed_context_sections: tuple[str, ...] = (),
        use_shared_contract: bool = True,
        output_contracts: tuple[str, ...] = (),
        can_delegate_to_agents: bool = False,
        allowed_delegate_agent_ids: tuple[str, ...] = (),
        allowed_delegate_agent_categories: tuple[str, ...] = ("worker_sub_agent",),
        max_delegate_calls_per_turn: int = 1,
        delegate_context_policy: str = "summary_and_refs_only",
        approval_policy: str = "default",
        trace_policy: str = "runtime_event_log",
        lifecycle_policy: str = "orchestration_managed",
        metadata: dict[str, Any] | None = None,
    ) -> AgentRuntimeProfile:
        target = normalize_agent_id(agent_id)
        if not target.startswith("agent:"):
            raise ValueError("agent_id must start with agent:")
        if self.agent_registry.get_agent(target) is None:
            raise ValueError("unknown agent")
        current = self.get_profile(target)
        profile = AgentRuntimeProfile(
            agent_profile_id=str(agent_profile_id or (current.agent_profile_id if current else f"{target.removeprefix('agent:').replace(':', '_')}_runtime")).strip(),
            agent_id=target,
            allowed_task_modes=tuple(str(item).strip() for item in allowed_task_modes if str(item).strip()),
            allowed_runtime_lanes=tuple(str(item).strip() for item in allowed_runtime_lanes if str(item).strip()),
            allowed_operations=tuple(str(item).strip() for item in allowed_operations if str(item).strip()),
            blocked_operations=tuple(str(item).strip() for item in blocked_operations if str(item).strip()),
            allowed_memory_scopes=tuple(str(item).strip() for item in allowed_memory_scopes if str(item).strip()),
            allowed_context_sections=tuple(str(item).strip() for item in allowed_context_sections if str(item).strip()),
            use_shared_contract=bool(use_shared_contract),
            output_contracts=tuple(str(item).strip() for item in output_contracts if str(item).strip()),
            can_delegate_to_agents=bool(can_delegate_to_agents),
            allowed_delegate_agent_ids=normalize_agent_id_sequence(
                str(item).strip() for item in allowed_delegate_agent_ids if str(item).strip()
            ),
            allowed_delegate_agent_categories=tuple(
                str(item).strip() for item in allowed_delegate_agent_categories if str(item).strip()
            ) or ("worker_sub_agent",),
            max_delegate_calls_per_turn=max(0, int(max_delegate_calls_per_turn or 0)),
            delegate_context_policy=str(delegate_context_policy or "summary_and_refs_only").strip() or "summary_and_refs_only",
            approval_policy=str(approval_policy or "default").strip() or "default",
            trace_policy=str(trace_policy or "runtime_event_log").strip() or "runtime_event_log",
            lifecycle_policy=str(lifecycle_policy or "orchestration_managed").strip() or "orchestration_managed",
            metadata=dict(metadata or {}),
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
            "summary": {
                "agent_count": len(agents),
                "runtime_profile_count": len(profiles),
                "profile_missing_count": sum(1 for agent in agents if agent.agent_id not in profile_by_agent),
                "main_agent_count": sum(1 for item in agents if item.profile_type == "main_agent"),
                "system_management_agent_count": sum(1 for item in agents if item.profile_type == "system_management_agent"),
                "worker_sub_agent_count": sum(1 for item in agents if item.profile_type == "worker_sub_agent"),
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
    metadata = dict(payload.get("metadata") or {})
    metadata.pop("legacy_agent_id", None)
    next_payload["metadata"] = metadata
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
        "allowed_task_modes",
        "allowed_runtime_lanes",
        "allowed_operations",
        "blocked_operations",
        "allowed_memory_scopes",
        "allowed_context_sections",
        "output_contracts",
        "allowed_delegate_agent_ids",
        "allowed_delegate_agent_categories",
    ):
        enforced[key] = _merge_sequence_field(
            default_payload.get(key),
            payload.get(key),
        )
    enforced["metadata"] = {
        **dict(payload.get("metadata") or {}),
        **{
            key: value
            for key, value in dict(default_payload.get("metadata") or {}).items()
            if key in {"system_key", "manager_kind"}
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
