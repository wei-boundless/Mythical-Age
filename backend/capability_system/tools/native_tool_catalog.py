from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from capability_system.tools.base_tool import BaseTool
from capability_system.tools.contracts import (
    ToolExecutionContract,
    ToolOutputContract,
    ToolProjectionContract,
    ToolPromptExposurePolicy,
    ToolResolutionContract,
    ToolResourceExposurePolicy,
    ToolRuntimeVisibility,
)
from capability_system.tools.tool_units.agent_state_tool import AgentStateTool
from capability_system.tools.tool_units.browser_tool import BrowserTool
from capability_system.tools.tool_units.code_structure_tool import CodeStructureTool
from capability_system.tools.tool_units.git_tool import GitTool
from capability_system.tools.tool_units.image_tool import ImageTool
from capability_system.tools.tool_units.local_execution_tool import LocalExecutionTool
from capability_system.tools.tool_units.office_document_tool import OfficeDocumentTool
from capability_system.tools.tool_units.project_network_tool import ProjectNetworkTool
from capability_system.tools.tool_units.subagent_tool import SubagentTool
from capability_system.tools.tool_units.web_tool import WebTool
from permissions.operation_packages import default_tool_packages
from permissions.operations import build_default_operation_registry


ToolFactory = Callable[[Path], BaseTool]
_OPERATION_REGISTRY = build_default_operation_registry()


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    display_name: str
    operation_id: str
    module: str
    factory: ToolFactory | None = None
    contract: ToolExecutionContract = field(default_factory=ToolExecutionContract)
    resolution_contract: ToolResolutionContract = field(default_factory=ToolResolutionContract)
    output_contract: ToolOutputContract = field(default_factory=ToolOutputContract)
    projection_contract: ToolProjectionContract = field(default_factory=ToolProjectionContract)
    capability_tags: list[str] = field(default_factory=list)
    supported_modalities: list[str] = field(default_factory=list)
    safety_tags: list[str] = field(default_factory=list)
    route_hints: list[str] = field(default_factory=list)
    safe_for_auto_route: bool = False
    schema_identity: str = ""
    action_operation_ids: dict[str, str] = field(default_factory=dict)
    runtime_visibility: ToolRuntimeVisibility = "main_runtime"
    prompt_exposure_policy: ToolPromptExposurePolicy = "schema_only"
    resource_exposure_policy: ToolResourceExposurePolicy = "none"
    native_runtime_only: bool = False
    is_read_only: bool = field(init=False)
    is_destructive: bool = field(init=False)
    is_concurrency_safe: bool = field(init=False)

    def __post_init__(self) -> None:
        operation = _OPERATION_REGISTRY.get_operation(self.operation_id)
        if operation is None:
            raise ValueError(f"Tool {self.name!r} references unknown operation {self.operation_id!r}")
        for action, operation_id in dict(self.action_operation_ids or {}).items():
            if _OPERATION_REGISTRY.get_operation(operation_id) is None:
                raise ValueError(f"Tool {self.name!r} action {action!r} references unknown operation {operation_id!r}")
        object.__setattr__(self, "is_read_only", bool(operation.read_only))
        object.__setattr__(self, "is_destructive", bool(operation.destructive))
        object.__setattr__(self, "is_concurrency_safe", bool(operation.concurrency_safe))

    def build(self, base_dir: Path) -> BaseTool:
        if self.factory is None:
            raise RuntimeError(f"Tool {self.name!r} is native-runtime-only and has no BaseTool factory")
        return self.factory(base_dir)

    def to_registry_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("factory", None)
        return payload


def _contract(
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    owner_scope: str = "none",
    missing_binding_behavior: str = "clarify",
    context_policy: str = "inline",
    result_channel: str = "canonical",
) -> ToolExecutionContract:
    return ToolExecutionContract(
        required_inputs=list(required),
        optional_inputs=list(optional),
        owner_scope=owner_scope,
        missing_binding_behavior=missing_binding_behavior,
        context_policy=context_policy,
        result_channel=result_channel,
    )


