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
            agent_id="agent:project_network_builder",
            agent_group_id="group.project_network_builders",
            agent_profile_id="project_network_builder_agent",
            node_contract_id="node-contract:project_network_module_index",
            output_contract_id="project_network.module_index.v1",
            prompt_contract=_project_network_prompt_contract(
                role="你是一名单文件语义模块索引员。",
                task="你只负责 assigned_scope 内的单文件模块职责、public surface、内部 endpoint 线索和模块级关系候选。你必须优先使用 Deep AST 和必要文件窗口。",
                output="输出 project_network.module_index.v1 结构化 work product，包含 module summary、public surface、candidate edges、coverage、limitations 和 evidence_refs。",
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


def _project_network_prompt_contract(*, role: str, task: str, output: str) -> dict[str, Any]:
    return {
        "role_prompt": role,
        "task_instruction": task,
        "output_instruction": output,
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
