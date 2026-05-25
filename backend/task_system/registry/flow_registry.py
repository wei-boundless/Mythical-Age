from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.identity import normalize_agent_id, normalize_agent_id_sequence
from agent_system.registry.agent_registry import AgentRegistry
from project_layout import ProjectLayout
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry

from task_system.registry.flow_models import (
    AgentTaskCarryingProfile,
    AgentTaskConnectionProfile,
    CoordinationTaskDefinition,
    GeneralTaskProfile,
    SpecificTaskRecord,
    TaskDomainRecord,
    TaskAgentAdoptionPlan,
    TaskAgentBinding,
    TaskAssignment,
    TaskCommunicationProtocol,
    TaskFlowDefinition,
    TaskFlowContractBinding,
    TaskMemoryRequestProfile,
    TaskProjectionBinding,
    TopologyTemplate,
)
from task_system.contracts.contract_models import TaskContractDescriptor
from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    task_graph_from_dict,
)
from task_system.registry.workflow_registry import TaskWorkflowRegistry


CONTRACT_TITLE_MAP: dict[str, str] = {
    "UserMessage": "用户消息",
    "WorkspaceTaskInput": "工作区任务输入",
    "WorkspacePatchTaskInput": "工作区补丁任务输入",
    "AssistantFinalAnswer": "最终回答",
    "LightWebGameTaskInput": "网页小游戏任务输入",
    "LightWebGameResult": "网页游戏产物",
    "ArcadeGameBundleTaskInput": "复合网页游戏任务输入",
    "ShortStoryTaskInput": "短篇小说任务输入",
    "ShortStoryResult": "短篇小说成稿",
    "HealthIssue": "健康问题",
}


CONTRACT_KIND_LABELS: dict[str, str] = {
    "input": "输入契约",
    "output": "输出契约",
    "flow": "流程契约",
    "payload": "通信载荷契约",
}

def normalize_task_agent_adoption_mode(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized == "spawn_worker_allowed":
        return "adopt_with_projection"
    return normalized or "adopt_existing"


def default_health_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return ()


def default_task_flows() -> tuple[TaskFlowDefinition, ...]:
    return default_health_task_flows()


def _system_task_specs() -> dict[str, dict[str, Any]]:
    return {}


def _is_removed_health_task_config(payload: dict[str, Any]) -> bool:
    metadata = dict(payload.get("metadata") or {})
    values = (
        payload.get("task_id"),
        payload.get("flow_id"),
        payload.get("workflow_id"),
        payload.get("default_workflow_id"),
        payload.get("default_flow_contract_id"),
        payload.get("flow_contract_id"),
        payload.get("binding_id"),
        payload.get("plan_id"),
        payload.get("profile_id"),
        metadata.get("task_resource"),
        metadata.get("source_flow_id"),
    )
    return any(
        str(value or "").strip().startswith(("task.health.", "flow.health.", "workflow.health."))
        for value in values
    )


def _synthetic_specific_task_record_for_runtime(task_id: str) -> SpecificTaskRecord | None:
    target = str(task_id or "").strip()
    spec = _system_task_specs().get(target)
    if spec is None:
        return None
    workflow_id = str(spec.get("workflow_id") or "").strip()
    runtime_lane = str(spec.get("runtime_lane") or "main_conversation").strip()
    return SpecificTaskRecord(
        task_id=target,
        task_title=str(spec.get("title") or target),
        domain_id=str(spec.get("domain_id") or "").strip(),
        description=str(spec.get("description") or spec.get("title") or target),
        enabled=True,
        runtime_lane=runtime_lane,
        input_contract_id=str(spec.get("input_contract_id") or "UserMessage"),
        output_contract_id=str(spec.get("output_contract_id") or "AssistantFinalAnswer"),
        acceptance_profile_id="",
        default_flow_contract_id=workflow_id.replace("workflow.", "flow.", 1) if workflow_id else f"flow.{target.removeprefix('task.')}",
        default_workflow_id=workflow_id,
        default_projection_policy="workflow_compatible_or_task_default",
        task_policy={
            "safety_policy": dict(spec.get("safety_policy") or {}),
            "task_structure": {
                "runtime_lane_hint": runtime_lane,
                "memory_scope_hint": "conversation",
            },
        },
        metadata={
            "managed_by": "task_system",
            "source": "task_system_runtime_projection",
        },
    )

def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).tasks_dir


def _flows_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flows.json"


def _general_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "general_task_profiles.json"


def _assignments_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_assignments.json"


def _specific_task_records_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "specific_task_records.json"


def _task_domains_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_domains.json"


def _task_graphs_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_graphs.json"


def _topology_templates_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "topology_templates.json"


def _projection_bindings_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_projection_bindings.json"


def _flow_contract_bindings_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_flow_contract_bindings.json"


def _adoption_plans_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_agent_adoption_plans.json"


def _memory_request_profiles_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_memory_request_profiles.json"


def _communication_protocols_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_communication_protocols.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        import json

        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _merge_default_overlay_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    defaults_by_key = {
        str(item.get(key) or "").strip(): dict(item)
        for item in default_items
        if str(item.get(key) or "").strip()
    }
    merged: dict[str, dict[str, Any]] = {}
    for item_key, item in defaults_by_key.items():
        merged[item_key] = dict(item)
    for stored in stored_items:
        item_key = str(stored.get(key) or "").strip()
        if not item_key:
            continue
        base = dict(defaults_by_key.get(item_key) or {})
        merged_item = {**base, **dict(stored)}
        if isinstance(base.get("metadata"), dict) or isinstance(stored.get("metadata"), dict):
            merged_item["metadata"] = {
                **dict(base.get("metadata") or {}),
                **{
                    meta_key: meta_value
                    for meta_key, meta_value in dict(stored.get("metadata") or {}).items()
                    if meta_value not in ("", None, [], {})
                    or meta_key not in dict(base.get("metadata") or {})
                },
            }
        if isinstance(base.get("task_policy"), dict) or isinstance(stored.get("task_policy"), dict):
            base_policy = dict(base.get("task_policy") or {})
            stored_policy = dict(stored.get("task_policy") or {})
            merged_policy = {**base_policy, **stored_policy}
            if isinstance(base_policy.get("task_structure"), dict) or isinstance(stored_policy.get("task_structure"), dict):
                merged_policy["task_structure"] = {
                    **dict(base_policy.get("task_structure") or {}),
                    **dict(stored_policy.get("task_structure") or {}),
                }
            if isinstance(base_policy.get("safety_policy"), dict) or isinstance(stored_policy.get("safety_policy"), dict):
                merged_policy["safety_policy"] = {
                    **dict(base_policy.get("safety_policy") or {}),
                    **dict(stored_policy.get("safety_policy") or {}),
                }
            merged_item["task_policy"] = merged_policy
        merged[item_key] = merged_item
    return list(merged.values())


def _merge_authoritative_defaults_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    defaults_by_key = {
        str(item.get(key) or "").strip(): dict(item)
        for item in default_items
        if str(item.get(key) or "").strip()
    }
    merged: dict[str, dict[str, Any]] = {item_key: dict(item) for item_key, item in defaults_by_key.items()}
    for stored in stored_items:
        item_key = str(stored.get(key) or "").strip()
        if not item_key:
            continue
        default_item = dict(defaults_by_key.get(item_key) or {})
        if default_item and _is_system_managed_item(default_item):
            continue
        if default_item:
            merged[item_key] = {**default_item, **dict(stored)}
            continue
        merged[item_key] = dict(stored)
    return list(merged.values())


def _is_system_managed_item(item: dict[str, Any]) -> bool:
    metadata = dict(item.get("metadata") or {})
    if str(metadata.get("managed_by") or "").strip() == "task_system":
        return True
    return bool(str(metadata.get("task_resource") or "").strip())


def _derived_count(effective_items: list[Any], explicit_items: list[Any], *, key_attr: str) -> int:
    explicit_keys = {
        str(getattr(item, key_attr, "") or "").strip()
        for item in explicit_items
        if str(getattr(item, key_attr, "") or "").strip()
    }
    return sum(
        1
        for item in effective_items
        if str(getattr(item, key_attr, "") or "").strip()
        and str(getattr(item, key_attr, "") or "").strip() not in explicit_keys
    )


def _next_prefixed_id(existing_ids: list[str], *, prefix: str, width: int = 6) -> str:
    max_value = 0
    for raw in existing_ids:
        value = str(raw or "").strip()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            max_value = max(max_value, int(suffix))
    return f"{prefix}{max_value + 1:0{width}d}"


def _family_from_ref(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    prefixes = (
        ("development", ("task.dev.", "flow.dev.", "graph.dev.", "topology.dev.", "protocol.dev.", "workflow.dev.")),
        ("writing", ("task.writing.", "flow.writing.", "graph.writing.", "topology.writing.", "protocol.writing.", "workflow.writing.")),
        ("health", ("task.health.", "flow.health.", "graph.health.", "topology.health.", "protocol.health.", "workflow.health.")),
        ("general", ("task.general.", "flow.general.", "graph.general.", "topology.general.", "protocol.general.", "workflow.general.")),
    )
    for family, family_prefixes in prefixes:
        if any(raw.startswith(prefix) for prefix in family_prefixes):
            return family
    return ""


def _default_coordination_graph(
    *,
    coordinator_agent_id: str,
    participant_agent_ids: tuple[str, ...],
    subtask_refs: tuple[str, ...] = (),
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    coordinator = str(coordinator_agent_id or "agent:0").strip() or "agent:0"
    participants = tuple(str(item).strip() for item in participant_agent_ids if str(item).strip())
    subtasks = tuple(str(item).strip() for item in subtask_refs if str(item).strip())
    nodes: list[dict[str, Any]] = [
        {
            "node_id": "coordinator",
            "node_type": "coordinator",
            "agent_id": coordinator,
            "role": "coordinator",
            "label": "协调者",
        }
    ]
    edges: list[dict[str, Any]] = []
    for index, agent_id in enumerate(participants or tuple("" for _ in subtasks), start=1):
        task_id = subtasks[index - 1] if index - 1 < len(subtasks) else ""
        node_id = f"subtask_{index}" if task_id else f"agent_{index}"
        nodes.append(
            {
                "node_id": node_id,
                "node_type": "subtask" if task_id else "agent_role",
                "task_id": task_id,
                "agent_id": agent_id,
                "role": "participant",
            }
        )
        edges.append({"edge_id": f"edge_{index}", "from": "coordinator", "to": node_id, "mode": "structured_handoff"})
        edges.append({"edge_id": f"edge_{index}_back", "from": node_id, "to": "coordinator", "mode": "review_feedback"})
    return tuple(nodes), tuple(edges)


def _subtask_refs_from_graph_nodes(nodes: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(node.get("task_id") or node.get("subtask_ref") or "").strip()
            for node in nodes
            if str(node.get("node_type") or "").strip() != "graph_module"
            and str(node.get("task_id") or node.get("subtask_ref") or "").strip().startswith("task.")
        )
    )


def _runtime_graph_view_nodes_and_edges(graph: TaskGraphDefinition) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    try:
        from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec

        runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    except Exception:
        return (), ()
    if not getattr(runtime_spec, "graph_module_runtime_plans", ()):
        return (), ()
    nodes = tuple(node.to_dict() for node in runtime_spec.nodes)
    edges = tuple({**edge.to_dict(), "edge_type": edge.mode} for edge in runtime_spec.edges)
    return nodes, edges


def default_task_domains() -> tuple[TaskDomainRecord, ...]:
    return ()

def default_general_task_profiles() -> tuple[GeneralTaskProfile, ...]:
    return ()

def default_coordination_tasks() -> tuple[CoordinationTaskDefinition, ...]:
    return ()

def default_task_communication_protocols() -> tuple[TaskCommunicationProtocol, ...]:
    return ()

def default_topology_templates() -> tuple[TopologyTemplate, ...]:
    return ()

def _default_projection_binding(task: TaskAssignment) -> TaskProjectionBinding:
    selected_projection_ids = tuple(
        item
        for item in [str(task.projection_id or "").strip()]
        if item
    )
    default_projection_id = selected_projection_ids[0] if selected_projection_ids else ""
    return TaskProjectionBinding(
        binding_id=f"taskprojbind:{task.task_id}",
        task_id=task.task_id,
        projection_selection_mode="task_default" if default_projection_id else "workflow_compatible_or_task_default",
        allowed_projection_ids=selected_projection_ids,
        default_projection_id=default_projection_id,
        projection_required=bool(default_projection_id),
        notes="Derived from task assignment defaults.",
        metadata={"derived_from": "task_assignment"},
    )


def _default_flow_contract_binding(task: TaskAssignment) -> TaskFlowContractBinding:
    flow_contract_id = str(task.flow_id or "").strip()
    return TaskFlowContractBinding(
        binding_id=f"taskflowbind:{task.task_id}",
        task_id=task.task_id,
        flow_contract_id=flow_contract_id,
        override_policy="task_default",
        verification_gate_profile=str(dict(task.safety_policy or {}).get("verification_mode") or ""),
        fallback_policy="fail_closed",
        metadata={"derived_from": "task_assignment"},
    )


def _default_adoption_plan(task: TaskAssignment) -> TaskAgentAdoptionPlan:
    participant_ids = tuple(str(item).strip() for item in task.participant_agent_ids if str(item).strip())
    task_structure = dict(task.task_structure or {})
    task_metadata = dict(task.metadata or {})
    runtime_limits = dict(task_structure.get("runtime_limits") or {})
    task_graph_id = str(
        task_structure.get("task_graph_id") or task_structure.get("graph_id") or task_metadata.get("task_graph_id") or ""
    ).strip()
    communication_protocol_id = str(
        task_structure.get("communication_protocol_id") or task_metadata.get("communication_protocol_id") or ""
    ).strip()
    topology_template_id = str(
        task_structure.get("topology_template_id") or task_metadata.get("topology_template_id") or ""
    ).strip()
    agent_group_id = str(task_structure.get("agent_group_id") or task_metadata.get("agent_group_id") or "").strip()
    execution_chain_type = str(task.to_dict().get("execution_chain_type") or "").strip() or (
        "coordination_chain" if task_graph_id else "single_agent_chain"
    )
    return TaskAgentAdoptionPlan(
        plan_id=f"taskadopt:{task.task_id}",
        task_id=task.task_id,
        adoption_mode="adopt_existing" if not participant_ids else "adopt_with_projection",
        default_agent_id=normalize_agent_id(str(task.default_agent_id or "agent:0").strip() or "agent:0"),
        allow_worker_agent_spawn=False,
        worker_agent_blueprint_id="",
        worker_agent_naming_rule="",
        notes="Derived from task assignment defaults.",
        metadata={
            "derived_from": "task_assignment",
            "participant_agent_ids": list(participant_ids),
            "runtime_limits": runtime_limits,
            "execution_chain_type": execution_chain_type,
            "task_graph_id": task_graph_id,
            "graph_id": task_graph_id,
            "communication_protocol_id": communication_protocol_id,
            "topology_template_id": topology_template_id,
            "agent_group_id": agent_group_id,
        },
    )


def _default_memory_request_profile(task: TaskAssignment) -> TaskMemoryRequestProfile:
    memory_scope_hint = str(dict(task.task_structure or {}).get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [task.task_id or "general_task"]
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{task.task_id}",
        task_id=task.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="normal",
        writeback_policy="task_default",
        allow_long_term_memory=False,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "task_assignment"},
    )


