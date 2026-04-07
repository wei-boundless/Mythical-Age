from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ToolDefinition:
    name: str
    module: str
    capability_tags: list[str] = field(default_factory=list)
    supported_modalities: list[str] = field(default_factory=list)
    safe_for_auto_route: bool = True
    search_terms: list[str] = field(default_factory=list)
    typical_queries: list[str] = field(default_factory=list)


TOOL_RECORDS: list[ToolDefinition] = [
    ToolDefinition(
        name="get_weather",
        module="tools.get_weather_tool",
        capability_tags=["weather", "forecast", "realtime"],
        supported_modalities=["realtime"],
        search_terms=["天气", "气温", "温度", "预报", "weather", "forecast"],
        typical_queries=["北京今天天气怎么样", "上海明天气温多少"],
    ),
    ToolDefinition(
        name="get_gold_price",
        module="tools.get_gold_price_tool",
        capability_tags=["finance", "gold", "realtime", "price"],
        supported_modalities=["realtime"],
        search_terms=["黄金", "金价", "gold", "xau", "spot gold"],
        typical_queries=["查询黄金价格", "XAU USD price today"],
    ),
    ToolDefinition(
        name="web_search",
        module="tools.web_search_tool",
        capability_tags=["search", "news", "finance", "official-docs"],
        supported_modalities=["web", "realtime"],
        search_terms=["联网", "搜索", "最新", "新闻", "官网", "web search"],
        typical_queries=["联网查 OpenAI API 最新更新"],
    ),
    ToolDefinition(
        name="structured_data_analysis",
        module="tools.structured_data_analysis_tool",
        capability_tags=["analytics", "table", "top-n", "group-by", "schema", "dataset"],
        supported_modalities=["table", "spreadsheet", "csv", "json"],
        search_terms=["表格", "excel", "csv", "库存", "缺货", "排名", "汇总", "schema"],
        typical_queries=["销售前五的有哪些", "从我的数据库中查询哪些商品库存不足"],
    ),
    ToolDefinition(
        name="pdf_analysis",
        module="tools.pdf_analysis_tool",
        capability_tags=["pdf", "browse", "deep-read", "page-read", "document"],
        supported_modalities=["pdf", "document"],
        search_terms=["白皮书", "报告", "pdf", "第几页", "page read"],
        typical_queries=["白皮书第五页讲得什么", "详细解读这份 PDF"],
    ),
    ToolDefinition(
        name="search_knowledge",
        module="tools.search_knowledge_tool",
        capability_tags=["rag", "retrieval", "local-knowledge", "faq"],
        supported_modalities=["text", "document", "knowledge"],
        search_terms=["知识库", "本地资料", "查资料", "faq", "为什么找不到订单", "knowledge"],
        typical_queries=["从本地知识库里查一下三一重工前三大股东", "为什么我在我的帐户中找不到我的订单"],
    ),
    ToolDefinition(
        name="analyze_multimodal_file",
        module="tools.analyze_multimodal_file_tool",
        capability_tags=["multimodal", "inspection", "preview"],
        supported_modalities=["pdf", "table", "image", "document"],
        safe_for_auto_route=False,
        search_terms=["分析文件", "预览文件", "多模态预览"],
        typical_queries=["帮我看看这个文件内容", "先分析这个 PDF"],
    ),
    ToolDefinition(
        name="index_multimodal_file",
        module="tools.index_multimodal_file_tool",
        capability_tags=["indexing", "multimodal", "ingest"],
        supported_modalities=["pdf", "table", "image", "document"],
        safe_for_auto_route=False,
        search_terms=["入库", "索引", "ingest", "index"],
        typical_queries=["把这个文件入库", "重建这个文件的索引"],
    ),
    ToolDefinition(
        name="read_file",
        module="tools.read_file_tool",
        capability_tags=["file", "read", "local"],
        supported_modalities=["text", "code", "document"],
        safe_for_auto_route=False,
        search_terms=["读取文件", "read file"],
    ),
    ToolDefinition(
        name="fetch_url",
        module="tools.fetch_url_tool",
        capability_tags=["web", "fetch", "verification"],
        supported_modalities=["web"],
        safe_for_auto_route=False,
        search_terms=["抓取网页", "fetch url"],
    ),
    ToolDefinition(
        name="terminal",
        module="tools.terminal_tool",
        capability_tags=["shell", "terminal", "command"],
        supported_modalities=["system"],
        safe_for_auto_route=False,
        search_terms=["终端", "命令行", "shell"],
    ),
    ToolDefinition(
        name="python_repl",
        module="tools.python_repl_tool",
        capability_tags=["python", "repl", "scripting"],
        supported_modalities=["system"],
        safe_for_auto_route=False,
        search_terms=["python", "脚本", "repl"],
    ),
]


class ToolRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.registry_path = base_dir / "TOOLS_REGISTRY.json"
        self._tools: list[ToolDefinition] = []
        self.reload()

    def reload(self) -> None:
        if not self.registry_path.exists():
            self._tools = []
            return
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            self._tools = []
            return
        tools: list[ToolDefinition] = []
        for item in payload.get("tools", []):
            if not isinstance(item, dict):
                continue
            tools.append(
                ToolDefinition(
                    name=str(item.get("name", "")).strip(),
                    module=str(item.get("module", "")).strip(),
                    capability_tags=[str(v) for v in item.get("capability_tags", []) if str(v).strip()],
                    supported_modalities=[str(v) for v in item.get("supported_modalities", []) if str(v).strip()],
                    safe_for_auto_route=bool(item.get("safe_for_auto_route", True)),
                    search_terms=[str(v) for v in item.get("search_terms", []) if str(v).strip()],
                    typical_queries=[str(v) for v in item.get("typical_queries", []) if str(v).strip()],
                )
            )
        self._tools = tools

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    def get_by_name(self, name: str | None) -> ToolDefinition | None:
        if not name:
            return None
        target = name.strip().lower()
        for tool in self._tools:
            if tool.name.lower() == target:
                return tool
        return None

    def filter_names(self, names: list[str] | None, *, safe_only: bool = False) -> list[ToolDefinition]:
        if not names:
            return []
        allowed = {name.strip().lower() for name in names if name.strip()}
        results: list[ToolDefinition] = []
        for tool in self._tools:
            if tool.name.lower() not in allowed:
                continue
            if safe_only and not tool.safe_for_auto_route:
                continue
            results.append(tool)
        return results

    def select_best(
        self,
        message: str,
        *,
        candidate_names: list[str] | None = None,
        modality: str | None = None,
        route: str | None = None,
        safe_only: bool = True,
    ) -> ToolDefinition | None:
        candidates = self.filter_names(candidate_names, safe_only=safe_only) if candidate_names else [
            tool for tool in self._tools if (tool.safe_for_auto_route or not safe_only)
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        normalized = (message or "").strip().lower()
        best_tool: ToolDefinition | None = None
        best_score = float("-inf")

        for tool in candidates:
            score = 0.0
            if modality and modality in tool.supported_modalities:
                score += 4.0
            if route == "tool" and tool.safe_for_auto_route:
                score += 1.0
            for query in tool.typical_queries:
                if query and query.lower() in normalized:
                    score += 5.0
            for term in tool.search_terms:
                if term and term.lower() in normalized:
                    score += 3.0
            for tag in tool.capability_tags:
                if tag and tag.lower() in normalized:
                    score += 2.0
            if score > best_score:
                best_score = score
                best_tool = tool

        if best_score <= 0:
            return None
        return best_tool


def build_tool_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "tool_count": len(TOOL_RECORDS),
        "tools": [asdict(record) for record in TOOL_RECORDS],
    }


def refresh_tool_registry(base_dir: Path) -> Path:
    registry_path = base_dir / "TOOLS_REGISTRY.json"
    registry_path.write_text(
        json.dumps(build_tool_registry(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry_path
