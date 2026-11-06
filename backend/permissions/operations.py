from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OperationDescriptor:
    operation_id: str
    operation_type: str
    title: str
    capability_summary: str
    provider: str = "builtin"
    aliases: tuple[str, ...] = ()
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    input_contract_ref: str = ""
    output_contract_ref: str = ""
    risk_tags: tuple[str, ...] = ()
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False
    open_world: bool = False
    concurrency_safe: bool = False
    requires_user_interaction: bool = False
    requires_approval_by_default: bool = False
    max_result_size_chars: int = 0
    interrupt_behavior: str = "defer"
    deferred_loading: bool = False
    always_load: bool = False
    safety_validator_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OperationRegistry:
    def __init__(self, operations: list[OperationDescriptor] | None = None) -> None:
        self._operations: dict[str, OperationDescriptor] = {}
        self._aliases: dict[str, str] = {}
        for operation in operations or []:
            self.register(operation)

    def register(self, operation: OperationDescriptor) -> None:
        self._operations[operation.operation_id] = operation
        self._aliases[operation.operation_id] = operation.operation_id
        for alias in operation.aliases:
            if alias:
                self._aliases[alias] = operation.operation_id

    def normalize_id(self, operation_id: str) -> str:
        value = str(operation_id or "").strip()
        return self._aliases.get(value, value)

    def get_operation(self, operation_id: str) -> OperationDescriptor | None:
        return self._operations.get(self.normalize_id(operation_id))

    def list_operations(self) -> list[OperationDescriptor]:
        return [self._operations[key] for key in sorted(self._operations)]

    def export_manifest(self) -> dict[str, Any]:
        return {
            "authority": "operation_registry",
            "operations": [operation.to_dict() for operation in self.list_operations()],
        }


def _descriptor(
    operation_id: str,
    operation_type: str,
    title: str,
    capability_summary: str,
    *,
    aliases: tuple[str, ...] = (),
    risk_tags: tuple[str, ...] = (),
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
    concurrency_safe: bool = False,
    requires_user_interaction: bool = False,
    requires_approval_by_default: bool = False,
    max_result_size_chars: int = 0,
    interrupt_behavior: str = "defer",
    deferred_loading: bool = False,
    always_load: bool = False,
    safety_validator_ref: str = "",
    metadata: dict[str, Any] | None = None,
) -> OperationDescriptor:
    input_contract_ref = f"{operation_id}.input"
    output_contract_ref = f"{operation_id}.output"
    return OperationDescriptor(
        operation_id=operation_id,
        operation_type=operation_type,
        title=title,
        capability_summary=capability_summary,
        aliases=aliases,
        input_contract={"contract_ref": input_contract_ref},
        output_contract={"contract_ref": output_contract_ref},
        input_contract_ref=input_contract_ref,
        output_contract_ref=output_contract_ref,
        risk_tags=risk_tags,
        read_only=read_only,
        destructive=destructive,
        idempotent=idempotent,
        open_world=open_world,
        concurrency_safe=concurrency_safe,
        requires_user_interaction=requires_user_interaction,
        requires_approval_by_default=requires_approval_by_default,
        max_result_size_chars=max_result_size_chars,
        interrupt_behavior=interrupt_behavior,
        deferred_loading=deferred_loading,
        always_load=always_load,
        safety_validator_ref=safety_validator_ref,
        metadata=dict(metadata or {}),
    )


