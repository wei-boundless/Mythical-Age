from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.graphs.task_graph_models import TaskGraphNodeDefinition

from .shard_models import SemanticShardSpec


@dataclass(frozen=True, slots=True)
class ProjectNetworkNodeTemplate:
    template_id: str
    title: str
    node_type: str = "agent"
    node_config_id: str = ""
    work_posture: str = "index"
    node_contract_id: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    payload_contract_id: str = ""
    agent_id: str = ""
    agent_profile_id: str = ""
    agent_group_id: str = ""
    execution_mode: str = "sync"
    dispatch_group: str = ""
    wait_policy: str = "wait_all_upstream_completed"
    join_policy: str = "all_success"
    memory_read_policy: dict[str, Any] = field(default_factory=dict)
    memory_writeback_policy: dict[str, Any] = field(default_factory=dict)
    dynamic_memory_read_policy: dict[str, Any] = field(default_factory=dict)
    executor_policy: dict[str, Any] = field(default_factory=dict)
    failure_policy: dict[str, Any] = field(default_factory=dict)
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.project_network.node_template"

    def __post_init__(self) -> None:
        if self.authority != "task_system.project_network.node_template":
            raise ValueError("ProjectNetworkNodeTemplate authority mismatch")
        if not str(self.template_id or "").strip():
            raise ValueError("ProjectNetworkNodeTemplate requires template_id")

    def materialize_node(self, shard: SemanticShardSpec, *, sequence_index: int = 0) -> TaskGraphNodeDefinition:
        executor = shard.executor_policy
        metadata = {
            **dict(self.metadata or {}),
            "project_network_template_id": self.template_id,
            "prompt_contract": dict(self.prompt_contract or {}),
            "semantic_shard": shard.to_dict(),
            "assigned_scope": shard.assigned_scope,
            "required_refs": list(shard.input_refs),
            "required_anchor_refs": list(shard.required_anchor_refs),
            "work_product_contract_id": shard.expected_work_product_contract_id,
        }
        agent_profile_id = executor.agent_profile_id or self.agent_profile_id
        if agent_profile_id:
            metadata["agent_profile_id"] = agent_profile_id
        node_config_overrides = {
            "assigned_scope": shard.assigned_scope,
            "input_refs": list(shard.input_refs),
            "required_anchor_refs": list(shard.required_anchor_refs),
            "work_product_contract_id": shard.expected_work_product_contract_id,
        }
        output_contract_id = shard.output_contract_id or self.output_contract_id
        payload_contract_id = shard.payload_contract_id or self.payload_contract_id
        contract_bindings = {
            "schema": {
                key: value
                for key, value in {
                    "input_contract_id": self.input_contract_id,
                    "output_contract_id": output_contract_id,
                    "payload_contract_id": payload_contract_id,
                }.items()
                if value
            },
            "execution": {
                key: value
                for key, value in {
                    "node_contract_id": self.node_contract_id,
                    "executor_policy": {
                        **dict(self.executor_policy or {}),
                        **executor.to_dict(),
                    },
                }.items()
                if value
            },
            "semantic": {
                "layer_id": shard.layer_id,
                "work_unit_kind": shard.work_unit_kind,
                "work_posture": executor.work_posture or self.work_posture,
            },
        }
        return TaskGraphNodeDefinition(
            node_id=_node_id_for_shard(shard),
            node_type=self.node_type,
            title=f"{self.title}: {shard.shard_id}",
            node_config_id=self.node_config_id,
            node_config_overrides=node_config_overrides,
            agent_id=executor.agent_id or self.agent_id,
            agent_group_id=executor.agent_group_id or self.agent_group_id,
            work_posture=executor.work_posture or self.work_posture,
            node_contract_id=self.node_contract_id,
            input_contract_id=self.input_contract_id,
            output_contract_id=output_contract_id,
            contract_bindings=contract_bindings,
            executor_policy={**dict(self.executor_policy or {}), **executor.to_dict()},
            memory_read_policy=dict(self.memory_read_policy or {}),
            memory_writeback_policy=dict(self.memory_writeback_policy or {}),
            dynamic_memory_read_policy=dict(self.dynamic_memory_read_policy or {}),
            failure_policy=dict(self.failure_policy or {}),
            runtime_policy=dict(self.runtime_policy or {}),
            sequence_index=sequence_index,
            execution_mode=self.execution_mode,
            dispatch_group=self.dispatch_group or _slug(shard.layer_id),
            wait_policy=self.wait_policy,
            join_policy=self.join_policy,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def build_project_network_template_catalog() -> dict[str, ProjectNetworkNodeTemplate]:
    templates = [
        ProjectNetworkNodeTemplate(
            template_id="project_network.source_snapshot",
            title="Project network source snapshot",
            node_type="input",
            work_posture="index",
            execution_mode="sync",
            node_contract_id="node-contract:project_network_source_snapshot",
            output_contract_id="project_network.source_snapshot.v1",
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.system_classify",
            title="Project network system classify",
            work_posture="classify",
            execution_mode="parallel",
            dispatch_group="project_network_system",
            agent_id="agent:project_network_builder",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_builder_agent",
            node_contract_id="node-contract:project_network_system_classify",
            output_contract_id="project_network.system_map.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目系统层建图员。",
                task="你只负责在 assigned_scope 内识别 functional systems、owned folders、入口点和系统边界候选。你必须基于 source snapshots、文件树、registry facts 和必要的只读文件窗口判断。",
                output="输出 project_network.system_map.v1 结构化 work product，包含 accepted_candidates、rejected_candidates、conflicts、coverage、evidence_refs 和 downstream_shard_hints。",
            ),
            runtime_policy=_project_network_ast_runtime_policy("basic_ast"),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.folder_index",
            title="Project network folder index",
            work_posture="index",
            execution_mode="parallel",
            dispatch_group="project_network_folder",
            agent_id="agent:project_network_builder",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_builder_agent",
            node_contract_id="node-contract:project_network_folder_index",
            output_contract_id="project_network.folder_index.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目文件夹层索引员。",
                task="你只负责在 assigned_scope 内建立文件夹职责、关键文件、边界风险和下游模块分片建议。你不得重新定义上游系统边界。",
                output="输出 project_network.folder_index.v1 结构化 work product，包含 folder candidates、evidence_refs、coverage、conflicts 和 downstream_shard_hints。",
            ),
            runtime_policy=_project_network_ast_runtime_policy("basic_ast"),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.module_index",
            title="Project network module index",
            work_posture="index",
            execution_mode="parallel",
            dispatch_group="project_network_module",
            agent_id="agent:project_network_file_reviewer",
            agent_group_id="group.project_network_reviewers",
            agent_profile_id="project_network_file_reviewer_agent",
            node_contract_id="node-contract:project_network_module_index",
            output_contract_id="project_network.module_index.v1",
            executor_policy=_model_response_only_executor_policy("single_file_module_index"),
            prompt_contract=_project_network_prompt_contract(
                role="你是一名单文件项目语义网络审查员。",
                task=(
                    "你只审查 assigned_scope 指定的一个文件。系统已经把当前文件文本、file_hash、file_stable_ref、文件骨架卡片和可用 AST 投影送到你的输入包中；"
                    "你不需要也不允许自行读取文件、搜索代码、读取记忆或扩大目录范围。你的任务是把这个物理文件转换成后续 agent 能顺着项目网络使用的语义路标。"
                    "先确认文件稳定引用、文件哈希、AST/骨架输入是否存在；输入不足时 block，不猜测。"
                    "然后给当前文件本身产出一个 file_module semantic_label，说明它的职责、可控入口、领域标签、证据和可信度。"
                    "再审查文件内部对项目控制有意义的 class/function/method/config/registry/tool/prompt/data model 等节点，为每个节点给出 semantic_label、stable_ref、证据锚点和关系候选。"
                    "最后只接受当前文件内可见证据支撑的关系边；跨文件关系只能作为 relation_candidate 或 external_stub，不能凭语义相似度补线。"
                ),
                output=(
                    "完成时选择 respond，并在 respond 动作的 diagnostics.project_network_semantic_submissions 提交且只提交一个 module_index 审查事实。"
                    "该提交不是自然语言报告，也不是系统内部 work product envelope；你只提交语义审查事实，系统会把它装配为 work product。"
                    "提交必须包含 submission_kind=module_index、semantic_label、module_summary、public_surface、semantic_nodes、semantic_edges、relation_candidates、coverage、limitations、uncovered_refs。"
                    "semantic_label 至少包含 stable_ref、label、summary、tags、evidence_refs、anchor_refs、confidence。"
                    "每个 semantic_nodes 项必须包含 stable_ref、node_kind、name、semantic_label、evidence_refs、anchor_refs、confidence；每个节点的 semantic_label 是后续网络导航路标。"
                    "每个 semantic_edges 项必须包含 source_ref、target_ref、edge_kind、direction、status、evidence_refs、anchor_refs、confidence、limitations。"
                    "edge_kind 只能表达真实工程关系，例如 defines、imports、calls、registers、routes_to、reads、writes、emits、consumes、configures、depends_on、owns。"
                    "final_answer 只写极短收口，说明已提交当前文件语义索引；不要把完整审查结果写进最终文本。"
                ),
                work_product_contract={
                    "product_kind": "module_index",
                    "stable_ref_source": "assigned_scope.file_stable_ref",
                    "required_payload_fields": (
                        "file_ref",
                        "file_path",
                        "file_hash",
                        "semantic_label",
                        "module_summary",
                        "public_surface",
                        "semantic_network_index",
                        "relation_candidates",
                        "coverage",
                        "limitations",
                        "uncovered_refs",
                    ),
                },
                semantic_network_contract=_module_semantic_network_contract(),
                input_boundary_contract=_module_review_input_boundary_contract(),
                typed_submission_contract=_module_typed_submission_contract(),
                review_judgment_contract=_module_review_judgment_contract(),
                quality_gate_contract=_project_network_review_quality_gate_contract(),
                failure_handling_contract=_project_network_review_failure_handling_contract(),
            ),
            metadata=_with_model_response_only_tools(
                _project_network_runtime_algorithm_metadata(
                    algorithm_kind="tree_reduce",
                    adapter_id="project_network_work_product",
                    failure_mode="retry_same_node",
                    max_quality_retries=2,
                ),
                reason="single_file_module_index_uses_system_supplied_file_packet",
            ),
            runtime_policy=_project_network_ast_runtime_policy("deep_ast", required=True),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.ast_endpoint_extract",
            title="Project network AST endpoint extract",
            work_posture="index",
            execution_mode="parallel",
            dispatch_group="project_network_endpoint",
            agent_id="agent:project_network_builder",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_builder_agent",
            node_contract_id="node-contract:project_network_ast_endpoint_extract",
            output_contract_id="project_network.endpoint_index.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名 AST endpoint 索引员。",
                task="你只围绕 assigned_scope 内的 AST anchors 审查 class、function、parameter、call-site 和可控入口。没有 anchor 或 hash 证据时不能接受 endpoint。",
                output="输出 project_network.endpoint_index.v1 结构化 work product，所有 accepted endpoint 必须包含 anchor_ref、evidence_ref、coverage 和 limitations。",
            ),
            runtime_policy=_project_network_ast_runtime_policy("deep_ast", required=True),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.relation_trace",
            title="Project network relation trace",
            work_posture="trace",
            execution_mode="parallel",
            dispatch_group="project_network_relation",
            agent_id="agent:project_network_builder",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_builder_agent",
            node_contract_id="node-contract:project_network_relation_trace",
            output_contract_id="project_network.relation_candidates.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名跨模块关系追踪员。",
                task="你只顺着 import、call、registry、router、tool、prompt refs 建立候选 control routes。每条关系必须列出证据链，不能凭语义相似度补线。",
                output="输出 project_network.relation_candidates.v1 结构化 work product，包含 relation_candidates、edge evidence chain、conflicts、coverage 和 rejected_candidates。",
            ),
            runtime_policy=_project_network_ast_runtime_policy("deep_ast", required=True),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.layer_aggregate",
            title="Project network layer aggregate",
            work_posture="aggregate",
            agent_id="agent:project_network_aggregator",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_aggregator_agent",
            node_contract_id="node-contract:project_network_layer_aggregate",
            output_contract_id="project_network.layer_summary.v1",
            join_policy="allow_partial_with_issues",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目网络层级汇总员。",
                task="你只消费同层 typed work products 和上游 layer summary refs，合并 accepted、rejected、conflict 与 coverage。你不能把自然语言摘要直接当作图事实。",
                output="输出 project_network.layer_summary.v1，包含 accepted_refs、rejected_refs、conflict_refs、coverage、uncovered_scope_refs 和 next_layer_shard_hints。",
            ),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.directory_aggregate",
            title="Project network directory aggregate",
            work_posture="aggregate",
            agent_id="agent:project_network_directory_reviewer",
            agent_group_id="group.project_network_reviewers",
            agent_profile_id="project_network_directory_reviewer_agent",
            node_contract_id="node-contract:project_network_directory_aggregate",
            output_contract_id="project_network.directory_summary.v1",
            execution_mode="barrier",
            wait_policy="wait_all_upstream_completed",
            join_policy="all_success",
            executor_policy=_model_response_only_executor_policy("directory_tree_reduce_aggregate"),
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目目录语义网络汇总审查员。",
                task=(
                    "你只负责当前 directory_frame 的直接文件 module_index 审查事实和已回传的子目录 directory_summary refs。"
                    "系统会向你提供上游 typed work products；你不重新扫描物理树、不读取文件、不搜索代码，也不把自然语言摘要当作图事实。"
                    "你的任务是为当前目录生成一个可提取 semantic_label，说明这个目录在项目物理层中的语义职责，并把子文件、子目录的语义路标合并成目录级网络。"
                    "你必须先确认 child work products 的来源和覆盖范围，再按 stable_ref 去重，保留 source_work_product_refs，标出冲突边、未覆盖范围、外部桩和需要父目录继续判断的关系候选。"
                    "只有带 evidence_refs 或 anchor_refs 的节点和边可以进入 accepted_relation_candidates；证据不足的跨目录关系只能上交为候选或 blocker。"
                ),
                output=(
                    "完成时选择 respond，并在 respond 动作的 diagnostics.project_network_semantic_submissions 提交且只提交一个 directory_summary 审查事实。"
                    "该提交不是自然语言报告，也不是系统内部 work product envelope；你只提交目录级语义审查事实，系统会把它装配为 work product。"
                    "提交必须包含 submission_kind=directory_summary、semantic_label、directory_summary、directory_nodes、module_nodes、semantic_edges、external_stubs、source_work_product_refs、direct_module_refs、child_summary_refs、accepted_relation_candidates、conflicts、coverage、uncovered_refs、parent_return_payload。"
                    "semantic_label 至少包含 stable_ref、label、summary、tags、evidence_refs、anchor_refs、confidence。"
                    "directory_nodes 和 module_nodes 中每个节点都必须包含 stable_ref、node_kind、name、semantic_label、evidence_refs、anchor_refs、confidence；这些 semantic_label 是上层目录和后续 agent 的路标。"
                    "semantic_edges 中每条边必须包含 source_ref、target_ref、edge_kind、direction、status、evidence_refs、anchor_refs、confidence、limitations。"
                    "parent_return_payload 只能包含父目录继续汇总所需的 stable_ref、semantic_label、summary、coverage、accepted_relation_candidates、conflicts 和 blockers。"
                    "final_answer 只写极短收口，说明已提交当前目录语义汇总；不要把完整汇总结果写进最终文本。"
                ),
                work_product_contract={
                    "product_kind": "directory_summary",
                    "stable_ref_source": "folder_stable_ref",
                    "required_payload_fields": (
                        "directory_frame_id",
                        "folder_stable_ref",
                        "semantic_label",
                        "directory_summary",
                        "semantic_network_index",
                        "direct_module_refs",
                        "child_summary_refs",
                        "accepted_relation_candidates",
                        "conflicts",
                        "coverage",
                        "uncovered_refs",
                        "parent_return_payload",
                    ),
                },
                semantic_network_contract=_directory_semantic_network_contract(),
                input_boundary_contract=_directory_review_input_boundary_contract(),
                typed_submission_contract=_directory_typed_submission_contract(),
                review_judgment_contract=_directory_review_judgment_contract(),
                quality_gate_contract=_project_network_review_quality_gate_contract(),
                failure_handling_contract=_project_network_review_failure_handling_contract(),
            ),
            metadata=_with_model_response_only_tools(
                _project_network_runtime_algorithm_metadata(
                    algorithm_kind="tree_reduce",
                    adapter_id="project_network_work_product",
                    failure_mode="retry_same_node",
                    max_quality_retries=2,
                ),
                reason="directory_aggregate_consumes_typed_inbound_work_products",
            ),
            runtime_policy={
                "context_policy": {
                    "project_network": {
                        "directory_tree_reduce": {
                            "enabled": True,
                            "consume_typed_child_returns_only": True,
                            "authority": "task_system.project_network.directory_aggregate.runtime_policy",
                        }
                    }
                }
            },
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.cross_layer_validate",
            title="Project network cross layer validate",
            work_posture="validate",
            agent_id="agent:project_network_curator",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_curator_agent",
            node_contract_id="node-contract:project_network_cross_layer_validate",
            output_contract_id="project_network.validation_report.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目网络跨层校验员。",
                task="你只校验 system、folder、module、endpoint、relation 各层之间的一致性、覆盖率、anchor/hash 有效性和 schema 完整性。",
                output="输出 project_network.validation_report.v1，包含 pass/fail findings、conflict_refs、stale_refs、coverage gaps 和 needs_human_review。",
            ),
            runtime_policy=_project_network_ast_runtime_policy("deep_ast", required=True),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.conflict_curate",
            title="Project network conflict curate",
            work_posture="curate",
            agent_id="agent:project_network_curator",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_curator_agent",
            node_contract_id="node-contract:project_network_conflict_curate",
            output_contract_id="project_network.conflict_report.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目网络冲突裁决员。",
                task="你只裁决已输入的冲突候选。证据不足、跨层不一致或 anchor 失效时必须拒绝或进入人工确认，不能为完成图而补事实。",
                output="输出 project_network.conflict_report.v1，包含 accepted_conflicts、resolved_conflicts、rejected_candidates、needs_human_review 和裁决证据。",
            ),
            runtime_policy=_project_network_ast_runtime_policy("deep_ast", required=True),
        ),
        ProjectNetworkNodeTemplate(
            template_id="project_network.generation_publish",
            title="Project network generation publish",
            work_posture="publish",
            agent_id="agent:project_network_curator",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_curator_agent",
            node_contract_id="node-contract:project_network_generation_publish",
            output_contract_id="project_network.publish_candidate.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名项目网络发布候选裁决员。",
                task="你只在 schema、anchor、coverage、conflict 校验通过后形成 publish candidate。你不直接写 Project Semantic Space Store；发布由系统 publish gate 执行。",
                output="输出 project_network.publish_candidate.v1，包含 generation_candidate_ref、source_layer_refs、validation_refs、remaining_risks 和 publish_blockers。",
            ),
        ),
    ]
    return {item.template_id: item for item in templates}


