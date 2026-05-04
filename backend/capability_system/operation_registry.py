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
            "Generate the model response for the single-agent runtime lane.",
            aliases=("model_response", "main_response"),
            risk_tags=("model_response", "read_only"),
            read_only=True,
            idempotent=False,
            concurrency_safe=True,
            max_result_size_chars=80_000,
            interrupt_behavior="abort_safe",
            always_load=True,
        ),
        _descriptor(
            "op.read_file",
            "filesystem",
            "Read file",
            "Read task-relevant local workspace files.",
            aliases=("read_file",),
            risk_tags=("read_only", "local_read"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.search_files",
            "filesystem",
            "Search files",
            "Find files in the local workspace.",
            aliases=("search_files",),
            risk_tags=("read_only", "local_read"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=80_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.search_text",
            "filesystem",
            "Search text",
            "Search text in local workspace files.",
            aliases=("search_text",),
            risk_tags=("read_only", "local_read"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
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
            "op.get_weather",
            "network",
            "Get weather",
            "Read current weather information for a location.",
            aliases=("get_weather",),
            risk_tags=("read_only", "network_open_world"),
            read_only=True,
            idempotent=True,
            open_world=True,
            concurrency_safe=True,
            max_result_size_chars=40_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.get_gold_price",
            "network",
            "Get gold price",
            "Read current gold price information.",
            aliases=("get_gold_price",),
            risk_tags=("read_only", "network_open_world", "finance"),
            read_only=True,
            idempotent=True,
            open_world=True,
            concurrency_safe=True,
            max_result_size_chars=40_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.search_knowledge",
            "memory",
            "Search knowledge",
            "Read local knowledge retrieval results.",
            aliases=("search_knowledge",),
            risk_tags=("read_only", "memory_read", "retrieval"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=80_000,
        ),
        _descriptor(
            "op.pdf_analysis",
            "filesystem",
            "PDF analysis",
            "Read and analyze a local PDF file.",
            aliases=("pdf_analysis",),
            risk_tags=("read_only", "local_read", "document_analysis"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.structured_data_analysis",
            "filesystem",
            "Structured data analysis",
            "Read and analyze a local structured data file.",
            aliases=("structured_data_analysis",),
            risk_tags=("read_only", "local_read", "structured_data"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.analyze_multimodal_file",
            "filesystem",
            "Analyze multimodal file",
            "Read and inspect a local multimodal file.",
            aliases=("analyze_multimodal_file",),
            risk_tags=("read_only", "local_read", "multimodal"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=120_000,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.index_multimodal_file",
            "filesystem",
            "Index multimodal file",
            "Index a local multimodal file into an internal artifact candidate.",
            aliases=("index_multimodal_file",),
            risk_tags=("local_write", "indexing", "multimodal"),
            destructive=False,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            interrupt_behavior="defer",
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.write_file",
            "filesystem",
            "Write file",
            "Create or overwrite a local file.",
            aliases=("write_file",),
            risk_tags=("local_write",),
            destructive=False,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.edit_file",
            "filesystem",
            "Edit file",
            "Modify an existing local file.",
            aliases=("edit_file",),
            risk_tags=("local_write",),
            destructive=False,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            safety_validator_ref="filesystem_path",
        ),
        _descriptor(
            "op.shell",
            "shell",
            "Shell",
            "Run a local shell command.",
            aliases=("shell", "terminal", "op.terminal"),
            risk_tags=("shell_execution",),
            destructive=True,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            interrupt_behavior="terminate_process",
            safety_validator_ref="shell_read_only",
        ),
        _descriptor(
            "op.python_repl",
            "shell",
            "Python REPL",
            "Run local Python code.",
            aliases=("python_repl",),
            risk_tags=("python_execution",),
            destructive=True,
            requires_user_interaction=True,
            requires_approval_by_default=True,
            interrupt_behavior="terminate_process",
        ),
        _descriptor(
            "op.memory_read",
            "memory",
            "Memory read",
            "Read scoped memory summaries.",
            aliases=("memory_read",),
            risk_tags=("read_only", "memory_read"),
            read_only=True,
            idempotent=True,
            concurrency_safe=True,
            max_result_size_chars=40_000,
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
            "op.mcp_retrieval",
            "mcp",
            "Retrieval MCP",
            "Run a bounded retrieval MCP capability.",
            aliases=("mcp_retrieval",),
            risk_tags=("mcp_execution",),
            max_result_size_chars=120_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.mcp_pdf",
            "mcp",
            "PDF MCP",
            "Run a bounded PDF analysis MCP capability.",
            aliases=("mcp_pdf",),
            risk_tags=("mcp_execution",),
            max_result_size_chars=120_000,
            deferred_loading=True,
        ),
        _descriptor(
            "op.mcp_structured_data",
            "mcp",
            "Structured data MCP",
            "Run a bounded structured-data MCP capability.",
            aliases=("mcp_structured_data",),
            risk_tags=("mcp_execution",),
            max_result_size_chars=120_000,
            deferred_loading=True,
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
