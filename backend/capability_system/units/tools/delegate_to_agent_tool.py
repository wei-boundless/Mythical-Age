from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class DelegateToAgentInput(BaseModel):
    target_agent_id: str = Field(
        default="",
        description="目标子Agent正式ID：agent:knowledge_searcher、agent:codebase_searcher、agent:memory_searcher、agent:pdf_reader、agent:table_analyst、agent:web_researcher、agent:verifier。必须显式填写；运行时只做权限校验，不会根据 delegation_kind 替你选择目标。",
    )
    instruction: str = Field(..., description="委派任务说明；像给专业同事派活一样写清目标、对象、路径、页码、筛选口径和期望结果。")
    delegation_kind: str = Field(
        default="",
        description="委派类型：知识库/RAG 用 knowledge_search；本地代码库搜索用 codebase_search；正式记忆召回用 memory_search；PDF 文件阅读用 pdf_reading；Excel/CSV/表格分析用 table_analysis；公开网页检索与来源核验用 web_research。",
    )
    input_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="结构化输入载荷；PDF/表格任务放入 file_path 或 path，后续任务可放 active_pdf/active_dataset。",
    )


class DelegateToAgentTool(BaseTool):
    name: str = "delegate_to_agent"
    description: str = (
        "把一个边界清楚的专业任务交给内置子Agent，并拿回结构化摘要、证据引用和限制说明。"
        "你负责像调度者一样判断最合适的专家：知识库证据检索交给 knowledge_search，本地代码库搜索交给 codebase_search，正式记忆召回交给 memory_search，PDF 阅读交给 pdf_reading，表格/Excel/CSV 分析交给 table_analysis，公开网页检索、最新信息、官方来源核验交给 web_research。"
        "委派时请把专业同事完成任务所需的上下文一次打包清楚，例如文件路径、页码、数据集、筛选条件、统计口径、查询主题、时效要求、来源范围和期望输出。"
        "子Agent返回后，主Agent负责基于其结果和限制说明为用户收口。"
    )
    args_schema: type[BaseModel] = DelegateToAgentInput

    def _run(self, **_: Any) -> str:
        return "delegate_to_agent is handled by runtime loop dispatcher."