def resolve_project_network_node_template(
    template_id: str,
    catalog: dict[str, ProjectNetworkNodeTemplate] | None = None,
) -> ProjectNetworkNodeTemplate:
    templates = catalog or build_project_network_template_catalog()
    if template_id in templates:
        return templates[template_id]
    raise KeyError(f"unknown project network node template: {template_id}")


def _node_id_for_shard(shard: SemanticShardSpec) -> str:
    return f"pn.{_slug(shard.layer_id)}.{_slug(shard.shard_id)}"


def _slug(value: str) -> str:
    return ".".join(part for part in str(value or "").replace(":", ".").replace("/", ".").replace("\\", ".").replace("_", ".").replace("-", ".").split(".") if part)


def _module_review_input_boundary_contract() -> dict[str, Any]:
    return {
        "work_unit": "one physical source file as one semantic module",
        "system_supplied_inputs": (
            "assigned_scope.file_path",
            "assigned_scope.file_stable_ref",
            "project_network_file_review.file_text",
            "project_network_file_review.file_hash",
            "project_network_file_review.ast_projection",
            "project_network_file_review.file_skeleton",
        ),
        "allowed_context": (
            "current file text",
            "current file AST projection",
            "current file skeleton and stable refs",
            "upstream directory/system labels already included in the input packet",
        ),
        "forbidden_context_requests": (
            "do not call file read",
            "do not call workspace search",
            "do not read memory",
            "do not infer outside files beyond visible import/call/registry evidence",
        ),
        "missing_required_input_behavior": "choose block and explain which system-supplied input is missing; do not fabricate a semantic index",
    }


