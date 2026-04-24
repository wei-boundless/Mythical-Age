from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import BaseTool

from tools.contracts import (
    ToolExecutionContract,
    ToolOutputContract,
    ToolProjectionContract,
    ToolResolutionContract,
)
from tools.analyze_multimodal_file_tool import AnalyzeMultimodalFileTool
from tools.fetch_url_tool import FetchURLTool
from tools.get_gold_price_tool import GetGoldPriceTool
from tools.get_weather_tool import GetWeatherTool
from tools.index_multimodal_file_tool import IndexMultimodalFileTool
from tools.pdf_analysis_tool import PdfAnalysisTool
from tools.python_repl_tool import PythonReplTool
from tools.read_file_tool import ReadFileTool
from tools.search_knowledge_tool import SearchKnowledgeBaseTool
from tools.structured_data_analysis_tool import StructuredDataAnalysisTool
from tools.terminal_tool import TerminalTool
from tools.web_search_tool import WebSearchTool


ToolFactory = Callable[[Path], BaseTool]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    module: str
    factory: ToolFactory
    contract: ToolExecutionContract = field(default_factory=ToolExecutionContract)
    resolution_contract: ToolResolutionContract = field(default_factory=ToolResolutionContract)
    output_contract: ToolOutputContract = field(default_factory=ToolOutputContract)
    projection_contract: ToolProjectionContract = field(default_factory=ToolProjectionContract)
    capability_tags: list[str] = field(default_factory=list)
    supported_modalities: list[str] = field(default_factory=list)
    safety_tags: list[str] = field(default_factory=list)
    route_hints: list[str] = field(default_factory=list)
    safe_for_auto_route: bool = True
    is_read_only: bool = True
    is_destructive: bool = False
    is_concurrency_safe: bool = False

    def build(self, base_dir: Path) -> BaseTool:
        return self.factory(base_dir)

    def to_registry_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("factory", None)
        return payload


