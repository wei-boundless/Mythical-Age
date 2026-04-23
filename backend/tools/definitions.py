from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import BaseTool

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
    capability_tags: list[str] = field(default_factory=list)
    supported_modalities: list[str] = field(default_factory=list)
    safety_tags: list[str] = field(default_factory=list)
    route_hints: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    typical_queries: list[str] = field(default_factory=list)
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
            capability_tags=["weather", "forecast", "realtime"],
            supported_modalities=["realtime"],
            safety_tags=["read", "network"],
            route_hints=["tool", "realtime_lookup"],
            search_terms=["天气", "气温", "温度", "预报", "weather", "forecast"],
            typical_queries=["北京今天天气怎么样", "上海明天气温多少"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="get_gold_price",
            module="tools.get_gold_price_tool",
            factory=lambda base_dir: GetGoldPriceTool(root_dir=base_dir),
            capability_tags=["finance", "gold", "realtime", "price"],
            supported_modalities=["realtime"],
            safety_tags=["read", "network"],
            route_hints=["tool", "realtime_lookup"],
            search_terms=["黄金", "金价", "gold", "xau", "spot gold"],
            typical_queries=["查询黄金价格", "XAU USD price today"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="web_search",
            module="tools.web_search_tool",
            factory=lambda base_dir: WebSearchTool(root_dir=base_dir),
            capability_tags=["search", "news", "finance", "official-docs"],
            supported_modalities=["web", "realtime"],
            safety_tags=["read", "network"],
            route_hints=["tool", "latest_information"],
            search_terms=["联网", "搜索", "最新", "新闻", "官网", "web search"],
            typical_queries=["联网查 OpenAI API 最新更新"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="structured_data_analysis",
            module="tools.structured_data_analysis_tool",
            factory=lambda base_dir: StructuredDataAnalysisTool(root_dir=base_dir),
            capability_tags=["analytics", "table", "top-n", "group-by", "schema", "dataset"],
            supported_modalities=["table", "spreadsheet", "csv", "json"],
            safety_tags=["read", "compute"],
            route_hints=["tool", "dataset_analysis"],
            search_terms=["表格", "excel", "csv", "库存", "缺货", "排名", "汇总", "schema"],
            typical_queries=["销售前五的有哪些", "从我的数据库中查询哪些商品库存不足"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="pdf_analysis",
            module="tools.pdf_analysis_tool",
            factory=lambda base_dir: PdfAnalysisTool(root_dir=base_dir),
            capability_tags=["pdf", "document", "page", "section"],
            supported_modalities=["pdf", "document"],
            safety_tags=["read", "compute"],
            route_hints=["tool", "document_analysis"],
            search_terms=["白皮书", "报告", "pdf", "第几页", "章节"],
            typical_queries=["白皮书第五页讲得什么", "这份 PDF 的结论是什么"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="search_knowledge",
            module="tools.search_knowledge_tool",
            factory=lambda base_dir: SearchKnowledgeBaseTool(root_dir=base_dir),
            capability_tags=["rag", "retrieval", "local-knowledge", "faq"],
            supported_modalities=["text", "document", "knowledge"],
            safety_tags=["read", "retrieval"],
            route_hints=["rag", "knowledge_lookup"],
            search_terms=["知识库", "本地资料", "查资料", "faq", "为什么找不到订单", "knowledge"],
            typical_queries=["从本地知识库里查一下三一重工前三大股东", "为什么我在我的帐户中找不到我的订单"],
            safe_for_auto_route=True,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="analyze_multimodal_file",
            module="tools.analyze_multimodal_file_tool",
            factory=lambda base_dir: AnalyzeMultimodalFileTool(root_dir=base_dir),
            capability_tags=["multimodal", "inspection", "preview"],
            supported_modalities=["pdf", "table", "image", "document"],
            safety_tags=["read", "compute"],
            route_hints=["tool", "file_preview"],
            search_terms=["分析文件", "预览文件", "多模态预览"],
            typical_queries=["帮我看看这个文件内容", "先分析这个 PDF"],
            safe_for_auto_route=False,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="index_multimodal_file",
            module="tools.index_multimodal_file_tool",
            factory=lambda base_dir: IndexMultimodalFileTool(root_dir=base_dir),
            capability_tags=["indexing", "multimodal", "ingest"],
            supported_modalities=["pdf", "table", "image", "document"],
            safety_tags=["write", "compute"],
            route_hints=["tool", "indexing"],
            search_terms=["入库", "索引", "ingest", "index"],
            typical_queries=["把这个文件入库", "重建这个文件的索引"],
            safe_for_auto_route=False,
            is_read_only=False,
            is_destructive=False,
            is_concurrency_safe=False,
        ),
        ToolDefinition(
            name="read_file",
            module="tools.read_file_tool",
            factory=lambda base_dir: ReadFileTool(root_dir=base_dir),
            capability_tags=["file", "read", "local"],
            supported_modalities=["text", "code", "document"],
            safety_tags=["read"],
            route_hints=["tool", "workspace_read"],
            search_terms=["读取文件", "read file"],
            safe_for_auto_route=False,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="fetch_url",
            module="tools.fetch_url_tool",
            factory=lambda _base_dir: FetchURLTool(),
            capability_tags=["web", "fetch", "verification"],
            supported_modalities=["web"],
            safety_tags=["read", "network"],
            route_hints=["tool", "verification"],
            search_terms=["抓取网页", "fetch url"],
            safe_for_auto_route=False,
            is_read_only=True,
            is_destructive=False,
            is_concurrency_safe=True,
        ),
        ToolDefinition(
            name="terminal",
            module="tools.terminal_tool",
            factory=lambda base_dir: TerminalTool(root_dir=base_dir),
            capability_tags=["shell", "terminal", "command"],
            supported_modalities=["system"],
            safety_tags=["write", "shell", "destructive"],
            route_hints=["tool", "local_command"],
            search_terms=["终端", "命令行", "shell"],
            safe_for_auto_route=False,
            is_read_only=False,
            is_destructive=True,
            is_concurrency_safe=False,
        ),
        ToolDefinition(
            name="python_repl",
            module="tools.python_repl_tool",
            factory=lambda base_dir: PythonReplTool(root_dir=base_dir),
            capability_tags=["python", "repl", "scripting"],
            supported_modalities=["system"],
            safety_tags=["write", "compute", "shell"],
            route_hints=["tool", "local_scripting"],
            search_terms=["python", "脚本", "repl"],
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