def _directory_review_input_boundary_contract() -> dict[str, Any]:
    return {
        "work_unit": "one directory frame",
        "system_supplied_inputs": (
            "directory_frame_id",
            "folder_stable_ref",
            "direct module_index work products",
            "child directory_summary work products",
            "parent/system scope labels when available",
        ),
        "allowed_context": (
            "typed child work products",
            "stable refs and evidence refs inside child payloads",
            "directory frame metadata",
        ),
        "forbidden_context_requests": (
            "do not rescan the directory",
            "do not read files",
            "do not call workspace search",
            "do not turn natural-language summaries into accepted graph facts",
        ),
        "missing_required_input_behavior": "choose block if required typed child inputs are absent; otherwise submit coverage gaps and blockers",
    }


def _module_typed_submission_contract() -> dict[str, Any]:
    return {
        "channel": "respond.diagnostics.project_network_semantic_submissions",
        "cardinality": "exactly_one",
        "submission_kind": "module_index",
        "agent_owns": "semantic judgment facts for the current file: labels, accepted nodes, accepted edges, candidates, conflicts, coverage, limitations",
        "system_owns": "work_product_id, build_id, graph_run_id, node_id, shard_id, storage envelope, ingestion side effect",
        "submission_rule": (
            "choose respond, put exactly one module_index fact object in diagnostics.project_network_semantic_submissions, "
            "and keep final_answer as a one-sentence receipt"
        ),
        "not_allowed": (
            "do not put the semantic network in final_answer",
            "do not wrap a natural-language report as the submission",
            "do not submit a system work_product envelope",
            "do not submit multiple competing module_index facts for the same file",
        ),
        "required_submission_fields": (
            "submission_kind",
            "semantic_label",
            "module_summary",
            "public_surface",
            "semantic_nodes",
            "semantic_edges",
            "relation_candidates",
            "coverage",
            "limitations",
            "uncovered_refs",
        ),
        "semantic_label_fields": (
            "stable_ref",
            "label",
            "summary",
            "tags",
            "evidence_refs",
            "anchor_refs",
            "confidence",
        ),
        "semantic_label_meaning": (
            "stable_ref points to the physical file or symbol",
            "label is the short road-sign name",
            "summary states responsibility and control meaning",
            "tags support routing by system, capability, domain, and artifact kind",
            "evidence_refs cite visible file/hash/import/call/registry/router facts",
            "anchor_refs cite AST or skeleton anchors when available",
            "confidence reflects evidence strength, not optimism",
        ),
        "node_fact_fields": (
            "stable_ref",
            "node_kind",
            "name",
            "semantic_label",
            "evidence_refs",
            "anchor_refs",
            "confidence",
        ),
        "edge_fact_fields": (
            "source_ref",
            "target_ref",
            "edge_kind",
            "direction",
            "status",
            "evidence_refs",
            "anchor_refs",
            "confidence",
            "limitations",
        ),
        "final_answer_policy": "final_answer is only a short receipt; the semantic network must be in the typed diagnostics channel",
    }


