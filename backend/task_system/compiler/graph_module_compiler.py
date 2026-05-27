from __future__ import annotations

from dataclasses import replace
from typing import Any

from task_system.compiler.coordination_graph_models import (
    TaskGraphModuleRuntimePlan,
    TaskGraphRuntimeNode,
    TaskGraphRuntimeValidationIssue,
)
from task_system.graphs.task_graph_models import TaskGraphDefinition


def graph_module_runtime_plans_from_layered_graph(
    *,
    graph: TaskGraphDefinition,
    layered_graph: dict[str, Any],
) -> list[TaskGraphModuleRuntimePlan]:
    plans: list[TaskGraphModuleRuntimePlan] = []
    seen: set[str] = set()
    for index, raw_node in enumerate(list(graph.nodes or []), start=1):
        if str(getattr(raw_node, "node_type", "") or "").strip() != "graph_module":
            continue
        metadata = dict(getattr(raw_node, "metadata", {}) or {})
        contract_bindings = dict(getattr(raw_node, "contract_bindings", {}) or {})
        runtime_bindings = dict(contract_bindings.get("runtime") or {})
        graph_module_runtime = dict(runtime_bindings.get("graph_module_runtime") or {})
        executor_policy = dict(getattr(raw_node, "executor_policy", {}) or {})
        linked_graph_id = str(
            graph_module_runtime.get("linked_graph_id")
            or metadata.get("linked_graph_id")
            or executor_policy.get("linked_graph_id")
            or executor_policy.get("imported_graph_id")
            or ""
        ).strip()
        if not linked_graph_id:
            continue
        node_id = str(getattr(raw_node, "node_id", "") or f"graph_module_{index}").strip() or f"graph_module_{index}"
        identifier = _safe_runtime_identifier(node_id.removeprefix("graph_module."))
        plan_id = str(metadata.get("graph_module_runtime_plan_id") or f"graph_module_runtime.{identifier}").strip()
        if plan_id in seen:
            plan_id = f"{plan_id}.{index}"
        seen.add(plan_id)
        handoff_bindings = dict(contract_bindings.get("handoff") or {})
        plans.append(
            TaskGraphModuleRuntimePlan(
                plan_id=plan_id,
                importing_graph_id=graph.graph_id,
                unit_id=f"unit.graph.{identifier}",
                runtime_node_id=node_id,
                linked_graph_id=linked_graph_id,
                version_ref=str(graph_module_runtime.get("version_ref") or metadata.get("version_ref") or "").strip(),
                handoff_contract_id=str(handoff_bindings.get("handoff_contract_id") or metadata.get("handoff_contract_id") or "").strip(),
                input_port_id=str(metadata.get("input_port_id") or "input.default").strip() or "input.default",
                output_port_id=str(metadata.get("output_port_id") or "output.default").strip() or "output.default",
                isolation_policy=str(graph_module_runtime.get("isolation_policy") or metadata.get("isolation_policy") or "isolated_per_graph_module_run").strip() or "isolated_per_graph_module_run",
                visibility_policy=str(handoff_bindings.get("visibility_policy") or metadata.get("visibility_policy") or "committed_only").strip() or "committed_only",
                detach_policy=str(metadata.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
                phase_id=str(getattr(raw_node, "phase_id", "") or "").strip(),
                sequence_index=int(getattr(raw_node, "sequence_index", 0) or index),
                metadata={
                    "source_node_id": node_id,
                    "source_authority": "task_system.graph_module_node",
                    "contract_bindings": contract_bindings,
                    "raw_node": raw_node.to_dict() if hasattr(raw_node, "to_dict") else {},
                },
            )
        )
    return plans


def runtime_nodes_from_graph_module_runtime_plans(plans: list[TaskGraphModuleRuntimePlan]) -> list[TaskGraphRuntimeNode]:
    return [
        TaskGraphRuntimeNode(
            node_id=plan.runtime_node_id,
            title=str(dict(plan.metadata or {}).get("raw_node", {}).get("title") or plan.linked_graph_id or plan.runtime_node_id),
            node_type="graph_module",
            role="graph_module",
            task_id=f"task_graph.node.{plan.importing_graph_id}.{plan.runtime_node_id}",
            executor_policy={
                "default_executor": "graph_module",
                "allowed_executors": ["graph_module"],
                "linked_graph_id": plan.linked_graph_id,
                "imported_graph_id": plan.linked_graph_id,
                "auto_start_imported_initial_stage": True,
                "source": "graph_module_runtime_plan",
            },
            execution_mode="async",
            wait_policy="wait_all_upstream_completed",
            join_policy="all_success",
            phase_id=plan.phase_id,
            sequence_index=plan.sequence_index,
            timeline_group_id=f"graph_module_runtime:{plan.unit_id}",
            blocks_phase_exit=True,
            context_visibility_policy={
                "graph_module_runtime_visibility": plan.visibility_policy,
                "importing_graph_visible_scope": "run_handle_and_committed_output",
            },
            artifact_policy={
                "visibility_policy": plan.visibility_policy,
                "source": "graph_module_commit",
            },
            metadata={
                "graph_module": True,
                "execution_mode": "graph_module_run",
                "graph_module_runtime_plan_id": plan.plan_id,
                "graph_module_runtime_plan": plan.to_dict(),
                "linked_graph_id": plan.linked_graph_id,
                "version_ref": plan.version_ref,
                "handoff_contract_id": plan.handoff_contract_id,
                "input_port_id": plan.input_port_id,
                "output_port_id": plan.output_port_id,
                "isolation_policy": plan.isolation_policy,
                "visibility_policy": plan.visibility_policy,
                "detach_policy": plan.detach_policy,
                "effective_policy_sources": {
                    "node_id": "graph.nodes[].graph_module_runtime.linked_graph_id",
                    "execution_mode": "graph_module_runtime_plan",
                    "wait_policy": "graph_module_runtime_plan.default_wait_policy",
                    "join_policy": "graph_module_runtime_plan.default_join_policy",
                },
            },
        )
        for plan in plans
    ]


def merge_graph_module_runtime_nodes(
    *,
    explicit_nodes: list[TaskGraphRuntimeNode],
    graph_module_nodes: list[TaskGraphRuntimeNode],
) -> list[TaskGraphRuntimeNode]:
    graph_module_by_id = {node.node_id: node for node in graph_module_nodes if node.node_id}
    merged: list[TaskGraphRuntimeNode] = []
    for explicit in explicit_nodes:
        graph_module_runtime = graph_module_by_id.pop(explicit.node_id, None)
        if graph_module_runtime is None:
            merged.append(explicit)
            continue
        merged.append(_merge_explicit_graph_module_node(explicit=explicit, graph_module_runtime=graph_module_runtime))
    merged.extend(graph_module_by_id.values())
    return merged


def graph_module_runtime_plan_issues(plans: list[TaskGraphModuleRuntimePlan]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for plan in plans:
        if not plan.version_ref:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="graph_module_version_anchor_missing",
                    message="图模块缺少 version_ref，导入方运行无法稳定锚定图模块版本。",
                    severity="warning",
                    node_id=plan.runtime_node_id,
                )
            )
        if not plan.handoff_contract_id:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="graph_module_handoff_contract_missing",
                    message="图模块缺少 handoff_contract_id，导入图模块提交包无法通过契约追溯。",
                    severity="warning",
                    node_id=plan.runtime_node_id,
                )
            )
    return issues


