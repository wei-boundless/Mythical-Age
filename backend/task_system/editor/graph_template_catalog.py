from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskGraphTemplateSlot:
    slot_id: str
    title: str
    semantic_role: str
    required: bool = True
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    default_node_type: str = "agent_role"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphTemplateMemoryLayer:
    layer_id: str
    title: str
    repository_role: str
    mutable: bool
    collections: tuple[str, ...] = ()
    collection_specs: tuple[dict[str, Any], ...] = ()
    write_policy: str = "commit_only"
    read_policy: str = "explicit_edges_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        collection_specs = [dict(item) for item in self.collection_specs]
        payload["collection_specs"] = collection_specs
        payload["collections"] = list(self.collections) or [
            str(item.get("collection_id") or "").strip()
            for item in collection_specs
            if str(item.get("collection_id") or "").strip()
        ]
        return payload


@dataclass(frozen=True, slots=True)
class TaskGraphTemplateDefinition:
    template_id: str
    title: str
    intent: str
    best_for: str
    structure_pattern: str
    slots: tuple[TaskGraphTemplateSlot, ...] = ()
    memory_layers: tuple[TaskGraphTemplateMemoryLayer, ...] = ()
    artifact_layers: tuple[dict[str, Any], ...] = ()
    validation_rules: tuple[dict[str, Any], ...] = ()
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["slots"] = [item.to_dict() for item in self.slots]
        payload["memory_layers"] = [item.to_dict() for item in self.memory_layers]
        payload["artifact_layers"] = [dict(item) for item in self.artifact_layers]
        payload["validation_rules"] = [dict(item) for item in self.validation_rules]
        return payload


def _slot(
    slot_id: str,
    title: str,
    semantic_role: str,
    *,
    default_node_type: str = "agent_role",
    required: bool = True,
) -> TaskGraphTemplateSlot:
    return TaskGraphTemplateSlot(
        slot_id=slot_id,
        title=title,
        semantic_role=semantic_role,
        required=required,
        default_node_type=default_node_type,
        prompt_contract={
            "role_identity_required": True,
            "responsibility_scope_required": True,
            "responsibility_exclusions_required": True,
            "definition_of_done_required": True,
            "developer_description_forbidden": True,
        },
    )


def _canonical_requirement() -> dict[str, bool]:
    return {"canonical_text_required": True, "artifact_ref_only_allowed": False}


def _refs_only_requirement() -> dict[str, bool]:
    return {"canonical_text_required": False, "artifact_ref_only_allowed": True}


def _collection_spec(
    collection_id: str,
    *,
    content_requirement: dict[str, Any],
    schema_id: str = "",
    record_kinds: tuple[str, ...] = (),
    snapshot_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "collection_id": collection_id,
        "title": collection_id.replace("_", " "),
        "schema_id": schema_id,
        "record_kinds": list(record_kinds or (collection_id,)),
        "content_requirement": dict(content_requirement),
        "snapshot_budget": dict(snapshot_budget or {"default_max_records": 12, "default_max_chars": 24000}),
    }


def _collection_specs(
    collection_ids: tuple[str, ...],
    *,
    content_requirement: dict[str, Any],
    schema_id: str,
    snapshot_budget: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        _collection_spec(
            collection_id,
            content_requirement=content_requirement,
            schema_id=schema_id,
            snapshot_budget=snapshot_budget,
        )
        for collection_id in collection_ids
    )