def _specific_task_record_from_assignment(task: TaskAssignment) -> SpecificTaskRecord:
    projection_policy = "fixed_projection" if str(task.projection_id or "").strip() else "workflow_compatible_or_task_default"
    return SpecificTaskRecord(
        task_id=task.task_id,
        task_title=task.task_title,
        domain_id=task.domain_id,
        description=str(dict(task.metadata or {}).get("description") or task.task_title),
        enabled=task.enabled,
        runtime_lane=task.runtime_lane,
        input_contract_id=task.input_contract_id,
        output_contract_id=task.output_contract_id,
        acceptance_profile_id=str(dict(task.metadata or {}).get("acceptance_profile_id") or ""),
        default_flow_contract_id=str(task.flow_id or ""),
        default_workflow_id=str(task.workflow_id or ""),
        default_projection_policy=projection_policy,
        task_policy={
            "safety_policy": dict(task.safety_policy or {}),
            "task_structure": dict(task.task_structure or {}),
            "runtime_limits": dict(dict(task.task_structure or {}).get("runtime_limits") or {}),
        },
        metadata=dict(task.metadata or {}),
    )


def _default_projection_binding_from_specific_record(record: SpecificTaskRecord) -> TaskProjectionBinding | None:
    projection_policy = str(record.default_projection_policy or "").strip()
    if projection_policy in {"", "prompt_library_stage_role", "workflow_compatible_or_task_default"}:
        return None
    projection_required = projection_policy == "fixed_projection"
    return TaskProjectionBinding(
        binding_id=f"taskprojbind:{record.task_id}",
        task_id=record.task_id,
        projection_selection_mode=projection_policy or "workflow_compatible_or_task_default",
        allowed_projection_ids=(),
        default_projection_id="",
        projection_required=projection_required,
        notes="Derived from specific task record defaults.",
        metadata={"derived_from": "specific_task_record"},
    )


def _default_flow_contract_binding_from_specific_record(record: SpecificTaskRecord) -> TaskFlowContractBinding:
    return TaskFlowContractBinding(
        binding_id=f"taskflowbind:{record.task_id}",
        task_id=record.task_id,
        flow_contract_id=str(record.default_flow_contract_id or "").strip(),
        override_policy="task_default",
        verification_gate_profile=str(dict(record.task_policy or {}).get("verification_gate_profile") or ""),
        fallback_policy="fail_closed",
        metadata={"derived_from": "specific_task_record"},
    )


