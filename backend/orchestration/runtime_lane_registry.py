from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeLaneDescriptor:
    lane_id: str
    title: str
    category: str
    description: str
    requestable: bool = True
    system_only: bool = False
    default_operations: tuple[str, ...] = ()
    default_memory_scopes: tuple[str, ...] = ()
    default_context_sections: tuple[str, ...] = ()
    default_approval_policy: str = "default"
    delegation_kinds: tuple[str, ...] = ()
    runtime_template_hints: tuple[str, ...] = ()
    deprecated: bool = False
    replacement_lane_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_lane_registry"

    def __post_init__(self) -> None:
        if not self.lane_id:
            raise ValueError("RuntimeLaneDescriptor requires lane_id")
        if not self.title:
            raise ValueError("RuntimeLaneDescriptor requires title")
        if not self.category:
            raise ValueError("RuntimeLaneDescriptor requires category")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "default_operations",
            "default_memory_scopes",
            "default_context_sections",
            "delegation_kinds",
            "runtime_template_hints",
        ):
            payload[key] = list(payload[key])
        return payload

    def to_option(self) -> dict[str, Any]:
        return {
            "id": self.lane_id,
            "value": self.lane_id,
            "label": self.title,
            "description": self.description,
            "category": self.category,
            "requestable": self.requestable,
            "system_only": self.system_only,
            "deprecated": self.deprecated,
            "replacement_lane_id": self.replacement_lane_id,
            "metadata": dict(self.metadata or {}),
        }