def _directory_typed_submission_contract() -> dict[str, Any]:
    return {
        "channel": "respond.diagnostics.project_network_semantic_submissions",
        "cardinality": "exactly_one",
        "submission_kind": "directory_summary",
        "agent_owns": "directory-level semantic merge, conflict preservation, parent return payload, and coverage judgment",
        "system_owns": "work_product_id, build_id, graph_run_id, node_id, shard_id, storage envelope, ingestion side effect",
        "submission_rule": (
            "choose respond, put exactly one directory_summary fact object in diagnostics.project_network_semantic_submissions, "
            "and keep final_answer as a one-sentence receipt"
        ),
        "not_allowed": (
            "do not put the merged semantic graph in final_answer",
            "do not rescan files or directories",
            "do not promote natural-language summaries into accepted graph facts",
            "do not overwrite conflicting child facts silently",
        ),
        "required_submission_fields": (
            "submission_kind",
            "semantic_label",
            "directory_summary",
            "directory_nodes",
            "module_nodes",
            "semantic_edges",
            "external_stubs",
            "source_work_product_refs",
            "direct_module_refs",
            "child_summary_refs",
            "accepted_relation_candidates",
            "conflicts",
            "coverage",
            "uncovered_refs",
            "parent_return_payload",
        ),
        "semantic_label_fields": (
            "stable_ref",
            "label",
            "summary",
            "tags",
            "evidence_refs",
            "anchor_refs",
            "confidence",
        ),
        "semantic_label_meaning": (
            "stable_ref points to the directory frame or folder stable ref",
            "label is the short road-sign name for the folder",
            "summary states the folder's coordination responsibility",
            "tags support parent-layer routing by system, capability, domain, and artifact kind",
            "evidence_refs cite child work product refs or visible frame facts",
            "anchor_refs cite folder/frame refs when AST anchors are not available",
            "confidence reflects child evidence coverage and conflicts",
        ),
        "parent_return_payload_fields": (
            "stable_ref",
            "semantic_label",
            "summary",
            "coverage",
            "accepted_relation_candidates",
            "conflicts",
            "blockers",
        ),
        "final_answer_policy": "final_answer is only a short receipt; the semantic network must be in the typed diagnostics channel",
    }


