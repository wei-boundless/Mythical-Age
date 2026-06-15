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
            package_id="pkg.filesystem.read",
            title="文件只读",
            description="读取、查找和检查工作区文件，并恢复运行时持久化的只读工具输出，不修改内容。",
            category="本地文件",
            operation_ids=(
                "op.read_file",
                "op.read_persisted_tool_result",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.read_structured_file",
            ),
            risk_level="低",
            default_enabled=True,
            tags=("filesystem", "read", "runtime_context"),
        ),
        ToolPackageDefinition(
            package_id="pkg.filesystem.write",
            title="文件写入",
            description="创建、覆盖或精确编辑工作区文件。",
            category="本地文件",
            operation_ids=("op.write_file", "op.edit_file"),
            risk_level="高",
            default_enabled=True,
            tags=("filesystem", "write"),
        ),
        ToolPackageDefinition(
            package_id="pkg.search.local",
            title="本地搜索",
            description="搜索工作区路径和文本内容。",
            category="本地文件",
            operation_ids=("op.search_files", "op.search_text"),
            risk_level="低",
            default_enabled=True,
            tags=("search", "workspace"),
        ),
        ToolPackageDefinition(
            package_id="pkg.development.python",
            title="Python 开发工具",
            description="基于 Python 官方 ast 标准库的代码结构、符号定位、语法检查，以及开发诊断类只读工具。",
            category="开发工具",
            operation_ids=(
                "op.codebase_search",
                "op.python_code_outline",
                "op.python_symbol_search",
                "op.python_parse_check",
                "op.git_status",
                "op.git_diff",
                "op.git_log",
                "op.git_show",
                "op.git_branch_list",
            ),
            risk_level="低",
            default_enabled=True,
            tags=("development", "python", "official_ast", "code_intelligence"),
            metadata={
                "parser_authority": "python.stdlib.ast",
                "usage_policy": (
                    "For Python development tasks, use symbol/outline/parse tools before broad file reading. "
                    "File reads, writes, and command execution remain governed by their own generic packages."
                ),
            },
        ),
        ToolPackageDefinition(
            package_id="pkg.git.read",
            title="Git 只读",
            description="查看版本库状态、差异、日志、对象和分支。",
            category="版本控制",
            operation_ids=("op.git_status", "op.git_diff", "op.git_log", "op.git_show", "op.git_branch_list"),
            risk_level="低",
            default_enabled=True,
            tags=("git", "read", "vcs"),
        ),
        ToolPackageDefinition(
            package_id="pkg.git.write",
            title="Git 写入",
            description="创建分支、暂存指定文件、取消暂存、提交和恢复指定路径。",
            category="版本控制",
            operation_ids=("op.git_branch_create", "op.git_stage", "op.git_unstage", "op.git_commit", "op.git_restore"),
            risk_level="高",
            default_enabled=True,
            tags=("git", "write", "vcs"),
        ),
        ToolPackageDefinition(
            package_id="pkg.git.remote",
            title="Git 远端",
            description="推送分支到远端仓库。默认不启用。",
            category="版本控制",
            operation_ids=("op.git_push",),
            risk_level="极高",
            default_enabled=False,
            tags=("git", "remote", "push"),
        ),
        ToolPackageDefinition(
            package_id="pkg.web",
            title="网络查询",
            description="开放网络搜索和抓取网页内容。",
            category="实时查询",
            operation_ids=("op.web_search", "op.fetch_url"),
            risk_level="中",
            default_enabled=True,
            tags=("web", "network"),
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
            package_id="pkg.agent",
            title="Agent 状态",
            description="维护任务步骤状态。",
            category="通用能力",
            operation_ids=("op.agent_todo",),
            risk_level="低",
            default_enabled=True,
            tags=("agent", "state"),
        ),
        ToolPackageDefinition(
            package_id="pkg.subagent.lifecycle",
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
            package_id="pkg.execution",
            title="本地执行",
            description="本地命令和脚本执行能力。",
            category="系统执行",
            operation_ids=("op.shell", "op.python_repl"),
            risk_level="极高",
            default_enabled=False,
            tags=("shell", "execution"),
        ),
        ToolPackageDefinition(
            package_id="pkg.multimodal",
            title="多模态生成",
            description="生成图像和视觉资产。",
            category="多模态处理",
            operation_ids=("op.image_generate",),
            risk_level="高",
            default_enabled=True,
            tags=("image", "multimodal"),
        ),
        ToolPackageDefinition(
            package_id="pkg.mcp.local",
            title="本地能力端点",
            description="调用本地检索、PDF、结构化数据和附件 OCR MCP 能力。",
            category="文档数据",
            operation_ids=("op.mcp_retrieval", "op.mcp_pdf", "op.mcp_structured_data", "op.mcp_image_ocr"),
            risk_level="中",
            default_enabled=True,
            tags=("mcp", "local", "attachment"),
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
        if package.package_id == "pkg.execution" and not include_high_risk_execution:
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
