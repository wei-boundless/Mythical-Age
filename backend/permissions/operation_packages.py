from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolPackageDefinition:
    package_id: str
    title: str
    description: str
    category: str
    operation_ids: tuple[str, ...]
    risk_level: str = "低"
    managed: bool = True
    default_enabled: bool = False
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operation_ids"] = list(self.operation_ids)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class ToolPackageSelection:
    package_id: str
    enabled: bool = True
    include_operations: tuple[str, ...] = ()
    exclude_operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["include_operations"] = list(self.include_operations)
        payload["exclude_operations"] = list(self.exclude_operations)
        return payload


def default_tool_packages() -> tuple[ToolPackageDefinition, ...]:
    return (
        ToolPackageDefinition(
            package_id="pkg.workspace.read",
            title="工作区读取",
            description="工作区路径/文本定位、精确读取和代码结构读取。默认启用，不修改内容。",
            category="本地文件",
            operation_ids=("op.workspace_search", "op.workspace_read", "op.code_structure_read"),
            risk_level="低",
            default_enabled=True,
            tags=("workspace", "read", "search", "code_structure"),
        ),
        ToolPackageDefinition(
            package_id="pkg.workspace.write",
            title="工作区写入",
            description="创建、覆盖或精确编辑工作区文件。",
            category="本地文件",
            operation_ids=("op.workspace_write", "op.workspace_edit"),
            risk_level="高",
            default_enabled=False,
            tags=("workspace", "write", "edit"),
        ),
        ToolPackageDefinition(
            package_id="pkg.agent.state",
            title="Agent 状态",
            description="维护当前任务的可见执行状态。",
            category="通用能力",
            operation_ids=("op.agent_todo",),
            risk_level="低",
            default_enabled=True,
            tags=("agent", "state"),
        ),
        ToolPackageDefinition(
            package_id="pkg.subagent",
            title="子 Agent 生命周期",
            description="启动、通信、观察和关闭任务内子 Agent。",
            category="通用能力",
            operation_ids=(
                "op.subagent_spawn",
                "op.subagent_message",
                "op.subagent_wait",
                "op.subagent_list",
                "op.subagent_close",
            ),
            risk_level="高",
            default_enabled=False,
            tags=("agent", "subagent", "lifecycle"),
        ),
        ToolPackageDefinition(
            package_id="pkg.git",
            title="Git",
            description="查看、准备、提交和远端推送 Git 变更；远端操作由 op.git_remote 单独表达。",
            category="版本控制",
            operation_ids=("op.git_read", "op.git_write", "op.git_remote"),
            risk_level="高",
            default_enabled=False,
            tags=("git", "vcs"),
            metadata={"read_operations": ("op.git_read",), "write_operations": ("op.git_write",), "remote_operations": ("op.git_remote",)},
        ),
        ToolPackageDefinition(
            package_id="pkg.project_network",
            title="项目网络",
            description="构建、读取、扩展和维护项目结构网络，并提交语义覆盖候选。",
            category="项目网络",
            operation_ids=(
                "op.project_network_read",
                "op.project_network_build",
                "op.project_network_maintenance",
                "op.project_network_semantic_submit",
                "op.project_network_control",
            ),
            risk_level="中",
            default_enabled=False,
            tags=("project_network", "deep_network", "semantic_overlay", "maintenance"),
            metadata={
                "state_owner": "file_management.project_structure",
                "storage": "storage/file_management/project_structure/project_structure.sqlite",
            },
        ),
        ToolPackageDefinition(
            package_id="pkg.web",
            title="网络查询",
            description="开放网络搜索和抓取网页内容。",
            category="实时查询",
            operation_ids=("op.web_search", "op.fetch_url"),
            risk_level="中",
            default_enabled=False,
            tags=("web", "network"),
        ),
        ToolPackageDefinition(
            package_id="pkg.browser",
            title="浏览器控制",
            description="观察和操作真实浏览器页面，用于页面状态、交互、截图和前端联调证据。",
            category="实时查询",
            operation_ids=("op.browser_control",),
            risk_level="高",
            default_enabled=False,
            tags=("browser", "web_automation", "interactive"),
        ),
        ToolPackageDefinition(
            package_id="pkg.media",
            title="多模态生成",
            description="生成图像和视觉资产。",
            category="多模态处理",
            operation_ids=("op.image_generate",),
            risk_level="高",
            default_enabled=False,
            tags=("image", "multimodal"),
        ),
        ToolPackageDefinition(
            package_id="pkg.office",
            title="办公文档处理",
            description="读取、创建、编辑和验证 Word、Excel、PowerPoint 与 PDF 产物。",
            category="文档数据",
            operation_ids=("op.office_document",),
            risk_level="高",
            default_enabled=False,
            tags=("office", "document", "word", "excel", "powerpoint", "pdf"),
        ),
        ToolPackageDefinition(
            package_id="pkg.memory",
            title="记忆读取",
            description="读取会话、状态或正式记忆视图。",
            category="知识检索",
            operation_ids=("op.memory_read",),
            risk_level="低",
            default_enabled=True,
            tags=("memory", "read"),
        ),
        ToolPackageDefinition(
            package_id="pkg.local_execution",
            title="本地执行",
            description="本地命令执行能力。",
            category="系统执行",
            operation_ids=("op.shell",),
            risk_level="极高",
            default_enabled=False,
            tags=("shell", "execution"),
        ),
        ToolPackageDefinition(
            package_id="pkg.local_mcp",
            title="本地能力端点",
            description="本地检索、PDF、结构化数据和附件 OCR 能力；不作为 ordinary native model tool 暴露。",
            category="文档数据",
            operation_ids=("op.mcp_retrieval", "op.mcp_pdf", "op.mcp_structured_data", "op.mcp_image_ocr"),
            risk_level="中",
            default_enabled=False,
            tags=("mcp", "local", "attachment"),
        ),
        ToolPackageDefinition(
            package_id="pkg.agent.capability",
            title="Agent 专家能力",
            description="受控专家 Agent 能力 operation，不对应普通模型可见工具。",
            category="通用能力",
            operation_ids=("op.codebase_search", "op.search_agent", "op.agent_bounded"),
            risk_level="中",
            default_enabled=False,
            tags=("agent", "capability", "subagent"),
        ),
        ToolPackageDefinition(
            package_id="pkg.commit_candidates",
            title="提交候选",
            description="记忆、会话消息和 artifact 结果引用的提交候选 operation。",
            category="系统状态",
            operation_ids=("op.memory_write_candidate", "op.session_message_candidate", "op.artifact_result_ref"),
            risk_level="中",
            default_enabled=False,
            tags=("commit_gate", "candidate"),
        ),
    )