def _module_review_judgment_contract() -> dict[str, Any]:
    return {
        "review_sequence": (
            "1. confirm the file stable ref, file hash, file text, skeleton, and AST projection supplied by the system",
            "2. identify the file's project responsibility before listing symbols; the file label is the root road sign for this module",
            "3. enumerate only symbols and control points that matter for later navigation or control, not every trivial local helper",
            "4. give each accepted symbol a semantic_label tied to stable_ref, evidence_refs, anchor_refs, tags, and confidence",
            "5. record only evidence-backed intra-file edges as accepted semantic_edges",
            "6. send cross-file, uncertain, or unresolved links to relation_candidates or external_stubs",
            "7. declare coverage gaps and limitations instead of filling missing evidence",
        ),
        "semantic_label_standard": (
            "label is a short road-sign name, not a paragraph",
            "summary states responsibility and control meaning",
            "tags help later agents route by system, domain, capability, and artifact kind",
            "stable_ref must be the route key a later agent can use to land back on this node",
            "evidence_refs must point to visible file facts, not private intuition",
            "anchor_refs should use AST/skeleton anchors when available; if unavailable, cite the file/module ref and lower confidence",
            "confidence must reflect evidence strength",
        ),
        "node_acceptance": (
            "accept public surfaces, exported functions/classes, registry entries, routes, config definitions, tool/prompt entries, data models, and important orchestration helpers",
            "skip tiny private helpers unless they control routing, IO, state, permissions, prompt assembly, task flow, tool dispatch, or semantic network behavior",
            "a node without stable_ref or evidence_refs cannot be accepted",
        ),
        "edge_acceptance": (
            "accepted edges require source_ref, target_ref, edge_kind, direction, status, evidence_refs, anchor_refs, confidence, and limitations",
            "call/import/register/router/tool/prompt evidence can support edges",
            "semantic similarity alone cannot support an accepted edge",
            "cross-file targets without a resolvable stable_ref must become external_stub plus relation_candidate",
        ),
    }