def _tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="get_weather",
            module="tools.get_weather_tool",
            factory=lambda _base_dir: GetWeatherTool(),
            contract=ToolExecutionContract(
                required_inputs=["query", "location"],
                owner_scope="none",
                missing_binding_behavior="clarify",
                context_policy="inline",
                result_channel="canonical",
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=["weather", "forecast", "realtime"],
            supported_modalities=["realtime"],
            safety_tags=["read", "network"],
            route_hints=["tool", "realtime_lookup"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="get_gold_price",
            module="tools.get_gold_price_tool",
            factory=lambda base_dir: GetGoldPriceTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["query"],
                owner_scope="none",
                missing_binding_behavior="deny",
                context_policy="inline",
                result_channel="canonical",
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=["finance", "gold", "gold_price", "realtime", "price"],
            supported_modalities=["realtime"],
            safety_tags=["read", "network"],
            route_hints=["tool", "realtime_lookup"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="web_search",
            module="tools.web_search_tool",
            factory=lambda base_dir: WebSearchTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["query"],
                owner_scope="none",
                missing_binding_behavior="clarify",
                context_policy="inline",
                result_channel="canonical",
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=["search", "news", "finance", "official-docs"],
            supported_modalities=["web", "realtime"],
            safety_tags=["read", "network"],
            route_hints=["tool", "latest_information"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="structured_data_analysis",
            module="tools.structured_data_analysis_tool",
            factory=lambda base_dir: StructuredDataAnalysisTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["query"],
                required_bindings=["active_dataset"],
                owner_scope="active_binding_or_explicit_path",
                allow_catalog_default=False,
                allow_history_binding=True,
                missing_binding_behavior="clarify",
                context_policy="isolated",
                result_channel="canonical",
            ),
            resolution_contract=ToolResolutionContract(
                path_field="path",
                path_kind="dataset",
                binding_field="dataset_path",
            ),
            output_contract=ToolOutputContract(display_mode="canonical_structured"),
            projection_contract=ToolProjectionContract(memory_projection_policy="canonical_summary_only"),
            capability_tags=["analytics", "table", "top-n", "group-by", "schema", "dataset"],
            supported_modalities=["table", "spreadsheet", "csv", "json"],
            safety_tags=["read", "compute"],
            route_hints=["tool", "dataset_analysis"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="pdf_analysis",
            module="tools.pdf_analysis_tool",
            factory=lambda base_dir: PdfAnalysisTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["query"],
                required_bindings=["active_pdf"],
                owner_scope="active_binding_or_explicit_path",
                allow_catalog_default=False,
                allow_history_binding=True,
                missing_binding_behavior="clarify",
                context_policy="isolated",
                result_channel="canonical",
            ),
            resolution_contract=ToolResolutionContract(
                path_field="path",
                path_kind="pdf",
                allow_message_extraction=True,
            ),
            output_contract=ToolOutputContract(
                display_mode="finalize_then_display",
                finalization_policy="route_required",
                persistence_policy="persist_if_canonical",
            ),
            projection_contract=ToolProjectionContract(memory_projection_policy="persistable_pdf_only"),
            capability_tags=["document_analysis", "pdf", "document", "page", "section"],
            supported_modalities=["pdf", "document"],
            safety_tags=["read", "compute"],
            route_hints=["tool", "document_analysis"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="search_knowledge",
            module="tools.search_knowledge_tool",
            factory=lambda base_dir: SearchKnowledgeBaseTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["query"],
                owner_scope="none",
                missing_binding_behavior="fallback_to_rag",
                context_policy="inline",
                result_channel="canonical",
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=["rag", "retrieval", "local-knowledge", "faq"],
            supported_modalities=["text", "document", "knowledge"],
            safety_tags=["read", "retrieval"],
            route_hints=["rag", "knowledge_lookup"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="analyze_multimodal_file",
            module="tools.analyze_multimodal_file_tool",
            factory=lambda base_dir: AnalyzeMultimodalFileTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["path"],
                owner_scope="explicit_path",
                missing_binding_behavior="clarify",
                context_policy="isolated",
                result_channel="canonical",
            ),
            resolution_contract=ToolResolutionContract(
                path_field="path",
                path_kind="multimodal",
            ),
            output_contract=ToolOutputContract(display_mode="artifact_only"),
            capability_tags=["multimodal", "inspection", "preview"],
            supported_modalities=["pdf", "table", "image", "document"],
            safety_tags=["read", "compute"],
            route_hints=["tool", "file_preview"],
            safe_for_auto_route=False,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="index_multimodal_file",
            module="tools.index_multimodal_file_tool",
            factory=lambda base_dir: IndexMultimodalFileTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["path"],
                owner_scope="explicit_path",
                missing_binding_behavior="deny",
                context_policy="isolated",
                result_channel="artifact_only",
            ),
            resolution_contract=ToolResolutionContract(
                path_field="path",
                path_kind="multimodal",
            ),
            output_contract=ToolOutputContract(display_mode="artifact_only", persistence_policy="do_not_persist"),
            capability_tags=["indexing", "multimodal", "ingest"],
            supported_modalities=["pdf", "table", "image", "document"],
            safety_tags=["write", "compute"],
            route_hints=["tool", "indexing"],
            safe_for_auto_route=False,
            is_read_only=False,
            is_destructive=False,
            is_concurrency_safe=False,
        ),
        ToolDefinition(
            name="read_file",
            module="tools.read_file_tool",
            factory=lambda base_dir: ReadFileTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["path"],
                owner_scope="explicit_path",
                missing_binding_behavior="clarify",
                context_policy="inline",
                result_channel="canonical",
            ),
            resolution_contract=ToolResolutionContract(
                path_field="path",
                path_kind="workspace",
            ),
            output_contract=ToolOutputContract(display_mode="verbatim_text"),
            capability_tags=["file", "read", "local"],
            supported_modalities=["text", "code", "document"],
            safety_tags=["read"],
            route_hints=["tool", "workspace_read"],
            safe_for_auto_route=False,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="fetch_url",
            module="tools.fetch_url_tool",
            factory=lambda _base_dir: FetchURLTool(),
            contract=ToolExecutionContract(
                required_inputs=["url"],
                owner_scope="none",
                missing_binding_behavior="clarify",
                context_policy="inline",
                result_channel="canonical",
            ),
            output_contract=ToolOutputContract(display_mode="summary_text"),
            capability_tags=["web", "fetch", "verification"],
            supported_modalities=["web"],
            safety_tags=["read", "network"],
            route_hints=["tool", "verification"],
            safe_for_auto_route=False,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="terminal",
            module="tools.terminal_tool",
            factory=lambda base_dir: TerminalTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["command"],
                owner_scope="none",
                missing_binding_behavior="deny",
                context_policy="isolated",
                result_channel="tool_raw",
            ),
            output_contract=ToolOutputContract(display_mode="raw_debug_only", persistence_policy="do_not_persist"),
            capability_tags=["shell", "terminal", "command"],
            supported_modalities=["system"],
            safety_tags=["write", "shell", "destructive"],
            route_hints=["tool", "local_command"],
            safe_for_auto_route=False,
            is_read_only=False,
            is_destructive=True,
            is_concurrency_safe=False,
        ),
        ToolDefinition(
            name="python_repl",
            module="tools.python_repl_tool",
            factory=lambda base_dir: PythonReplTool(root_dir=base_dir),
            contract=ToolExecutionContract(
                required_inputs=["code"],
                owner_scope="none",
                missing_binding_behavior="deny",
                context_policy="isolated",
                result_channel="tool_raw",
            ),
            output_contract=ToolOutputContract(display_mode="raw_debug_only", persistence_policy="do_not_persist"),
            capability_tags=["python", "repl", "scripting"],
            supported_modalities=["system"],
            safety_tags=["write", "compute", "shell"],
            route_hints=["tool", "local_scripting"],
            safe_for_auto_route=False,
            is_read_only=False,
            is_destructive=False,
            is_concurrency_safe=False,
        ),
    ]


def get_tool_definitions() -> list[ToolDefinition]:
    return list(_tool_definitions())


def get_tool_definition_map() -> dict[str, ToolDefinition]:
    return {definition.name: definition for definition in get_tool_definitions()}


def build_tool_instances(base_dir: Path) -> list[BaseTool]:
    return [definition.build(base_dir) for definition in get_tool_definitions()]


def build_tool_registry_payload() -> dict[str, Any]:
    definitions = get_tool_definitions()
    return {
        "version": 2,
        "tool_count": len(definitions),
        "tools": [definition.to_registry_record() for definition in definitions],
    }
