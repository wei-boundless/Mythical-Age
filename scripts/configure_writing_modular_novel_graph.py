from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tasks.contract_definition_models import AcceptanceRule, ContractField, ContractSpec
from tasks.contract_registry import TaskContractRegistry
from tasks.flow_registry import TaskFlowRegistry


MANAGED_BY = "codex_writing_modular_novel_graph_20260520"
DOMAIN_ID = "domain.writing.modular_novel"
TASK_FAMILY = "writing_modular_novel"
PROTOCOL_ID = "protocol.writing.modular_novel"
MODEL_PROFILE_REF = "llm.deepseek.long_output_65536"

MASTER_GRAPH_ID = "graph.writing.modular_novel.master"
DESIGN_GRAPH_ID = "graph.writing.modular_novel.design_init"
CHAPTER_GRAPH_ID = "graph.writing.modular_novel.chapter_cycle"
FINALIZE_GRAPH_ID = "graph.writing.modular_novel.finalize"

SOURCE_GRAPH_ID = "graph.writing.simple_novel"
SOURCE_TASK_PREFIX = "task.writing.simple_novel."
SOURCE_CONTRACT_PREFIX = "contract.writing.simple_novel."
SOURCE_FLOW_PREFIX = "flow.writing.simple_novel."
SOURCE_WORKFLOW_PREFIX = "workflow.writing.simple_novel."
SOURCE_PROJECTION_PREFIX = "projection.writing.simple_novel."

TARGET_VOLUMES = 1
CHAPTERS_PER_VOLUME = 50
CHAPTER_BATCH_SIZE = 10
CHAPTER_TARGET_WORDS = 2000
VOLUME_TARGET_WORDS = CHAPTERS_PER_VOLUME * CHAPTER_TARGET_WORDS
TARGET_WORDS = TARGET_VOLUMES * VOLUME_TARGET_WORDS
CHAPTER_REQUESTED_COUNT = TARGET_VOLUMES * CHAPTERS_PER_VOLUME

PHASE_TASKS: dict[str, tuple[str, ...]] = {
    DESIGN_GRAPH_ID: (
        "project_brief",
        "world_design",
        "world_review",
        "memory_commit_world",
        "character_design",
        "plot_design",
        "design_sync",
        "outline_design",
        "outline_review",
        "baseline_memory_seed",
    ),
    CHAPTER_GRAPH_ID: (
        "volume_plan",
        "chapter_outline",
        "chapter_draft",
        "chapter_review",
        "memory_commit_chapter",
        "chapter_progress_router",
        "volume_review",
        "volume_commit",
        "volume_postmortem",
        "world_outline_extension_proposal",
        "extension_review",
        "extension_commit",
        "next_volume_router",
    ),
    FINALIZE_GRAPH_ID: (
        "final_assemble",
        "final_review",
        "memory_finalize",
    ),
}

GRAPH_TITLES = {
    MASTER_GRAPH_ID: "模块化长篇写作总任务图",
    DESIGN_GRAPH_ID: "设计初始化任务图",
    CHAPTER_GRAPH_ID: "章节批次创作任务图",
    FINALIZE_GRAPH_ID: "收尾交付任务图",
}


def configure(base_dir: Path | str | None = None) -> dict[str, Any]:
    backend_dir = Path(base_dir or BACKEND_DIR).resolve()
    registry = TaskFlowRegistry(backend_dir)
    contract_registry = TaskContractRegistry(backend_dir)
    source_graph = registry.get_task_graph(SOURCE_GRAPH_ID)
    if source_graph is None:
        raise RuntimeError(f"source writing graph not found: {SOURCE_GRAPH_ID}")

    _upsert_domain(registry)
    _upsert_contracts(contract_registry)
    _upsert_protocol(registry)
    _upsert_modular_task_assets(registry)
    _upsert_modular_node_task_assets(registry)

    source_nodes = {node.node_id: node.to_dict() for node in source_graph.nodes}
    source_edges = [edge.to_dict() for edge in source_graph.edges]
    for graph_id, node_ids in PHASE_TASKS.items():
        _upsert_child_graph(
            registry=registry,
            source_graph=source_graph.to_dict(),
            source_nodes=source_nodes,
            source_edges=source_edges,
            graph_id=graph_id,
            node_ids=node_ids,
        )
    _upsert_master_graph(registry=registry)

    configured = {
        "domain_id": DOMAIN_ID,
        "protocol_id": PROTOCOL_ID,
        "graph_ids": [MASTER_GRAPH_ID, DESIGN_GRAPH_ID, CHAPTER_GRAPH_ID, FINALIZE_GRAPH_ID],
        "requested_chapters": CHAPTER_REQUESTED_COUNT,
        "chapter_batch_size": CHAPTER_BATCH_SIZE,
        "target_volumes": TARGET_VOLUMES,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
            "chapter_batch_count": (CHAPTERS_PER_VOLUME + CHAPTER_BATCH_SIZE - 1) // CHAPTER_BATCH_SIZE,
        "managed_by": MANAGED_BY,
    }
    print(
        "configured modular writing graphs: "
        f"{', '.join(configured['graph_ids'])}; "
        f"{TARGET_VOLUMES} volume(s), {CHAPTERS_PER_VOLUME} chapters per volume, "
        f"{CHAPTER_BATCH_SIZE} chapters per batch"
    )
    return configured


def _upsert_domain(registry: TaskFlowRegistry) -> None:
    registry.upsert_task_domain(
        domain_id=DOMAIN_ID,
        task_family=TASK_FAMILY,
        title="模块化长篇写作",
        description="以任务图为一等对象组织设计初始化、章节批次创作与收尾交付的长篇写作任务域。",
        enabled=True,
        sort_order=88,
        metadata={
            "managed_by": MANAGED_BY,
            "source_graph_id": SOURCE_GRAPH_ID,
            "architecture": "graph_unit_composition",
        },
    )