def _directory_review_judgment_contract() -> dict[str, Any]:
    return {
        "review_sequence": (
            "1. confirm the directory frame, folder stable ref, direct module refs, child summary refs, and source child work products",
            "2. assign one directory semantic_label that describes the folder's project responsibility and coordination role",
            "3. merge child module and directory labels by stable_ref without rewriting their evidence",
            "4. accept only relations that are backed by child evidence refs or source work product refs",
            "5. preserve conflicting or incomplete relations as conflicts, blockers, or parent candidates",
            "6. produce a compact parent_return_payload for the next reduce layer",
        ),
        "merge_standard": (
            "same stable_ref means same node unless evidence says otherwise",
            "do not overwrite conflicting labels silently",
            "directory summary should explain coordination responsibility, not restate every child",
            "directory semantic_label must help the parent decide where this folder sits in the physical and semantic hierarchy",
            "parent payload must be compact and route-oriented",
        ),
        "edge_acceptance": (
            "directory accepted_relation_candidates require source child refs and evidence refs",
            "cross-directory links remain candidates unless both sides have evidence chains",
            "natural-language summaries are never accepted graph facts by themselves",
            "when child facts conflict, preserve both refs and explain the mismatch instead of choosing a silent winner",
        ),
    }


def _project_network_review_quality_gate_contract() -> dict[str, Any]:
    return {
        "required_for_acceptance": (
            "exactly one typed semantic submission",
            "top-level semantic_label has stable_ref, label, summary, tags, evidence_refs, anchor_refs, and confidence",
            "semantic network node lists are present",
            "every accepted node has stable_ref, node_kind, name, semantic_label, evidence_refs, anchor_refs, and confidence",
            "every accepted edge has source_ref, target_ref, edge_kind, direction, status, evidence_refs, anchor_refs, confidence, and limitations",
            "coverage and limitations are explicit",
        ),
        "retry_feedback": "missing fields are returned to the same graph node as project_network_contract_feedback",
        "acceptance_authority": "graph_system.runtime_algorithm_adapter.project_network_tree_reduce",
    }


