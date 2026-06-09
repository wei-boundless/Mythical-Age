from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.graph.edge_contracts import edge_contract_or_projection
from harness.graph.models import GraphHarnessConfig, GraphLoopState, safe_id
from task_system import TaskFlowRegistry
from task_system.graph_instances.decision_models import next_human_artifact_submission_id
from task_system.graph_instances.decision_repository import HumanEdgeDecisionRepository
from task_system.graph_instances.file_service import GraphTaskInstanceFileService
from task_system.graph_instances.repository import GraphTaskInstanceRepository


class HumanEdgeDecisionService:
    authority = "task_system.graph_instance.human_edge_decision_service"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.instances = GraphTaskInstanceRepository(self.base_dir)
        self.decisions = HumanEdgeDecisionRepository(self.base_dir)
        self.files = GraphTaskInstanceFileService(self.base_dir)
        self.registry = TaskFlowRegistry(self.base_dir)

    def submit(
        self,
        *,
        runtime: Any,
        instance_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        instance = self.instances.require(instance_id)
        graph_config = self._graph_config(instance.graph_id)
        graph_run_id = str(payload.get("graph_run_id") or instance.active_graph_run_id or "").strip()
        if not graph_run_id:
            raise ValueError("HumanEdgeDecision requires graph_run_id or active graph run")
        if instance.graph_run_ids and graph_run_id not in set(instance.graph_run_ids):
            raise ValueError("HumanEdgeDecision graph_run_id does not belong to graph task instance")
        state = runtime.harness_runtime.graph_harness.graph_loop.get_state(graph_run_id)
        if state is None:
            raise ValueError(f"GraphLoopState not found: {graph_run_id}")
        edge = _edge_by_id(graph_config, str(payload.get("edge_id") or ""))
        if edge is None:
            raise ValueError(f"HumanEdgeDecision edge not found: {payload.get('edge_id')}")
        decision_kind = str(payload.get("decision") or "").strip()
        policy = _human_control_policy(graph_config=graph_config, edge=edge)
        _assert_decision_allowed(policy=policy, decision=decision_kind, edge=edge)
        normalized = self._normalized_decision_payload(
            instance=instance,
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            state=state,
            edge=edge,
            payload=payload,
        )
        idempotency_key = str(normalized.get("idempotency_key") or "").strip()
        existing = self.decisions.find_by_idempotency_key(instance.graph_task_instance_id, idempotency_key)
        if existing is not None:
            if existing.status == "applied" or not bool(payload.get("apply_now", True)):
                return {
                    "authority": "task_system.graph_instance.human_edge_decision_submit",
                    "decision": existing.to_dict(),
                    "apply_result": None,
                    "idempotent": True,
                }
            decision = existing
        else:
            decision = self.decisions.create(instance.graph_task_instance_id, normalized)
        apply_result = None
        if bool(payload.get("apply_now", True)):
            try:
                advance = runtime.harness_runtime.graph_harness.apply_human_edge_decision(
                    graph_config=graph_config,
                    graph_run_id=graph_run_id,
                    decision=decision.to_dict(),
                )
            except Exception as exc:
                self.decisions.transition(
                    instance.graph_task_instance_id,
                    decision.decision_id,
                    "failed",
                    {"apply_error": str(exc)},
                )
                raise
            checkpoint = dict(advance.checkpoint or {})
            decision = self.decisions.transition(
                instance.graph_task_instance_id,
                decision.decision_id,
                "applied",
                {"apply_result_ref": str(checkpoint.get("checkpoint_id") or checkpoint.get("checkpoint_ref") or "")},
            )
            apply_result = {
                "graph_loop_state": advance.loop_state.to_dict(),
                "checkpoint": checkpoint,
                "accepted_result": advance.accepted_result.to_dict() if advance.accepted_result is not None else None,
                "graph_result": advance.graph_result.to_dict() if advance.graph_result is not None else None,
                "node_work_orders": [item.to_dict() for item in advance.node_work_orders],
                "events": [dict(item) for item in advance.events],
                "authority": "task_system.graph_instance.human_edge_decision_apply_result",
            }
        return {
            "authority": "task_system.graph_instance.human_edge_decision_submit",
            "decision": decision.to_dict(),
            "apply_result": apply_result,
            "idempotent": False,
        }

    def list(self, instance_id: str, *, limit: int = 100) -> dict[str, Any]:
        instance = self.instances.require(instance_id)
        decisions = self.decisions.list(instance.graph_task_instance_id, limit=limit)
        return {
            "authority": "task_system.graph_instance.human_edge_decisions",
            "graph_task_instance_id": instance.graph_task_instance_id,
            "decisions": [item.to_dict() for item in decisions],
            "summary": {"decision_count": len(decisions)},
        }

    def human_controls(
        self,
        *,
        instance_id: str,
        graph_config: GraphHarnessConfig | None,
        state: GraphLoopState | None,
        limit: int = 50,
    ) -> dict[str, Any]:
        instance = self.instances.require(instance_id)
        decisions = [item.to_dict() for item in self.decisions.list(instance.graph_task_instance_id, limit=limit)]
        if graph_config is None or state is None:
            return {
                "authority": "api.graph_task_instances.human_control_projection",
                "pending": [],
                "available": [],
                "history": decisions,
                "summary": {"pending_count": 0, "available_count": 0, "decision_count": len(decisions)},
            }
        pending = _pending_human_controls(graph_config=graph_config, state=state)
        available = _available_human_controls(graph_config=graph_config, state=state)
        return {
            "authority": "api.graph_task_instances.human_control_projection",
            "pending": pending,
            "available": available,
            "history": decisions,
            "summary": {
                "pending_count": len(pending),
                "available_count": len(available),
                "decision_count": len(decisions),
            },
        }

    def _graph_config(self, graph_id: str) -> GraphHarnessConfig:
        graph_config = self.registry.get_published_graph_harness_config(graph_id)
        if graph_config is None:
            raise ValueError(f"GraphHarnessConfig not found for graph: {graph_id}")
        return graph_config

    def _normalized_decision_payload(
        self,
        *,
        instance: Any,
        graph_config: GraphHarnessConfig,
        graph_run_id: str,
        state: GraphLoopState,
        edge: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del state
        decision_kind = str(payload.get("decision") or "").strip()
        content_submission = dict(payload.get("content_submission") or {})
        artifact_refs = [dict(item) for item in list(payload.get("artifact_refs") or []) if isinstance(item, dict)]
        if content_submission:
            materialized = self._materialize_submission(
                instance_id=instance.graph_task_instance_id,
                decision=decision_kind,
                content_submission=content_submission,
            )
            content_submission = materialized["content_submission"]
            artifact_refs = [*artifact_refs, *materialized["artifact_refs"]]
        normalized = {
            "graph_task_instance_id": instance.graph_task_instance_id,
            "graph_id": instance.graph_id,
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_config.config_id,
            "edge_id": str(edge.get("edge_id") or ""),
            "source_node_id": str(edge.get("source_node_id") or ""),
            "target_node_id": str(edge.get("target_node_id") or ""),
            "decision": decision_kind,
            "instruction": str(payload.get("instruction") or "").strip(),
            "artifact_refs": artifact_refs,
            "content_submission": content_submission,
            "operator": dict(payload.get("operator") or {}),
            "idempotency_key": str(payload.get("idempotency_key") or "").strip(),
            "status": "submitted",
            "metadata": {
                **dict(payload.get("metadata") or {}),
                "source": "graph_task_instance_api",
            },
        }
        return normalized

    def _materialize_submission(
        self,
        *,
        instance_id: str,
        decision: str,
        content_submission: dict[str, Any],
    ) -> dict[str, Any]:
        path = str(content_submission.get("path") or "").strip()
        content = str(content_submission.get("content") or "")
        if not path:
            raise ValueError("HumanEdgeDecision content_submission requires path")
        self.files.write_file(instance_id, path, content)
        absolute = (self.files.root(instance_id) / path.replace("\\", "/").strip("/")).resolve()
        submission = {
            "submission_id": str(content_submission.get("submission_id") or next_human_artifact_submission_id(instance_id)),
            "graph_task_instance_id": instance_id,
            "repository_id": "instance",
            "path": path,
            "content_kind": str(content_submission.get("content_kind") or ""),
            "commit_policy": str(content_submission.get("commit_policy") or "project_file"),
            "memory_policy": str(content_submission.get("memory_policy") or "none"),
            "source": f"human_edge_decision.{decision}",
            "artifact_ref": str(absolute),
        }
        return {
            "content_submission": {key: value for key, value in {**content_submission, **submission}.items() if key != "content"},
            "artifact_refs": [
                {
                    "ref_kind": "project_file",
                    "repository_id": "instance",
                    "path": path,
                    "artifact_ref": str(absolute),
                    "content_kind": submission["content_kind"],
                    "authority": "task_system.graph_instance.human_artifact_submission_ref",
                }
            ],
        }


def _edge_by_id(graph_config: GraphHarnessConfig, edge_id: str) -> dict[str, Any] | None:
    target = str(edge_id or "").strip()
    return next((dict(item) for item in graph_config.edges if str(dict(item).get("edge_id") or "") == target), None)


def _human_control_policy(*, graph_config: GraphHarnessConfig, edge: dict[str, Any]) -> dict[str, Any]:
    contract = edge_contract_or_projection(graph_config, edge)
    return dict(contract.get("human_control") or {})


def _assert_decision_allowed(*, policy: dict[str, Any], decision: str, edge: dict[str, Any]) -> None:
    if not policy or policy.get("enabled") is False:
        raise ValueError(f"Human edge control is not enabled for edge: {edge.get('edge_id')}")
    allowed = {str(item) for item in list(policy.get("allowed_decisions") or []) if str(item)}
    if decision not in allowed:
        raise ValueError(f"HumanEdgeDecision {decision} is not allowed for edge: {edge.get('edge_id')}")


def _pending_human_controls(*, graph_config: GraphHarnessConfig, state: GraphLoopState) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for node_id, node_state in dict(state.node_states or {}).items():
        payload = dict(node_state or {})
        if str(payload.get("status") or "") != "waiting_human_gate":
            continue
        outgoing = [
            _control_for_edge(graph_config=graph_config, state=state, edge=dict(edge), pending_node_id=str(node_id))
            for edge in graph_config.edges
            if str(dict(edge).get("source_node_id") or "") == str(node_id)
        ]
        controls.extend(item for item in outgoing if item)
    return controls


def _available_human_controls(*, graph_config: GraphHarnessConfig, state: GraphLoopState) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for edge in graph_config.edges:
        control = _control_for_edge(graph_config=graph_config, state=state, edge=dict(edge), pending_node_id="")
        if control:
            controls.append(control)
    return controls


def _control_for_edge(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    edge: dict[str, Any],
    pending_node_id: str = "",
) -> dict[str, Any] | None:
    policy = _human_control_policy(graph_config=graph_config, edge=edge)
    if not policy or policy.get("enabled") is False:
        return None
    configured_decisions = [str(item) for item in list(policy.get("allowed_decisions") or []) if str(item)]
    if not configured_decisions:
        return None
    source = str(edge.get("source_node_id") or "")
    target = str(edge.get("target_node_id") or "")
    source_state = dict(dict(state.node_states or {}).get(source) or {})
    target_state = dict(dict(state.node_states or {}).get(target) or {})
    source_status = str(source_state.get("status") or "")
    target_status = str(target_state.get("status") or "")
    source_result_ref = str(
        source_state.get("result_ref")
        or dict(source_state.get("human_gate") or {}).get("source_result_ref")
        or ""
    )
    if target_status == "running":
        return None
    source_can_forward = bool(source_result_ref) and source_status in {"completed", "waiting_human_gate"}
    allowed = []
    for decision in configured_decisions:
        if decision == "replace":
            if source_status != "running":
                allowed.append(decision)
            continue
        if source_can_forward:
            allowed.append(decision)
    if not allowed:
        return None
    labels = dict(policy.get("decision_labels") or {})
    return {
        "authority": "harness.graph.human_control_view",
        "control_id": f"hctrl:{safe_id(state.graph_run_id)}:{safe_id(str(edge.get('edge_id') or 'edge'))}",
        "graph_run_id": state.graph_run_id,
        "edge_id": str(edge.get("edge_id") or ""),
        "source_node_id": source,
        "target_node_id": target,
        "source_node_status": source_status,
        "target_node_status": target_status,
        "source_result_ref": source_result_ref,
        "pending_node_id": pending_node_id,
        "artifact_refs": _artifact_refs_from_source(state=state, source_node_id=source),
        "allowed_decisions": allowed,
        "decision_labels": labels,
        "default_decision": str(policy.get("default_decision") or allowed[0]),
        "reason": str(policy.get("reason") or "该边允许人工控制传播。"),
        "human_control_policy": policy,
    }


def _artifact_refs_from_source(*, state: GraphLoopState, source_node_id: str) -> list[dict[str, Any]]:
    result = dict(dict(state.result_index or {}).get(source_node_id) or {})
    refs = []
    for raw in list(result.get("artifact_refs") or []):
        if isinstance(raw, dict):
            refs.append(dict(raw))
        elif str(raw or "").strip():
            refs.append({"artifact_ref": str(raw).strip(), "ref_kind": "artifact"})
    return refs