def _lane(
    lane_id: str,
    title: str,
    category: str,
    description: str,
    *,
    requestable: bool = True,
    system_only: bool = False,
    default_operations: tuple[str, ...] = ("op.model_response",),
    default_memory_scopes: tuple[str, ...] = (),
    default_context_sections: tuple[str, ...] = ("task", "runtime_contracts"),
    default_approval_policy: str = "default",
    delegation_kinds: tuple[str, ...] = (),
    runtime_template_hints: tuple[str, ...] = (),
    deprecated: bool = False,
    replacement_lane_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> RuntimeLaneDescriptor:
    return RuntimeLaneDescriptor(
        lane_id=lane_id,
        title=title,
        category=category,
        description=description,
        requestable=requestable,
        system_only=system_only,
        default_operations=default_operations,
        default_memory_scopes=default_memory_scopes,
        default_context_sections=default_context_sections,
        default_approval_policy=default_approval_policy,
        delegation_kinds=delegation_kinds,
        runtime_template_hints=runtime_template_hints,
        deprecated=deprecated,
        replacement_lane_id=replacement_lane_id,
        metadata=dict(metadata or {}),
    )


def default_runtime_lane_descriptors() -> tuple[RuntimeLaneDescriptor, ...]:
    read_ops = ("op.model_response", "op.read_file", "op.search_text")
    return (
        _lane(
            "role_interaction",
            "角色模式交互",
            "主 Agent 模式",
            "灵魂系统主场，用于角色对话、记忆延续、轻问答和只读检索。",
            default_operations=("op.model_response", "op.mcp_retrieval", "op.web_search", "op.fetch_url", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate"),
            default_context_sections=("conversation", "state", "projection", "task", "runtime_contracts"),
            default_approval_policy="read_only_first",
            runtime_template_hints=("builtin.main.default",),
            metadata={"interaction_mode": "role_mode", "projection_strength": "primary"},
        ),
        _lane(
            "standard_task",
            "标准模式任务",
            "主 Agent 模式",
            "主 Agent 在当前回合内用有限工具解决明确问题，并给出真实依据和限制。",
            default_operations=(
                "op.model_response",
                "op.read_file",
                "op.read_structured_file",
                "op.search_text",
                "op.search_files",
                "op.web_search",
                "op.fetch_url",
                "op.write_file",
                "op.edit_file",
                "op.shell",
            ),
            default_memory_scopes=("conversation_readonly", "state_readonly", "task_working_memory"),
            default_context_sections=("conversation", "task", "projection", "tool", "runtime_contracts", "working_memory"),
            default_approval_policy="task_bounded_write",
            runtime_template_hints=("builtin.main.default",),
            metadata={"interaction_mode": "standard_mode", "projection_strength": "companion"},
        ),
        _lane(
            "professional_task",
            "专业模式长任务",
            "主 Agent 模式",
            "主 Agent 以语义契约、专业职责、证据包、checkpoint 和交付验证承接长任务。",
            default_operations=(
                "op.model_response",
                "op.read_file",
                "op.read_structured_file",
                "op.search_text",
                "op.search_files",
                "op.git_status",
                "op.git_diff",
                "op.memory_read",
                "op.delegate_to_agent",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.web_search",
                "op.fetch_url",
            ),
            default_memory_scopes=("conversation_readonly", "state_readonly", "task_working_memory"),
            default_context_sections=(
                "conversation",
                "task",
                "projection",
                "tool",
                "runtime_contracts",
                "runtime_trace",
                "working_memory",
            ),
            default_approval_policy="task_bounded_write",
            delegation_kinds=("rag", "pdf_reading", "table_analysis", "web_research", "readonly_exploration"),
            runtime_template_hints=("builtin.main.default",),
            metadata={
                "interaction_mode": "professional_mode",
                "projection_strength": "style_only",
                "runtime_driver": "professional_task_run",
            },
        ),
        _lane(
            "full_interactive",
            "主会话完整交互",
            "主 Agent 场景",
            "主 Agent 承接用户当前回合、工具调用和最终答复的完整交互场景。",
            requestable=False,
            default_operations=("op.model_response", "op.read_file", "op.search_text", "op.delegate_to_agent"),
            default_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate"),
            default_context_sections=("conversation", "state", "task", "projection", "tool", "runtime_contracts"),
            runtime_template_hints=("builtin.main.default",),
            deprecated=True,
            replacement_lane_id="role_interaction",
        ),
        _lane(
            "task_dispatch",
            "任务分派",
            "主 Agent 场景",
            "主 Agent 将当前目标拆分为可执行任务或子 Agent 委派的场景。",
            requestable=False,
            default_operations=("op.model_response", "op.delegate_to_agent"),
            default_context_sections=("conversation", "task", "projection", "runtime_contracts"),
            runtime_template_hints=("builtin.main.default",),
            deprecated=True,
            replacement_lane_id="professional_task",
        ),
        _lane(
            "final_integration",
            "最终整合",
            "主 Agent 场景",
            "主 Agent 汇总子任务、工具结果和产物后生成主回答的场景。",
            requestable=False,
            default_operations=("op.model_response", "op.read_file", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly"),
            default_context_sections=("conversation", "task", "artifact_refs", "runtime_contracts"),
            runtime_template_hints=("builtin.main.default",),
            deprecated=True,
            replacement_lane_id="professional_task",
        ),
        _lane(
            "game_delivery",
            "游戏交付",
            "主 Agent 场景",
            "主 Agent 承接游戏或交互体验交付的场景。",
            default_operations=("op.model_response", "op.read_file", "op.write_file", "op.edit_file"),
            default_context_sections=("conversation", "task", "projection", "tool", "runtime_contracts"),
            default_approval_policy="task_bounded_write",
            runtime_template_hints=("builtin.main.default",),
        ),
        _lane(
            "retrieval_delegate",
            "检索分析委派",
            "内置专业 Agent",
            "RAG 专业 Agent 处理知识库检索、证据查找和结果摘要的场景。",
            default_operations=("op.model_response", "op.mcp_retrieval", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly"),
            default_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
            default_approval_policy="read_only_first",
            delegation_kinds=("evidence_lookup", "retrieval", "rag"),
            runtime_template_hints=("builtin.specialist.rag_analyst",),
        ),
        _lane(
            "pdf_delegate",
            "PDF 阅读委派",
            "内置专业 Agent",
            "PDF 专业 Agent 解析、阅读和归纳 PDF 文档的场景。",
            default_operations=("op.model_response", "op.mcp_pdf", "op.read_file"),
            default_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            default_approval_policy="read_only_first",
            delegation_kinds=("pdf_reading", "document_analysis"),
            runtime_template_hints=("builtin.specialist.pdf_reader",),
        ),
        _lane(
            "structured_data_delegate",
            "结构化数据分析委派",
            "内置专业 Agent",
            "表格或结构化文件专业 Agent 执行数据读取、查询和分析的场景。",
            default_operations=("op.model_response", "op.mcp_structured_data", "op.read_structured_file", "op.read_file"),
            default_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            default_approval_policy="read_only_first",
            delegation_kinds=("table_analysis", "structured_data"),
            runtime_template_hints=("builtin.specialist.table_analyst",),
        ),
        _lane(
            "web_research_delegate",
            "网页研究委派",
            "内置专业 Agent",
            "网页研究专业 Agent 搜索、打开网页并归纳当前信息的场景。",
            default_operations=("op.model_response", "op.web_search", "op.fetch_url"),
            default_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            default_approval_policy="read_only_first",
            delegation_kinds=("web_research", "external_web_lookup", "current_information_lookup", "official_source_lookup"),
            runtime_template_hints=("builtin.specialist.web_researcher",),
        ),
        _lane(
            "readonly_exploration",
            "只读探索",
            "内置专业 Agent",
            "专业 Agent 在不写入、不执行危险操作的前提下读取材料并形成分析的场景。",
            default_operations=("op.model_response", "op.read_file", "op.search_text", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly"),
            default_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            default_approval_policy="read_only_first",
        ),
        _lane(
            "memory_trace_read",
            "记忆追踪读取",
            "系统管理 Agent",
            "系统管理 Agent 读取记忆运行视图、记忆链路和相关诊断的场景。",
            system_only=True,
            default_operations=("op.model_response", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly"),
            default_context_sections=("task", "runtime_trace", "memory_runtime_view", "prompt_manifest", "runtime_contracts"),
            default_approval_policy="read_only_first",
            runtime_template_hints=("builtin.system.memory_manager", "builtin.system.health_manager"),
        ),
        _lane(
            "session_memory_maintenance",
            "会话记忆整理",
            "系统管理 Agent",
            "记忆管理 Agent 整理当前会话压缩记忆候选的场景。",
            system_only=True,
            default_operations=("op.model_response", "op.memory_read", "op.memory_write_candidate"),
            default_memory_scopes=("conversation_readonly", "state_readonly", "session_memory_write_candidate"),
            default_context_sections=("task", "runtime_trace", "memory_runtime_view", "runtime_contracts"),
            default_approval_policy="read_only_first",
            runtime_template_hints=("builtin.system.memory_manager",),
        ),
        _lane(
            "durable_memory_extraction",
            "持久记忆提取",
            "系统管理 Agent",
            "记忆管理 Agent 判断并生成跨会话持久记忆候选的场景。",
            system_only=True,
            default_operations=("op.model_response", "op.memory_read", "op.memory_write_candidate"),
            default_memory_scopes=("conversation_readonly", "state_readonly", "durable_memory_write_candidate"),
            default_context_sections=("task", "runtime_trace", "memory_runtime_view", "runtime_contracts"),
            default_approval_policy="read_only_first",
            runtime_template_hints=("builtin.system.memory_manager",),
        ),
        _lane(
            "memory_candidate_review",
            "记忆候选审查",
            "系统管理 Agent",
            "记忆管理 Agent 审查待写入记忆候选质量和归属的场景。",
            system_only=True,
            default_operations=("op.model_response", "op.memory_read", "op.memory_write_candidate"),
            default_memory_scopes=("conversation_readonly", "state_readonly", "long_term_candidate"),
            default_context_sections=("task", "runtime_trace", "memory_runtime_view", "runtime_contracts"),
            default_approval_policy="read_only_first",
            runtime_template_hints=("builtin.system.memory_manager",),
        ),
        _lane(
            "health_issue_read",
            "健康问题读取",
            "系统管理 Agent",
            "健康管理 Agent 读取健康问题、问题上下文和诊断材料的场景。",
            system_only=True,
            default_operations=read_ops,
            default_memory_scopes=("issue_local_readonly", "health_trace_readonly"),
            default_context_sections=("task", "health_issue", "runtime_trace", "runtime_contracts"),
            default_approval_policy="read_only_first",
            runtime_template_hints=("builtin.system.health_manager",),
        ),
        _lane("health_trace_read", "健康追踪读取", "系统管理 Agent", "健康管理 Agent 读取健康系统运行追踪的场景。", system_only=True, default_operations=read_ops, default_memory_scopes=("issue_local_readonly", "health_trace_readonly"), default_context_sections=("task", "health_issue", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.health_manager",)),
        _lane("prompt_trace_read", "Prompt 追踪读取", "系统管理 Agent", "系统管理 Agent 读取 prompt manifest 和投影诊断的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "prompt_manifest", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.health_manager",)),
        _lane("runtime_trace_read", "运行追踪读取", "系统管理 Agent", "系统管理 Agent 读取 RuntimeLoop 事件和运行诊断的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.health_manager",)),
        _lane("assertion_trace_read", "断言追踪读取", "系统管理 Agent", "系统管理 Agent 读取测试断言、健康断言和失败证据的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "assertions", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.health_manager",)),
        _lane("case_draft_candidate", "修复案例草案", "系统管理 Agent", "健康管理 Agent 生成修复案例候选而不直接改代码的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "health_issue", "runtime_trace", "assertions", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.health_manager",)),
        _lane("fix_verification_candidate", "修复验证候选", "系统管理 Agent", "健康管理 Agent 检查修复证据并生成验证候选的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "health_issue", "runtime_trace", "assertions", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.health_manager",)),
        _lane("config_trace_read", "配置追踪读取", "系统管理 Agent", "配置管理 Agent 读取配置状态和变更诊断的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.config_manager",)),
        _lane("task_trace_read", "任务追踪读取", "系统管理 Agent", "任务管理 Agent 读取任务定义、任务图和运行关联诊断的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.task_manager",)),
        _lane("capability_trace_read", "能力追踪读取", "系统管理 Agent", "能力管理 Agent 读取工具、MCP、Skill 和能力目录诊断的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first", runtime_template_hints=("builtin.system.capability_manager",)),
        _lane("permission_trace_read", "权限追踪读取", "系统管理 Agent", "系统管理 Agent 读取权限管线、准入和资源策略诊断的场景。", system_only=True, default_operations=read_ops, default_context_sections=("task", "runtime_trace", "runtime_contracts"), default_approval_policy="read_only_first"),
        _lane(
            "coordination_task",
            "任务图协调运行",
            "任务图场景",
            "TaskGraph 节点或协调运行实例使用的图化执行场景。",
            default_operations=("op.model_response", "op.read_file", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly"),
            default_context_sections=("task", "projection", "runtime_contracts", "artifact_refs", "memory_runtime_view"),
        ),
        _lane(
            "task_graph_monitor",
            "任务图监测",
            "任务图场景",
            "TaskGraph 通用异步监测节点读取运行状态并生成监测意见的场景。",
            default_operations=("op.model_response", "op.read_file", "op.search_text", "op.memory_read"),
            default_memory_scopes=("conversation_readonly", "state_readonly"),
            default_context_sections=("task", "runtime_trace", "runtime_contracts", "artifact_refs"),
            default_approval_policy="read_only_first",
        ),
        _lane(
            "resource",
            "图资源节点",
            "任务图场景",
            "TaskGraph 资源节点占位场景，用于表达记忆、产物或运行资源，不代表模型执行权限。",
            requestable=False,
            default_operations=(),
            default_context_sections=(),
            metadata={"runtime_executable": False},
        ),
        _lane(
            "system_memory",
            "系统记忆资源",
            "任务图场景",
            "TaskGraph 中系统记忆资源节点使用的场景标识，不代表模型执行权限。",
            requestable=False,
            system_only=True,
            default_operations=(),
            default_context_sections=(),
            metadata={"runtime_executable": False},
        ),
    )


class RuntimeLaneRegistry:
    def __init__(self, descriptors: tuple[RuntimeLaneDescriptor, ...] | None = None) -> None:
        self._descriptors = descriptors or default_runtime_lane_descriptors()
        self._by_id = {item.lane_id: item for item in self._descriptors}

    def list_lanes(self, *, include_non_requestable: bool = True) -> tuple[RuntimeLaneDescriptor, ...]:
        lanes = tuple(self._descriptors)
        if include_non_requestable:
            return lanes
        return tuple(item for item in lanes if item.requestable and not item.deprecated)

    def get(self, lane_id: str) -> RuntimeLaneDescriptor | None:
        return self._by_id.get(str(lane_id or "").strip())

    def require(self, lane_id: str) -> RuntimeLaneDescriptor:
        lane = self.get(lane_id)
        if lane is None:
            raise ValueError(f"unknown runtime lane: {lane_id}")
        return lane

    def normalize_sequence(
        self,
        lanes: Any,
        *,
        allow_unregistered: bool = False,
        allow_system_only: bool = True,
    ) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in list(lanes or []):
            lane_id = str(raw or "").strip()
            if not lane_id or lane_id in seen:
                continue
            descriptor = self.get(lane_id)
            if descriptor is None:
                if allow_unregistered:
                    seen.add(lane_id)
                    result.append(lane_id)
                    continue
                raise ValueError(f"unknown runtime lane: {lane_id}")
            if descriptor.system_only and not allow_system_only:
                raise ValueError(f"runtime lane is system-only: {lane_id}")
            seen.add(lane_id)
            result.append(lane_id)
        return tuple(result)

    def option_payloads(self, *, include_non_requestable: bool = False) -> list[dict[str, Any]]:
        return [item.to_option() for item in self.list_lanes(include_non_requestable=include_non_requestable)]

    def catalog_payload(self) -> dict[str, Any]:
        return {
            "authority": "orchestration.runtime_lane_registry",
            "runtime_lanes": [item.to_dict() for item in self.list_lanes()],
            "runtime_lane_options": self.option_payloads(include_non_requestable=False),
        }


DEFAULT_RUNTIME_LANE_REGISTRY = RuntimeLaneRegistry()


def normalize_runtime_lane_sequence(
    lanes: Any,
    *,
    allow_unregistered: bool = False,
    allow_system_only: bool = True,
) -> tuple[str, ...]:
    return DEFAULT_RUNTIME_LANE_REGISTRY.normalize_sequence(
        lanes,
        allow_unregistered=allow_unregistered,
        allow_system_only=allow_system_only,
    )


def runtime_lane_option_payloads(*, include_non_requestable: bool = False) -> list[dict[str, Any]]:
    return DEFAULT_RUNTIME_LANE_REGISTRY.option_payloads(include_non_requestable=include_non_requestable)