def _project_network_review_failure_handling_contract() -> dict[str, Any]:
    return {
        "insufficient_input": "block with a precise missing-input reason; do not submit guessed graph facts",
        "uncertain_node": "include the node only if it has evidence; otherwise list it in limitations or uncovered_refs",
        "uncertain_edge": "put it in relation_candidates or conflicts, not semantic_edges",
        "conflicting_child_facts": "preserve both refs in conflicts and explain the evidence mismatch",
        "too_many_minor_nodes": "prefer control surfaces, public APIs, registry/config/prompt/tool/data model entries, and externally reachable functions; record the rest as coverage limitations",
        "label_uncertainty": "keep the stable_ref and evidence, lower confidence, and state the uncertainty in limitations instead of inventing a confident role",
        "scope_pressure": "prioritize public surfaces, registry/control points, and externally reachable functions; record uncovered_refs",
    }


def _module_semantic_network_contract() -> dict[str, Any]:
    return {
        "scope": "single_file_module",
        "network_model": (
            "one file_module root node",
            "zero or more symbol/control nodes under the file",
            "accepted intra-file edges with evidence",
            "cross-file links as relation_candidates or external_stubs",
        ),
        "node_required_fields": (
            "stable_ref",
            "node_kind",
            "name",
            "semantic_label",
            "evidence_refs",
            "anchor_refs",
            "confidence",
        ),
        "edge_required_fields": (
            "source_ref",
            "target_ref",
            "edge_kind",
            "direction",
            "status",
            "evidence_refs",
            "anchor_refs",
            "confidence",
            "limitations",
        ),
        "allowed_node_kinds": (
            "file_module",
            "class",
            "function",
            "method",
            "public_surface",
            "configuration",
            "registry_entry",
            "route",
            "tool_entry",
            "prompt_entry",
            "data_model",
            "external_stub",
        ),
        "allowed_edge_kinds": (
            "defines",
            "imports",
            "calls",
            "registers",
            "routes_to",
            "reads",
            "writes",
            "emits",
            "consumes",
            "configures",
            "depends_on",
            "owns",
        ),
        "acceptance_rules": (
            "每个节点必须给出可提取 semantic_label，作为后续 agent 导航路标。",
            "accepted edge 必须有 evidence_refs；函数/类/方法节点必须有 anchor_ref 或明确说明 AST 缺口。",
            "跨文件 target 如果没有可定位 anchor，只能输出为 external_stub + relation_candidate。",
            "confidence=deterministic 只允许来自 AST、file_hash、import/call/registry/router 等可追踪证据。",
            "不能为了让网络连通而补线；不确定关系必须进入 relation_candidates 或 conflicts。",
        ),
        "semantic_label_quality": (
            "label must be short and stable enough to appear in an index",
            "summary must describe what a later agent can control or understand through this node",
            "tags must include at least one artifact/domain tag and one capability/control tag when evidence supports it",
            "evidence_refs and anchor_refs must be concrete route handles, not prose",
        ),
    }


def _directory_semantic_network_contract() -> dict[str, Any]:
    return {
        "scope": "directory_frame",
        "network_model": (
            "one directory root node",
            "direct module nodes from child module_index products",
            "child directory nodes from child directory_summary products",
            "accepted or candidate relations backed by child evidence",
            "parent_return_payload as the compact upward route card",
        ),
        "required_sections": (
            "directory_nodes",
            "module_nodes",
            "edges",
            "external_stubs",
            "source_work_product_refs",
        ),
        "merge_rules": (
            "只合并 typed semantic submissions 装配出的 work product payload，不合并纯自然语言摘要。",
            "同一 stable_ref 的节点必须去重，并保留 source_work_product_refs。",
            "冲突边不得静默覆盖，必须进入 conflicts。",
            "父目录只接收稳定 refs、coverage、accepted_relation_candidates、conflicts 和 blockers。",
        ),
        "acceptance_rules": (
            "目录节点和模块节点都必须给出可提取 semantic_label，作为父层和后续 agent 导航路标。",
            "目录级 accepted_relation_candidates 必须来自至少一个 module_index 或 child directory_summary 的 evidence_refs。",
            "跨目录关系只能作为候选上交，除非上下游 work products 都提供证据链。",
            "coverage 必须声明 direct files、child summaries、uncovered_refs 和 limitations。",
        ),
        "semantic_label_quality": (
            "directory label must name the folder's responsibility, not merely restate its path",
            "summary must explain the folder's coordination role over child modules",
            "tags must help the parent route by system, capability, domain, and artifact kind",
            "source_work_product_refs must show which child facts support this directory judgment",
        ),
    }