def _merge_explicit_graph_module_node(
    *,
    explicit: TaskGraphRuntimeNode,
    graph_module_runtime: TaskGraphRuntimeNode,
) -> TaskGraphRuntimeNode:
    explicit_metadata = dict(explicit.metadata or {})
    graph_module_metadata = dict(graph_module_runtime.metadata or {})
    definition_metadata = {
        key: value
        for key, value in explicit_metadata.items()
        if key not in {"agent_group_id", "model_requirement", "model_resolution"}
    }
    return replace(
        explicit,
        title=explicit.title or graph_module_runtime.title,
        node_type="graph_module",
        role="graph_module",
        agent_id="",
        runtime_lane="",
        task_id=graph_module_runtime.task_id,
        executor_policy={
            **dict(explicit.executor_policy or {}),
            **dict(graph_module_runtime.executor_policy or {}),
        },
        execution_mode=explicit.execution_mode or graph_module_runtime.execution_mode,
        wait_policy=explicit.wait_policy or graph_module_runtime.wait_policy,
        join_policy=explicit.join_policy or graph_module_runtime.join_policy,
        phase_id=explicit.phase_id or graph_module_runtime.phase_id,
        sequence_index=explicit.sequence_index or graph_module_runtime.sequence_index,
        timeline_group_id=explicit.timeline_group_id or graph_module_runtime.timeline_group_id,
        blocks_phase_exit=explicit.blocks_phase_exit or graph_module_runtime.blocks_phase_exit,
        context_visibility_policy={
            **dict(explicit.context_visibility_policy or {}),
            **dict(graph_module_runtime.context_visibility_policy or {}),
        },
        artifact_policy={
            **dict(explicit.artifact_policy or {}),
            **dict(graph_module_runtime.artifact_policy or {}),
        },
        metadata={
            **definition_metadata,
            **graph_module_metadata,
            "explicit_graph_module_node": True,
            "runtime_role": "graph_module_container",
            "model_visible": False,
            "definition_node_metadata": definition_metadata,
            "effective_policy_sources": {
                **dict(explicit_metadata.get("effective_policy_sources") or {}),
                **dict(graph_module_metadata.get("effective_policy_sources") or {}),
                "agent_id": "graph_module_container",
                "graph_module_merge": "graph.nodes[]",
            },
        },
    )


def _safe_runtime_identifier(value: str) -> str:
    sanitized = str(value or "").strip().replace(":", ".").replace("/", ".").replace("\\", ".")
    sanitized = ".".join(part for part in sanitized.split(".") if part)
    return sanitized or "unknown"
