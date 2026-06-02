from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.identity import normalize_agent_id, normalize_agent_id_sequence

from task_system.graphs.task_graph_models import TaskGraphDefinition


class TaskGraphRegistryService:
    def __init__(self, registry: Any, base_dir: Path) -> None:
        self.registry = registry
        self.base_dir = Path(base_dir)

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
    return next_payload