def _project_network_runtime_algorithm_metadata(
    *,
    algorithm_kind: str,
    adapter_id: str,
    failure_mode: str,
    max_quality_retries: int,
) -> dict[str, Any]:
    return {
        "runtime_algorithm": {
            "algorithm_kind": algorithm_kind,
            "adapter_id": adapter_id,
            "contract_gate": "typed_work_product_schema",
            "authority": "task_system.project_network.runtime_algorithm_metadata",
        },
        "quality_retry_policy": {
            "failure_mode": failure_mode,
            "max_quality_retries": int(max_quality_retries),
            "requirements_input_key": "project_network_contract_feedback",
            "carry_current_output_as": "previous_invalid_project_network_output",
            "authority": "task_system.project_network.quality_retry_policy",
        },
    }


def _model_response_only_tool_policy(reason: str) -> dict[str, Any]:
    return {
        "allowed_operations": ("op.model_response",),
        "operation_ceiling": ("op.model_response",),
        "blocked_operations": (
            "op.workspace_read",
            "op.workspace_search",
            "op.code_structure_read",
            "op.git_read",
            "op.project_network_read",
            "op.project_network_build",
            "op.project_network_maintenance",
            "op.memory_read",
            "op.memory_write_candidate",
            "op.shell",
            "op.web_search",
            "op.fetch_url",
        ),
        "reason": reason,
        "authority": "task_system.project_network.model_response_only_tool_policy",
    }


def _model_response_only_executor_policy(reason: str) -> dict[str, Any]:
    policy = _model_response_only_tool_policy(reason)
    return {
        "operation_policy": policy,
        "tool_policy": policy,
        "authority": "task_system.project_network.model_response_only_executor_policy",
    }


def _with_model_response_only_tools(metadata: dict[str, Any], *, reason: str) -> dict[str, Any]:
    policy = _model_response_only_tool_policy(reason)
    runtime_profile = dict(metadata.get("runtime_profile") or {})
    runtime_profile["tool_policy"] = policy
    runtime_profile["tool_exposure_policy"] = policy
    return {
        **dict(metadata or {}),
        "tools": policy,
        "runtime_profile": runtime_profile,
    }


def _project_network_prompt_contract(
    *,
    role: str,
    task: str,
    output: str,
    work_product_contract: dict[str, Any] | None = None,
    semantic_network_contract: dict[str, Any] | None = None,
    input_boundary_contract: dict[str, Any] | None = None,
    typed_submission_contract: dict[str, Any] | None = None,
    review_judgment_contract: dict[str, Any] | None = None,
    quality_gate_contract: dict[str, Any] | None = None,
    failure_handling_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "role_prompt": role,
        "task_instruction": task,
        "output_instruction": output,
        "input_boundary_contract": dict(input_boundary_contract or {}),
        "typed_submission_contract": dict(typed_submission_contract or {}),
        "review_judgment_contract": dict(review_judgment_contract or {}),
        "work_product_contract": dict(work_product_contract or {}),
        "semantic_network_contract": dict(semantic_network_contract or {}),
        "quality_gate_contract": dict(quality_gate_contract or {}),
        "failure_handling_contract": dict(failure_handling_contract or {}),
        "forbidden_behavior": [
            "不能修改源码、写文件或执行破坏性命令。",
            "不能发布最终 Project Semantic Space generation。",
            "不能把没有 evidence_ref 或 anchor_ref 的推测写成 accepted candidate。",
            "不能扩大 assigned_scope 或重新解释上游已裁决边界。",
        ],
        "definition_of_done": [
            "输出符合当前节点 output_contract。",
            "accepted candidate 均带可追踪 evidence_ref 或 anchor_ref。",
            "coverage、limitations 和冲突/拒绝项已明确列出。",
            "下游需要继续处理的 refs 或 blockers 已结构化呈现。",
        ],
    }


def _project_network_ast_runtime_policy(ast_mode: str, *, required: bool = False) -> dict[str, Any]:
    mode = str(ast_mode or "disabled").strip()
    if mode in {"", "disabled", "none", "off"}:
        return {}
    if mode == "basic_ast":
        read_units = ("file_outline", "import_outline", "symbol_outline")
        projection_policy = "outline_only"
        index_store_policy = "node_agent_basic_ast_index"
    else:
        read_units = ("file_module", "function_endpoint", "class_endpoint", "call_site", "import_edge", "relation_candidate")
        projection_policy = "file_module_index"
        index_store_policy = "node_agent_deep_ast_index"
    return {
        "context_policy": {
            "code_intelligence": {
                "ast": {
                    "enabled": True,
                    "mode": mode,
                    "required": required,
                    "language_profiles": ("python",),
                    "read_units": read_units,
                    "refresh_policy": "on_file_hash_change" if mode == "deep_ast" else "manual_or_file_hash_change",
                    "projection_policy": projection_policy,
                    "freshness_policy": "file_hash_bound",
                    "index_store_policy": index_store_policy,
                    "degraded_behavior": "report_low_confidence_and_request_deep_ast" if required else "use_outline_and_report_limitations",
                    "authority": "task_graph_node.runtime_policy.code_intelligence",
                }
            }
        }
    }


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