def _default_memory_request_profile_from_specific_record(record: SpecificTaskRecord) -> TaskMemoryRequestProfile:
    task_policy = dict(record.task_policy or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    memory_scope_hint = str(task_structure.get("memory_scope_hint") or "").strip()
    requested_layers = ["conversation"]
    requested_topics = [record.task_id or "specific_task"]
    return TaskMemoryRequestProfile(
        profile_id=f"taskmem:{record.task_id}",
        task_id=record.task_id,
        requested_memory_layers=tuple(requested_layers),
        requested_topics=tuple(requested_topics),
        memory_priority="normal",
        writeback_policy="task_default",
        allow_long_term_memory=False,
        memory_scope_hint=memory_scope_hint,
        metadata={"derived_from": "specific_task_record"},
    )


def _synthetic_task_from_general_profile(profile: GeneralTaskProfile) -> TaskAssignment:
    return TaskAssignment(
        task_id=profile.profile_id,
        task_title=profile.title,
        task_kind="general_task",
        flow_id="flow.general.main_conversation",
        domain_id="domain.general",
        runtime_lane="main_conversation",
        default_agent_id=normalize_agent_id(str(profile.default_agent_id or "agent:0").strip() or "agent:0"),
        participant_agent_ids=(),
        workflow_id=str(profile.default_workflow_id or ""),
        workflow_file_ref=f"workflow:{profile.default_workflow_id}" if profile.default_workflow_id else "",
        projection_id=str(profile.default_projection_id or ""),
        input_contract_id=str(profile.input_contract_id or ""),
        output_contract_id=str(profile.output_contract_id or ""),
        safety_policy={},
        task_structure={
            "entry_channel": str(profile.entry_channel or "main_conversation"),
            "memory_scope_hint": "conversation_readonly",
        },
        enabled=profile.enabled,
        metadata=dict(profile.metadata or {}),
    )


class TaskFlowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.agent_group_registry = None
        self.agent_runtime_registry = AgentRuntimeRegistry(self.base_dir)
        self.workflow_registry = TaskWorkflowRegistry(self.base_dir)
        self._cache: dict[str, Any] = {}

    def _get_cached(self, key: str, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def _invalidate_cache(self, *keys: str) -> None:
        if not keys:
            self._cache.clear()
            return
        for key in keys:
            self._cache.pop(key, None)

    def list_general_task_profiles(self) -> list[GeneralTaskProfile]:
        payload = _read_json(
            _general_profiles_path(self.base_dir),
            {"profiles": [item.to_dict() for item in default_general_task_profiles()]},
        )
        profiles: list[GeneralTaskProfile] = []
        for item in list(payload.get("profiles") or []):
            if not isinstance(item, dict):
                continue
            profiles.append(
                GeneralTaskProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    title=str(item.get("title") or ""),
                    entry_channel=str(item.get("entry_channel") or "main_conversation"),
                    default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "agent:0")),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_id=str(item.get("default_projection_id") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    conversation_entry_policy=str(item.get("conversation_entry_policy") or "user_dialogue_to_main_agent"),
                    enabled=bool(item.get("enabled", True)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return profiles

    def upsert_general_task_profile(
        self,
        *,
        profile_id: str,
        title: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_projection_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        conversation_entry_policy: str = "user_dialogue_to_main_agent",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> GeneralTaskProfile:
        target = str(profile_id or "").strip()
        if not target.startswith("general."):
            raise ValueError("profile_id must start with general.")
        profile = GeneralTaskProfile(
            profile_id=target,
            title=str(title or target).strip(),
            entry_channel="main_conversation",
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_id=str(default_projection_id or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            conversation_entry_policy=str(conversation_entry_policy or "user_dialogue_to_main_agent").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_general_task_profiles() if item.profile_id != target]
        profiles.append(profile)
        _write_json(_general_profiles_path(self.base_dir), {"profiles": [item.to_dict() for item in profiles]})
        self._invalidate_cache()
        return profile

    def list_flows(self) -> list[TaskFlowDefinition]:
        def load() -> list[TaskFlowDefinition]:
            default_payload = [item.to_dict() for item in default_task_flows()]
            payload = _read_json(
                _flows_path(self.base_dir),
                {"flows": default_payload},
            )
            merged_payload = _merge_default_overlay_by_key(
                default_payload,
                [
                    item
                    for item in list(payload.get("flows") or [])
                    if isinstance(item, dict) and not _is_removed_health_task_config(item)
                ],
                key="flow_id",
            )
            flows = []
            for item in merged_payload:
                flows.append(
                    TaskFlowDefinition(
                        flow_id=str(item.get("flow_id") or ""),
                        title=str(item.get("title") or ""),
                        input_contract_id=str(item.get("input_contract_id") or ""),
                        output_contract_id=str(item.get("output_contract_id") or ""),
                        default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "")),
                        default_workflow_id=str(item.get("default_workflow_id") or ""),
                        default_runtime_lane=str(item.get("default_runtime_lane") or ""),
                        default_memory_scope=str(item.get("default_memory_scope") or ""),
                        enabled=bool(item.get("enabled", True)),
                        metadata=dict(item.get("metadata") or {}),
                    )
                )
            normalized = [item.to_dict() for item in flows]
            if payload.get("flows") != normalized:
                _write_json(_flows_path(self.base_dir), {"flows": normalized})
            return flows

        return self._get_cached("flows", load)

    def get_flow(self, flow_id: str) -> TaskFlowDefinition | None:
        target = str(flow_id or "").strip()
        return next((item for item in self.list_flows() if item.flow_id == target), None)

    def next_flow_id(self) -> str:
        return _next_prefixed_id(
            [item.flow_id for item in self.list_flows()],
            prefix="flow.",
        )

    def upsert_flow(
        self,
        *,
        flow_id: str,
        title: str,
        input_contract_id: str,
        output_contract_id: str,
        default_agent_id: str,
        default_workflow_id: str,
        default_runtime_lane: str,
        default_memory_scope: str,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowDefinition:
        normalized_flow_id = str(flow_id or "").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        flow = TaskFlowDefinition(
            flow_id=normalized_flow_id,
            title=str(title or normalized_flow_id).strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            default_agent_id=normalize_agent_id(str(default_agent_id or "").strip()),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_runtime_lane=str(default_runtime_lane or "").strip(),
            default_memory_scope=str(default_memory_scope or "").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        flows = [item for item in self.list_flows() if item.flow_id != normalized_flow_id]
        flows.append(flow)
        _write_json(_flows_path(self.base_dir), {"flows": [item.to_dict() for item in flows]})
        self._invalidate_cache()
        return flow

    def list_task_assignments(self) -> list[TaskAssignment]:
        def load() -> list[TaskAssignment]:
            flow_by_id = {item.flow_id: item for item in self.list_flows()}
            projection_binding_by_task_id = {
                item.task_id: item
                for item in self.list_projection_bindings()
            }
            default_assignments = [
                self._assignment_from_specific_task_record(
                    item,
                    flow=flow_by_id.get(str(item.default_flow_contract_id or f"flow.{item.task_id.removeprefix('task.')}").strip()),
                    projection_binding=projection_binding_by_task_id.get(item.task_id),
                ).to_dict()
                for item in self.list_specific_task_records()
            ]
            payload = _read_json(
                _assignments_path(self.base_dir),
                {"assignments": default_assignments},
            )
            merged_payload = _merge_items_by_key(
                default_assignments,
                [
                    item
                    for item in list(payload.get("assignments") or [])
                    if isinstance(item, dict) and not _is_removed_health_task_config(item)
                ],
                key="task_id",
            )
            assignments: list[TaskAssignment] = []
            for item in merged_payload:
                assignments.append(_assignment_from_dict(item))
            normalized = [item.to_dict() for item in assignments]
            if payload.get("assignments") != normalized:
                _write_json(_assignments_path(self.base_dir), {"assignments": normalized})
            return assignments

        return self._get_cached("task_assignments", load)

    def get_general_task_profile(self, profile_id: str) -> GeneralTaskProfile | None:
        target = str(profile_id or "").strip()
        return next((item for item in self.list_general_task_profiles() if item.profile_id == target), None)

    def get_task_assignment(self, task_id: str) -> TaskAssignment | None:
        target = str(task_id or "").strip()
        stored_assignment = next((item for item in self.list_task_assignments() if item.task_id == target), None)
        if stored_assignment is not None:
            return stored_assignment
        synthetic_record = _synthetic_specific_task_record_for_runtime(target)
        if synthetic_record is None:
            return None
        return self._assignment_from_specific_task_record(synthetic_record)

    def next_specific_task_id(self) -> str:
        ids = [item.task_id for item in self.list_task_assignments()]
        ids.extend(item.task_id for item in self.list_specific_task_records())
        return _next_prefixed_id(ids, prefix="task.")

    def list_task_domains(self) -> list[TaskDomainRecord]:
        default_payload = [item.to_dict() for item in default_task_domains()]
        payload = _read_json(
            _task_domains_path(self.base_dir),
            {"task_domains": default_payload},
        )
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip()
        }
        merged_payload = _merge_default_overlay_by_key(
            [item for item in default_payload if str(item.get("domain_id") or "").strip() not in deleted_domain_ids],
            [item for item in list(payload.get("task_domains") or []) if isinstance(item, dict)],
            key="domain_id",
        )
        domains: list[TaskDomainRecord] = []
        for item in merged_payload:
            domain_id = str(item.get("domain_id") or "").strip()
            if not domain_id:
                continue
            domains.append(
                TaskDomainRecord(
                    domain_id=domain_id,
                    title=str(item.get("title") or domain_id).strip(),
                    description=str(item.get("description") or "").strip(),
                    enabled=bool(item.get("enabled", True)),
                    sort_order=int(item.get("sort_order", 0) or 0),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        domains = sorted(domains, key=lambda item: (item.sort_order, item.title, item.domain_id))
        normalized = [item.to_dict() for item in domains]
        if payload.get("task_domains") != normalized:
            _write_json(
                _task_domains_path(self.base_dir),
                {
                    "task_domains": normalized,
                    "deleted_domain_ids": sorted(deleted_domain_ids),
                },
            )
        return domains

    def get_task_domain(self, domain_id: str) -> TaskDomainRecord | None:
        target = str(domain_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list_task_domains() if item.domain_id == target), None)

    def upsert_task_domain(
        self,
        *,
        domain_id: str,
        title: str,
        description: str = "",
        enabled: bool = True,
        sort_order: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TaskDomainRecord:
        normalized_domain_id = str(domain_id or "").strip()
        if not normalized_domain_id.startswith("domain."):
            raise ValueError("domain_id must start with domain.")
        record = TaskDomainRecord(
            domain_id=normalized_domain_id,
            title=str(title or normalized_domain_id).strip(),
            description=str(description or "").strip(),
            enabled=bool(enabled),
            sort_order=int(sort_order),
            metadata=dict(metadata or {}),
        )
        domains = [item for item in self.list_task_domains() if item.domain_id != normalized_domain_id]
        domains.append(record)
        domains = sorted(domains, key=lambda item: (item.sort_order, item.title, item.domain_id))
        payload = _read_json(_task_domains_path(self.base_dir), {"task_domains": []})
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip() and str(item).strip() != normalized_domain_id
        }
        _write_json(
            _task_domains_path(self.base_dir),
            {
                "task_domains": [item.to_dict() for item in domains],
                "deleted_domain_ids": sorted(deleted_domain_ids),
            },
        )
        self._invalidate_cache()
        return record

    def delete_task_domain(self, domain_id: str) -> dict[str, Any]:
        target = str(domain_id or "").strip()
        domain = self.get_task_domain(target)
        if domain is None:
            raise ValueError("task domain not found")
        task_ids = {
            item.task_id
            for item in self.list_specific_task_records()
            if str(item.domain_id or item.metadata.get("domain_id") or "").strip() == target
        }
        flow_ids = {
            item.flow_id
            for item in self.list_flows()
            if str(item.metadata.get("domain_id") or "").strip() == target
            or str(item.metadata.get("task_id") or "") in task_ids
        }
        coordination_ids = {
            str(item.graph_id or "")
            for item in self.list_task_graphs()
            if str(item.metadata.get("domain_id") or item.domain_id or "") == target
            or any(ref in task_ids for ref in item.to_dict().get("subtask_refs") or [])
        }
        topology_ids = {
            item.template_id
            for item in self.list_topology_templates()
            if str(item.metadata.get("domain_id") or "") == target
        }
        protocol_ids = {
            item.protocol_id
            for item in self.list_task_communication_protocols()
            if str(item.metadata.get("domain_id") or "") == target
            or str(item.metadata.get("task_id") or "") in task_ids
        }
        workflow_ids = self._collect_deletable_workflow_ids(
            task_ids=task_ids,
            flow_ids=flow_ids,
        )

        domains = [item for item in self.list_task_domains() if item.domain_id != target]
        payload = _read_json(_task_domains_path(self.base_dir), {"task_domains": []})
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip()
        }
        deleted_domain_ids.add(target)
        _write_json(
            _task_domains_path(self.base_dir),
            {
                "task_domains": [item.to_dict() for item in domains],
                "deleted_domain_ids": sorted(deleted_domain_ids),
            },
        )
        _write_json(
            _specific_task_records_path(self.base_dir),
            {"specific_task_records": [item.to_dict() for item in self.list_specific_task_records() if item.task_id not in task_ids]},
        )
        _write_json(
            _assignments_path(self.base_dir),
            {"assignments": [item.to_dict() for item in self.list_task_assignments() if item.task_id not in task_ids]},
        )
        _write_json(
            _flows_path(self.base_dir),
            {"flows": [item.to_dict() for item in self.list_flows() if item.flow_id not in flow_ids]},
        )
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in self.list_projection_bindings() if item.task_id not in task_ids]},
        )
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings() if item.task_id not in task_ids]},
        )
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_dict() for item in self.list_task_agent_adoption_plans() if item.task_id not in task_ids]},
        )
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in self.list_task_memory_request_profiles() if item.task_id not in task_ids]},
        )
        _write_json(
            _topology_templates_path(self.base_dir),
            {"topology_templates": [item.to_dict() for item in self.list_topology_templates() if item.template_id not in topology_ids]},
        )
        _write_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": [item.to_dict() for item in self.list_task_communication_protocols() if item.protocol_id not in protocol_ids]},
        )
        deleted_workflow_ids = self.workflow_registry.delete_workflows(workflow_ids)
        return {
            "domain_id": target,
            "deleted_task_ids": sorted(task_ids),
            "deleted_flow_ids": sorted(flow_ids),
            "deleted_workflow_ids": list(deleted_workflow_ids),
            "deleted_task_graph_ids": sorted(coordination_ids),
            "deleted_topology_template_ids": sorted(topology_ids),
            "deleted_protocol_ids": sorted(protocol_ids),
        }

    def list_specific_task_records(self) -> list[SpecificTaskRecord]:
        default_records = [self._specific_task_record_from_flow(flow).to_dict() for flow in self.list_flows()]
        payload = _read_json(
            _specific_task_records_path(self.base_dir),
            {"specific_task_records": default_records},
        )
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }
        records: list[SpecificTaskRecord] = []
        merged_payload = _merge_default_overlay_by_key(
            [item for item in default_records if str(item.get("task_id") or "").strip() not in deleted_task_ids],
            [
                item
                for item in list(payload.get("specific_task_records") or [])
                if isinstance(item, dict) and not _is_removed_health_task_config(item)
            ],
            key="task_id",
        )
        for item in merged_payload:
            records.append(
                SpecificTaskRecord(
                    task_id=str(item.get("task_id") or ""),
                    task_title=str(item.get("task_title") or ""),
                    domain_id=str(item.get("domain_id") or dict(item.get("metadata") or {}).get("domain_id") or ""),
                    description=str(item.get("description") or ""),
                    enabled=bool(item.get("enabled", True)),
                    runtime_lane=str(item.get("runtime_lane") or dict(dict(item.get("task_policy") or {}).get("task_structure") or {}).get("runtime_lane_hint") or ""),
                    input_contract_id=str(item.get("input_contract_id") or ""),
                    output_contract_id=str(item.get("output_contract_id") or ""),
                    acceptance_profile_id=str(item.get("acceptance_profile_id") or ""),
                    default_flow_contract_id=str(item.get("default_flow_contract_id") or ""),
                    default_workflow_id=str(item.get("default_workflow_id") or ""),
                    default_projection_policy=str(item.get("default_projection_policy") or ""),
                    task_policy=dict(item.get("task_policy") or {}),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        if not records:
            records = [self._specific_task_record_from_flow(flow) for flow in self.list_flows()]
        if records:
            normalized = [item.to_dict() for item in records]
            if payload.get("specific_task_records") != normalized:
                _write_json(
                    _specific_task_records_path(self.base_dir),
                    {
                        "specific_task_records": normalized,
                        "deleted_task_ids": sorted(deleted_task_ids),
                    },
                )
        return records

    def get_specific_task_record(self, task_id: str) -> SpecificTaskRecord | None:
        target = str(task_id or "").strip()
        stored_record = next((item for item in self.list_specific_task_records() if item.task_id == target), None)
        if stored_record is not None:
            return stored_record
        return _synthetic_specific_task_record_for_runtime(target)

    def upsert_task_assignment(
        self,
        *,
        task_id: str,
        task_title: str,
        task_kind: str,
        flow_id: str,
        domain_id: str = "",
        runtime_lane: str = "",
        default_agent_id: str,
        participant_agent_ids: tuple[str, ...] = (),
        workflow_id: str = "",
        workflow_file_ref: str = "",
        projection_id: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        safety_policy: dict[str, Any] | None = None,
        task_structure: dict[str, Any] | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskAssignment:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        normalized_flow_id = str(flow_id or f"flow.{target.removeprefix('task.')}").strip()
        if not normalized_flow_id.startswith("flow."):
            raise ValueError("flow_id must start with flow.")
        normalized_metadata = dict(metadata or {})
        normalized_task_structure = dict(task_structure or {})
        record = self.upsert_specific_task_record(
            task_id=target,
            task_title=task_title,
            domain_id=str(domain_id or normalized_metadata.get("domain_id") or "").strip(),
            description=str(normalized_metadata.get("description") or task_title or target).strip(),
            enabled=enabled,
            runtime_lane=runtime_lane,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            acceptance_profile_id=str(normalized_metadata.get("acceptance_profile_id") or ""),
            default_flow_contract_id=normalized_flow_id,
            default_workflow_id=workflow_id,
            default_projection_policy="fixed_projection" if str(projection_id or "").strip() else "workflow_compatible_or_task_default",
            task_policy={
                "safety_policy": dict(safety_policy or {}),
                "task_structure": {
                    **normalized_task_structure,
                    "trigger_signals": list(normalized_task_structure.get("trigger_signals") or []),
                    "notes": str(normalized_task_structure.get("notes") or ""),
                },
            },
            metadata=normalized_metadata,
        )
        self.upsert_flow(
            flow_id=normalized_flow_id,
            title=record.task_title,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            default_workflow_id=record.default_workflow_id,
            default_runtime_lane=record.runtime_lane or str(dict(record.task_policy or {}).get("task_structure", {}).get("runtime_lane_hint") or ""),
            default_memory_scope=str(dict(record.task_policy or {}).get("task_structure", {}).get("memory_scope_hint") or ""),
            enabled=record.enabled,
            metadata={**dict(record.metadata or {}), "task_assignment_id": record.task_id},
        )
        assignment = TaskAssignment(
            task_id=target,
            task_title=record.task_title,
            task_kind=str(task_kind or "specific_task").strip(),
            flow_id=normalized_flow_id,
            domain_id=record.domain_id,
            runtime_lane=record.runtime_lane,
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            participant_agent_ids=normalize_agent_id_sequence(str(item).strip() for item in participant_agent_ids if str(item).strip()),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=str(workflow_file_ref or "").strip(),
            projection_id=str(projection_id or "").strip(),
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=dict(safety_policy or {}),
            task_structure=normalized_task_structure,
            enabled=record.enabled,
            metadata=normalized_metadata,
        )
        assignments = [item for item in self.list_task_assignments() if item.task_id != target]
        assignments.append(assignment)
        _write_json(_assignments_path(self.base_dir), {"assignments": [item.to_dict() for item in assignments]})
        return assignment

    def upsert_specific_task_record(
        self,
        *,
        task_id: str,
        task_title: str,
        domain_id: str = "",
        description: str = "",
        enabled: bool = True,
        runtime_lane: str = "",
        input_contract_id: str = "",
        output_contract_id: str = "",
        acceptance_profile_id: str = "",
        default_flow_contract_id: str = "",
        default_workflow_id: str = "",
        default_projection_policy: str = "",
        task_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpecificTaskRecord:
        target = str(task_id or "").strip()
        if not target.startswith("task."):
            raise ValueError("task_id must start with task.")
        record = SpecificTaskRecord(
            task_id=target,
            task_title=str(task_title or target).strip(),
            domain_id=str(domain_id or "").strip(),
            description=str(description or task_title or target).strip(),
            enabled=bool(enabled),
            runtime_lane=str(runtime_lane or "").strip(),
            input_contract_id=str(input_contract_id or "").strip(),
            output_contract_id=str(output_contract_id or "").strip(),
            acceptance_profile_id=str(acceptance_profile_id or "").strip(),
            default_flow_contract_id=str(default_flow_contract_id or "").strip(),
            default_workflow_id=str(default_workflow_id or "").strip(),
            default_projection_policy=str(default_projection_policy or "").strip(),
            task_policy=dict(task_policy or {}),
            metadata=dict(metadata or {}),
        )
        records = [item for item in self.list_specific_task_records() if item.task_id != target]
        records.append(record)
        payload = _read_json(_specific_task_records_path(self.base_dir), {"specific_task_records": []})
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip() and str(item).strip() != target
        }
        _write_json(
            _specific_task_records_path(self.base_dir),
            {
                "specific_task_records": [item.to_dict() for item in records],
                "deleted_task_ids": sorted(deleted_task_ids),
            },
        )
        self._invalidate_cache()
        return record

    def delete_specific_task_record(self, task_id: str) -> dict[str, Any]:
        target = str(task_id or "").strip()
        record = self.get_specific_task_record(target)
        if record is None:
            raise ValueError("specific task not found")
        flow_ids = {
            item.flow_id
            for item in self.list_flows()
            if str(item.metadata.get("task_id") or "") == target
            or item.flow_id == record.default_flow_contract_id
            or item.flow_id == f"flow.{target.removeprefix('task.')}"
        }
        workflow_ids = self._collect_deletable_workflow_ids(
            task_ids={target},
            flow_ids=flow_ids,
        )
        payload = _read_json(_specific_task_records_path(self.base_dir), {"specific_task_records": []})
        deleted_task_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_task_ids") or [])
            if str(item).strip()
        }
        deleted_task_ids.add(target)
        _write_json(
            _specific_task_records_path(self.base_dir),
            {
                "specific_task_records": [item.to_dict() for item in self.list_specific_task_records() if item.task_id != target],
                "deleted_task_ids": sorted(deleted_task_ids),
            },
        )
        _write_json(
            _assignments_path(self.base_dir),
            {"assignments": [item.to_dict() for item in self.list_task_assignments() if item.task_id != target]},
        )
        _write_json(
            _flows_path(self.base_dir),
            {"flows": [item.to_dict() for item in self.list_flows() if item.flow_id not in flow_ids]},
        )
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in self.list_projection_bindings() if item.task_id != target]},
        )
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in self.list_flow_contract_bindings() if item.task_id != target]},
        )
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_dict() for item in self.list_task_agent_adoption_plans() if item.task_id != target]},
        )
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in self.list_task_memory_request_profiles() if item.task_id != target]},
        )
        deleted_workflow_ids = self.workflow_registry.delete_workflows(workflow_ids)
        self._invalidate_cache()
        return {
            "task_id": target,
            "deleted_flow_ids": sorted(flow_ids),
            "deleted_workflow_ids": list(deleted_workflow_ids),
        }

    def _assignment_from_flow(self, flow: TaskFlowDefinition) -> TaskAssignment:
        workflow = self.workflow_registry.get_workflow(flow.default_workflow_id)
        task_id = str(flow.metadata.get("task_id") or flow.metadata.get("task_assignment_id") or f"task.{flow.flow_id.removeprefix('flow.')}").strip()
        spec = _system_task_specs().get(task_id)
        return TaskAssignment(
            task_id=task_id,
            task_title=flow.title,
            task_kind="specific_task",
            flow_id=flow.flow_id,
            domain_id=str(flow.metadata.get("domain_id") or ""),
            runtime_lane=flow.default_runtime_lane,
            default_agent_id=flow.default_agent_id or "agent:0",
            participant_agent_ids=(),
            workflow_id=flow.default_workflow_id,
            workflow_file_ref=f"workflow:{flow.default_workflow_id}" if flow.default_workflow_id else "",
            projection_id="",
            input_contract_id=flow.input_contract_id,
            output_contract_id=flow.output_contract_id,
            safety_policy=dict(spec.get("safety_policy") or {}) if spec is not None else {},
            task_structure={
                "runtime_lane_hint": flow.default_runtime_lane,
                "memory_scope_hint": flow.default_memory_scope,
                "workflow_steps": [dict(item) for item in workflow.steps] if workflow is not None else [],
                "task_resource_kind": str(flow.metadata.get("task_resource") or ""),
            },
            enabled=flow.enabled,
            metadata={**flow.metadata, "source_flow_id": flow.flow_id},
        )

    def _specific_task_record_from_flow(self, flow: TaskFlowDefinition) -> SpecificTaskRecord:
        assignment = self._assignment_from_flow(flow)
        return _specific_task_record_from_assignment(assignment)

    def _assignment_from_specific_task_record(
        self,
        record: SpecificTaskRecord,
        *,
        flow: TaskFlowDefinition | None = None,
        projection_binding: TaskProjectionBinding | None = None,
    ) -> TaskAssignment:
        flow_id = str(record.default_flow_contract_id or f"flow.{record.task_id.removeprefix('task.')}").strip()
        task_policy = dict(record.task_policy or {})
        task_structure = dict(task_policy.get("task_structure") or {})
        safety_policy = dict(task_policy.get("safety_policy") or {})
        flow = flow if flow is not None else self.get_flow(flow_id)
        default_agent_id = str(getattr(flow, "default_agent_id", "") or "agent:0").strip() or "agent:0"
        flow_metadata = dict(getattr(flow, "metadata", {}) or {})
        task_structure = {
            **task_structure,
            **(
                {
                    "task_graph_id": str(flow_metadata.get("task_graph_id") or flow_metadata.get("graph_id") or "").strip(),
                    "communication_protocol_id": str(flow_metadata.get("communication_protocol_id") or "").strip(),
                    "topology_template_id": str(flow_metadata.get("topology_template_id") or "").strip(),
                    "agent_group_id": str(flow_metadata.get("agent_group_id") or "").strip(),
                }
                if flow is not None
                else {}
            ),
        }
        projection_id = ""
        projection_binding = projection_binding if projection_binding is not None else self.get_projection_binding(record.task_id)
        if projection_binding is not None:
            projection_id = str(projection_binding.default_projection_id or "").strip()
        workflow_file_ref = f"workflow:{record.default_workflow_id}" if record.default_workflow_id else ""
        return TaskAssignment(
            task_id=record.task_id,
            task_title=record.task_title,
            task_kind="specific_task",
            flow_id=flow_id,
            domain_id=record.domain_id,
            runtime_lane=record.runtime_lane or str(task_structure.get("runtime_lane_hint") or getattr(flow, "default_runtime_lane", "") or ""),
            default_agent_id=default_agent_id,
            participant_agent_ids=(),
            workflow_id=record.default_workflow_id,
            workflow_file_ref=workflow_file_ref,
            projection_id=projection_id,
            input_contract_id=record.input_contract_id,
            output_contract_id=record.output_contract_id,
            safety_policy=safety_policy,
            task_structure=task_structure,
            enabled=record.enabled,
            metadata=dict(record.metadata or {}),
        )

    def list_bindings(self) -> list[TaskAgentBinding]:
        return [self.build_binding_for_flow(flow) for flow in self.list_flows()]

    def list_projection_bindings(self) -> list[TaskProjectionBinding]:
        def load() -> list[TaskProjectionBinding]:
            default_bindings = [
                *[
                    binding.to_dict()
                    for item in self.list_general_task_profiles()
                    for binding in (_default_projection_binding(_synthetic_task_from_general_profile(item)),)
                    if binding.binding_id
                ],
                *[
                    binding.to_dict()
                    for item in self.list_specific_task_records()
                    for binding in (_default_projection_binding_from_specific_record(item),)
                    if binding is not None
                ],
            ]
            payload = _read_json(
                _projection_bindings_path(self.base_dir),
                {"projection_bindings": default_bindings},
            )
            merged_payload = _merge_items_by_key(
                default_bindings,
                [
                    item
                    for item in list(payload.get("projection_bindings") or [])
                    if isinstance(item, dict) and not _is_removed_health_task_config(item)
                ],
                key="binding_id",
            )
            bindings: list[TaskProjectionBinding] = []
            for item in merged_payload:
                bindings.append(
                    TaskProjectionBinding(
                        binding_id=str(item.get("binding_id") or ""),
                        task_id=str(item.get("task_id") or ""),
                        projection_selection_mode=str(item.get("projection_selection_mode") or "task_default"),
                        allowed_projection_ids=tuple(
                            str(value).strip()
                            for value in list(item.get("allowed_projection_ids") or [])
                            if str(value).strip()
                        ),
                        default_projection_id=str(item.get("default_projection_id") or ""),
                        projection_required=bool(item.get("projection_required", False)),
                        notes=str(item.get("notes") or ""),
                        metadata=dict(item.get("metadata") or {}),
                    )
                )
            normalized = [item.to_dict() for item in bindings]
            if payload.get("projection_bindings") != normalized:
                _write_json(_projection_bindings_path(self.base_dir), {"projection_bindings": normalized})
            return bindings

        return self._get_cached("projection_bindings", load)

    def list_explicit_projection_bindings(self) -> list[TaskProjectionBinding]:
        payload = _read_json(_projection_bindings_path(self.base_dir), {"projection_bindings": []})
        bindings: list[TaskProjectionBinding] = []
        for item in list(payload.get("projection_bindings") or []):
            if not isinstance(item, dict):
                continue
            bindings.append(
                TaskProjectionBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    projection_selection_mode=str(item.get("projection_selection_mode") or "task_default"),
                    allowed_projection_ids=tuple(
                        str(value).strip()
                        for value in list(item.get("allowed_projection_ids") or [])
                        if str(value).strip()
                    ),
                    default_projection_id=str(item.get("default_projection_id") or ""),
                    projection_required=bool(item.get("projection_required", False)),
                    notes=str(item.get("notes") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return bindings

    def get_projection_binding(self, task_id: str) -> TaskProjectionBinding | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_projection_bindings() if item.task_id == target), None)

    def upsert_projection_binding(
        self,
        *,
        task_id: str,
        projection_selection_mode: str = "task_default",
        allowed_projection_ids: tuple[str, ...] = (),
        default_projection_id: str = "",
        projection_required: bool = False,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskProjectionBinding:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        binding = TaskProjectionBinding(
            binding_id=f"taskprojbind:{target}",
            task_id=target,
            projection_selection_mode=str(projection_selection_mode or "task_default").strip(),
            allowed_projection_ids=tuple(
                str(value).strip()
                for value in allowed_projection_ids
                if str(value).strip()
            ),
            default_projection_id=str(default_projection_id or "").strip(),
            projection_required=bool(projection_required),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        bindings = [item for item in self.list_projection_bindings() if item.task_id != target]
        bindings.append(binding)
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in bindings]},
        )
        self._invalidate_cache()
        return binding

    def delete_projection_binding(self, task_id: str) -> TaskProjectionBinding | None:
        target = str(task_id or "").strip()
        if not target:
            return None
        existing = self.list_projection_bindings()
        deleted = next((item for item in existing if item.task_id == target), None)
        if deleted is None:
            return None
        _write_json(
            _projection_bindings_path(self.base_dir),
            {"projection_bindings": [item.to_dict() for item in existing if item.task_id != target]},
        )
        self._invalidate_cache()
        return deleted

    def list_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        default_bindings = [
            *[_default_flow_contract_binding(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_flow_contract_binding_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": default_bindings},
        )
        merged_payload = _merge_items_by_key(
            default_bindings,
            [
                item
                for item in list(payload.get("flow_contract_bindings") or [])
                if isinstance(item, dict) and not _is_removed_health_task_config(item)
            ],
            key="binding_id",
        )
        bindings: list[TaskFlowContractBinding] = []
        for item in merged_payload:
            bindings.append(
                TaskFlowContractBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    flow_contract_id=str(item.get("flow_contract_id") or ""),
                    override_policy=str(item.get("override_policy") or "task_default"),
                    verification_gate_profile=str(item.get("verification_gate_profile") or ""),
                    fallback_policy=str(item.get("fallback_policy") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in bindings]
        if payload.get("flow_contract_bindings") != normalized:
            _write_json(_flow_contract_bindings_path(self.base_dir), {"flow_contract_bindings": normalized})
        return bindings

    def list_explicit_flow_contract_bindings(self) -> list[TaskFlowContractBinding]:
        payload = _read_json(_flow_contract_bindings_path(self.base_dir), {"flow_contract_bindings": []})
        bindings: list[TaskFlowContractBinding] = []
        for item in list(payload.get("flow_contract_bindings") or []):
            if not isinstance(item, dict):
                continue
            bindings.append(
                TaskFlowContractBinding(
                    binding_id=str(item.get("binding_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    flow_contract_id=str(item.get("flow_contract_id") or ""),
                    override_policy=str(item.get("override_policy") or "task_default"),
                    verification_gate_profile=str(item.get("verification_gate_profile") or ""),
                    fallback_policy=str(item.get("fallback_policy") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return bindings

    def get_flow_contract_binding(self, task_id: str) -> TaskFlowContractBinding | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_flow_contract_bindings() if item.task_id == target), None)

    def upsert_flow_contract_binding(
        self,
        *,
        task_id: str,
        flow_contract_id: str,
        override_policy: str = "task_default",
        verification_gate_profile: str = "",
        fallback_policy: str = "fail_closed",
        metadata: dict[str, Any] | None = None,
    ) -> TaskFlowContractBinding:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        binding = TaskFlowContractBinding(
            binding_id=f"taskflowbind:{target}",
            task_id=target,
            flow_contract_id=str(flow_contract_id or "").strip(),
            override_policy=str(override_policy or "task_default").strip(),
            verification_gate_profile=str(verification_gate_profile or "").strip(),
            fallback_policy=str(fallback_policy or "fail_closed").strip(),
            metadata=dict(metadata or {}),
        )
        bindings = [item for item in self.list_flow_contract_bindings() if item.task_id != target]
        bindings.append(binding)
        _write_json(
            _flow_contract_bindings_path(self.base_dir),
            {"flow_contract_bindings": [item.to_dict() for item in bindings]},
        )
        self._invalidate_cache()
        return binding

    def list_task_agent_adoption_plans(self) -> list[TaskAgentAdoptionPlan]:
        def load() -> list[TaskAgentAdoptionPlan]:
            default_tasks = [
                *[_synthetic_task_from_general_profile(item) for item in self.list_general_task_profiles()],
                *self.list_task_assignments(),
            ]
            payload = _read_json(
                _adoption_plans_path(self.base_dir),
                {"adoption_plans": [_default_adoption_plan(item).to_dict() for item in default_tasks]},
            )
            default_plans = [_default_adoption_plan(item).to_dict() for item in default_tasks]
            merged_payload = _merge_default_overlay_by_key(
                default_plans,
                [
                    item
                    for item in list(payload.get("adoption_plans") or [])
                    if isinstance(item, dict) and not _is_removed_health_task_config(item)
                ],
                key="plan_id",
            )
            plans: list[TaskAgentAdoptionPlan] = []
            for item in merged_payload:
                plans.append(
                    TaskAgentAdoptionPlan(
                        plan_id=str(item.get("plan_id") or ""),
                        task_id=str(item.get("task_id") or ""),
                        adoption_mode=normalize_task_agent_adoption_mode(str(item.get("adoption_mode") or "adopt_existing")),
                        default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "agent:0")),
                        allow_worker_agent_spawn=bool(item.get("allow_worker_agent_spawn", False)),
                        worker_agent_blueprint_id=str(item.get("worker_agent_blueprint_id") or ""),
                        worker_agent_naming_rule=str(item.get("worker_agent_naming_rule") or ""),
                        notes=str(item.get("notes") or ""),
                        metadata=dict(item.get("metadata") or {}),
                    )
                )
            normalized = [item.to_dict() for item in plans]
            if payload.get("adoption_plans") != normalized:
                _write_json(_adoption_plans_path(self.base_dir), {"adoption_plans": normalized})
            return plans

        return self._get_cached("task_agent_adoption_plans", load)

    def list_explicit_task_agent_adoption_plans(self) -> list[TaskAgentAdoptionPlan]:
        payload = _read_json(_adoption_plans_path(self.base_dir), {"adoption_plans": []})
        plans: list[TaskAgentAdoptionPlan] = []
        for item in list(payload.get("adoption_plans") or []):
            if not isinstance(item, dict):
                continue
            plans.append(
                TaskAgentAdoptionPlan(
                    plan_id=str(item.get("plan_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    adoption_mode=normalize_task_agent_adoption_mode(str(item.get("adoption_mode") or "adopt_existing")),
                    default_agent_id=normalize_agent_id(str(item.get("default_agent_id") or "agent:0")),
                    allow_worker_agent_spawn=bool(item.get("allow_worker_agent_spawn", False)),
                    worker_agent_blueprint_id=str(item.get("worker_agent_blueprint_id") or ""),
                    worker_agent_naming_rule=str(item.get("worker_agent_naming_rule") or ""),
                    notes=str(item.get("notes") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return plans

    def get_task_agent_adoption_plan(self, task_id: str) -> TaskAgentAdoptionPlan | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_agent_adoption_plans() if item.task_id == target), None)

    def upsert_task_agent_adoption_plan(
        self,
        *,
        task_id: str,
        adoption_mode: str,
        default_agent_id: str = "agent:0",
        allow_worker_agent_spawn: bool = False,
        worker_agent_blueprint_id: str = "",
        worker_agent_naming_rule: str = "",
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskAgentAdoptionPlan:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        plan = TaskAgentAdoptionPlan(
            plan_id=f"taskadopt:{target}",
            task_id=target,
            adoption_mode=normalize_task_agent_adoption_mode(adoption_mode),
            default_agent_id=normalize_agent_id(str(default_agent_id or "agent:0").strip() or "agent:0"),
            allow_worker_agent_spawn=bool(allow_worker_agent_spawn),
            worker_agent_blueprint_id=str(worker_agent_blueprint_id or "").strip(),
            worker_agent_naming_rule=str(worker_agent_naming_rule or "").strip(),
            notes=str(notes or "").strip(),
            metadata=dict(metadata or {}),
        )
        plans = [item for item in self.list_task_agent_adoption_plans() if item.task_id != target]
        plans.append(plan)
        _write_json(
            _adoption_plans_path(self.base_dir),
            {"adoption_plans": [item.to_dict() for item in plans]},
        )
        self._invalidate_cache()
        return plan

    def _collect_deletable_workflow_ids(
        self,
        *,
        task_ids: set[str],
        flow_ids: set[str],
    ) -> set[str]:
        candidates = {
            str(item.default_workflow_id or "").strip()
            for item in self.list_specific_task_records()
            if item.task_id in task_ids
        }
        candidates.update(
            str(item.workflow_id or "").strip()
            for item in self.list_task_assignments()
            if item.task_id in task_ids
        )
        candidates.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_flows()
            if item.flow_id in flow_ids or str(item.metadata.get("task_id") or "") in task_ids
        )
        candidates = {item for item in candidates if item}
        if not candidates:
            return set()

        remaining_task_ids = {
            item.task_id
            for item in self.list_specific_task_records()
            if item.task_id not in task_ids
        }
        referenced_after_delete: set[str] = set()
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_general_task_profiles()
            if str(item.default_workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_specific_task_records()
            if item.task_id in remaining_task_ids and str(item.default_workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.workflow_id or "").strip()
            for item in self.list_task_assignments()
            if item.task_id in remaining_task_ids and str(item.workflow_id or "").strip()
        )
        referenced_after_delete.update(
            str(item.default_workflow_id or "").strip()
            for item in self.list_flows()
            if item.flow_id not in flow_ids
            and str(item.metadata.get("task_id") or "") not in task_ids
            and str(item.default_workflow_id or "").strip()
        )
        return {
            item
            for item in candidates
            if item not in referenced_after_delete
        }

    def list_task_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        default_profiles = [
            *[_default_memory_request_profile(_synthetic_task_from_general_profile(item)).to_dict() for item in self.list_general_task_profiles()],
            *[_default_memory_request_profile_from_specific_record(item).to_dict() for item in self.list_specific_task_records()],
        ]
        payload = _read_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": default_profiles},
        )
        merged_payload = _merge_items_by_key(
            default_profiles,
            [
                item
                for item in list(payload.get("memory_request_profiles") or [])
                if isinstance(item, dict) and not _is_removed_health_task_config(item)
            ],
            key="profile_id",
        )
        profiles: list[TaskMemoryRequestProfile] = []
        for item in merged_payload:
            profiles.append(
                TaskMemoryRequestProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    requested_memory_layers=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_memory_layers") or [])
                        if str(value).strip()
                    ),
                    requested_topics=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_topics") or [])
                        if str(value).strip()
                    ),
                    memory_priority=str(item.get("memory_priority") or "normal"),
                    writeback_policy=str(item.get("writeback_policy") or "task_default"),
                    allow_long_term_memory=bool(item.get("allow_long_term_memory", False)),
                    memory_scope_hint=str(item.get("memory_scope_hint") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in profiles]
        if payload.get("memory_request_profiles") != normalized:
            _write_json(_memory_request_profiles_path(self.base_dir), {"memory_request_profiles": normalized})
        return profiles

    def list_explicit_task_memory_request_profiles(self) -> list[TaskMemoryRequestProfile]:
        payload = _read_json(_memory_request_profiles_path(self.base_dir), {"memory_request_profiles": []})
        profiles: list[TaskMemoryRequestProfile] = []
        for item in list(payload.get("memory_request_profiles") or []):
            if not isinstance(item, dict):
                continue
            profiles.append(
                TaskMemoryRequestProfile(
                    profile_id=str(item.get("profile_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    requested_memory_layers=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_memory_layers") or [])
                        if str(value).strip()
                    ),
                    requested_topics=tuple(
                        str(value).strip()
                        for value in list(item.get("requested_topics") or [])
                        if str(value).strip()
                    ),
                    memory_priority=str(item.get("memory_priority") or "normal"),
                    writeback_policy=str(item.get("writeback_policy") or "task_default"),
                    allow_long_term_memory=bool(item.get("allow_long_term_memory", False)),
                    memory_scope_hint=str(item.get("memory_scope_hint") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return profiles

    def get_task_memory_request_profile(self, task_id: str) -> TaskMemoryRequestProfile | None:
        target = str(task_id or "").strip()
        return next((item for item in self.list_task_memory_request_profiles() if item.task_id == target), None)

    def upsert_task_memory_request_profile(
        self,
        *,
        task_id: str,
        requested_memory_layers: tuple[str, ...] = (),
        requested_topics: tuple[str, ...] = (),
        memory_priority: str = "normal",
        writeback_policy: str = "task_default",
        allow_long_term_memory: bool = False,
        memory_scope_hint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TaskMemoryRequestProfile:
        target = str(task_id or "").strip()
        if not target.startswith(("task.", "general.")):
            raise ValueError("task_id must start with task. or general.")
        profile = TaskMemoryRequestProfile(
            profile_id=f"taskmem:{target}",
            task_id=target,
            requested_memory_layers=tuple(
                str(value).strip()
                for value in requested_memory_layers
                if str(value).strip()
            ),
            requested_topics=tuple(
                str(value).strip()
                for value in requested_topics
                if str(value).strip()
            ),
            memory_priority=str(memory_priority or "normal").strip(),
            writeback_policy=str(writeback_policy or "task_default").strip(),
            allow_long_term_memory=bool(allow_long_term_memory),
            memory_scope_hint=str(memory_scope_hint or "").strip(),
            metadata=dict(metadata or {}),
        )
        profiles = [item for item in self.list_task_memory_request_profiles() if item.task_id != target]
        profiles.append(profile)
        _write_json(
            _memory_request_profiles_path(self.base_dir),
            {"memory_request_profiles": [item.to_dict() for item in profiles]},
        )
        self._invalidate_cache()
        return profile

    def derive_coordination_task_view_from_graph(self, graph: TaskGraphDefinition) -> CoordinationTaskDefinition:
        metadata = dict(graph.metadata or {})
        runtime_policy = dict(graph.runtime_policy or {})
        continuation_policy = {
            **dict(metadata.get("continuation_policy") or {}),
        }
        human_gate_mode = str(runtime_policy.get("human_gate_mode") or "").strip()
        if human_gate_mode and "human_gate_mode" not in continuation_policy:
            continuation_policy["human_gate_mode"] = human_gate_mode
        if continuation_policy:
            metadata["continuation_policy"] = continuation_policy
        coordinator_agent_id = normalize_agent_id(str(runtime_policy.get("coordinator_agent_id") or "agent:0").strip() or "agent:0")
        domain_id = str(graph.domain_id or metadata.get("domain_id") or "").strip()
        stored_nodes = tuple(node.to_dict() for node in graph.nodes)
        metadata_task_id = str(metadata.get("task_id") or "").strip()
        raw_subtask_refs = [
            *[str(value).strip() for value in list(metadata.get("subtask_refs") or []) if str(value).strip()],
            *_subtask_refs_from_graph_nodes(stored_nodes),
            *([metadata_task_id] if metadata_task_id.startswith("task.") else []),
        ]
        subtask_refs = tuple(dict.fromkeys(value for value in raw_subtask_refs if value.startswith("task.")))
        participant_agent_ids = self._resolve_coordination_participants(
            coordinator_agent_id=coordinator_agent_id,
            agent_group_id=str(runtime_policy.get("agent_group_id") or metadata.get("agent_group_id") or ""),
            participant_agent_ids=normalize_agent_id_sequence(
                str(value)
                for value in list(runtime_policy.get("participant_agent_ids") or metadata.get("participant_agent_ids") or [])
                if str(value)
            ),
        )
        fallback_nodes, fallback_edges = _default_coordination_graph(
            coordinator_agent_id=coordinator_agent_id,
            participant_agent_ids=participant_agent_ids,
            subtask_refs=subtask_refs,
        )
        runtime_nodes, runtime_edges = _runtime_graph_view_nodes_and_edges(graph)
        graph_nodes = runtime_nodes or stored_nodes or fallback_nodes
        graph_edges = runtime_edges or tuple(edge.to_dict() for edge in graph.edges) or fallback_edges
        subtask_refs = tuple(dict.fromkeys([*subtask_refs, *_subtask_refs_from_graph_nodes(graph_nodes)]))
        communication_modes = tuple(
            str(value).strip()
            for value in list(metadata.get("business_communication_modes") or metadata.get("communication_modes") or [])
            if str(value).strip()
        ) or tuple(
            dict(edge).get("mode", "")
            for edge in graph_edges
            if str(dict(edge).get("mode", "")).strip()
        )
        derived_metadata = {
            **metadata,
            "graph_id": graph.graph_id,
            "task_graph_id": graph.graph_id,
        }
        return CoordinationTaskDefinition(
            graph_id=graph.graph_id,
            title=str(graph.title or ""),
            coordination_mode=str(runtime_policy.get("coordination_mode") or metadata.get("coordination_mode") or "review_merge"),
            coordinator_agent_id=coordinator_agent_id,
            domain_id=domain_id,
            agent_group_id=str(runtime_policy.get("agent_group_id") or metadata.get("agent_group_id") or ""),
            participant_agent_ids=participant_agent_ids,
            topology_template_id=str(metadata.get("topology_template_id") or ""),
            shared_context_policy=str(dict(graph.context_policy or {}).get("shared_context_policy") or "explicit_refs_only"),
            memory_sharing_policy=str(dict(graph.context_policy or {}).get("memory_sharing_policy") or "isolated_by_default"),
            handoff_policy=str(metadata.get("handoff_policy") or "filtered_handoff"),
            conflict_resolution_policy=str(metadata.get("conflict_resolution_policy") or "coordinator_review"),
            output_merge_policy=str(metadata.get("output_merge_policy") or "coordinator_final_merge"),
            stop_conditions=tuple(str(value) for value in list(metadata.get("stop_conditions") or []) if str(value)),
            subtask_refs=subtask_refs,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            communication_modes=tuple(dict.fromkeys(str(value).strip() for value in communication_modes if str(value).strip())),
            enabled=bool(graph.enabled),
            metadata=derived_metadata,
        )

    def list_task_graphs(self) -> list[TaskGraphDefinition]:
        payload = _read_json(_task_graphs_path(self.base_dir), {"task_graphs": []})
        graphs = [
            task_graph_from_dict(item)
            for item in list(payload.get("task_graphs") or [])
            if isinstance(item, dict)
        ]
        graphs = sorted(
            [item for item in graphs if item.graph_id],
            key=lambda item: (item.domain_id, item.title, item.graph_id),
        )
        normalized = [item.to_dict() for item in graphs]
        if payload.get("task_graphs") != normalized:
            _write_json(_task_graphs_path(self.base_dir), {"task_graphs": normalized})
        return graphs

    def get_task_graph(self, graph_id: str) -> TaskGraphDefinition | None:
        target = str(graph_id or "").strip()
        return next((item for item in self.list_task_graphs() if item.graph_id == target), None)

    def next_task_graph_id(self) -> str:
        return _next_prefixed_id(
            [item.graph_id for item in self.list_task_graphs()],
            prefix="graph.",
        )

    def upsert_task_graph(
        self,
        *,
        graph_id: str,
        title: str,
        domain_id: str = "",
        graph_kind: str = "single_agent",
        entry_node_id: str = "",
        output_node_id: str = "",
        nodes: tuple[dict[str, Any], ...] = (),
        edges: tuple[dict[str, Any], ...] = (),
        graph_contract_id: str = "",
        contract_bindings: dict[str, Any] | None = None,
        default_protocol_id: str = "",
        working_memory_policy_profile_id: str = "",
        working_memory_policy: dict[str, Any] | None = None,
        runtime_policy: dict[str, Any] | None = None,
        context_policy: dict[str, Any] | None = None,
        publish_state: str = "draft",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskGraphDefinition:
        target = str(graph_id or "").strip()
        if not target.startswith("graph."):
            raise ValueError("graph_id must start with graph.")
        graph = task_graph_from_dict(
            {
                "graph_id": target,
                "title": title,
                "domain_id": domain_id,
                "graph_kind": graph_kind,
                "entry_node_id": entry_node_id,
                "output_node_id": output_node_id,
                "nodes": [dict(item) for item in nodes],
                "edges": [dict(item) for item in edges],
                "graph_contract_id": graph_contract_id,
                "contract_bindings": dict(contract_bindings or {}),
                "default_protocol_id": default_protocol_id,
                "working_memory_policy_profile_id": working_memory_policy_profile_id,
                "working_memory_policy": dict(working_memory_policy or {}),
                "runtime_policy": dict(runtime_policy or {}),
                "context_policy": dict(context_policy or {}),
                "publish_state": publish_state,
                "enabled": enabled,
                "metadata": dict(metadata or {}),
            }
        )
        graphs = [item for item in self.list_task_graphs() if item.graph_id != target]
        graphs.append(graph)
        _write_json(_task_graphs_path(self.base_dir), {"task_graphs": [item.to_dict() for item in graphs]})
        self._invalidate_cache()
        return graph

    def get_topology_template(self, template_id: str) -> TopologyTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in self.list_topology_templates() if item.template_id == target), None)

    def list_topology_templates(self) -> list[TopologyTemplate]:
        default_payload = [item.to_dict() for item in default_topology_templates()]
        payload = _read_json(
            _topology_templates_path(self.base_dir),
            {"topology_templates": default_payload},
        )
        merged_payload = _merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("topology_templates") or []) if isinstance(item, dict)],
            key="template_id",
        )
        templates: list[TopologyTemplate] = []
        for item in merged_payload:
            templates.append(
                TopologyTemplate(
                    template_id=str(item.get("template_id") or ""),
                    title=str(item.get("title") or ""),
                    nodes=tuple(_normalize_agent_refs_in_mapping(dict(value)) for value in list(item.get("nodes") or []) if isinstance(value, dict)),
                    edges=tuple(dict(value) for value in list(item.get("edges") or []) if isinstance(value, dict)),
                    handoff_rules=tuple(dict(value) for value in list(item.get("handoff_rules") or []) if isinstance(value, dict)),
                    join_policy=str(item.get("join_policy") or "explicit_join"),
                    failure_policy=str(item.get("failure_policy") or "fail_closed"),
                    terminal_policy=str(item.get("terminal_policy") or "coordinator_terminal"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in templates]
        if payload.get("topology_templates") != normalized:
            _write_json(_topology_templates_path(self.base_dir), {"topology_templates": normalized})
        return templates

    def next_topology_template_id(self) -> str:
        return _next_prefixed_id(
            [item.template_id for item in self.list_topology_templates()],
            prefix="topology.",
        )

    def list_task_communication_protocols(self) -> list[TaskCommunicationProtocol]:
        default_payload = [item.to_dict() for item in default_task_communication_protocols()]
        payload = _read_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": default_payload},
        )
        merged_payload = _merge_authoritative_defaults_by_key(
            default_payload,
            [item for item in list(payload.get("communication_protocols") or []) if isinstance(item, dict)],
            key="protocol_id",
        )
        protocols: list[TaskCommunicationProtocol] = []
        for item in merged_payload:
            protocols.append(
                TaskCommunicationProtocol(
                    protocol_id=str(item.get("protocol_id") or ""),
                    title=str(item.get("title") or ""),
                    message_types=tuple(str(value).strip() for value in list(item.get("message_types") or []) if str(value).strip()),
                    payload_contracts=tuple(str(value).strip() for value in list(item.get("payload_contracts") or []) if str(value).strip()),
                    signal_rules=tuple(str(value).strip() for value in list(item.get("signal_rules") or []) if str(value).strip()),
                    handoff_rules=tuple(str(value).strip() for value in list(item.get("handoff_rules") or []) if str(value).strip()),
                    ack_policy=str(item.get("ack_policy") or "explicit_ack"),
                    timeout_policy=str(item.get("timeout_policy") or "fail_closed"),
                    error_signal_policy=str(item.get("error_signal_policy") or "raise_to_coordinator"),
                    enabled=bool(item.get("enabled", False)),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        normalized = [item.to_dict() for item in protocols]
        if payload.get("communication_protocols") != normalized:
            _write_json(_communication_protocols_path(self.base_dir), {"communication_protocols": normalized})
        return protocols

    def list_contract_descriptors(self) -> list[TaskContractDescriptor]:
        collected: dict[tuple[str, str], dict[str, Any]] = {}

        def append_contract(
            contract_id: str,
            kind: str,
            *,
            source_ref: str = "",
            usage_ref: str = "",
            title: str = "",
            summary: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> None:
            normalized_id = str(contract_id or "").strip()
            if not normalized_id:
                return
            normalized_kind = str(kind or "").strip() or "unknown"
            key = (normalized_id, normalized_kind)
            current = collected.setdefault(
                key,
                {
                    "contract_id": normalized_id,
                    "title": str(title or CONTRACT_TITLE_MAP.get(normalized_id) or normalized_id).strip(),
                    "contract_kind": normalized_kind,
                    "summary": str(summary or CONTRACT_KIND_LABELS.get(normalized_kind) or "").strip(),
                    "source_refs": [],
                    "usage_refs": [],
                    "metadata": {},
                },
            )
            if source_ref:
                current["source_refs"].append(source_ref)
            if usage_ref:
                current["usage_refs"].append(usage_ref)
            current["metadata"] = {**dict(current.get("metadata") or {}), **dict(metadata or {})}

        for profile in self.list_general_task_profiles():
            append_contract(profile.input_contract_id, "input", source_ref=profile.profile_id, usage_ref=profile.title)
            append_contract(profile.output_contract_id, "output", source_ref=profile.profile_id, usage_ref=profile.title)

        for flow in self.list_flows():
            append_contract(flow.input_contract_id, "input", source_ref=flow.flow_id, usage_ref=flow.title)
            append_contract(flow.output_contract_id, "output", source_ref=flow.flow_id, usage_ref=flow.title)
            append_contract(
                flow.flow_id,
                "flow",
                source_ref=flow.flow_id,
                usage_ref=flow.title,
                title=flow.title,
                summary=f"{CONTRACT_TITLE_MAP.get(flow.input_contract_id, flow.input_contract_id)} -> {CONTRACT_TITLE_MAP.get(flow.output_contract_id, flow.output_contract_id)}",
                metadata={
                    "default_workflow_id": flow.default_workflow_id,
                    "default_runtime_lane": flow.default_runtime_lane,
                },
            )

        for record in self.list_specific_task_records():
            append_contract(record.input_contract_id, "input", source_ref=record.task_id, usage_ref=record.task_title)
            append_contract(record.output_contract_id, "output", source_ref=record.task_id, usage_ref=record.task_title)
            append_contract(record.default_flow_contract_id, "flow", source_ref=record.task_id, usage_ref=record.task_title)

        for protocol in self.list_task_communication_protocols():
            for contract_id in protocol.payload_contracts:
                append_contract(contract_id, "payload", source_ref=protocol.protocol_id, usage_ref=protocol.title)

        descriptors = []
        for item in collected.values():
            descriptors.append(
                TaskContractDescriptor(
                    contract_id=str(item["contract_id"]),
                    title=str(item["title"]),
                    contract_kind=str(item["contract_kind"]),
                    summary=str(item.get("summary") or ""),
                    source_refs=tuple(dict.fromkeys(str(ref) for ref in list(item.get("source_refs") or []) if str(ref))),
                    usage_refs=tuple(dict.fromkeys(str(ref) for ref in list(item.get("usage_refs") or []) if str(ref))),
                    editable=False,
                    status="derived",
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return sorted(descriptors, key=lambda item: (item.contract_kind, item.title, item.contract_id))

    def get_task_communication_protocol(self, protocol_id: str) -> TaskCommunicationProtocol | None:
        target = str(protocol_id or "").strip()
        return next((item for item in self.list_task_communication_protocols() if item.protocol_id == target), None)

    def upsert_task_communication_protocol(
        self,
        *,
        protocol_id: str,
        title: str,
        message_types: tuple[str, ...] = (),
        payload_contracts: tuple[str, ...] = (),
        signal_rules: tuple[str, ...] = (),
        handoff_rules: tuple[str, ...] = (),
        ack_policy: str = "explicit_ack",
        timeout_policy: str = "fail_closed",
        error_signal_policy: str = "raise_to_coordinator",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskCommunicationProtocol:
        target = str(protocol_id or "").strip()
        if not target.startswith("protocol."):
            raise ValueError("protocol_id must start with protocol.")
        protocol = TaskCommunicationProtocol(
            protocol_id=target,
            title=str(title or target).strip(),
            message_types=tuple(
                str(value).strip()
                for value in message_types
                if str(value).strip()
            ),
            payload_contracts=tuple(
                str(value).strip()
                for value in payload_contracts
                if str(value).strip()
            ),
            signal_rules=tuple(
                str(value).strip()
                for value in signal_rules
                if str(value).strip()
            ),
            handoff_rules=tuple(
                str(value).strip()
                for value in handoff_rules
                if str(value).strip()
            ),
            ack_policy=str(ack_policy or "explicit_ack").strip(),
            timeout_policy=str(timeout_policy or "fail_closed").strip(),
            error_signal_policy=str(error_signal_policy or "raise_to_coordinator").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        protocols = [item for item in self.list_task_communication_protocols() if item.protocol_id != target]
        protocols.append(protocol)
        _write_json(
            _communication_protocols_path(self.base_dir),
            {"communication_protocols": [item.to_dict() for item in protocols]},
        )
        return protocol

    def upsert_graph_task(
        self,
        *,
        graph_id: str,
        title: str,
        coordination_mode: str,
        coordinator_agent_id: str,
        domain_id: str = "",
        agent_group_id: str = "",
        participant_agent_ids: tuple[str, ...] = (),
        topology_template_id: str = "",
        shared_context_policy: str = "explicit_refs_only",
        memory_sharing_policy: str = "isolated_by_default",
        handoff_policy: str = "filtered_handoff",
        conflict_resolution_policy: str = "coordinator_review",
        output_merge_policy: str = "coordinator_final_merge",
        stop_conditions: tuple[str, ...] = (),
        subtask_refs: tuple[str, ...] = (),
        graph_nodes: tuple[dict[str, Any], ...] = (),
        graph_edges: tuple[dict[str, Any], ...] = (),
        communication_modes: tuple[str, ...] = (),
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TaskGraphDefinition:
        target = str(graph_id or "").strip()
        if not target.startswith("graph."):
            raise ValueError("graph_id must start with graph.")
        normalized_domain_id = str(domain_id or "").strip()
        normalized_subtask_refs = tuple(
            dict.fromkeys(str(item).strip() for item in subtask_refs if str(item).strip().startswith("task."))
        )
        normalized_graph_nodes = tuple(dict(item) for item in graph_nodes if isinstance(item, dict))
        normalized_graph_edges = tuple(dict(item) for item in graph_edges if isinstance(item, dict))
        topology_ref = str(topology_template_id or "").strip()
        topology_template = self.get_topology_template(topology_ref) if topology_ref else None
        if topology_template is not None:
            if not normalized_graph_nodes and topology_template.nodes:
                normalized_graph_nodes = tuple(dict(item) for item in topology_template.nodes)
            if not normalized_graph_edges and topology_template.edges:
                normalized_graph_edges = tuple(dict(item) for item in topology_template.edges)
        if normalized_graph_nodes:
            normalized_subtask_refs = tuple(
                dict.fromkeys([*normalized_subtask_refs, *_subtask_refs_from_graph_nodes(normalized_graph_nodes)])
            )
        else:
            normalized_graph_nodes, default_edges = _default_coordination_graph(
                coordinator_agent_id=normalize_agent_id(str(coordinator_agent_id or "agent:0").strip() or "agent:0"),
                participant_agent_ids=normalize_agent_id_sequence(str(item).strip() for item in participant_agent_ids if str(item).strip()),
                subtask_refs=normalized_subtask_refs,
            )
            if not normalized_graph_edges:
                normalized_graph_edges = default_edges
        graph = self.upsert_task_graph(
            graph_id=target,
            title=str(title or target).strip(),
            domain_id=normalized_domain_id,
            graph_kind="coordination",
            nodes=tuple(_normalize_agent_refs_in_mapping(dict(item)) for item in normalized_graph_nodes),
            edges=normalized_graph_edges,
            default_protocol_id=str(dict(metadata or {}).get("protocol_id") or ""),
            runtime_policy={
                "coordinator_agent_id": str(coordinator_agent_id or "agent:0").strip() or "agent:0",
                "agent_group_id": str(agent_group_id or "").strip(),
                "coordination_mode": str(coordination_mode or "review_merge").strip(),
                "participant_agent_ids": list(
                    self._resolve_coordination_participants(
                        coordinator_agent_id=normalize_agent_id(str(coordinator_agent_id or "agent:0").strip() or "agent:0"),
                        agent_group_id=str(agent_group_id or "").strip(),
                        participant_agent_ids=normalize_agent_id_sequence(str(item).strip() for item in participant_agent_ids if str(item).strip()),
                    )
                ),
            },
            context_policy={
                "shared_context_policy": str(shared_context_policy or "explicit_refs_only").strip(),
                "memory_sharing_policy": str(memory_sharing_policy or "isolated_by_default").strip(),
            },
            publish_state="published" if enabled else "draft",
            enabled=bool(enabled),
            metadata={
                **dict(metadata or {}),
                "graph_id": target,
                "domain_id": normalized_domain_id,
                "topology_template_id": topology_ref,
                "handoff_policy": str(handoff_policy or "filtered_handoff").strip(),
                "conflict_resolution_policy": str(conflict_resolution_policy or "coordinator_review").strip(),
                "output_merge_policy": str(output_merge_policy or "coordinator_final_merge").strip(),
                "stop_conditions": [str(item).strip() for item in stop_conditions if str(item).strip()],
                "subtask_refs": list(normalized_subtask_refs),
                "communication_modes": [str(item).strip() for item in communication_modes if str(item).strip()],
            },
        )
        return graph

    def _resolve_coordination_participants(
        self,
        *,
        coordinator_agent_id: str,
        agent_group_id: str,
        participant_agent_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        explicit = normalize_agent_id_sequence(str(item).strip() for item in participant_agent_ids if str(item).strip())
        if explicit:
            return explicit
        from agent_system.groups.registry import AgentGroupRegistry

        group = AgentGroupRegistry(self.base_dir).get_group(agent_group_id)
        if group is None:
            return ()
        coordinator = normalize_agent_id(str(coordinator_agent_id or group.coordinator_agent_id or "").strip())
        return tuple(
            normalize_agent_id(item)
            for item in group.member_agent_ids
            if item and normalize_agent_id(item) != coordinator
        )

    def upsert_topology_template(
        self,
        *,
        template_id: str,
        title: str,
        nodes: tuple[dict[str, Any], ...] = (),
        edges: tuple[dict[str, Any], ...] = (),
        handoff_rules: tuple[dict[str, Any], ...] = (),
        join_policy: str = "explicit_join",
        failure_policy: str = "fail_closed",
        terminal_policy: str = "coordinator_terminal",
        enabled: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> TopologyTemplate:
        target = str(template_id or "").strip()
        if not target.startswith("topology."):
            raise ValueError("template_id must start with topology.")
        template = TopologyTemplate(
            template_id=target,
            title=str(title or target).strip(),
            nodes=tuple(_normalize_agent_refs_in_mapping(dict(item)) for item in nodes if isinstance(item, dict)),
            edges=tuple(dict(item) for item in edges if isinstance(item, dict)),
            handoff_rules=tuple(dict(item) for item in handoff_rules if isinstance(item, dict)),
            join_policy=str(join_policy or "explicit_join").strip(),
            failure_policy=str(failure_policy or "fail_closed").strip(),
            terminal_policy=str(terminal_policy or "coordinator_terminal").strip(),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        templates = [item for item in self.list_topology_templates() if item.template_id != target]
        templates.append(template)
        _write_json(_topology_templates_path(self.base_dir), {"topology_templates": [item.to_dict() for item in templates]})
        return template

    def build_binding_for_flow(self, flow: TaskFlowDefinition) -> TaskAgentBinding:
        agent = self.agent_registry.get_agent(flow.default_agent_id)
        profile = self.agent_runtime_registry.get_profile(flow.default_agent_id)
        diagnostics: dict[str, Any] = {}
        failures: list[str] = []
        if agent is None:
            failures.append("agent_missing")
        elif agent.lifecycle_state not in {"enabled", "system_builtin"}:
            failures.append("agent_not_enabled")
        if profile is None:
            failures.append("runtime_profile_missing")
        else:
            _validate_contains(failures, diagnostics, "runtime_lane", flow.default_runtime_lane, profile.allowed_runtime_lanes)
            _validate_contains(failures, diagnostics, "memory_scope", flow.default_memory_scope, profile.allowed_memory_scopes)
        self._validate_workflow_ref(failures, diagnostics, flow.default_workflow_id)
        return TaskAgentBinding(
            binding_id=f"binding:{flow.flow_id}:{flow.default_agent_id}",
            task_id=str(flow.metadata.get("task_id") or flow.metadata.get("task_assignment_id") or f"task.{flow.flow_id.removeprefix('flow.')}"),
            flow_id=flow.flow_id,
            agent_id=flow.default_agent_id,
            agent_profile_id=profile.agent_profile_id if profile is not None else "",
            runtime_lane=flow.default_runtime_lane,
            workflow_id=flow.default_workflow_id,
            memory_scope=flow.default_memory_scope,
            output_contract_id=flow.output_contract_id,
            resource_policy_ref=f"resource-policy:{flow.flow_id}:candidate",
            validation_state="valid" if not failures else "invalid",
            diagnostics={**diagnostics, "failures": failures},
        )

    def build_link_permission_matrix(self) -> dict[str, Any]:
        bindings = self.list_bindings()
        return {
            "authority": "task_system.link_permission_matrix",
            "rows": [
                {
                    "agent_id": item.agent_id,
                    "agent_profile_id": item.agent_profile_id,
                    "task_ref": item.task_id,
                    "runtime_lane": item.runtime_lane,
                    "workflow": item.workflow_id,
                    "memory_scope": item.memory_scope,
                    "output_contract": item.output_contract_id,
                    "validation_state": item.validation_state,
                    "blocked_reasons": list(item.diagnostics.get("failures") or []),
                }
                for item in bindings
            ],
        }

    def list_agent_task_connection_profiles(
        self,
        *,
        owner_system: str = "",
    ) -> list[AgentTaskConnectionProfile]:
        flows = self.list_flows()
        bindings = self.list_bindings()
        topologies = self.list_topology_templates()
        profiles: list[AgentTaskConnectionProfile] = []
        for agent in self.agent_registry.list_agents():
            agent_bindings = [item for item in bindings if item.agent_id == agent.agent_id]
            agent_flows = [flow for flow in flows if any(binding.flow_id == flow.flow_id for binding in agent_bindings)]
            if owner_system and agent.owner_system != owner_system:
                continue
            capability = self.agent_runtime_registry.get_profile(agent.agent_id)
            topology_refs = tuple(
                template.template_id
                for template in topologies
                if any(dict(node).get("agent_id") == agent.agent_id for node in template.nodes)
            )
            blocked_reasons = tuple(
                dict.fromkeys(
                    reason
                    for binding in agent_bindings
                    for reason in list(binding.diagnostics.get("failures") or [])
                    if reason
                )
            )
            profile_validation_state = "valid" if agent_bindings and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            default_flow = agent_flows[0] if agent_flows else None
            default_binding = agent_bindings[0] if agent_bindings else None
            profiles.append(
                AgentTaskConnectionProfile(
                    profile_id=f"agent-task-connection:{agent.agent_id}",
                    agent_id=agent.agent_id,
                    agent_profile_id=capability.agent_profile_id if capability is not None else "",
                    owner_system=agent.owner_system,
                    profile_type=agent.profile_type,
                    lifecycle_state=agent.lifecycle_state,
                    task_refs=tuple(
                        dict.fromkeys(
                            str(flow.metadata.get("task_id") or flow.metadata.get("task_assignment_id") or f"task.{flow.flow_id.removeprefix('flow.')}")
                            for flow in agent_flows
                        )
                    ),
                    flow_refs=tuple(flow.flow_id for flow in agent_flows),
                    binding_refs=tuple(binding.binding_id for binding in agent_bindings),
                    workflow_refs=tuple(
                        dict.fromkeys(binding.workflow_id for binding in agent_bindings if binding.workflow_id)
                    ),
                    topology_refs=topology_refs,
                    default_flow_ref=default_flow.flow_id if default_flow is not None else "",
                    default_workflow_ref=default_binding.workflow_id if default_binding is not None else "",
                    default_runtime_lane_hint=default_binding.runtime_lane if default_binding is not None else "",
                    validation_state=profile_validation_state,
                    blocked_reasons=blocked_reasons,
                    diagnostics={
                        "agent": agent.to_dict(),
                        "runtime_profile_present": capability is not None,
                        "flow_count": len(agent_flows),
                        "binding_count": len(agent_bindings),
                        "topology_count": len(topology_refs),
                    },
                )
            )
        return profiles

    def build_agent_task_connection_overview(
        self,
        *,
        owner_system: str = "",
    ) -> dict[str, Any]:
        profiles = self.list_agent_task_connection_profiles(owner_system=owner_system)
        topology_refs = {topology for profile in profiles for topology in profile.topology_refs}
        return {
            "authority": "task_system.agent_task_connections",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "topology_count": len(topology_refs),
            },
            "diagnostics": {
                "owner_system_filter": owner_system,
            },
        }

    def list_agent_task_carrying_profiles(self) -> list[AgentTaskCarryingProfile]:
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        bindings = self.list_bindings()
        binding_by_flow = {item.flow_id: item for item in bindings}
        workflow_ids = {item.workflow_id for item in self.workflow_registry.list_workflows()}
        profiles: list[AgentTaskCarryingProfile] = []
        for agent in self.agent_registry.list_agents():
            carried_general = [
                item
                for item in general_profiles
                if item.default_agent_id == agent.agent_id
            ]
            carried_specific = [
                item
                for item in assignments
                if item.default_agent_id == agent.agent_id or agent.agent_id in set(item.participant_agent_ids)
            ]
            workflow_refs = tuple(
                dict.fromkeys(
                    [
                        *(item.default_workflow_id for item in carried_general if item.default_workflow_id),
                        *(item.workflow_id for item in carried_specific if item.workflow_id),
                    ]
                )
            )
            blocked_reasons = list(self._agent_assignment_failures(agent.agent_id, carried_general, carried_specific, workflow_ids=workflow_ids))
            for assignment in carried_specific:
                binding = binding_by_flow.get(assignment.flow_id)
                if binding is not None and binding.validation_state != "valid":
                    blocked_reasons.extend(str(item) for item in list(binding.diagnostics.get("failures") or []) if item)
            validation_state = "valid" if (carried_general or carried_specific) and not blocked_reasons else "invalid" if blocked_reasons else "unbound"
            profiles.append(
                AgentTaskCarryingProfile(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    profile_type=agent.profile_type,
                    owner_system=agent.owner_system,
                    lifecycle_state=agent.lifecycle_state,
                    carried_general_task_refs=tuple(item.profile_id for item in carried_general),
                    carried_specific_task_refs=tuple(item.task_id for item in carried_specific),
                    workflow_refs=workflow_refs,
                    validation_state=validation_state,
                    blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
                    diagnostics={
                        "general_task_count": len(carried_general),
                        "specific_task_count": len(carried_specific),
                        "workflow_count": len(workflow_refs),
                    },
                )
            )
        return profiles

    def build_agent_carrying_overview(self) -> dict[str, Any]:
        profiles = self.list_agent_task_carrying_profiles()
        return {
            "authority": "task_system.agent_carrying_profiles",
            "profiles": [item.to_dict() for item in profiles],
            "summary": {
                "profile_count": len(profiles),
                "invalid_profile_count": sum(1 for item in profiles if item.validation_state == "invalid"),
                "unbound_profile_count": sum(1 for item in profiles if item.validation_state == "unbound"),
            },
        }

    def build_connection_diagnostics(self) -> dict[str, Any]:
        agents = {item.agent_id for item in self.agent_registry.list_agents()}
        workflows = {item.workflow_id for item in self.workflow_registry.list_workflows()}
        general_profiles = self.list_general_task_profiles()
        assignments = self.list_task_assignments()
        carrying_profiles = self.list_agent_task_carrying_profiles()
        issues: list[dict[str, Any]] = []
        for profile in general_profiles:
            self._append_ref_issue(issues, profile.profile_id, "general_task", "default_agent_id", profile.default_agent_id, agents)
            if profile.default_workflow_id:
                self._append_ref_issue(issues, profile.profile_id, "general_task", "workflow_id", profile.default_workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(profile.profile_id, "general_task", "workflow_missing", "default_workflow_id"))
        for assignment in assignments:
            self._append_ref_issue(issues, assignment.task_id, "specific_task", "default_agent_id", assignment.default_agent_id, agents)
            for participant_id in assignment.participant_agent_ids:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "participant_agent_id", participant_id, agents)
            if assignment.workflow_id:
                self._append_ref_issue(issues, assignment.task_id, "specific_task", "workflow_id", assignment.workflow_id, workflows)
            else:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "workflow_missing", "workflow_id"))
            if not assignment.input_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "input_contract_missing", "input_contract_id"))
            if not assignment.output_contract_id:
                issues.append(_diagnostic_issue(assignment.task_id, "specific_task", "output_contract_missing", "output_contract_id"))
        for profile in carrying_profiles:
            if profile.validation_state == "unbound":
                issues.append(_diagnostic_issue(profile.agent_id, "agent", "agent_without_task", "carried_tasks"))
            for reason in profile.blocked_reasons:
                issues.append(_diagnostic_issue(profile.agent_id, "agent", reason, "task_connection"))
        return {
            "authority": "task_system.connection_diagnostics",
            "issues": issues,
            "summary": {
                "issue_count": len(issues),
                "blocking_issue_count": sum(1 for item in issues if item.get("severity") == "blocking"),
            },
        }

    def _agent_assignment_failures(
        self,
        agent_id: str,
        general_profiles: list[GeneralTaskProfile],
        assignments: list[TaskAssignment],
        workflow_ids: set[str] | None = None,
    ) -> tuple[str, ...]:
        workflow_ids = workflow_ids if workflow_ids is not None else {
            item.workflow_id for item in self.workflow_registry.list_workflows()
        }
        failures: list[str] = []
        if any(item.default_workflow_id and item.default_workflow_id not in workflow_ids for item in general_profiles):
            failures.append("general_workflow_missing")
        if any(item.workflow_id and item.workflow_id not in workflow_ids for item in assignments):
            failures.append("specific_workflow_missing")
        if agent_id == "agent:0" and not general_profiles:
            failures.append("main_agent_without_general_task")
        return tuple(dict.fromkeys(failures))

    def _append_ref_issue(
        self,
        issues: list[dict[str, Any]],
        object_id: str,
        object_type: str,
        field: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if not value or value not in allowed:
            issues.append(_diagnostic_issue(object_id, object_type, f"{field}_missing_ref", field, value=value))

    def _validate_workflow_ref(
        self,
        failures: list[str],
        diagnostics: dict[str, Any],
        workflow_id: str,
    ) -> None:
        value = str(workflow_id or "").strip()
        if not value:
            failures.append("workflow_missing")
            diagnostics["workflow"] = {"value": value, "status": "missing"}
            return
        if self.workflow_registry.get_workflow(value) is not None:
            return
        failures.append("workflow_missing")
        diagnostics["workflow"] = {"value": value, "status": "missing"}

    def build_overview(self) -> dict[str, Any]:
        agent_catalog = self.agent_registry.build_catalog()
        flows = self.list_flows()
        bindings = self.list_bindings()
        general_profiles = self.list_general_task_profiles()
        task_assignments = self.list_task_assignments()
        task_domains = self.list_task_domains()
        invalid_bindings = [item for item in bindings if item.validation_state != "valid"]
        projection_bindings = self.list_projection_bindings()
        explicit_projection_bindings = self.list_explicit_projection_bindings()
        flow_contract_bindings = self.list_flow_contract_bindings()
        explicit_flow_contract_bindings = self.list_explicit_flow_contract_bindings()
        adoption_plans = self.list_task_agent_adoption_plans()
        explicit_adoption_plans = self.list_explicit_task_agent_adoption_plans()
        communication_protocols = self.list_task_communication_protocols()
        return {
            "authority": "task_system.overview",
            "summary": {
                "agent_count": agent_catalog["summary"]["agent_count"],
                "main_agent_count": agent_catalog["summary"]["main_agent_count"],
                "builtin_agent_count": agent_catalog["summary"]["builtin_agent_count"],
                "custom_agent_count": agent_catalog["summary"]["custom_agent_count"],
                "system_manager_agent_count": agent_catalog["summary"]["system_manager_agent_count"],
                "delegation_enabled_agent_count": agent_catalog["summary"].get("delegation_enabled_agent_count", 0),
                "general_task_count": len(general_profiles),
                "specific_task_count": len(task_assignments),
                "task_flow_count": len(flows),
                "enabled_task_flow_count": sum(1 for item in flows if item.enabled),
                "runtime_recipe_protocol": "task_graph_derived",
                "task_template_count": 0,
                "enabled_task_template_count": 0,
                "task_domain_count": len(task_domains),
                "projection_binding_count": len(explicit_projection_bindings),
                "derived_projection_binding_count": _derived_count(
                    projection_bindings,
                    explicit_projection_bindings,
                    key_attr="binding_id",
                ),
                "effective_projection_binding_count": len(projection_bindings),
                "flow_contract_binding_count": len(explicit_flow_contract_bindings),
                "derived_flow_contract_binding_count": _derived_count(
                    flow_contract_bindings,
                    explicit_flow_contract_bindings,
                    key_attr="binding_id",
                ),
                "effective_flow_contract_binding_count": len(flow_contract_bindings),
                "adoption_plan_count": len(explicit_adoption_plans),
                "derived_adoption_plan_count": _derived_count(
                    adoption_plans,
                    explicit_adoption_plans,
                    key_attr="plan_id",
                ),
                "effective_adoption_plan_count": len(adoption_plans),
                "communication_protocol_count": len(communication_protocols),
                "invalid_binding_count": len(invalid_bindings),
                "invalid_template_count": 0,
            },
            "agents": agent_catalog["agents"],
            "task_domains": [item.to_dict() for item in task_domains],
            "general_task_profiles": [item.to_dict() for item in general_profiles],
            "specific_task_records": [item.to_dict() for item in self.list_specific_task_records()],
            "task_assignments": [item.to_dict() for item in task_assignments],
            "flows": [item.to_dict() for item in flows],
            "bindings": [item.to_dict() for item in bindings],
            "projection_bindings": [item.to_dict() for item in projection_bindings],
            "flow_contract_bindings": [item.to_dict() for item in flow_contract_bindings],
            "agent_adoption_plans": [item.to_dict() for item in adoption_plans],
            "templates": [],
            "template_validation_matrix": _removed_template_protocol_matrix(),
            "topology_templates": [item.to_dict() for item in self.list_topology_templates()],
            "communication_protocols": [item.to_dict() for item in communication_protocols],
            "link_permission_matrix": self.build_link_permission_matrix(),
            "agent_task_connections": self.build_agent_task_connection_overview(),
            "agent_carrying_profiles": self.build_agent_carrying_overview(),
            "connection_diagnostics": self.build_connection_diagnostics(),
        }


def _validate_contains(
    failures: list[str],
    diagnostics: dict[str, Any],
    field: str,
    value: str,
    allowed: tuple[str, ...],
) -> None:
    if value not in allowed:
        failures.append(f"{field}_not_allowed")
        diagnostics[field] = {"value": value, "allowed": list(allowed)}


def _assignment_from_dict(payload: dict[str, Any]) -> TaskAssignment:
    return TaskAssignment(
        task_id=str(payload.get("task_id") or ""),
        task_title=str(payload.get("task_title") or ""),
        task_kind=str(payload.get("task_kind") or "specific_task"),
        flow_id=str(payload.get("flow_id") or ""),
        domain_id=str(payload.get("domain_id") or dict(payload.get("metadata") or {}).get("domain_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or dict(payload.get("task_structure") or {}).get("runtime_lane_hint") or ""),
        default_agent_id=normalize_agent_id(str(payload.get("default_agent_id") or "agent:0")),
        participant_agent_ids=normalize_agent_id_sequence(str(item) for item in list(payload.get("participant_agent_ids") or []) if str(item)),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_file_ref=str(payload.get("workflow_file_ref") or ""),
        projection_id=str(payload.get("projection_id") or payload.get("projection_template_id") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        safety_policy=dict(payload.get("safety_policy") or {}),
        task_structure=dict(payload.get("task_structure") or {}),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _normalize_agent_refs_in_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    if "agent_id" in next_payload:
        next_payload["agent_id"] = normalize_agent_id(str(next_payload.get("agent_id") or "").strip())
    if "coordinator_agent_id" in next_payload:
        next_payload["coordinator_agent_id"] = normalize_agent_id(str(next_payload.get("coordinator_agent_id") or "").strip())
    if "participant_agent_ids" in next_payload:
        next_payload["participant_agent_ids"] = list(
            normalize_agent_id_sequence(str(item) for item in list(next_payload.get("participant_agent_ids") or []) if str(item))
        )
    if not str(next_payload.get("projection_id") or "").strip():
        next_payload.pop("projection_id", None)
    if not str(next_payload.get("projection_overlay_id") or "").strip():
        next_payload.pop("projection_overlay_id", None)
    return next_payload


def _diagnostic_issue(
    object_id: str,
    object_type: str,
    reason: str,
    field: str,
    *,
    value: str = "",
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "object_type": object_type,
        "reason": reason,
        "field": field,
        "value": value,
        "severity": "blocking" if reason != "agent_without_task" else "warning",
    }


def _removed_template_protocol_matrix() -> dict[str, Any]:
    return {
        "authority": "task_system.runtime_recipe_validation",
        "status": "removed",
        "rows": [],
        "template_protocol_removed": True,
        "replacement": "TaskGraph + runtime.recipe",
    }