def _definition(
    *,
    name: str,
    display_name: str,
    operation_id: str,
    module: str,
    factory: ToolFactory | None = None,
    contract: ToolExecutionContract | None = None,
    resolution_contract: ToolResolutionContract | None = None,
    output_contract: ToolOutputContract | None = None,
    capability_tags: tuple[str, ...] = (),
    supported_modalities: tuple[str, ...] = (),
    safety_tags: tuple[str, ...] = (),
    route_hints: tuple[str, ...] = (),
    safe_for_auto_route: bool = False,
    action_operation_ids: dict[str, str] | None = None,
    prompt_exposure_policy: ToolPromptExposurePolicy = "schema_only",
    resource_exposure_policy: ToolResourceExposurePolicy = "none",
    native_runtime_only: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        display_name=display_name,
        operation_id=operation_id,
        module=module,
        factory=factory,
        contract=contract or ToolExecutionContract(),
        resolution_contract=resolution_contract or ToolResolutionContract(),
        output_contract=output_contract or ToolOutputContract(),
        capability_tags=list(capability_tags),
        supported_modalities=list(supported_modalities),
        safety_tags=list(safety_tags),
        route_hints=list(route_hints),
        safe_for_auto_route=safe_for_auto_route,
        schema_identity=f"local.tools/{name}",
        action_operation_ids=dict(action_operation_ids or {}),
        prompt_exposure_policy=prompt_exposure_policy,
        resource_exposure_policy=resource_exposure_policy,
        native_runtime_only=native_runtime_only,
    )


