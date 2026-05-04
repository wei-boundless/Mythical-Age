from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Type

import pandas as pd
from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.units.mcp.local.structured_data import (
    StructuredDataArtifactBuilder,
    StructuredDataCatalog,
    StructuredDataEngine,
    StructuredDataPlanner,
)


class StructuredDataAnalysisInput(BaseModel):
    query: str = Field(..., description="用户关于 Excel/CSV/JSON 结构化数据的分析问题")
    path: str = Field(
        default="",
        description="可选的相对路径，如 knowledge/E-commerce Data/employees.xlsx；不填时会自动推断数据文件",
    )
    analysis_type: str = Field(
        default="auto",
        description=(
            "分析类型：auto/schema_preview/row_count/"
            "inventory_shortage/inventory_summary/extreme_record/grouped_summary/top_n"
        ),
    )
    sheet_name: str = Field(default="", description="Excel 的可选 sheet 名称")
    limit: int = Field(default=10, ge=1, le=50, description="结果展示条数上限")
    semantic_hints: dict[str, Any] = Field(
        default_factory=dict,
        description="来自 task understanding 的结构化语义提示",
    )


class StructuredDataAnalysisTool(BaseTool):
    name: str = "structured_data_analysis"
    description: str = (
        "Analyze local Excel/CSV/JSON structured data. Use for schema preview, row counts, "
        "filtered table analysis, grouped summaries, rankings, top-N queries, and domain-agnostic structured analytics."
    )
    args_schema: Type[BaseModel] = StructuredDataAnalysisInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()
    _planner: StructuredDataPlanner = PrivateAttr()
    _engine: StructuredDataEngine = PrivateAttr()
    _artifact_builder: StructuredDataArtifactBuilder = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()
        self._planner = StructuredDataPlanner()
        self._engine = StructuredDataEngine()
        self._artifact_builder = StructuredDataArtifactBuilder(root_dir=self._root_dir)

    def _resolve_explicit_path(self, path: str) -> Path:
        normalized = str(path or "").strip()
        if not normalized:
            raise ValueError("missing_explicit_dataset_path")
        candidates = StructuredDataCatalog.list_dataset_paths(self._root_dir)
        matched = StructuredDataCatalog._match_filename(self._root_dir, candidates, normalized)
        if matched is not None:
            return matched
        resolved = StructuredDataCatalog.resolve_dataset_path(self._root_dir, normalized, normalized)
        if not resolved.exists():
            raise ValueError("file_does_not_exist")
        if resolved.is_dir():
            raise ValueError("path_is_directory")
        return resolved

    def _load_dataframe(self, file_path: Path, sheet_name: str = "") -> pd.DataFrame:
        suffix = file_path.suffix.lower()
        if suffix == ".xlsx":
            return pd.read_excel(file_path, sheet_name=sheet_name or 0)
        if suffix == ".csv":
            return pd.read_csv(file_path)
        if suffix == ".json":
            try:
                return pd.read_json(file_path)
            except ValueError:
                return pd.read_json(file_path, lines=True)
        raise ValueError("目前仅支持 xlsx/csv/json 结构化分析。")

    def _run(
        self,
        query: str,
        path: str = "",
        analysis_type: str = "auto",
        sheet_name: str = "",
        limit: int = 10,
        semantic_hints: dict[str, Any] | None = None,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._resolve_explicit_path(path)
        except ValueError as exc:
            code = str(exc)
            if code == "missing_explicit_dataset_path":
                try:
                    file_path = StructuredDataCatalog.resolve_dataset_path(self._root_dir, "", query)
                    path = StructuredDataCatalog.relative_path(self._root_dir, file_path)
                except Exception:
                    return "结构化分析失败：必须显式提供数据文件 path。"
            if code == "file_does_not_exist":
                return "结构化分析失败：文件不存在。"
            if code == "path_is_directory":
                return "结构化分析失败：给定路径是目录。"
            if code not in {"missing_explicit_dataset_path", "file_does_not_exist", "path_is_directory"}:
                return f"结构化分析失败：{exc}"

        try:
            df = self._load_dataframe(file_path, sheet_name=sheet_name)
        except Exception as exc:
            return f"结构化分析失败：无法读取文件。{exc}"

        df = self._planner.normalize_columns(df)
        rel_path = str(file_path.relative_to(self._root_dir)).replace("\\", "/")
        self._artifact_builder.save_profile(rel_path, df)
        plan = self._planner.build_plan(
            query=query,
            df=df,
            dataset_rel_path=rel_path,
            requested_analysis_type=analysis_type,
            sheet_name=sheet_name,
            limit=limit,
            semantic_hints=semantic_hints or {},
        )
        return self._engine.execute(plan=plan, df=df, file_path=file_path)

    async def _arun(
        self,
        query: str,
        path: str = "",
        analysis_type: str = "auto",
        sheet_name: str = "",
        limit: int = 10,
        semantic_hints: dict[str, Any] | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._run,
            query,
            path,
            analysis_type,
            sheet_name,
            limit,
            semantic_hints,
            None,
        )