def _standard_memory_layers() -> tuple[TaskGraphTemplateMemoryLayer, ...]:
    baseline_collections = ("facts", "plans", "decisions")
    mutable_collections = ("progress", "state_delta", "continuity")
    issue_collections = ("issues", "revision_requests", "risk_notes")
    artifact_index_collections = ("candidate_refs", "review_refs", "commit_refs")
    return (
        TaskGraphTemplateMemoryLayer(
            layer_id="memory.baseline",
            title="基准记忆库",
            repository_role="committed_canon",
            mutable=False,
            collections=baseline_collections,
            collection_specs=_collection_specs(
                baseline_collections,
                content_requirement=_canonical_requirement(),
                schema_id="memory.collection.baseline_canon",
                snapshot_budget={"default_max_records": 16, "default_max_chars": 32000},
            ),
            write_policy="review_approved_commit_only",
        ),
        TaskGraphTemplateMemoryLayer(
            layer_id="memory.mutable",
            title="动态记忆库",
            repository_role="runtime_delta",
            mutable=True,
            collections=mutable_collections,
            collection_specs=_collection_specs(
                mutable_collections,
                content_requirement=_canonical_requirement(),
                schema_id="memory.collection.mutable_delta",
                snapshot_budget={"default_max_records": 20, "default_max_chars": 24000},
            ),
            write_policy="post_review_delta_commit",
        ),
        TaskGraphTemplateMemoryLayer(
            layer_id="memory.issue_ledger",
            title="问题台账",
            repository_role="review_issues",
            mutable=True,
            collections=issue_collections,
            collection_specs=_collection_specs(
                issue_collections,
                content_requirement=_canonical_requirement(),
                schema_id="memory.collection.issue_ledger",
                snapshot_budget={"default_max_records": 30, "default_max_chars": 24000},
            ),
            write_policy="review_nodes_only",
        ),
        TaskGraphTemplateMemoryLayer(
            layer_id="memory.artifact_index",
            title="产物索引库",
            repository_role="artifact_refs",
            mutable=True,
            collections=artifact_index_collections,
            collection_specs=_collection_specs(
                artifact_index_collections,
                content_requirement=_refs_only_requirement(),
                schema_id="memory.collection.artifact_index",
                snapshot_budget={"default_max_records": 40, "default_max_chars": 12000},
            ),
            write_policy="artifact_ref_only",
        ),
    )


