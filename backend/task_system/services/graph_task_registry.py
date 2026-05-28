from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.identity import normalize_agent_id, normalize_agent_id_sequence

from task_system.graphs.task_graph_models import TaskGraphDefinition
from task_system.registry.flow_models import CoordinationTaskDefinition


class TaskGraphRegistryService:
    def __init__(self, registry: Any, base_dir: Path) -> None:
        self.registry = registry
        self.base_dir = Path(base_dir)

    def derive_coordination_task_view_from_graph(self, graph: TaskGraphDefinition) -> CoordinationTaskDefinition:
        metadata = dict(graph.metadata or {})
        runtime_policy = dict(graph.runtime_policy or {})
        continuation_policy = {**dict(metadata.get("continuation_policy") or {})}
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
        participant_agent_ids = self.resolve_coordination_participants(
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
        graph_nodes = stored_nodes or fallback_nodes
        graph_edges = tuple(edge.to_dict() for edge in graph.edges) or fallback_edges
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
        topology_template = self.registry.get_topology_template(topology_ref) if topology_ref else None
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
        resolved_participants = self.resolve_coordination_participants(
            coordinator_agent_id=normalize_agent_id(str(coordinator_agent_id or "agent:0").strip() or "agent:0"),
            agent_group_id=str(agent_group_id or "").strip(),
            participant_agent_ids=normalize_agent_id_sequence(str(item).strip() for item in participant_agent_ids if str(item).strip()),
        )
        return self.registry.upsert_task_graph(
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
                "participant_agent_ids": list(resolved_participants),
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

    def resolve_coordination_participants(
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
    next_payload.pop("projection_id", None)
    next_payload.pop("projection_overlay_id", None)
    return next_payload