def default_operation_descriptors() -> list[OperationDescriptor]:
    return [
        _descriptor(
            "op.model_response",
            "model",
            "Model response",
            "Generate the model response for the current agent invocation.",
            aliases=("model_response", "main_response"),
            risk_tags=("model_response", "read_only"),
            read_only=True,
            concurrency_safe=True,
            max_result_size_chars=80_000,
            interrupt_behavior="abort_safe",
            always_load=True,
        ),
        _descriptor(
            "op.agent_todo",
            "state",
            "Agent state",
            "Maintain the current task's visible execution state.",
            aliases=("agent_state",),
            risk_tags=("agent_state", "session_write_candidate", "non_destructive"),
            max_result_size_chars=40_000,
            interrupt_behavior="checkpoint_then_abort",
        ),
        _descriptor(
            "op.workspace_search",
            "filesystem",
            "Workspace search",
            "Locate workspace paths and text candidates without treating previews as exact evidence.",
            aliases=("workspace_search",),
            risk_tags=("read_only", "local_read", "locator_only"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.workspace_read",
            "filesystem",
            "Workspace read",
            "Read exact workspace files, directories, metadata, and persisted runtime tool output.",
            aliases=("workspace_read",),
            risk_tags=("read_only", "local_read", "exact_evidence"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.workspace_write",
            "filesystem",
            "Workspace write",
            "Create or overwrite explicit workspace files under file evidence and overwrite guards.",
            aliases=("workspace_write",),
            risk_tags=("local_write",),
            requires_user_interaction=True,
            requires_approval_by_default=True,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.workspace_edit",
            "filesystem",
            "Workspace edit",
            "Precisely edit existing workspace files with current read evidence.",
            aliases=("workspace_edit",),
            risk_tags=("local_write",),
            requires_user_interaction=True,
            requires_approval_by_default=True,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.code_structure_read",
            "code_intelligence",
            "Code structure read",
            "Read AST-backed code outlines, symbol indexes, and parse diagnostics.",
            aliases=("code_structure_read",),
            risk_tags=("read_only", "local_read", "code_intelligence"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.git_read",
            "vcs",
            "Git read",
            "Inspect repository status, diff, history, objects, and branches.",
            aliases=("git_read",),
            risk_tags=("read_only", "git_read"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
        ),
        _descriptor(
            "op.git_write",
            "vcs",
            "Git write",
            "Create branches, stage paths, unstage paths, commit, or restore explicit paths.",
            aliases=("git_write",),
            risk_tags=("git_write", "local_write"),
            requires_user_interaction=True,
            requires_approval_by_default=True,
            concurrency_safe=False,
            max_result_size_chars=40_000,
        ),
        _descriptor(
            "op.git_remote",
            "vcs",
            "Git remote",
            "Push a branch to a git remote without force.",
            aliases=("git_remote",),
            risk_tags=("git_write", "remote_write", "network"),
            open_world=True,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            concurrency_safe=False,
            max_result_size_chars=40_000,
        ),
        _descriptor(
            "op.subagent_spawn",
            "session",
            "Spawn subagent",
            "Create a child agent run under the current task.",
            aliases=("subagent_spawn",),
            risk_tags=("agent_execution", "subagent_lifecycle", "state_write"),
            interrupt_behavior="checkpoint_then_abort",
            deferred_loading=True,
        ),
        _descriptor(
            "op.subagent_message",
            "session",
            "Message subagent",
            "Send a message to an existing child agent run.",
            aliases=("subagent_message",),
            risk_tags=("agent_execution", "subagent_lifecycle", "state_write"),
            interrupt_behavior="checkpoint_then_abort",
            deferred_loading=True,
        ),
        _descriptor(
            "op.subagent_wait",
            "session",
            "Wait subagent",
            "Read a child agent mailbox once without blocking the main loop.",
            aliases=("subagent_wait",),
            risk_tags=("agent_execution", "subagent_lifecycle", "read_only"),
            read_only=True,
            idempotent=True,
            interrupt_behavior="abort_safe",
            deferred_loading=True,
        ),
        _descriptor(
            "op.subagent_list",
            "session",
            "List subagents",
            "List child agent runs for the current task and parent agent.",
            aliases=("subagent_list",),
            risk_tags=("agent_execution", "subagent_lifecycle", "read_only"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            interrupt_behavior="abort_safe",
            deferred_loading=True,
        ),
        _descriptor(
            "op.subagent_close",
            "session",
            "Close subagent",
            "Close or kill a child agent run owned by the current parent agent.",
            aliases=("subagent_close",),
            risk_tags=("agent_execution", "subagent_lifecycle", "state_write"),
            interrupt_behavior="checkpoint_then_abort",
            deferred_loading=True,
        ),
        _descriptor(
            "op.project_network_read",
            "project_network",
            "Project network read",
            "Read project skeleton nodes, edges, expansions, and directory relation projections.",
            aliases=("project_network_read",),
            risk_tags=("project_network", "deep_network", "read_only", "project_index"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=180_000,
        ),
        _descriptor(
            "op.project_network_build",
            "project_network",
            "Project network build",
            "Build deterministic project skeleton graph generations from file tree, AST, and git facts.",
            aliases=("project_network_build",),
            risk_tags=("project_network", "deep_network", "index_write", "state_write", "non_destructive"),
            max_result_size_chars=80_000,
            metadata={"writes_store": "storage/file_management/project_structure/project_structure.sqlite"},
        ),
        _descriptor(
            "op.project_network_maintenance",
            "project_network",
            "Project network maintenance",
            "Collect git changes and create semantic repair work items for the project network.",
            aliases=("project_network_maintenance",),
            risk_tags=("project_network", "deep_network", "state_write", "maintenance"),
            max_result_size_chars=120_000,
            metadata={"writes_store": "storage/file_management/project_structure/project_structure.sqlite"},
        ),
        _descriptor(
            "op.project_network_semantic_submit",
            "project_network",
            "Project network semantic submit",
            "Submit an agent-reviewed semantic overlay candidate attached to physical skeleton refs.",
            aliases=("project_network_semantic_submit",),
            risk_tags=("project_network", "deep_network", "state_write", "semantic_candidate", "memory_like"),
            max_result_size_chars=80_000,
            metadata={"accepted_overlay_requires_evidence_refs": True},
        ),
        _descriptor(
            "op.project_network_control",
            "project_network",
            "Project network control",
            "Maintain navigation sessions, precomputed path candidates, opened refs, and agent path decisions for project network navigation.",
            aliases=("project_network_control",),
            risk_tags=("project_network", "deep_network", "state_write", "agent_control", "non_destructive"),
            max_result_size_chars=120_000,
            metadata={
                "writes_store": "storage/file_management/project_structure/project_structure.sqlite",
                "does_not_publish_semantic_facts": True,
                "does_not_modify_physical_skeleton": True,
            },
        ),
        _descriptor(
            "op.web_search",
            "network",
            "Web search",
            "Search external web sources for current information.",
            aliases=("web_search",),
            risk_tags=("read_only", "network_open_world"),
            read_only=True,
            idempotent=True,
            open_world=True,
            concurrency_safe=True,
            max_result_size_chars=80_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.fetch_url",
            "network",
            "Fetch URL",
            "Fetch a specific external URL for evidence gathering.",
            aliases=("fetch_url",),
            risk_tags=("read_only", "external_fetch"),
            read_only=True,
            idempotent=True,
            open_world=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.browser_control",
            "browser",
            "Browser control",
            "Operate a local browser page for navigation, interaction, screenshots, and extraction.",
            aliases=("browser", "web_automation"),
            risk_tags=("network_open_world", "interactive_browser", "external_write_possible"),
            open_world=True,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            max_result_size_chars=40_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.image_generate",
            "multimodal",
            "Image generation",
            "Generate a saved image asset from a precise visual prompt.",
            aliases=("image", "generate_image", "text_to_image"),
            risk_tags=("external_model", "image_generation", "asset_write"),
            max_result_size_chars=20_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.office_document",
            "document",
            "Office document processing",
            "Inspect, create, edit, convert, and verify Word, Excel, PowerPoint, and PDF files.",
            aliases=("office_document", "office_file", "document_office", "mcp_office_document"),
            risk_tags=("document_processing", "local_read", "local_write", "office_document"),
            requires_user_interaction=True,
            requires_approval_by_default=True,
            max_result_size_chars=120_000,
            deferred_loading=True,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.shell",
            "shell",
            "Shell",
            "Run a local shell command.",
            aliases=("local_execution", "shell"),
            risk_tags=("shell_execution",),
            destructive=True,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            interrupt_behavior="terminate_process",
            safety_validator_ref="shell_read_only",
        ),
        _descriptor(
            "op.memory_read",
            "memory",
            "Memory read",
            "Read and search scoped formal task memory summaries.",
            aliases=("memory", "memory_read"),
            risk_tags=("read_only", "memory_read"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=40_000,
            metadata={"model_visible_tools": ["memory"], "database_search": True},
        ),
        _descriptor(
            "op.memory_write_candidate",
            "memory",
            "Memory write candidate",
            "Submit a memory write candidate for CommitGate review.",
            aliases=("memory_write_candidate",),
            risk_tags=("memory_write_candidate",),
            requires_approval_by_default=True,
            requires_user_interaction=True,
        ),
        _descriptor(
            "op.codebase_search",
            "agent_capability",
            "Codebase search capability",
            "Run the read-only codebase search capability for a codebase search subagent.",
            aliases=("codebase_search",),
            risk_tags=("read_only", "local_read", "agent_capability", "codebase_search"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
            metadata={
                "agent_id": "agent:codebase_searcher",
                "subagent_only": True,
                "required_operations": ["op.workspace_search", "op.workspace_read", "op.code_structure_read"],
                "source_class": "local_files",
            },
        ),
        _descriptor(
            "op.search_agent",
            "agent_capability",
            "DeepSearch capability",
            "Run the multi-source DeepSearch capability for a search specialist subagent.",
            aliases=("search_agent", "deepsearch"),
            risk_tags=("read_only", "agent_capability", "deepsearch"),
            read_only=True,
            idempotent=False,
            open_world=True,
            concurrency_safe=False,
            max_result_size_chars=120_000,
            deferred_loading=True,
            metadata={
                "agent_id": "agent:web_researcher",
                "subagent_only": True,
                "required_operations": ["op.web_search", "op.fetch_url"],
                "source_class": "web",
            },
        ),
        _descriptor(
            "op.mcp_retrieval",
            "mcp",
            "Retrieval MCP",
            "Run a bounded retrieval MCP capability.",
            aliases=("mcp_retrieval",),
            risk_tags=("mcp_execution", "read_only"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.mcp_pdf",
            "mcp",
            "PDF MCP",
            "Run a bounded PDF analysis MCP capability.",
            aliases=("mcp_pdf",),
            risk_tags=("mcp_execution", "read_only", "local_read", "document_analysis"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            deferred_loading=True,
            safety_validator_ref="filesystem_path",
            metadata={"source_class": "document"},
        ),
        _descriptor(
            "op.mcp_structured_data",
            "mcp",
            "Structured data MCP",
            "Run a bounded structured-data MCP capability.",
            aliases=("mcp_structured_data",),
            risk_tags=("mcp_execution", "read_only", "local_read", "structured_data"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            deferred_loading=True,
            safety_validator_ref="filesystem_path",
            metadata={"source_class": "data"},
        ),
        _descriptor(
            "op.mcp_image_ocr",
            "mcp",
            "Image OCR MCP",
            "Run the local image OCR MCP capability for a controlled image attachment.",
            aliases=("image_ocr", "ocr_image"),
            risk_tags=("mcp_execution", "read_only", "local_read", "attachment_processing", "ocr"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=40_000,
            deferred_loading=True,
            safety_validator_ref="filesystem_path",
            metadata={"source_class": "attachment"},
        ),
        _descriptor(
            "op.agent_bounded",
            "agent",
            "Bounded agent",
            "Run an isolated bounded specialist agent.",
            aliases=("agent_bounded",),
            risk_tags=("agent_execution",),
            requires_user_interaction=True,
            interrupt_behavior="checkpoint_then_abort",
            deferred_loading=True,
        ),
        _descriptor(
            "op.session_message_candidate",
            "session",
            "Session message candidate",
            "Submit a session message candidate for CommitGate.",
            aliases=("session_message_candidate",),
            risk_tags=("session_write_candidate",),
        ),
        _descriptor(
            "op.artifact_result_ref",
            "artifact",
            "Artifact result ref",
            "Submit an artifact result reference candidate.",
            aliases=("artifact_result_ref",),
            risk_tags=("artifact_write_candidate",),
        ),
    ]


def build_default_operation_registry() -> OperationRegistry:
    return OperationRegistry(default_operation_descriptors())
