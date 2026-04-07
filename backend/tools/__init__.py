from __future__ import annotations

from pathlib import Path

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


def get_all_tools(base_dir: Path) -> list[BaseTool]:
    return [
        GetGoldPriceTool(root_dir=base_dir),
        GetWeatherTool(),
        WebSearchTool(root_dir=base_dir),
        TerminalTool(root_dir=base_dir),
        PythonReplTool(root_dir=base_dir),
        FetchURLTool(),
        ReadFileTool(root_dir=base_dir),
        PdfAnalysisTool(root_dir=base_dir),
        StructuredDataAnalysisTool(root_dir=base_dir),
        SearchKnowledgeBaseTool(root_dir=base_dir),
        AnalyzeMultimodalFileTool(root_dir=base_dir),
        IndexMultimodalFileTool(root_dir=base_dir),
    ]