def default_tool_package_map() -> dict[str, ToolPackageDefinition]:
    return {item.package_id: item for item in default_tool_packages()}


def parse_tool_package_selection(payload: Any) -> ToolPackageSelection | None:
    if isinstance(payload, str):
        value = payload.strip()
        return ToolPackageSelection(package_id=value) if value else None
    if not isinstance(payload, dict):
        return None
    package_id = str(payload.get("package_id") or payload.get("id") or "").strip()
    if not package_id:
        return None
    return ToolPackageSelection(
        package_id=package_id,
        enabled=bool(payload.get("enabled", True)),
        include_operations=tuple(_string_list(payload.get("include_operations"))),
        exclude_operations=tuple(_string_list(payload.get("exclude_operations"))),
    )


def resolve_tool_package_operations(
    selections: tuple[ToolPackageSelection, ...] | list[ToolPackageSelection],
    *,
    extra_allowed_operations: tuple[str, ...] | list[str] = (),
    blocked_operations: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    package_map = default_tool_package_map()
    resolved: list[str] = []
    excluded: set[str] = set()
    for selection in selections:
        if not selection.enabled:
            continue
        package = package_map.get(selection.package_id)
        if package is None:
            continue
        package_ops = _string_list(selection.include_operations) or list(package.operation_ids)
        resolved.extend(package_ops)
        excluded.update(_string_list(selection.exclude_operations))
    resolved.extend(_string_list(extra_allowed_operations))
    blocked = set(_string_list(blocked_operations))
    return tuple(_dedupe([item for item in resolved if item not in excluded and item not in blocked]))


def default_enabled_package_selections(*, include_high_risk_execution: bool = False) -> tuple[ToolPackageSelection, ...]:
    selections: list[ToolPackageSelection] = []
    for package in default_tool_packages():
        if not package.default_enabled:
            continue
        if package.package_id == "pkg.local_execution" and not include_high_risk_execution:
            continue
        selections.append(ToolPackageSelection(package_id=package.package_id))
    return tuple(selections)


def _string_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or ()) if str(item or "").strip()]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