def _tool_definitions() -> list[ToolDefinition]:
    return [
        _definition(
            name="agent_state",
            display_name="Agent State",
            operation_id="op.agent_todo",
            module="tools.agent_state_tool",
            factory=lambda base_dir: AgentStateTool(root_dir=base_dir),
            contract=_contract(
                required=("action",),
                optional=("session_id", "task_id", "items", "todo_id", "status", "notes"),
            ),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_canonical"),
            capability_tags=("todo", "planning", "progress_tracking", "agent_state"),
            supported_modalities=("task", "workspace", "text"),
            safety_tags=("state", "non_destructive"),
            route_hints=("tool", "agent_state", "task_progress"),
            prompt_exposure_policy="schema_plus_guidance",
        ),
        _definition(
            name="workspace_search",
            display_name="Workspace Search",
            operation_id="op.workspace_search",
            module="runtime.tool_runtime.native_tools",
            factory=None,
            contract=_contract(
                required=("action",),
                optional=(
                    "query",
                    "roots",
                    "paths",
                    "glob",
                    "pattern",
                    "max_results",
                    "output_mode",
                    "context",
                    "case_sensitive",
                    "head_limit",
                    "offset",
                ),
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=("workspace", "search", "path", "text", "locator", "symbol"),
            supported_modalities=("workspace", "text", "code"),
            safety_tags=("read",),
            route_hints=("tool", "workspace_search", "rg_like_search", "locator_only"),
            safe_for_auto_route=True,
            action_operation_ids={
                "path": "op.workspace_search",
                "text": "op.workspace_search",
                "glob": "op.workspace_search",
                "symbol": "op.code_structure_read",
            },
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
            native_runtime_only=True,
        ),
        _definition(
            name="workspace_read",
            display_name="Workspace Read",
            operation_id="op.workspace_read",
            module="runtime.tool_runtime.native_tools",
            factory=None,
            contract=_contract(
                required=("action",),
                optional=(
                    "path",
                    "start_line",
                    "line_count",
                    "read_intent",
                    "max_entries",
                    "replacement_id",
                    "task_run_id",
                    "start_byte",
                    "max_bytes",
                ),
                owner_scope="explicit_path",
            ),
            resolution_contract=ToolResolutionContract(path_field="path", path_kind="workspace"),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_canonical"),
            capability_tags=("workspace", "file", "directory", "metadata", "read"),
            supported_modalities=("workspace", "text", "code", "document"),
            safety_tags=("read",),
            route_hints=("tool", "workspace_read", "exact_evidence"),
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
            native_runtime_only=True,
        ),
        _definition(
            name="workspace_edit",
            display_name="Workspace Edit",
            operation_id="op.workspace_edit",
            module="runtime.tool_runtime.native_tools",
            factory=None,
            contract=_contract(
                required=("action", "path"),
                optional=(
                    "content",
                    "allow_overwrite",
                    "expected_previous_sha256",
                    "old_text",
                    "new_text",
                    "edits",
                    "base_sha256",
                    "base_mtime_ns",
                ),
                owner_scope="explicit_path",
                missing_binding_behavior="deny",
                context_policy="isolated",
            ),
            resolution_contract=ToolResolutionContract(path_field="path", path_kind="workspace"),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_if_canonical"),
            capability_tags=("workspace", "file", "write", "edit", "batch_edit"),
            supported_modalities=("workspace", "text", "code", "document"),
            safety_tags=("write", "local_write"),
            route_hints=("tool", "workspace_edit", "workspace_write"),
            action_operation_ids={"write": "op.workspace_write", "edit": "op.workspace_edit", "batch_edit": "op.workspace_edit"},
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
            native_runtime_only=True,
        ),
        _definition(
            name="code_structure",
            display_name="Code Structure",
            operation_id="op.code_structure_read",
            module="tools.code_structure_tool",
            factory=lambda base_dir: CodeStructureTool(root_dir=base_dir),
            contract=_contract(required=("action",), optional=("path", "query", "roots", "max_symbols", "max_results")),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=("code", "ast", "python", "symbol", "outline"),
            supported_modalities=("workspace", "code"),
            safety_tags=("read",),
            route_hints=("tool", "code_structure", "ast"),
            safe_for_auto_route=True,
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
        ),
        _definition(
            name="git",
            display_name="Git",
            operation_id="op.git_read",
            module="tools.git_tool",
            factory=lambda base_dir: GitTool(root_dir=base_dir),
            contract=_contract(
                required=("action",),
                optional=(
                    "short",
                    "path",
                    "staged",
                    "max_chars",
                    "max_count",
                    "revision",
                    "all_branches",
                    "branch_name",
                    "start_point",
                    "paths",
                    "message",
                    "remote",
                    "branch",
                ),
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=("git", "vcs", "workspace"),
            supported_modalities=("workspace", "system"),
            safety_tags=("read", "write", "git_write", "remote"),
            route_hints=("tool", "git"),
            action_operation_ids={
                "status": "op.git_read",
                "diff": "op.git_read",
                "log": "op.git_read",
                "show": "op.git_read",
                "branch_list": "op.git_read",
                "branch_create": "op.git_write",
                "stage": "op.git_write",
                "unstage": "op.git_write",
                "commit": "op.git_write",
                "restore": "op.git_write",
                "push": "op.git_remote",
            },
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
        ),
        _definition(
            name="subagent",
            display_name="Subagent",
            operation_id="op.subagent_spawn",
            module="tools.subagent_tool",
            factory=lambda base_dir: SubagentTool(root_dir=base_dir),
            contract=_contract(
                required=("action",),
                optional=(
                    "target_agent_id",
                    "goal",
                    "instructions",
                    "context_refs",
                    "expected_outputs",
                    "subagent_run_ref",
                    "message",
                    "since_message_ref",
                    "status",
                    "reason",
                ),
            ),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_canonical"),
            capability_tags=("agent", "subagent", "lifecycle"),
            supported_modalities=("task", "workspace", "text"),
            safety_tags=("agent_execution", "state"),
            route_hints=("tool", "subagent"),
            action_operation_ids={
                "spawn": "op.subagent_spawn",
                "send": "op.subagent_message",
                "wait": "op.subagent_wait",
                "list": "op.subagent_list",
                "close": "op.subagent_close",
            },
            prompt_exposure_policy="schema_plus_guidance",
        ),
        _definition(
            name="project_network",
            display_name="Project Network",
            operation_id="op.project_network_read",
            module="tools.project_network_tool",
            factory=lambda base_dir: ProjectNetworkTool(root_dir=base_dir),
            contract=_contract(
                required=("action",),
                optional=(
                    "build_id",
                    "scope_roots",
                    "generation",
                    "include_git_snapshot",
                    "node_id",
                    "stable_ref",
                    "path",
                    "edge_id",
                    "seed_node_ids",
                    "seed_stable_refs",
                    "seed_paths",
                    "edge_kinds",
                    "depth",
                    "limit",
                    "include_inbound",
                    "scope_root",
                    "max_nodes",
                    "max_edges",
                    "include_external",
                    "include_semantic_overlay",
                    "change_mode",
                    "skeleton_generation",
                    "change_set_id",
                    "group_by_folder_threshold",
                    "overlay_kind",
                    "skeleton_node_id",
                    "skeleton_edge_id",
                    "anchor_ref",
                    "status",
                    "confidence",
                    "payload",
                    "evidence_refs",
                    "created_by_task_run_id",
                    "created_by_agent_id",
                    "overlay_id",
                    "navigation_session_id",
                    "goal",
                    "anchor_node_ids",
                    "anchor_stable_refs",
                    "anchor_paths",
                    "route_depth",
                    "path_limit",
                    "selected_path_candidate_id",
                    "decision_kind",
                    "reason",
                    "decision_status",
                    "path_status",
                    "refresh_paths",
                    "include_local_slice",
                ),
            ),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_canonical"),
            capability_tags=("project_network", "project_structure", "deep_network", "semantic_overlay", "maintenance"),
            supported_modalities=("workspace", "code", "task"),
            safety_tags=("read", "state", "index_write"),
            route_hints=("tool", "project_network", "deep_network_management"),
            action_operation_ids={
                "build_skeleton": "op.project_network_build",
                "read_node": "op.project_network_read",
                "read_edge": "op.project_network_read",
                "expand": "op.project_network_read",
                "directory_relations": "op.project_network_read",
                "collect_changes": "op.project_network_maintenance",
                "repair_items": "op.project_network_maintenance",
                "submit_overlay": "op.project_network_semantic_submit",
                "start_navigation": "op.project_network_control",
                "read_paths": "op.project_network_control",
                "select_path": "op.project_network_control",
                "record_decision": "op.project_network_control",
            },
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
        ),
        _definition(
            name="memory",
            display_name="Memory",
            operation_id="op.memory_read",
            module="runtime.tool_runtime.native_tools",
            factory=None,
            contract=_contract(required=("query",), optional=("task_run_id", "project_id", "repositories", "collections", "limit")),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=("memory", "search", "read"),
            supported_modalities=("memory", "text", "task"),
            safety_tags=("read",),
            route_hints=("tool", "memory"),
            prompt_exposure_policy="schema_plus_guidance",
            native_runtime_only=True,
        ),
        _definition(
            name="web",
            display_name="Web",
            operation_id="op.web_search",
            module="tools.web_tool",
            factory=lambda base_dir: WebTool(root_dir=base_dir),
            contract=_contract(required=("action",), optional=("query", "url", "topic", "time_range", "max_results")),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=("web", "search", "fetch", "current_information"),
            supported_modalities=("web", "realtime"),
            safety_tags=("read", "network"),
            route_hints=("tool", "web", "latest_information"),
            safe_for_auto_route=True,
            action_operation_ids={"search": "op.web_search", "fetch": "op.fetch_url"},
            prompt_exposure_policy="schema_plus_guidance",
        ),
        _definition(
            name="browser",
            display_name="Browser",
            operation_id="op.browser_control",
            module="tools.browser_tool",
            factory=lambda base_dir: BrowserTool(root_dir=base_dir),
            contract=_contract(required=("action",), optional=("url", "selector", "text", "value", "timeout_ms", "screenshot_name")),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=("browser", "web_automation", "screenshot", "frontend_verification"),
            supported_modalities=("web", "browser", "image"),
            safety_tags=("network", "interactive", "external_write_possible"),
            route_hints=("tool", "browser"),
            prompt_exposure_policy="schema_plus_guidance",
        ),
        _definition(
            name="image",
            display_name="Image",
            operation_id="op.image_generate",
            module="tools.image_tool",
            factory=lambda base_dir: ImageTool(root_dir=base_dir),
            contract=_contract(
                required=("prompt",),
                optional=("model", "target_id", "asset_kind", "size", "quality", "request_timeout_seconds", "output_size", "overwrite"),
                context_policy="isolated",
            ),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_if_canonical"),
            capability_tags=("image", "multimodal", "asset_generation"),
            supported_modalities=("image", "asset"),
            safety_tags=("write", "external_model", "asset_write"),
            route_hints=("tool", "image"),
            prompt_exposure_policy="schema_plus_guidance",
        ),
        _definition(
            name="office_document",
            display_name="Office Document",
            operation_id="op.office_document",
            module="tools.office_document_tool",
            factory=lambda base_dir: OfficeDocumentTool(root_dir=base_dir),
            contract=_contract(
                required=("action", "path"),
                optional=("output_path", "target_file_type", "operations", "read_scope", "max_blocks", "allow_overwrite", "verification_level"),
                owner_scope="explicit_path",
                missing_binding_behavior="deny",
                context_policy="isolated",
            ),
            resolution_contract=ToolResolutionContract(path_field="path", path_kind="workspace"),
            output_contract=ToolOutputContract(display_mode="summary_text", persistence_policy="persist_if_canonical"),
            capability_tags=("office", "document", "word", "excel", "powerpoint", "pdf"),
            supported_modalities=("document", "spreadsheet", "presentation", "pdf"),
            safety_tags=("write", "local_write", "document_processing"),
            route_hints=("tool", "office_document", "document_processing"),
            prompt_exposure_policy="schema_plus_guidance",
            resource_exposure_policy="explicit_resource",
        ),
        _definition(
            name="local_execution",
            display_name="Local Execution",
            operation_id="op.shell",
            module="runtime.tool_runtime.native_tools",
            factory=lambda base_dir: LocalExecutionTool(root_dir=base_dir),
            contract=_contract(required=("command",), optional=("action", "verification_intent", "acceptance", "acceptance_checks"), context_policy="isolated", result_channel="tool_raw"),
            output_contract=ToolOutputContract(display_mode="raw_debug_only", persistence_policy="do_not_persist"),
            capability_tags=("shell", "terminal", "command", "local_execution"),
            supported_modalities=("system",),
            safety_tags=("write", "shell", "destructive"),
            route_hints=("tool", "local_execution", "local_command"),
            prompt_exposure_policy="schema_plus_guidance",
        ),
    ]


def get_tool_definitions() -> list[ToolDefinition]:
    return list(_tool_definitions())


def get_tool_definition_map() -> dict[str, ToolDefinition]:
    return {definition.name: definition for definition in get_tool_definitions()}


def build_tool_instances(base_dir: Path) -> list[BaseTool]:
    return [definition.build(base_dir) for definition in get_tool_definitions() if definition.factory is not None]


def build_tool_registry_payload() -> dict[str, Any]:
    definitions = get_tool_definitions()
    operation_ids_in_packages = {
        operation_id
        for package in default_tool_packages()
        for operation_id in package.operation_ids
    }
    return {
        "version": 3,
        "tool_count": len(definitions),
        "tools": [definition.to_registry_record() for definition in definitions],
        "tool_packages": [package.to_dict() for package in default_tool_packages()],
        "default_library": [
            {
                "tool_name": definition.name,
                "operation_id": definition.operation_id,
            }
            for definition in definitions
            if definition.operation_id not in operation_ids_in_packages
        ],
    }