def _upsert_contracts(contract_registry: TaskContractRegistry) -> None:
    specs = [
        _contract_spec(
            "contract.writing.modular_novel.graph",
            "模块化长篇写作图契约",
            "global_task",
            output_fields=("project_id", "project_title", "chapter_target", "artifact_refs", "run_summary"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.graph_unit_handoff",
            "父子任务图交接契约",
            "edge_handoff",
            input_fields=("parent_graph_id", "source_graph_unit_id", "upstream_commit_refs"),
            output_fields=("child_graph_id", "child_run_ref", "committed_output_refs", "handoff_summary"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.design_commit",
            "设计初始化提交契约",
            "final_output",
            output_fields=("project_brief_ref", "world_commit_ref", "character_design_ref", "plot_design_ref", "outline_commit_ref", "baseline_memory_ref"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.chapter_batch_request",
            "章节批次请求契约",
            "global_task",
            input_fields=("project_id", "batch_start_index", "batch_end_index", "unit_batch_id", "baseline_memory_ref"),
            output_fields=("batch_plan_ref", "batch_boundary", "required_memory_refs"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.chapter_batch_commit",
            "章节批次提交契约",
            "final_output",
            input_fields=("chapter_draft_ref", "chapter_review_ref", "unit_batch_id"),
            output_fields=("chapter_commit_refs", "chapter_summary_refs", "batch_receipt_ref", "unit_batch_id"),
        ),
        _contract_spec(
            "contract.writing.modular_novel.final_delivery",
            "最终交付契约",
            "final_output",
            input_fields=("chapter_commit_refs", "baseline_memory_ref", "delivery_requirements"),
            output_fields=("final_manuscript_ref", "final_review_ref", "delivery_manifest_ref", "memory_finalize_receipt_ref"),
        ),
    ]
    for spec in specs:
        contract_registry.upsert_contract_spec(spec)


def _contract_spec(
    contract_id: str,
    title_zh: str,
    contract_kind: str,
    *,
    input_fields: tuple[str, ...] = (),
    output_fields: tuple[str, ...] = (),
) -> ContractSpec:
    return ContractSpec(
        contract_id=contract_id,
        title_zh=title_zh,
        title_en=contract_id.rsplit(".", 1)[-1],
        contract_kind=contract_kind,
        description=f"{title_zh}。用于模块化长篇写作任务图，不承载任何写作专用后端权限。",
        input_fields=tuple(_field(name, source_hint="upstream_output") for name in input_fields),
        output_fields=tuple(_field(name, required=name.endswith("_ref") or name in {"project_id", "child_graph_id"}) for name in output_fields),
        acceptance_rules=(
            AcceptanceRule(
                rule_id=f"{_safe_id(contract_id)}.structured_refs",
                title_zh="必须使用结构化引用交接",
                rule_type="required_field_present",
                severity="error",
                target_field="artifact_refs",
                criteria="长文本、章节正文、设计文档与最终稿必须以 artifact/result ref 交接，不把全文塞入普通上下文。",
            ),
        ),
        version="1.0.0",
        enabled=True,
        metadata={
            "managed_by": MANAGED_BY,
            "domain_id": DOMAIN_ID,
            "task_family": TASK_FAMILY,
        },
    )


def _field(name: str, *, source_hint: str = "runtime_context", required: bool = False) -> ContractField:
    field_type = "array" if name.endswith("_refs") or name in {"artifact_refs", "committed_output_refs"} else "string"
    if name.endswith("_ref") or name.endswith("_id"):
        field_type = "result_ref" if name.endswith("_ref") else "string"
    return ContractField(
        field_id=name,
        title_zh=name,
        field_type=field_type,
        required=required,
        description=name,
        source_hint=source_hint,
        visibility="model_visible",
    )


def _upsert_protocol(registry: TaskFlowRegistry) -> None:
    registry.upsert_task_communication_protocol(
        protocol_id=PROTOCOL_ID,
        title="模块化长篇写作通信协议",
        message_types=(
            "message/send",
            "task/status",
            "task/artifact",
            "task/review_feedback",
            "task/revision_request",
            "task/memory_read",
            "task/memory_write",
            "task/graph_unit_commit",
        ),
        payload_contracts=(
            "contract.writing.modular_novel.graph",
            "contract.writing.modular_novel.graph_unit_handoff",
            "contract.writing.modular_novel.design_commit",
            "contract.writing.modular_novel.chapter_batch_request",
            "contract.writing.modular_novel.chapter_batch_commit",
            "contract.writing.modular_novel.final_delivery",
            "contract.writing.simple_novel.memory_pack",
            "contract.writing.simple_novel.memory_write_receipt",
        ),
        signal_rules=(
            "graph_unit_commits_before_next_graph_unit",
            "unit_batch_range_is_runtime_contract",
            "review_result_required_before_commit",
            "baseline_memory_updates_only_through_commit_nodes",
        ),
        handoff_rules=(
            "structured_artifact_refs_only",
            "no_raw_agent_dialogue",
            "committed_refs_only_between_graph_units",
            "batch_candidate_not_visible_as_committed_memory",
        ),
        ack_policy="explicit_ack",
        timeout_policy="fail_closed",
        error_signal_policy="raise_to_coordinator",
        enabled=True,
        metadata={"managed_by": MANAGED_BY, "task_family": TASK_FAMILY, "domain_id": DOMAIN_ID},
    )


def _upsert_modular_task_assets(registry: TaskFlowRegistry) -> None:
    for suffix, title, projection_id, output_contract in (
        ("master", "模块化长篇写作总任务", "projection.writing.simple_novel.project_brief", "contract.writing.modular_novel.graph"),
        ("design_init", "设计初始化任务图单元", "projection.writing.simple_novel.outline_designer", "contract.writing.modular_novel.design_commit"),
        ("chapter_cycle", "章节批次创作任务图单元", "projection.writing.simple_novel.chapter_writer", "contract.writing.modular_novel.chapter_batch_commit"),
        ("finalize", "收尾交付任务图单元", "projection.writing.simple_novel.final_assembler", "contract.writing.modular_novel.final_delivery"),
    ):
        task_id = f"task.writing.modular_novel.{suffix}"
        flow_id = f"flow.writing.modular_novel.{suffix}"
        workflow_id = f"workflow.writing.modular_novel.{suffix}"
        registry.workflow_registry.upsert_workflow(
            workflow_id=workflow_id,
            title=title,
            compatible_projection_ids=(projection_id,),
            steps=(
                {"step_id": "read_contract_packet", "title": "读取契约化输入包"},
                {"step_id": "execute_graph_unit", "title": "按任务图时序执行"},
                {"step_id": "commit_refs", "title": "提交结构化引用"},
            ),
            input_boundary="contract_payload_and_refs",
            output_boundary="artifact_refs_and_commit_receipt",
            output_contract_id=output_contract,
            enabled=True,
            metadata={"managed_by": MANAGED_BY, "task_family": TASK_FAMILY},
        )
        registry.upsert_flow(
            flow_id=flow_id,
            task_family=TASK_FAMILY,
            title=title,
            input_contract_id="contract.user_request.basic",
            output_contract_id=output_contract,
            default_agent_id="agent:writing_simple_worker",
            default_workflow_id=workflow_id,
            default_runtime_lane="coordination_task",
            default_memory_scope="writing_modular_novel",
            enabled=True,
            metadata={"managed_by": MANAGED_BY, "task_id": task_id},
        )
        registry.upsert_specific_task_record(
            task_id=task_id,
            task_title=title,
            task_family=TASK_FAMILY,
            description=f"{title}。任务图单元通过通用 GraphUnit / contract_bindings 执行。",
            enabled=True,
            runtime_lane="coordination_task",
            input_contract_id="contract.user_request.basic",
            output_contract_id=output_contract,
            default_flow_contract_id=flow_id,
            default_workflow_id=workflow_id,
            default_projection_policy="fixed_projection",
            task_policy={
                "safety_policy": {"verification_mode": "artifact_or_trace", "write_mode": "scoped", "safety_class": "S2_bounded"},
                "task_structure": {
                    "execution_chain_type": "coordination_node",
                    "memory_scope_hint": "writing_modular_novel",
                    "projection_id": projection_id,
                    "graph_unit_task": True,
                },
            },
            metadata={"managed_by": MANAGED_BY, "domain_id": DOMAIN_ID, "projection_id": projection_id},
        )
        registry.upsert_projection_binding(
            task_id=task_id,
            projection_selection_mode="fixed_projection",
            allowed_projection_ids=(projection_id,),
            default_projection_id=projection_id,
            projection_required=True,
            notes="模块化写作任务图配置生成。",
            metadata={"managed_by": MANAGED_BY},
        )
        registry.upsert_flow_contract_binding(
            task_id=task_id,
            flow_contract_id=flow_id,
            override_policy="task_default",
            fallback_policy="fail_closed",
            metadata={"managed_by": MANAGED_BY},
        )
        registry.upsert_task_memory_request_profile(
            task_id=task_id,
            requested_memory_layers=("state", "task_durable", "artifact_refs"),
            requested_topics=("writing_modular_novel", "baseline_memory", "dynamic_memory", "chapter_commits"),
            memory_priority="high",
            writeback_policy="task_graph_commit_edges",
            allow_long_term_memory=True,
            memory_scope_hint="writing_modular_novel",
            metadata={"managed_by": MANAGED_BY},
        )
        registry.upsert_task_agent_adoption_plan(
            task_id=task_id,
            adoption_mode="adopt_with_projection",
            default_agent_id="agent:writing_simple_worker",
            allow_worker_agent_spawn=False,
            notes="模块化写作图单元使用既有写作执行员，不额外开私门。",
            metadata={"managed_by": MANAGED_BY, "execution_chain_type": "coordination_chain"},
        )


def _upsert_modular_node_task_assets(registry: TaskFlowRegistry) -> None:
    for node_id in _all_phase_node_ids():
        source_task_id = f"{SOURCE_TASK_PREFIX}{node_id}"
        target_task_id = _modular_node_task_id(node_id)
        source_record = registry.get_specific_task_record(source_task_id)
        if source_record is None:
            raise RuntimeError(f"source writing node task not found: {source_task_id}")
        source_workflow = registry.workflow_registry.get_workflow(source_record.default_workflow_id)
        source_flow = registry.get_flow(source_record.default_flow_contract_id)
        projection_binding = registry.get_projection_binding(source_task_id)
        memory_profile = registry.get_task_memory_request_profile(source_task_id)
        adoption_plan = registry.get_task_agent_adoption_plan(source_task_id)

        target_workflow_id = _modular_workflow_id(node_id)
        target_flow_id = _modular_flow_id(node_id)
        projection_id = (
            str(getattr(projection_binding, "default_projection_id", "") or "")
            or str(dict(source_record.metadata or {}).get("projection_id") or "")
        )
        default_agent_id = str(getattr(source_flow, "default_agent_id", "") or "").strip() or "agent:writing_simple_worker"
        output_contract_id = str(source_record.output_contract_id or getattr(source_flow, "output_contract_id", "") or "").strip()
        input_contract_id = str(source_record.input_contract_id or getattr(source_flow, "input_contract_id", "") or "contract.user_request.basic").strip()

        registry.workflow_registry.upsert_workflow(
            workflow_id=target_workflow_id,
            title=f"模块化{source_record.task_title}工作流",
            compatible_projection_ids=(
                tuple(source_workflow.compatible_projection_ids)
                if source_workflow is not None and source_workflow.compatible_projection_ids
                else ((projection_id,) if projection_id else ())
            ),
            visible_skill_ids=tuple(source_workflow.visible_skill_ids) if source_workflow is not None else (),
            steps=(
                tuple(dict(item) for item in source_workflow.steps)
                if source_workflow is not None and source_workflow.steps
                else (
                    {"step_id": "read_contract_packet", "title": "读取契约化输入包"},
                    {"step_id": "execute_node", "title": "执行节点职责"},
                    {"step_id": "commit_artifact_refs", "title": "提交结构化产物引用"},
                )
            ),
            input_boundary=str(getattr(source_workflow, "input_boundary", "") or input_contract_id),
            output_boundary=str(getattr(source_workflow, "output_boundary", "") or output_contract_id),
            stop_conditions=tuple(source_workflow.stop_conditions) if source_workflow is not None else ("contract_output_ready", "blocking_issue_reported"),
            required_evidence_refs=tuple(source_workflow.required_evidence_refs) if source_workflow is not None else ("artifact_refs", "contract_payload"),
            output_contract_id=output_contract_id,
            prompt=str(getattr(source_workflow, "prompt", "") or "你需要按当前任务契约完成输出，只使用输入包中明确授权的上下文。"),
            enabled=True,
            metadata={
                **(dict(source_workflow.metadata or {}) if source_workflow is not None else {}),
                "managed_by": MANAGED_BY,
                "domain_id": DOMAIN_ID,
                "task_family": TASK_FAMILY,
                "task_id": target_task_id,
                "source_task_id": source_task_id,
                "source_workflow_id": str(source_record.default_workflow_id or ""),
            },
        )
        registry.upsert_flow(
            flow_id=target_flow_id,
            task_family=TASK_FAMILY,
            title=f"模块化{source_record.task_title}",
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            default_agent_id=default_agent_id,
            default_workflow_id=target_workflow_id,
            default_runtime_lane=str(getattr(source_flow, "default_runtime_lane", "") or source_record.runtime_lane or "coordination_task"),
            default_memory_scope="writing_modular_novel",
            enabled=True,
            metadata={
                **(dict(source_flow.metadata or {}) if source_flow is not None else {}),
                "managed_by": MANAGED_BY,
                "domain_id": DOMAIN_ID,
                "task_id": target_task_id,
                "source_task_id": source_task_id,
                "source_flow_id": str(source_record.default_flow_contract_id or ""),
            },
        )
        task_policy = copy.deepcopy(source_record.task_policy or {})
        task_structure = dict(task_policy.get("task_structure") or {})
        task_structure.update(
            {
                "memory_scope_hint": "writing_modular_novel",
                "task_resource_kind": target_task_id,
                "source_task_id": source_task_id,
                "modular_task_graph_node": True,
                "projection_id": projection_id or task_structure.get("projection_id", ""),
            }
        )
        task_policy["task_structure"] = task_structure
        registry.upsert_specific_task_record(
            task_id=target_task_id,
            task_title=f"模块化{source_record.task_title}",
            task_family=TASK_FAMILY,
            description=f"模块化长篇写作节点任务：{source_record.task_title}。职责继承原节点语义，但任务身份归属模块化任务图。",
            enabled=True,
            runtime_lane=str(source_record.runtime_lane or getattr(source_flow, "default_runtime_lane", "") or "coordination_task"),
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            acceptance_profile_id=str(source_record.acceptance_profile_id or ""),
            default_flow_contract_id=target_flow_id,
            default_workflow_id=target_workflow_id,
            default_projection_policy=str(source_record.default_projection_policy or "task_default_required"),
            task_policy=task_policy,
            metadata={
                **dict(source_record.metadata or {}),
                "managed_by": MANAGED_BY,
                "domain_id": DOMAIN_ID,
                "task_id": target_task_id,
                "source_task_id": source_task_id,
                "source_task_family": str(source_record.task_family or ""),
                "projection_id": projection_id,
                "package_template": TASK_FAMILY,
            },
        )
        if projection_binding is not None:
            registry.upsert_projection_binding(
                task_id=target_task_id,
                projection_selection_mode=str(projection_binding.projection_selection_mode or "task_default_required"),
                allowed_projection_ids=tuple(projection_binding.allowed_projection_ids),
                default_projection_id=projection_id,
                projection_required=bool(projection_binding.projection_required),
                notes="模块化长篇写作节点复用原写作投影，不改变 Agent 职责提示。",
                metadata={**dict(projection_binding.metadata or {}), "managed_by": MANAGED_BY, "source_task_id": source_task_id},
            )
        registry.upsert_flow_contract_binding(
            task_id=target_task_id,
            flow_contract_id=target_flow_id,
            override_policy="task_default",
            verification_gate_profile="",
            fallback_policy="fail_closed",
            metadata={"managed_by": MANAGED_BY, "source_task_id": source_task_id},
        )
        if memory_profile is not None:
            registry.upsert_task_memory_request_profile(
                task_id=target_task_id,
                requested_memory_layers=tuple(memory_profile.requested_memory_layers),
                requested_topics=tuple(
                    dict.fromkeys(
                        [
                            "writing_modular_novel",
                            *[str(item).strip() for item in memory_profile.requested_topics if str(item).strip()],
                        ]
                    )
                ),
                memory_priority=str(memory_profile.memory_priority or "normal"),
                writeback_policy=str(memory_profile.writeback_policy or "task_default"),
                allow_long_term_memory=bool(memory_profile.allow_long_term_memory),
                memory_scope_hint="writing_modular_novel",
                metadata={**dict(memory_profile.metadata or {}), "managed_by": MANAGED_BY, "source_task_id": source_task_id},
            )
        registry.upsert_task_agent_adoption_plan(
            task_id=target_task_id,
            adoption_mode=str(getattr(adoption_plan, "adoption_mode", "") or "adopt_with_projection"),
            default_agent_id=str(getattr(adoption_plan, "default_agent_id", "") or default_agent_id),
            allow_worker_agent_spawn=bool(getattr(adoption_plan, "allow_worker_agent_spawn", False)),
            worker_agent_blueprint_id=str(getattr(adoption_plan, "worker_agent_blueprint_id", "") or ""),
            worker_agent_naming_rule=str(getattr(adoption_plan, "worker_agent_naming_rule", "") or ""),
            notes="模块化写作节点复用既有写作 Agent 能力，不新增写作专用后端入口。",
            metadata={"managed_by": MANAGED_BY, "source_task_id": source_task_id, "execution_chain_type": "coordination_node"},
        )


def _upsert_child_graph(
    *,
    registry: TaskFlowRegistry,
    source_graph: dict[str, Any],
    source_nodes: dict[str, dict[str, Any]],
    source_edges: list[dict[str, Any]],
    graph_id: str,
    node_ids: tuple[str, ...],
) -> None:
    selected = set(node_ids)
    retained_edges = _phase_edges_with_resource_access(source_edges=source_edges, selected=selected)
    resource_node_ids = tuple(
        node_id
        for node_id in _resource_node_ids_for_edges(retained_edges=retained_edges, selected=selected)
        if node_id in source_nodes
    )
    graph_node_ids = tuple(dict.fromkeys([*node_ids, *resource_node_ids]))
    nodes = [_node_for_child_graph(source_nodes[node_id], graph_id=graph_id, graph_node_ids=graph_node_ids) for node_id in graph_node_ids]
    edges = [_edge_for_child_graph(edge) for edge in retained_edges]
    if graph_id == CHAPTER_GRAPH_ID:
        nodes = [_with_chapter_runtime_contracts(node) for node in nodes]

    metadata = {
        "managed_by": MANAGED_BY,
        "source_graph_id": SOURCE_GRAPH_ID,
        "source_node_ids": list(graph_node_ids),
        "architecture": "modular_task_graph_child",
        "business_communication_modes": ["structured_handoff", "memory_read", "memory_commit", "revision_request"],
        "phase_definitions": _phase_definitions_for_nodes(nodes),
        "subtask_refs": [str(node.get("task_id") or "") for node in nodes if str(node.get("task_id") or "").startswith("task.")],
        "editor_publish_state": "published",
        "graph_unit_role": graph_id.rsplit(".", 1)[-1],
    }
    if graph_id == CHAPTER_GRAPH_ID:
        metadata["unit_batch_contract"] = {
            "unit_kind": "chapter",
            "requested_count": CHAPTER_REQUESTED_COUNT,
            "batch_size": CHAPTER_BATCH_SIZE,
            "target_volumes": TARGET_VOLUMES,
            "chapters_per_volume": CHAPTERS_PER_VOLUME,
            "source_path": "graph.metadata.runtime_loop_policy.initial_inputs",
        }
        metadata["runtime_loop_policy"] = _chapter_runtime_loop_policy()
        metadata["loop_frames"] = list(_chapter_runtime_loop_policy()["frames"])

    registry.upsert_task_graph(
        graph_id=graph_id,
        title=GRAPH_TITLES[graph_id],
        domain_id=DOMAIN_ID,
        task_family=TASK_FAMILY,
        graph_kind="coordination",
        entry_node_id=node_ids[0],
        output_node_id=node_ids[-1],
        nodes=tuple(nodes),
        edges=tuple(edges),
        graph_contract_id=_graph_contract_id(graph_id),
        contract_bindings=_graph_contract_bindings(graph_id),
        default_protocol_id=PROTOCOL_ID,
        working_memory_policy_profile_id="wmprofile.writing.modular_novel",
        working_memory_policy=_working_memory_policy(source_graph),
        runtime_policy={
            "execution_mode": "coordinator_driven",
            "coordinator_agent_id": "agent:0",
            "agent_group_id": "group.writing.simple_novel",
            "default_execution_mode": "sync",
            "default_wait_policy": "wait_all_upstream_completed",
            "default_join_policy": "all_success",
            "human_gate_mode": "auto_continue",
            "task_run_scope_policy": "isolated_per_task_run",
            "failure_policy": "fail_closed",
        },
        context_policy={"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_and_summary_only"},
        publish_state="published",
        enabled=True,
        metadata=metadata,
    )


def _node_for_child_graph(node: dict[str, Any], *, graph_id: str, graph_node_ids: tuple[str, ...]) -> dict[str, Any]:
    result = copy.deepcopy(node)
    node_id = str(result.get("node_id") or "")
    source_task_id = str(result.get("task_id") or "")
    if source_task_id.startswith(SOURCE_TASK_PREFIX):
        result["task_id"] = _modular_node_task_id(node_id)
    result["metadata"] = {
        **dict(result.get("metadata") or {}),
        "managed_by": MANAGED_BY,
        "source_graph_id": SOURCE_GRAPH_ID,
        "source_node_id": result.get("node_id"),
        "source_task_id": source_task_id,
        "modular_graph_id": graph_id,
        "model_profile_ref": MODEL_PROFILE_REF,
    }
    result["contract_bindings"] = _with_model_requirement(dict(result.get("contract_bindings") or {}), node_id=node_id)
    result["phase_id"] = _modular_phase_id(graph_id, str(result.get("phase_id") or ""))
    result["sequence_index"] = _sequence_index(graph_node_ids, node_id)
    return result


def _edge_for_child_graph(edge: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(edge)
    result["metadata"] = {
        **dict(result.get("metadata") or {}),
        "managed_by": MANAGED_BY,
        "source_graph_id": SOURCE_GRAPH_ID,
        "source_edge_id": result.get("edge_id"),
    }
    result["contract_bindings"] = dict(result.get("contract_bindings") or {})
    return result


def _phase_edges_with_resource_access(*, source_edges: list[dict[str, Any]], selected: set[str]) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in source_edges:
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        edge_type = str(edge.get("edge_type") or edge.get("mode") or "")
        direct_business_edge = source in selected and target in selected
        resource_edge = edge_type in {"memory_read", "memory_write_candidate", "memory_commit"} and (
            source in selected or target in selected
        )
        if not direct_business_edge and not resource_edge:
            continue
        edge_id = str(edge.get("edge_id") or f"{source}->{target}:{len(retained)}")
        if edge_id in seen:
            continue
        retained.append(edge)
        seen.add(edge_id)
    return retained


def _resource_node_ids_for_edges(*, retained_edges: list[dict[str, Any]], selected: set[str]) -> list[str]:
    resource_ids: list[str] = []
    for edge in retained_edges:
        edge_type = str(edge.get("edge_type") or edge.get("mode") or "")
        if edge_type not in {"memory_read", "memory_write_candidate", "memory_commit"}:
            continue
        for key in ("source_node_id", "target_node_id"):
            node_id = str(edge.get(key) or "")
            if node_id and node_id not in selected and node_id not in resource_ids:
                resource_ids.append(node_id)
    return resource_ids


def _with_chapter_runtime_contracts(node: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(node)
    node_id = str(result.get("node_id") or "")
    if node_id == "chapter_draft":
        result = _with_chapter_batch_contract(result)
    if node_id in {"chapter_outline", "chapter_draft", "chapter_review", "memory_commit_chapter", "chapter_progress_router"}:
        result = _with_loop_node_policy(
            result,
            loop_scope_id="loop.chapter_batch",
            title_template="{batch_label}批次" + str(result.get("title") or node_id),
        )
    if node_id in {
        "volume_review",
        "volume_commit",
        "volume_postmortem",
        "world_outline_extension_proposal",
        "extension_review",
        "extension_commit",
        "next_volume_router",
    }:
        result = _with_loop_node_policy(
            result,
            loop_scope_id="loop.volume",
            title_template="{volume_label}" + str(result.get("title") or node_id),
        )
    if node_id == "chapter_progress_router":
        result["loop_route_policy"] = _chapter_progress_route_policy()
        result["metadata"] = {
            **dict(result.get("metadata") or {}),
            "loop_route_policy": _chapter_progress_route_policy(),
            "loop_scope_id": "loop.chapter_batch",
            "title_template": result.get("title_template"),
        }
    if node_id == "next_volume_router":
        result["loop_route_policy"] = _next_volume_route_policy()
        result["metadata"] = {
            **dict(result.get("metadata") or {}),
            "loop_route_policy": _next_volume_route_policy(),
            "loop_scope_id": "loop.volume",
            "title_template": result.get("title_template"),
        }
    return result


def _with_loop_node_policy(node: dict[str, Any], *, loop_scope_id: str, title_template: str) -> dict[str, Any]:
    result = copy.deepcopy(node)
    result["loop_policy"] = {
        "loop_kind": "bounded_metric_iteration",
        "loop_variable": "batch_start_index" if loop_scope_id == "loop.chapter_batch" else "volume_index",
        "iteration_size_key": "chapters_per_round" if loop_scope_id == "loop.chapter_batch" else "target_volumes",
        "iteration_size": CHAPTER_BATCH_SIZE if loop_scope_id == "loop.chapter_batch" else TARGET_VOLUMES,
        "exit_decision": "volume_target_reached" if loop_scope_id == "loop.chapter_batch" else "target_volumes_reached",
    }
    result["loop_kind"] = result["loop_policy"]["loop_kind"]
    result["loop_scope_id"] = loop_scope_id
    result["title_template"] = title_template
    result["metadata"] = {
        **dict(result.get("metadata") or {}),
        "loop_policy": dict(result["loop_policy"]),
        "loop_kind": result["loop_kind"],
        "loop_scope_id": loop_scope_id,
        "title_template": title_template,
    }
    return result


def _with_chapter_batch_contract(node: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(node)
    bindings = dict(result.get("contract_bindings") or {})
    runtime = dict(bindings.get("runtime") or {})
    runtime["split_policy"] = {
        "mode": "static_batch",
        "batch_size": CHAPTER_BATCH_SIZE,
        "range_label_template": "chapter_{start}_{end}",
        "child_execution_mode": "sequential",
        "max_batches": 200,
        "source": "contract_bindings.runtime.split_policy",
    }
    runtime["batch_acceptance_policy"] = {
        "mode": "review_then_commit",
        "review_graph_id": CHAPTER_GRAPH_ID,
        "review_node_id": "chapter_review",
        "repair_policy": "repair_until_pass_or_manual_gate",
        "max_repair_rounds": 3,
        "commit_visibility": "next_batch_after_acceptance",
    }
    runtime["merge_policy"] = {
        "mode": "wait_all_committed",
        "result_order": "batch_sequence",
        "allow_partial": False,
        "final_review_required": True,
    }
    bindings["runtime"] = runtime
    bindings["unit_batch"] = {
        "unit_kind": "chapter",
        "requested_count": CHAPTER_REQUESTED_COUNT,
        "range_start": 1,
        "input_contract_id": "contract.writing.modular_novel.chapter_batch_request",
        "output_contract_id": "contract.writing.modular_novel.chapter_batch_commit",
        "metadata": {
            "unit_label_zh": "章节",
            "requested_by": "user_requirement",
            "scope": "target_volume_batch_preview",
            "batch_review_required": True,
            "flow_control_owner": "graph.metadata.runtime_loop_policy",
        },
    }
    result["contract_bindings"] = bindings
    result["metadata"] = {
        **dict(result.get("metadata") or {}),
        "unit_batch_source": "contract_bindings",
        "unit_batch_role": "split_preview_not_flow_controller",
        "requested_chapters": CHAPTER_REQUESTED_COUNT,
        "chapter_batch_size": CHAPTER_BATCH_SIZE,
    }
    return result


def _chapter_runtime_loop_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "loop_owner": "graph",
        "flow_control": "chapter_batch_and_volume_frames",
        "initial_inputs": _chapter_initial_runtime_loop_inputs(),
        "derived_fields": _chapter_loop_derived_fields(),
        "summary": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；本次目标 {target_volumes} 卷；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。",
        "frames": [
            {
                "frame_id": "loop.chapter_batch",
                "title": "章节批次循环",
                "entry_stage_id": "chapter_outline",
                "router_stage_id": "chapter_progress_router",
                "continue_stage_id": "chapter_outline",
                "exit_stage_id": "volume_review",
                "unit_kind": "chapter",
                "iteration_size_key": "chapters_per_round",
            },
            {
                "frame_id": "loop.volume",
                "title": "分卷大循环",
                "entry_stage_id": "volume_plan",
                "router_stage_id": "next_volume_router",
                "continue_stage_id": "volume_plan",
                "exit_stage_id": "__graph_unit_complete__",
                "unit_kind": "volume",
                "iteration_size_key": "target_volumes",
            },
        ],
    }


def _chapter_initial_runtime_loop_inputs() -> dict[str, Any]:
    return {
        "target_volumes": TARGET_VOLUMES,
        "volume_index": 1,
        "volume_current_words": 0,
        "volume_target_words": VOLUME_TARGET_WORDS,
        "chapters_per_volume": CHAPTERS_PER_VOLUME,
        "chapter_index": 1,
        "chapters_per_round": CHAPTER_BATCH_SIZE,
        "chapter_batch_size": CHAPTER_BATCH_SIZE,
        "target_chapters": CHAPTER_REQUESTED_COUNT,
        "metric_label": "words",
        "target_metric_total": TARGET_WORDS,
        "target_words": TARGET_WORDS,
        "current_words": 0,
        "chapter_target_words": CHAPTER_TARGET_WORDS,
    }


def _chapter_loop_derived_fields() -> list[dict[str, Any]]:
    return [
        {"key": "volume_index_padded", "op": "format", "template": "{volume_index:03d}"},
        {"key": "volume_label", "op": "format", "template": "第{volume_index}卷"},
        {"key": "chapter_index_padded", "op": "format", "template": "{chapter_index:03d}"},
        {"key": "chapter_label", "op": "format", "template": "第{chapter_index}章"},
        {"key": "chapter_file_prefix", "op": "format", "template": "chapter_{chapter_index:03d}"},
        {"key": "batch_start_index", "op": "copy", "from_key": "chapter_index"},
        {"key": "batch_end_index", "op": "add", "from_key": "chapter_index", "value_key": "chapters_per_round", "value": CHAPTER_BATCH_SIZE - 1, "offset": -1},
        {"key": "batch_index", "op": "ordinal_group", "from_key": "chapter_index", "size_key": "chapters_per_round", "size": CHAPTER_BATCH_SIZE},
        {"key": "batch_index_padded", "op": "format", "template": "{batch_index:03d}"},
        {"key": "batch_start_index_padded", "op": "format", "template": "{batch_start_index:03d}"},
        {"key": "batch_end_index_padded", "op": "format", "template": "{batch_end_index:03d}"},
        {"key": "batch_chapter_range", "op": "format", "template": "{batch_start_index:03d}-{batch_end_index:03d}"},
        {"key": "batch_label", "op": "format", "template": "第{batch_start_index}章至第{batch_end_index}章"},
        {"key": "batch_chapter_numbers", "op": "range", "start_key": "batch_start_index", "end_key": "batch_end_index"},
        {"key": "batch_chapter_list", "op": "join", "from_key": "batch_chapter_numbers", "prefix": "第", "suffix": "章", "separator": "、"},
        {"key": "batch_target_words", "op": "multiply", "from_key": "chapter_target_words", "value_key": "chapters_per_round", "value": CHAPTER_BATCH_SIZE},
        {"key": "runtime_loop_summary", "op": "format", "template": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；本次目标 {target_volumes} 卷；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。"},
    ]


def _chapter_progress_route_policy() -> dict[str, Any]:
    return {
        "mode": "metric_target",
        "loop_scope_id": "loop.chapter_batch",
        "continue_stage_id": "chapter_outline",
        "exit_stage_id": "volume_review",
        "metric_key": "chapter_words",
        "diagnostic_metric_key": "chapter_words",
        "fallback_increment_key": "batch_target_words",
        "default_increment": CHAPTER_TARGET_WORDS * CHAPTER_BATCH_SIZE,
        "current_key": "volume_current_words",
        "target_key": "volume_target_words",
        "last_metric_key": "last_batch_words",
        "secondary_counters": [{"current_key": "current_words", "target_key": "target_words"}],
        "counter_updates": [{"key": "chapter_index", "mode": "increment", "step_key": "chapters_per_round", "step": CHAPTER_BATCH_SIZE}],
        "derived_fields": _chapter_loop_derived_fields(),
    }


def _next_volume_route_policy() -> dict[str, Any]:
    return {
        "mode": "metric_target",
        "loop_scope_id": "loop.volume",
        "continue_stage_id": "volume_plan",
        "exit_stage_id": "__graph_unit_complete__",
        "metric_key": "volume_router_metric",
        "default_increment": 1,
        "current_key": "completed_volumes",
        "target_key": "target_volumes",
        "counter_updates": [
            {"key": "volume_index", "mode": "increment", "step": 1},
            {"key": "volume_current_words", "mode": "reset", "value": 0},
        ],
        "derived_fields": _chapter_loop_derived_fields(),
    }


def _upsert_master_graph(*, registry: TaskFlowRegistry) -> None:
    nodes = (
        _graph_unit_node(
            node_id="graph_unit.design_init",
            title="设计初始化图",
            task_id="task.writing.modular_novel.design_init",
            linked_graph_id=DESIGN_GRAPH_ID,
            phase_id="phase.master.design_init",
            sequence_index=10,
        ),
        _graph_unit_node(
            node_id="graph_unit.chapter_cycle",
            title="章节批次创作图",
            task_id="task.writing.modular_novel.chapter_cycle",
            linked_graph_id=CHAPTER_GRAPH_ID,
            phase_id="phase.master.chapter_cycle",
            sequence_index=20,
        ),
        _graph_unit_node(
            node_id="graph_unit.finalize",
            title="收尾交付图",
            task_id="task.writing.modular_novel.finalize",
            linked_graph_id=FINALIZE_GRAPH_ID,
            phase_id="phase.master.finalize",
            sequence_index=30,
        ),
    )
    edges = (
        _master_edge(
            "edge.design_init.chapter_cycle",
            "graph_unit.design_init",
            "graph_unit.chapter_cycle",
            "设计初始化提交后进入章节批次创作。",
        ),
        _master_edge(
            "edge.chapter_cycle.finalize",
            "graph_unit.chapter_cycle",
            "graph_unit.finalize",
            "目标卷数完成并形成卷级提交后进入收尾交付。",
        ),
    )
    timeline_blocks = (
        _timeline_block("design_init", "设计初始化图", DESIGN_GRAPH_ID, "phase.master.design_init", 10),
        _timeline_block("chapter_cycle", "章节批次创作图", CHAPTER_GRAPH_ID, "phase.master.chapter_cycle", 20),
        _timeline_block("finalize", "收尾交付图", FINALIZE_GRAPH_ID, "phase.master.finalize", 30),
    )
    registry.upsert_task_graph(
        graph_id=MASTER_GRAPH_ID,
        title=GRAPH_TITLES[MASTER_GRAPH_ID],
        domain_id=DOMAIN_ID,
        task_family=TASK_FAMILY,
        graph_kind="coordination",
        entry_node_id="graph_unit.design_init",
        output_node_id="graph_unit.finalize",
        nodes=nodes,
        edges=edges,
        graph_contract_id="contract.writing.modular_novel.graph",
        contract_bindings={
            "schema": {"graph_contract_id": "contract.writing.modular_novel.graph"},
            "runtime": {
                "model_requirement": _model_requirement("master"),
                "graph_unit_composition": {
                    "mode": "sequential_nested_runtime",
                    "graph_unit_count": 3,
                    "child_run_scope": "isolated_per_nested_run",
                },
            },
            "governance": {"no_writing_specific_backend_shortcut": True},
        },
        default_protocol_id=PROTOCOL_ID,
        working_memory_policy_profile_id="wmprofile.writing.modular_novel",
        working_memory_policy={
            "memory_scope": "writing_modular_novel",
            "access_model": "graph_unit_committed_refs_only",
            "conversation_memory": "suppressed_for_creator_and_reviewer",
            "raw_full_text_global_context": "forbidden",
        },
        runtime_policy={
            "execution_mode": "coordinator_driven",
            "coordinator_agent_id": "agent:0",
            "agent_group_id": "group.writing.simple_novel",
            "default_execution_mode": "sync",
            "default_wait_policy": "wait_all_upstream_completed",
            "default_join_policy": "all_success",
            "human_gate_mode": "auto_continue",
            "task_run_scope_policy": "isolated_per_task_run",
            "failure_policy": "fail_closed",
        },
        context_policy={"handoff": "contract_payload_and_refs", "raw_dialogue_handoff": "forbidden", "long_text_policy": "artifact_ref_and_summary_only"},
        publish_state="published",
        enabled=True,
        metadata={
            "managed_by": MANAGED_BY,
            "architecture": "graph_as_first_class_task_unit",
            "graph_unit_composition": True,
            "timeline_blocks": list(timeline_blocks),
            "phase_definitions": [
                {"phase_id": "phase.master.design_init", "title": "设计初始化", "sequence_index": 10},
                {"phase_id": "phase.master.chapter_cycle", "title": "分卷创作循环", "sequence_index": 20},
                {"phase_id": "phase.master.finalize", "title": "收尾交付", "sequence_index": 30},
            ],
            "runtime_loop_policy": {
                "enabled": True,
                "flow_control": "graph_unit_sequence",
                "initial_inputs": {
                    "target_volumes": TARGET_VOLUMES,
                    "chapters_per_volume": CHAPTERS_PER_VOLUME,
                    "chapters_per_round": CHAPTER_BATCH_SIZE,
                    "chapter_batch_size": CHAPTER_BATCH_SIZE,
                    "chapter_target_words": CHAPTER_TARGET_WORDS,
                    "target_chapters": CHAPTER_REQUESTED_COUNT,
                    "target_words": TARGET_WORDS,
                },
                "frames": [
                    {"frame_id": "graph_unit.design_init", "entry_stage_id": "graph_unit.design_init", "exit_stage_id": "graph_unit.chapter_cycle"},
                    {"frame_id": "graph_unit.chapter_cycle", "entry_stage_id": "graph_unit.chapter_cycle", "exit_stage_id": "graph_unit.finalize"},
                ],
            },
            "composable_graph": {
                "version": "v1",
                "port_edges": [
                    {
                        "edge_id": "port_edge.design_init.chapter_cycle",
                        "source_unit_id": "unit.graph.design_init",
                        "source_port_id": "output.default",
                        "target_unit_id": "unit.graph.chapter_cycle",
                        "target_port_id": "input.default",
                        "payload_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
                        "temporal_semantics": {"trigger_timing": "after_source_commit", "visibility_timing": "committed_only"},
                    },
                    {
                        "edge_id": "port_edge.chapter_cycle.finalize",
                        "source_unit_id": "unit.graph.chapter_cycle",
                        "source_port_id": "output.default",
                        "target_unit_id": "unit.graph.finalize",
                        "target_port_id": "input.default",
                        "payload_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
                        "temporal_semantics": {"trigger_timing": "after_source_commit", "visibility_timing": "committed_only"},
                    },
                ],
            },
            "subtask_refs": [
                "task.writing.modular_novel.design_init",
                "task.writing.modular_novel.chapter_cycle",
                "task.writing.modular_novel.finalize",
            ],
            "editor_publish_state": "published",
        },
    )


def _graph_unit_node(*, node_id: str, title: str, task_id: str, linked_graph_id: str, phase_id: str, sequence_index: int) -> dict[str, Any]:
    block_id = node_id.removeprefix("graph_unit.")
    return {
        "node_id": node_id,
        "node_type": "graph_unit",
        "title": title,
        "task_id": task_id,
        "agent_id": "agent:writing_simple_worker",
        "work_posture": "graph_unit_runner",
        "projection_id": "projection.writing.simple_novel.project_brief",
        "phase_id": phase_id,
        "sequence_index": sequence_index,
        "execution_mode": "async",
        "wait_policy": "wait_all_upstream_completed",
        "join_policy": "all_success",
        "blocks_phase_exit": True,
        "executor_policy": {
            "default_executor": "graph_unit",
            "allowed_executors": ["graph_unit"],
            "subgraph_id": linked_graph_id,
            "auto_start_child_initial_stage": True,
        },
        "context_visibility_policy": {
            "shared_context_policy": "explicit_refs_only",
            "nested_runtime_visibility": "committed_only",
            "parent_visible_scope": "run_handle_and_committed_output",
        },
        "contract_bindings": {
            "schema": {
                "input_contract_id": "contract.user_request.basic",
                "output_contract_id": _graph_contract_id(linked_graph_id),
            },
            "execution": {
                "node_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
            },
            "handoff": {
                "handoff_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
                "visibility_policy": "committed_only",
            },
            "runtime": {
                "model_requirement": _model_requirement(block_id),
                "nested_runtime": {
                    "linked_graph_id": linked_graph_id,
                    "version_ref": "published",
                    "isolation_policy": "isolated_per_nested_run",
                },
            },
        },
        "metadata": {
            "managed_by": MANAGED_BY,
            "graph_unit": True,
            "linked_graph_id": linked_graph_id,
            "version_ref": "published",
            "handoff_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
            "input_port_id": "input.default",
            "output_port_id": "output.default",
            "isolation_policy": "isolated_per_nested_run",
            "visibility_policy": "committed_only",
            "detach_policy": "preserve_version_anchor",
            "execution_mode": "nested_graph_run",
            "nested_runtime_plan_id": f"nested.{block_id}",
        },
    }


def _master_edge(edge_id: str, source: str, target: str, summary: str) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": "structured_handoff",
        "payload_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
        "ack_policy": "explicit_ack",
        "ack_required": True,
        "failure_propagation_policy": "fail_downstream",
        "result_delivery_policy": "contract_payload_and_refs",
        "contract_bindings": {
            "schema": {"payload_contract_id": "contract.writing.modular_novel.graph_unit_handoff"},
            "handoff": {
                "handoff_contract_id": "contract.writing.modular_novel.graph_unit_handoff",
                "trigger_timing": "after_source_commit",
                "visibility_policy": "committed_only",
            },
            "temporal": {
                "trigger_timing": "after_source_commit",
                "visibility_timing": "committed_only",
                "propagation_timing": "next_graph_unit",
            },
        },
        "metadata": {
            "managed_by": MANAGED_BY,
            "handoff_summary": summary,
            "required_refs": ["committed_output_refs", "child_run_ref"],
            "dependency_role": "graph_unit_sequence",
            "temporal_semantics": {"trigger_timing": "after_source_commit", "visibility_timing": "committed_only"},
        },
    }


def _timeline_block(block_id: str, title: str, linked_graph_id: str, phase_id: str, sequence_index: int) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "block_type": "graph_unit",
        "title": title,
        "phase_id": phase_id,
        "linked_graph_id": linked_graph_id,
        "version_ref": "published",
        "entry_node_id": "",
        "exit_node_id": "",
        "input_port_id": "input.default",
        "output_port_id": "output.default",
        "isolation_policy": "isolated_per_nested_run",
        "visibility_policy": "committed_only",
        "detach_policy": "preserve_version_anchor",
        "contract_bindings": {
            "handoff": {"handoff_contract_id": "contract.writing.modular_novel.graph_unit_handoff"},
            "runtime": {"sequence_index": sequence_index},
        },
        "metadata": {"managed_by": MANAGED_BY, "sequence_index": sequence_index},
    }


def _with_model_requirement(bindings: dict[str, Any], *, node_id: str) -> dict[str, Any]:
    result = copy.deepcopy(bindings)
    runtime = dict(result.get("runtime") or {})
    runtime["model_requirement"] = _model_requirement(node_id)
    result["runtime"] = runtime
    return result


def _model_requirement(node_id: str) -> dict[str, Any]:
    preferred = 65536 if node_id in {"chapter_draft", "chapter_cycle"} else 32768 if node_id in {"volume_plan", "final_assemble"} else 16384
    return {
        "profile_ref": MODEL_PROFILE_REF,
        "provider_family": "deepseek",
        "model_family": "deepseek-v4",
        "capability_tags": ["long_output", "structured_artifact_refs", "creative_writing"],
        "min_context_tokens": 200000,
        "min_output_tokens": 8192,
        "preferred_output_tokens": preferred,
        "streaming_required": True,
        "fallback_allowed": True,
        "metadata": {"configured_by": MANAGED_BY, "node_id": node_id},
    }


def _graph_contract_id(graph_id: str) -> str:
    if graph_id == DESIGN_GRAPH_ID:
        return "contract.writing.modular_novel.design_commit"
    if graph_id == CHAPTER_GRAPH_ID:
        return "contract.writing.modular_novel.chapter_batch_commit"
    if graph_id == FINALIZE_GRAPH_ID:
        return "contract.writing.modular_novel.final_delivery"
    return "contract.writing.modular_novel.graph"


def _graph_contract_bindings(graph_id: str) -> dict[str, Any]:
    bindings: dict[str, Any] = {
        "schema": {"graph_contract_id": _graph_contract_id(graph_id)},
        "runtime": {"model_requirement": _model_requirement(graph_id.rsplit(".", 1)[-1])},
        "governance": {"no_writing_specific_backend_shortcut": True, "contract_source": "contract_bindings"},
    }
    if graph_id == CHAPTER_GRAPH_ID:
        bindings["unit_batch"] = {
            "unit_kind": "chapter",
            "requested_count": CHAPTER_REQUESTED_COUNT,
            "batch_size": CHAPTER_BATCH_SIZE,
            "range_start": 1,
            "target_volumes": TARGET_VOLUMES,
            "chapters_per_volume": CHAPTERS_PER_VOLUME,
            "chapter_target_words": CHAPTER_TARGET_WORDS,
            "volume_target_words": VOLUME_TARGET_WORDS,
            "unit_label_zh": "章节",
            "source": "metadata.runtime_loop_policy.initial_inputs",
            "source_node_id": "chapter_cycle_graph",
        }
        runtime = dict(bindings.get("runtime") or {})
        runtime["loop_policy_ref"] = "metadata.runtime_loop_policy"
        runtime["split_policy"] = {
            "mode": "static_batch",
            "batch_size": CHAPTER_BATCH_SIZE,
            "range_label_template": "chapter_{start}_{end}",
            "child_execution_mode": "sequential",
            "source": "graph.contract_bindings.runtime.split_policy",
            "flow_control_owner": "metadata.runtime_loop_policy.frames",
        }
        bindings["runtime"] = runtime
    return bindings


def _all_phase_node_ids() -> tuple[str, ...]:
    return tuple(dict.fromkeys(node_id for node_ids in PHASE_TASKS.values() for node_id in node_ids))


def _modular_node_task_id(node_id: str) -> str:
    return f"task.writing.modular_novel.node.{_safe_id(node_id)}"


def _modular_flow_id(node_id: str) -> str:
    return f"flow.writing.modular_novel.node.{_safe_id(node_id)}"


def _modular_workflow_id(node_id: str) -> str:
    return f"workflow.writing.modular_novel.node.{_safe_id(node_id)}"


def _working_memory_policy(source_graph: dict[str, Any]) -> dict[str, Any]:
    policy = copy.deepcopy(source_graph.get("working_memory_policy") or {})
    policy["memory_scope"] = "writing_modular_novel"
    policy["source_memory_scope"] = policy.get("memory_scope") or "writing_simple_novel"
    policy["raw_full_text_global_context"] = "forbidden"
    policy["access_model"] = "edge_based_repository_access"
    policy["graph_unit_boundary"] = "committed_refs_only"
    return policy


def _phase_definitions_for_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases: dict[str, dict[str, Any]] = {}
    for node in nodes:
        phase_id = str(node.get("phase_id") or "phase.unassigned")
        phases.setdefault(
            phase_id,
            {
                "phase_id": phase_id,
                "title": phase_id.removeprefix("phase.modular."),
                "sequence_index": int(node.get("sequence_index") or 0),
            },
        )
    return list(phases.values())


def _modular_phase_id(graph_id: str, old_phase_id: str) -> str:
    suffix = graph_id.rsplit(".", 1)[-1]
    clean = str(old_phase_id or "phase").removeprefix("phase.")
    return f"phase.modular.{suffix}.{clean}"


def _sequence_index(node_ids: tuple[str, ...], node_id: str) -> int:
    try:
        return (node_ids.index(node_id) + 1) * 10
    except ValueError:
        return 999


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "")).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure modular writing task graphs.")
    parser.add_argument("--base-dir", default=str(BACKEND_DIR), help="Backend dir or project root. Defaults to repo backend.")
    args = parser.parse_args()
    configure(Path(args.base_dir))


if __name__ == "__main__":
    main()