def default_task_graph_templates() -> tuple[TaskGraphTemplateDefinition, ...]:
    standard_validation = (
        {"rule_id": "role_contract_complete", "severity": "error", "target": "slots"},
        {"rule_id": "entry_and_output_nodes_required", "severity": "error", "target": "graph"},
        {"rule_id": "handoff_edges_have_contracts", "severity": "warning", "target": "edges"},
    )
    review_validation = (
        *standard_validation,
        {"rule_id": "review_cannot_write_canon", "severity": "error", "target": "review_gate"},
        {"rule_id": "commit_requires_approved_review", "severity": "error", "target": "memory_commit"},
    )
    return (
        TaskGraphTemplateDefinition(
            template_id="single_agent",
            title="单 Agent 长任务",
            intent="一个执行者持续完成任务并输出结果。",
            best_for="低交接成本、低资源读写复杂度的任务。",
            structure_pattern="single_executor",
            slots=(_slot("executor", "执行者", "producer"),),
            validation_rules=standard_validation,
        ),
        TaskGraphTemplateDefinition(
            template_id="multi_sequence",
            title="管线式多 Agent",
            intent="规划、执行、审查按顺序推进。",
            best_for="有清楚前后依赖的多阶段工作。",
            structure_pattern="pipeline",
            slots=(
                _slot("planner", "规划者", "producer"),
                _slot("executor", "执行者", "producer"),
                _slot("reviewer", "审查者", "validator", default_node_type="review_gate"),
            ),
            validation_rules=standard_validation,
        ),
        TaskGraphTemplateDefinition(
            template_id="multi_parallel_merge",
            title="并行审查 + 协调汇总",
            intent="多个独立节点并行产出判断，由协调者合并。",
            best_for="多视角评审、风险复核、方案对比。",
            structure_pattern="parallel_then_merge",
            slots=(
                _slot("reviewer_a", "审查者 A", "validator", default_node_type="review_gate"),
                _slot("reviewer_b", "审查者 B", "validator", default_node_type="review_gate"),
                _slot("coordinator", "协调汇总者", "aggregator"),
            ),
            validation_rules=standard_validation,
        ),
        TaskGraphTemplateDefinition(
            template_id="review_repair_loop",
            title="审核门 + 返修循环",
            intent="候选产物先审核，未通过则返修，审核通过后才进入下游。",
            best_for="质量门明确、需要多轮打磨的任务。",
            structure_pattern="produce_validate_repair",
            slots=(
                _slot("executor", "执行者", "producer"),
                _slot("reviewer", "审核员", "validator", default_node_type="review_gate"),
                _slot("repairer", "返修者", "producer"),
            ),
            memory_layers=_standard_memory_layers(),
            validation_rules=review_validation,
        ),
        TaskGraphTemplateDefinition(
            template_id="long_project_cycle",
            title="长期项目循环执行",
            intent="计划、执行、复盘、记忆写回形成持续循环。",
            best_for="长任务、持续运营、连续创作、长期研究。",
            structure_pattern="plan_execute_review_commit_loop",
            slots=(
                _slot("planner", "计划员", "producer"),
                _slot("executor", "执行者", "producer"),
                _slot("reviewer", "复盘员", "validator", default_node_type="review_gate"),
                _slot("memory_steward", "记忆管理员", "publisher", default_node_type="memory_commit"),
            ),
            memory_layers=_standard_memory_layers(),
            artifact_layers=(
                {"layer_id": "artifact.candidates", "title": "候选产物", "visibility": "review_only"},
                {"layer_id": "artifact.commits", "title": "提交产物", "visibility": "downstream_after_commit"},
            ),
            validation_rules=review_validation,
        ),
        TaskGraphTemplateDefinition(
            template_id="rag_research_writing",
            title="RAG + 资料分析 + 写作",
            intent="检索资料、分析证据、形成可交付文本。",
            best_for="知识密集型报告、研究写作、资料问答。",
            structure_pattern="evidence_analysis_delivery",
            slots=(
                _slot("retriever", "RAG 检索员", "producer"),
                _slot("analyst", "资料分析员", "producer"),
                _slot("writer", "写作者", "producer"),
            ),
            memory_layers=(
                TaskGraphTemplateMemoryLayer(
                    layer_id="memory.evidence",
                    title="证据记忆库",
                    repository_role="evidence_refs",
                    mutable=True,
                    collections=("source_refs", "evidence_slices", "uncertainties"),
                    collection_specs=(
                        _collection_spec("source_refs", content_requirement=_refs_only_requirement(), schema_id="memory.collection.artifact_index"),
                        _collection_spec("evidence_slices", content_requirement=_canonical_requirement(), schema_id="memory.collection.evidence"),
                        _collection_spec("uncertainties", content_requirement=_canonical_requirement(), schema_id="memory.collection.issue_ledger"),
                    ),
                    write_policy="evidence_nodes_only",
                ),
            ),
            validation_rules=standard_validation,
        ),
        TaskGraphTemplateDefinition(
            template_id="pdf_table_synthesis",
            title="PDF 分析 + 表格分析 + 汇总",
            intent="PDF 和表格并行产出证据，汇总节点形成结论。",
            best_for="报告解读、财务材料分析、PDF 与表格混合资料。",
            structure_pattern="parallel_evidence_then_synthesis",
            slots=(
                _slot("pdf_analyst", "PDF 分析员", "producer"),
                _slot("table_analyst", "表格分析员", "producer"),
                _slot("synthesizer", "综合汇总员", "aggregator"),
            ),
            memory_layers=(
                TaskGraphTemplateMemoryLayer(
                    layer_id="memory.evidence",
                    title="证据记忆库",
                    repository_role="evidence_refs",
                    mutable=True,
                    collections=("pdf_evidence", "table_evidence", "conflicts"),
                    collection_specs=(
                        _collection_spec("pdf_evidence", content_requirement=_canonical_requirement(), schema_id="memory.collection.evidence"),
                        _collection_spec("table_evidence", content_requirement=_canonical_requirement(), schema_id="memory.collection.evidence"),
                        _collection_spec("conflicts", content_requirement=_canonical_requirement(), schema_id="memory.collection.issue_ledger"),
                    ),
                    write_policy="evidence_nodes_only",
                ),
            ),
            validation_rules=standard_validation,
        ),
    )


def build_task_graph_template_catalog() -> dict[str, Any]:
    templates = default_task_graph_templates()
    return {
        "authority": "task_system.task_graph_template_catalog",
        "templates": [item.to_dict() for item in templates if item.enabled],
        "summary": {
            "template_count": len(templates),
            "enabled_template_count": sum(1 for item in templates if item.enabled),
            "foundation_layers": ["structure", "roles", "memory", "artifacts", "validation"],
        },
    }


