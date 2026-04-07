from __future__ import annotations

from pathlib import Path

import pandas as pd

from structured_data.catalog import StructuredDataCatalog
from structured_data.executor import QueryExecutionResult, StructuredQueryExecutor
from structured_data.models import StructuredDataPlan


class StructuredDataEngine:
    def __init__(self, catalog: type[StructuredDataCatalog] = StructuredDataCatalog) -> None:
        self.catalog = catalog
        self.query_executor = StructuredQueryExecutor()

    def execute(self, plan: StructuredDataPlan, df: pd.DataFrame, file_path: Path) -> str:
        if plan.analysis_type == "schema_preview":
            return self._schema_preview(df, file_path)
        if plan.analysis_type == "row_count":
            return self._row_count(df, file_path)
        if plan.analysis_type == "inventory_shortage":
            return self._inventory_shortage(df, file_path, plan.limit)
        if plan.analysis_type == "inventory_summary":
            return self._inventory_summary(df, file_path)
        if plan.analysis_type == "extreme_record":
            return self._extreme_record(df, file_path, plan)
        if plan.analysis_type == "grouped_summary":
            return self._grouped_summary(df, file_path, plan)
        if plan.analysis_type == "top_n":
            return self._top_n(df, file_path, plan)
        return (
            f"数据源：{file_path.name}\n"
            f"分析类型：{plan.analysis_type}\n"
            f"查询模式：{plan.query_mode}\n"
            f"总行数：{len(df)}\n"
            f"列名：{list(df.columns)}"
        )

    def _apply_filters(self, df: pd.DataFrame, filters: list[str]) -> pd.DataFrame:
        filtered = df.copy()
        for rule in filters:
            if "=" in rule:
                column, value = rule.split("=", 1)
                if column in filtered.columns:
                    filtered = filtered[filtered[column].astype(str) == value]
            elif "~" in rule:
                column, value = rule.split("~", 1)
                if column in filtered.columns:
                    filtered = filtered[filtered[column].astype(str).str.contains(value, case=False, na=False)]
        return filtered

    def _schema_preview(self, df: pd.DataFrame, file_path: Path) -> str:
        preview = df.head(10).fillna("").to_string(index=False)
        return (
            f"数据源：{file_path.name}\n"
            f"总行数：{len(df)}\n"
            f"列名：{list(df.columns)}\n\n"
            f"前 10 行预览：\n{preview}"
        )

    def _row_count(self, df: pd.DataFrame, file_path: Path) -> str:
        return (
            f"数据源：{file_path.name}\n"
            f"总行数：{len(df)}\n"
            f"列数：{len(df.columns)}\n"
            f"列名：{list(df.columns)}"
        )

    def _inventory_shortage(self, df: pd.DataFrame, file_path: Path, limit: int) -> str:
        required = {"sku", "product", "warehouse", "stock_on_hand", "reorder_level"}
        missing = sorted(required - set(df.columns))
        if missing:
            return (
                "库存缺货分析失败：缺少必要字段。\n"
                f"缺失字段：{missing}\n"
                f"当前列名：{list(df.columns)}"
            )

        normalized = df.copy()
        normalized["stock_on_hand"] = pd.to_numeric(normalized["stock_on_hand"], errors="coerce")
        normalized["reorder_level"] = pd.to_numeric(normalized["reorder_level"], errors="coerce")
        normalized = normalized.dropna(subset=["stock_on_hand", "reorder_level"])
        normalized["shortage_qty"] = normalized["reorder_level"] - normalized["stock_on_hand"]
        shortage = normalized[normalized["stock_on_hand"] < normalized["reorder_level"]].copy()
        shortage = shortage.sort_values("shortage_qty", ascending=False)
        tight = normalized[
            (normalized["stock_on_hand"] >= normalized["reorder_level"])
            & (normalized["stock_on_hand"] <= normalized["reorder_level"] * 1.2)
        ].copy()

        lines = [
            f"数据源：{file_path.name}",
            f"总商品数：{len(normalized)}",
            f"缺货商品数：{len(shortage)}",
            f"库存紧张商品数：{len(tight)}",
        ]
        if shortage.empty:
            lines.append("\n当前没有缺货商品。")
            return "\n".join(lines)

        display = shortage.head(limit)[["sku", "product", "warehouse", "stock_on_hand", "reorder_level", "shortage_qty"]]
        display = display.rename(
            columns={
                "sku": "SKU",
                "product": "商品名称",
                "warehouse": "仓库",
                "stock_on_hand": "当前库存",
                "reorder_level": "安全库存",
                "shortage_qty": "缺口",
            }
        )
        lines.append(f"\n缺货商品（前 {limit} 项）：")
        lines.append(display.to_string(index=False))
        if "category" in shortage.columns:
            lines.append("\n缺货类别分布：")
            lines.append(shortage.groupby("category").size().sort_values(ascending=False).to_string())
        lines.append("\n缺货仓库分布：")
        lines.append(shortage.groupby("warehouse").size().sort_values(ascending=False).to_string())
        return "\n".join(lines)

    def _inventory_summary(self, df: pd.DataFrame, file_path: Path) -> str:
        required = {"stock_on_hand", "reorder_level"}
        if not required.issubset(set(df.columns)):
            return self._schema_preview(df, file_path)

        normalized = df.copy()
        normalized["stock_on_hand"] = pd.to_numeric(normalized["stock_on_hand"], errors="coerce")
        normalized["reorder_level"] = pd.to_numeric(normalized["reorder_level"], errors="coerce")
        normalized = normalized.dropna(subset=["stock_on_hand", "reorder_level"])
        shortage_count = int((normalized["stock_on_hand"] < normalized["reorder_level"]).sum())
        tight_count = int(
            (
                (normalized["stock_on_hand"] >= normalized["reorder_level"])
                & (normalized["stock_on_hand"] <= normalized["reorder_level"] * 1.2)
            ).sum()
        )
        return (
            f"数据源：{file_path.name}\n"
            f"总行数：{len(normalized)}\n"
            f"缺货商品数：{shortage_count}\n"
            f"库存紧张商品数：{tight_count}\n"
            f"列名：{list(normalized.columns)}"
        )

    def _detail_columns(self, df: pd.DataFrame, plan: StructuredDataPlan) -> list[str]:
        if plan.select_columns:
            return [column for column in plan.select_columns if column in df.columns]
        columns: list[str] = []
        for column in (
            "employee_id",
            "name",
            "department",
            "title",
            "city",
            "product",
            "category",
            "warehouse",
            "region",
            "sku",
            plan.metric,
        ):
            if column and column in df.columns and column not in columns:
                columns.append(column)
        return columns

    def _execute_query_plan(self, df: pd.DataFrame, plan: StructuredDataPlan) -> QueryExecutionResult | None:
        return self.query_executor.execute(plan, df)

    def _render_grouped_frame(self, frame: pd.DataFrame, plan: StructuredDataPlan) -> pd.DataFrame:
        display = frame.copy()
        rename_map: dict[str, str] = {}
        for column in display.columns:
            if column == "__metric__":
                if plan.metric and plan.agg != "count":
                    rename_map[column] = self.catalog.display_label(plan.metric)
                else:
                    rename_map[column] = "数量"
            else:
                rename_map[column] = self.catalog.display_label(column)
        return display.rename(columns=rename_map)

    def _empty_grouped_result_message(self, file_path: Path, plan: StructuredDataPlan) -> str | None:
        query_plan = plan.query_plan
        if query_plan is None:
            return None
        if (
            query_plan.metric == "shortage_qty"
            and query_plan.metric_condition_operator == "="
            and query_plan.metric_condition_value == 0.0
        ):
            group_label = self.catalog.display_label(plan.group_by or "分组")
            return (
                f"数据源：{file_path.name}\n"
                f"筛选条件：{'；'.join(plan.filters) if plan.filters else '无'}\n"
                f"查询模式：分组聚合排名\n"
                f"排名维度：{group_label}\n"
                f"排序依据：总和（缺口）\n\n"
                f"当前没有完全不缺货的{group_label}。"
            )
        return None

    def _extreme_record(self, df: pd.DataFrame, file_path: Path, plan: StructuredDataPlan) -> str:
        if not plan.metric:
            return "极值分析失败：未识别出可比较的数值字段。"

        query_result = self._execute_query_plan(df, plan)
        if query_result is not None and not query_result.dataframe.empty:
            working = query_result.dataframe
        else:
            filtered = self._apply_filters(df, plan.filters)
            if filtered.empty:
                return "极值分析失败：根据问题筛选后没有匹配记录。"
            working = filtered.copy()
            working[plan.metric] = pd.to_numeric(working[plan.metric], errors="coerce")
            working = working.dropna(subset=[plan.metric])
            if working.empty:
                return f"极值分析失败：字段 {plan.metric} 没有可比较的数值。"
            working = working.sort_values(plan.metric, ascending=(plan.sort_direction == "asc")).head(1)

        best_row = working.iloc[0]
        entity_value = str(best_row.get(plan.entity_column, "")) if plan.entity_column else ""
        metric_label = self.catalog.display_label(plan.metric)
        filter_text = "；".join(plan.filters) if plan.filters else "无"
        direction_text = "最高" if plan.sort_direction == "desc" else "最低"
        conclusion = f"{direction_text}{metric_label}对应的是：{entity_value}。" if entity_value else f"{direction_text}记录已找到。"
        details = "\n".join(
            f"- {self.catalog.display_label(column)}: {best_row[column]}"
            for column in self._detail_columns(working, plan)
        )
        return (
            f"数据源：{file_path.name}\n"
            f"筛选条件：{filter_text}\n"
            f"查询模式：单条记录排序\n"
            f"比较字段：{metric_label}\n"
            f"结论：{conclusion}\n"
            f"{metric_label}：{best_row[plan.metric]}\n\n"
            f"详细信息：\n{details}"
        )

    def _grouped_summary(self, df: pd.DataFrame, file_path: Path, plan: StructuredDataPlan) -> str:
        if not plan.group_by:
            return "分组汇总失败：未识别出分组字段。"

        query_result = self._execute_query_plan(df, plan)
        if query_result is not None:
            result_frame = query_result.dataframe
            if result_frame.empty:
                return "分组汇总失败：没有得到有效结果。"
            sorted_result = self._render_grouped_frame(result_frame, plan)
        else:
            filtered = self._apply_filters(df, plan.filters)
            if filtered.empty:
                return "分组汇总失败：根据问题筛选后没有匹配记录。"
            result = self._aggregate(filtered, plan)
            if result is None or result.empty:
                return "分组汇总失败：没有得到有效结果。"
            sorted_result = result.sort_values(ascending=(plan.sort_direction == "asc")).head(plan.limit)
        agg_label = {"sum": "总和", "mean": "平均值", "max": "最大值", "min": "最小值", "count": "数量"}[plan.agg]
        filter_text = "；".join(plan.filters) if plan.filters else "无"
        metric_text = f"（{self.catalog.display_label(plan.metric)}）" if plan.metric and plan.agg != "count" else ""
        return (
            f"数据源：{file_path.name}\n"
            f"筛选条件：{filter_text}\n"
            f"查询模式：分组聚合\n"
            f"分组字段：{self.catalog.display_label(plan.group_by)}\n"
            f"汇总方式：{agg_label}{metric_text}\n\n"
            f"结果（前 {plan.limit} 项）：\n{sorted_result.to_string()}"
        )

    def _top_n(self, df: pd.DataFrame, file_path: Path, plan: StructuredDataPlan) -> str:
        if plan.is_grouped:
            query_result = self._execute_query_plan(df, plan)
            if query_result is not None:
                if query_result.dataframe.empty:
                    empty_message = self._empty_grouped_result_message(file_path, plan)
                    if empty_message is not None:
                        return empty_message
                    return "Top N 分析失败：没有得到有效聚合结果。"
                ranking = self._render_grouped_frame(query_result.dataframe, plan)
            else:
                filtered = self._apply_filters(df, plan.filters)
                if filtered.empty:
                    return "Top N 分析失败：根据问题筛选后没有匹配记录。"
                result = self._aggregate(filtered, plan)
                if result is None or result.empty:
                    return "Top N 分析失败：没有得到有效聚合结果。"
                ranking = result.sort_values(ascending=(plan.sort_direction == "asc")).head(plan.limit)
            metric_label = self.catalog.display_label(plan.metric) if plan.metric else "数量"
            agg_label = {"sum": "总和", "mean": "平均值", "max": "最大值", "min": "最小值", "count": "数量"}[plan.agg]
            return (
                f"数据源：{file_path.name}\n"
                f"筛选条件：{'；'.join(plan.filters) if plan.filters else '无'}\n"
                f"查询模式：分组聚合排名\n"
                f"排名维度：{self.catalog.display_label(plan.group_by or '')}\n"
                f"排序依据：{agg_label}"
                + (f"（{metric_label}）" if plan.metric and plan.agg != "count" else "")
                + f"\n\n前 {plan.limit} 项：\n{ranking.to_string()}"
            )

        if not plan.order_by:
            return "Top N 分析失败：未识别出排序字段。"
        query_result = self._execute_query_plan(df, plan)
        if query_result is not None:
            ranking = query_result.dataframe
            if ranking.empty:
                return f"Top N 分析失败：字段 {plan.order_by} 没有可比较的数值。"
        else:
            filtered = self._apply_filters(df, plan.filters)
            if filtered.empty:
                return "Top N 分析失败：根据问题筛选后没有匹配记录。"
            working = filtered.copy()
            working[plan.order_by] = pd.to_numeric(working[plan.order_by], errors="coerce")
            working = working.dropna(subset=[plan.order_by])
            if working.empty:
                return f"Top N 分析失败：字段 {plan.order_by} 没有可比较的数值。"
            ranking = working.sort_values(plan.order_by, ascending=(plan.sort_direction == "asc")).head(plan.limit)
        detail_columns = self._detail_columns(ranking, plan)
        display = ranking[detail_columns].rename(
            columns={column: self.catalog.display_label(column) for column in detail_columns}
        )
        return (
            f"数据源：{file_path.name}\n"
            f"筛选条件：{'；'.join(plan.filters) if plan.filters else '无'}\n"
            f"查询模式：记录排序\n"
            f"排序字段：{self.catalog.display_label(plan.order_by)}\n\n"
            f"前 {plan.limit} 条记录：\n{display.to_string(index=False)}"
        )

    def _aggregate(self, df: pd.DataFrame, plan: StructuredDataPlan) -> pd.Series | None:
        if not plan.group_by:
            return None
        if plan.agg == "count":
            return df.groupby(plan.group_by).size()
        if not plan.metric:
            return None

        working = df.copy()
        if plan.metric == "shortage_qty":
            required = {"stock_on_hand", "reorder_level"}
            if not required.issubset(set(working.columns)):
                return None
            working["stock_on_hand"] = pd.to_numeric(working["stock_on_hand"], errors="coerce")
            working["reorder_level"] = pd.to_numeric(working["reorder_level"], errors="coerce")
            working = working.dropna(subset=["stock_on_hand", "reorder_level"])
            if working.empty:
                return None
            working["shortage_qty"] = (working["reorder_level"] - working["stock_on_hand"]).clip(lower=0)
            working = working[working["shortage_qty"] > 0]
            if working.empty:
                return None
        else:
            working[plan.metric] = pd.to_numeric(working[plan.metric], errors="coerce")
            working = working.dropna(subset=[plan.metric])
        if working.empty:
            return None
        grouped = working.groupby(plan.group_by)[plan.metric]
        if plan.agg == "sum":
            return grouped.sum()
        if plan.agg == "mean":
            return grouped.mean()
        if plan.agg == "max":
            return grouped.max()
        if plan.agg == "min":
            return grouped.min()
        return None
