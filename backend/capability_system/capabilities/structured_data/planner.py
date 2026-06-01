from __future__ import annotations

import pandas as pd

from .catalog import StructuredDataCatalog
from .models import StructuredDataPlan, StructuredFilter, StructuredQueryPlan


class StructuredDataPlanner:
    def __init__(self, catalog: type[StructuredDataCatalog] = StructuredDataCatalog) -> None:
        self.catalog = catalog

    def normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        rename_map: dict[str, str] = {}
        for column in df.columns:
            raw = str(column).strip()
            lowered = raw.lower()
            for canonical, aliases in self.catalog.COLUMN_ALIASES.items():
                lowered_aliases = {alias.lower() for alias in aliases}
                if raw in aliases or lowered in lowered_aliases:
                    rename_map[column] = canonical
                    break
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    def _resolve_state_kind(self, lowered: str, semantic_hints: dict[str, object]) -> str | None:
        state_kind_hint = semantic_hints.get("state_kind")
        if isinstance(state_kind_hint, str) and state_kind_hint:
            return state_kind_hint
        return self._inventory_state_kind(lowered)

    def build_plan(
        self,
        query: str,
        df: pd.DataFrame,
        dataset_rel_path: str,
        requested_analysis_type: str = "auto",
        sheet_name: str = "",
        limit: int = 10,
        semantic_hints: dict[str, object] | None = None,
    ) -> StructuredDataPlan:
        semantic_hints = semantic_hints or {}
        lowered = (query or "").lower()
        state_kind = self._resolve_state_kind(lowered, semantic_hints)
        analysis_type = self._infer_analysis_type(
            query,
            requested_analysis_type,
            df,
            state_kind=state_kind,
            semantic_hints=semantic_hints,
        )
        effective_limit = self._infer_limit(query, limit)
        diagnostic = self._is_diagnostic_query(lowered)
        filters = self._build_filters(query, df, diagnostic=diagnostic)
        structured_filters = self._build_structured_filters(filters)
        subset_filters = self._build_subset_filters_from_hints(df, semantic_hints)
        if subset_filters:
            structured_filters.extend(subset_filters)
            filters.extend(item.filter_expression for item in subset_filters)
        metric = self._detect_metric_column(
            query,
            df,
            dataset_rel_path,
            state_kind=state_kind,
            semantic_hints=semantic_hints,
        )
        group_by = self._detect_group_column(query, df, dataset_rel_path, analysis_type, semantic_hints=semantic_hints)
        agg = self._detect_agg(query, analysis_type)
        sort_direction = self._detect_sort_direction(query, state_kind=state_kind)
        query_mode = self._determine_query_mode(
            query,
            analysis_type,
            df,
            group_by,
            diagnostic,
            semantic_hints=semantic_hints,
        )
        entity_column = self._detect_entity_column(df)
        select_columns = self._default_select_columns(df, metric)

        if analysis_type == "top_n" and query_mode == "grouped" and group_by is None:
            default_group = self.catalog.DEFAULT_GROUP_BY.get(dataset_rel_path)
            if default_group in df.columns:
                group_by = default_group

        if query_mode != "grouped":
            group_by = None

        query_plan = self._build_query_plan(
            analysis_type=analysis_type,
            limit=effective_limit,
            metric=metric,
            group_by=group_by,
            agg=agg,
            sort_direction=sort_direction,
            query_mode=query_mode,
            structured_filters=structured_filters,
            select_columns=select_columns,
            state_kind=state_kind,
            semantic_hints=semantic_hints,
        )

        return StructuredDataPlan(
            path=dataset_rel_path,
            analysis_type=analysis_type,
            sheet_name=sheet_name,
            limit=effective_limit,
            metric=metric,
            group_by=group_by,
            agg=agg,
            sort_direction=sort_direction,
            filters=filters,
            structured_filters=structured_filters,
            query_mode=query_mode,
            order_by=metric,
            entity_column=entity_column,
            select_columns=select_columns,
            diagnostic=diagnostic,
            query_plan=query_plan,
        )

    def _infer_analysis_type(
        self,
        query: str,
        requested: str,
        df: pd.DataFrame,
        *,
        state_kind: str | None = None,
        semantic_hints: dict[str, object] | None = None,
    ) -> str:
        if requested and requested != "auto":
            return requested

        lowered = (query or "").lower()
        semantic_hints = semantic_hints or {}
        if semantic_hints.get("analysis_type_hint"):
            return str(semantic_hints["analysis_type_hint"])
        wants_location_breakdown = self._wants_location_breakdown(lowered, df)

        if state_kind == "non_shortage" and wants_location_breakdown and self._looks_like_complete_non_shortage_query(lowered):
            return "inventory_no_gap_groups"
        if state_kind == "non_shortage" and wants_location_breakdown:
            return "top_n"
        if state_kind == "abundance":
            return "top_n"
        if state_kind == "shortage" and wants_location_breakdown:
            return "top_n"
        if state_kind == "shortage":
            return "inventory_shortage"
        if any(token in lowered for token in ("列名", "字段", "结构", "schema", "columns", "表头")):
            return "schema_preview"
        if any(token in lowered for token in ("总数", "总行数", "多少行", "行数", "多少条", "几条", "多少人", "多少商品", "row count")):
            return "row_count"
        if any(token in lowered for token in ("前三", "前五", "前十", "top 3", "top3", "top 5", "top5", "top 10", "top10", "排名", "排行")):
            return "top_n"
        if any(token in lowered for token in ("最高", "最大", "最低", "最小", "谁", "哪个")):
            return "extreme_record"
        if any(token in lowered for token in ("汇总", "分布", "按", "每个", "group")):
            return "grouped_summary"
        if any(token in lowered for token in ("库存状态", "库存概况", "inventory summary")):
            return "inventory_summary"
        if {"stock_on_hand", "reorder_level"}.issubset(set(df.columns)):
            return "inventory_summary"
        return "schema_preview"

    def _detect_metric_column(
        self,
        query: str,
        df: pd.DataFrame,
        dataset_rel_path: str,
        *,
        state_kind: str | None = None,
        semantic_hints: dict[str, object] | None = None,
    ) -> str | None:
        lowered = (query or "").lower()
        semantic_hints = semantic_hints or {}
        metric_hint = semantic_hints.get("metric_hint")
        if isinstance(metric_hint, str):
            return metric_hint
        if {"stock_on_hand", "reorder_level"}.issubset(set(df.columns)):
            effective_state_kind = state_kind or self._inventory_state_kind(lowered)
            if effective_state_kind in {"shortage", "non_shortage"}:
                return "shortage_qty"
            if effective_state_kind == "abundance":
                return "stock_on_hand"

        for column, hints in self.catalog.METRIC_HINTS:
            if column not in df.columns:
                continue
            if any(hint.lower() in lowered for hint in hints):
                return column

        for column in self.catalog.DEFAULT_METRIC.get(dataset_rel_path, ()):
            if column in df.columns:
                return column

        preferred = ("base_salary", "total_amount", "quantity", "stock_on_hand", "unit_price", "unit_cost")
        for column in preferred:
            if column in df.columns:
                return column

        numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
        return numeric_columns[0] if numeric_columns else None

    def _detect_group_column(
        self,
        query: str,
        df: pd.DataFrame,
        dataset_rel_path: str,
        analysis_type: str,
        *,
        semantic_hints: dict[str, object] | None = None,
    ) -> str | None:
        lowered = (query or "").lower()
        semantic_hints = semantic_hints or {}
        group_hint = semantic_hints.get("group_hint")
        if isinstance(group_hint, str) and group_hint in df.columns:
            return group_hint
        if analysis_type == "top_n" and self._looks_like_record_top_n(lowered):
            return None
        for column, hints in self.catalog.GROUP_HINTS:
            if column not in df.columns:
                continue
            if any(hint.lower() in lowered for hint in hints):
                return column

        if self._wants_location_breakdown(lowered, df):
            for candidate in ("warehouse", "city", "region", "province"):
                if candidate in df.columns:
                    return candidate

        if analysis_type == "grouped_summary":
            default_group = self.catalog.DEFAULT_GROUP_BY.get(dataset_rel_path)
            if default_group in df.columns:
                return default_group
        return None

    def _detect_agg(self, query: str, analysis_type: str) -> str:
        lowered = (query or "").lower()
        if analysis_type == "top_n":
            return "sum"
        if any(token in lowered for token in ("平均", "均值", "avg", "mean")):
            return "mean"
        if any(token in lowered for token in ("最高", "最大", "max")):
            return "max"
        if any(token in lowered for token in ("最低", "最小", "min")):
            return "min"
        if any(token in lowered for token in ("数量", "多少", "count", "人数", "订单数")):
            return "count"
        return "sum"

    def _detect_sort_direction(self, query: str, *, state_kind: str | None = None) -> str:
        lowered = (query or "").lower()
        if state_kind == "non_shortage":
            return "asc"
        if any(token in lowered for token in ("最低", "最小", "bottom", "倒数")):
            return "asc"
        return "desc"

    def _build_filters(self, query: str, df: pd.DataFrame, *, diagnostic: bool) -> list[str]:
        lowered = (query or "").lower()
        if diagnostic:
            return []

        filtered: list[str] = []
        fallback_tokens = ("销售", "运营", "产品", "技术", "财务", "人力", "电子", "日用", "美妆", "图书", "食品")

        for column in df.columns:
            if pd.api.types.is_numeric_dtype(df[column]) or str(df[column].dtype).startswith("datetime"):
                continue
            series = df[column].dropna().astype(str).str.strip()
            unique_values = list(dict.fromkeys(series.tolist()))
            if len(unique_values) > 100:
                continue
            for value in unique_values:
                if len(value) < 2:
                    continue
                if value.lower() in lowered:
                    filtered.append(f"{column}={value}")
                    break

        if not filtered:
            for token in fallback_tokens:
                if token not in query:
                    continue
                for column in ("department", "title", "category", "product", "region", "warehouse", "city"):
                    if column not in df.columns:
                        continue
                    mask = df[column].astype(str).str.contains(token, case=False, na=False)
                    if mask.any():
                        filtered.append(f"{column}~{token}")
                        break
                if filtered:
                    break

        return filtered

    def _build_structured_filters(self, filters: list[str]) -> list[StructuredFilter]:
        parsed: list[StructuredFilter] = []
        for rule in filters:
            if "=" in rule:
                column, value = rule.split("=", 1)
                parsed.append(StructuredFilter(column=column, operator="=", value=value))
            elif "~" in rule:
                column, value = rule.split("~", 1)
                parsed.append(StructuredFilter(column=column, operator="~", value=value))
        return parsed

    def _build_subset_filters_from_hints(
        self,
        df: pd.DataFrame,
        semantic_hints: dict[str, object],
    ) -> list[StructuredFilter]:
        column = str(semantic_hints.get("subset_filter_column", "") or "").strip()
        if not column or column not in df.columns:
            return []
        values = [
            str(item or "").strip()
            for item in list(semantic_hints.get("subset_allowed_values", []) or [])
            if str(item or "").strip()
        ]
        if not values:
            return []
        unique_values: list[str] = []
        for value in values:
            if value not in unique_values:
                unique_values.append(value)
        return [StructuredFilter(column=column, operator="in", value=unique_values)]

    def _infer_limit(self, query: str, default_limit: int) -> int:
        lowered = (query or "").lower()
        explicit_markers = (
            ("前三", 3),
            ("top 3", 3),
            ("top3", 3),
            ("前五", 5),
            ("top 5", 5),
            ("top5", 5),
            ("前十", 10),
            ("top 10", 10),
            ("top10", 10),
        )
        for marker, value in explicit_markers:
            if marker in lowered:
                return value
        return default_limit

    def _determine_query_mode(
        self,
        query: str,
        analysis_type: str,
        df: pd.DataFrame,
        group_by: str | None,
        diagnostic: bool,
        *,
        semantic_hints: dict[str, object] | None = None,
    ) -> str:
        lowered = (query or "").lower()
        semantic_hints = semantic_hints or {}
        query_mode_hint = semantic_hints.get("query_mode_hint")
        if isinstance(query_mode_hint, str) and query_mode_hint in {"record", "grouped", "diagnostic"}:
            return query_mode_hint
        if diagnostic:
            return "diagnostic"
        if analysis_type in {"schema_preview", "row_count", "inventory_shortage", "inventory_summary", "inventory_no_gap_groups"}:
            return "record"
        if analysis_type == "grouped_summary":
            return "grouped"
        if analysis_type == "top_n":
            if group_by is not None:
                return "grouped"
            if self._should_group_top_n(lowered, df):
                return "grouped"
            return "record"
        return "record"

    def _build_query_plan(
        self,
        *,
        analysis_type: str,
        limit: int,
        metric: str | None,
        group_by: str | None,
        agg: str,
        sort_direction: str,
        query_mode: str,
        structured_filters: list[StructuredFilter],
        select_columns: list[str],
        state_kind: str | None,
        semantic_hints: dict[str, object] | None,
    ) -> StructuredQueryPlan | None:
        if analysis_type not in {"top_n", "grouped_summary", "extreme_record"}:
            return None

        if query_mode == "grouped":
            group_fields = [group_by] if group_by else []
            derived_metrics = ["shortage_qty"] if metric == "shortage_qty" else []
            return StructuredQueryPlan(
                query_kind="grouped",
                filters=list(structured_filters),
                group_by=group_fields,
                metric=metric,
                aggregate=agg,
                order_by="__metric__",
                order_direction=sort_direction,
                limit=limit,
                derived_metrics=derived_metrics,
                metric_condition_operator="=" if state_kind == "non_shortage" and metric == "shortage_qty" else None,
                metric_condition_value=0.0 if state_kind == "non_shortage" and metric == "shortage_qty" else None,
            )

        effective_limit = 1 if analysis_type == "extreme_record" else limit
        detail_columns = [column for column in select_columns if column]
        if metric and metric not in detail_columns:
            detail_columns.append(metric)
        derived_metrics = ["shortage_qty"] if metric == "shortage_qty" else []
        return StructuredQueryPlan(
            query_kind="record",
            select_columns=detail_columns,
            filters=list(structured_filters),
            metric=metric,
            order_by=metric,
            order_direction=sort_direction,
            limit=effective_limit,
            derived_metrics=derived_metrics,
        )

    def _should_group_top_n(self, lowered: str, df: pd.DataFrame) -> bool:
        if self._wants_location_breakdown(lowered, df):
            return True
        if self._looks_like_record_top_n(lowered):
            return False

        aggregation_markers = (
            "总和",
            "合计",
            "汇总",
            "平均",
            "sum",
            "avg",
            "mean",
            "group",
            "group by",
            "按部门",
            "按地区",
            "按区域",
            "按仓库",
            "按品类",
            "按姓名",
            "按产品",
            "每个",
            "各个",
            "分布",
        )
        if any(marker in lowered for marker in aggregation_markers):
            return True

        for column, hints in self.catalog.GROUP_HINTS:
            if column in {"name", "product"}:
                continue
            if column not in df.columns:
                continue
            if any(hint.lower() in lowered for hint in hints if len(hint) >= 2):
                return True
        return False

    def _looks_like_record_top_n(self, lowered: str) -> bool:
        record_entity_markers = (
            "员工",
            "人员",
            "人",
            "客户",
            "用户",
            "订单",
            "商品",
            "产品",
            "记录",
            "明细",
            "employee",
            "customer",
            "order",
            "record",
            "item",
        )
        return any(marker in lowered for marker in record_entity_markers)

    def _detect_entity_column(self, df: pd.DataFrame) -> str | None:
        for column in ("name", "product", "sku", "employee_id", "order_id", "customer_id"):
            if column in df.columns:
                return column
        return None

    def _default_select_columns(self, df: pd.DataFrame, metric: str | None) -> list[str]:
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
            metric,
        ):
            if column and column in df.columns and column not in columns:
                columns.append(column)
        return columns

    def _is_diagnostic_query(self, lowered: str) -> bool:
        markers = (
            "为什么",
            "原因",
            "分析原因",
            "不对",
            "不一致",
            "差异",
            "矛盾",
            "为啥",
            "why",
            "reason",
            "inconsistent",
            "mismatch",
        )
        return any(marker in lowered for marker in markers)

    def _inventory_state_kind(self, lowered: str) -> str | None:
        non_shortage_markers = (
            "不缺货",
            "不缺",
            "没有缺货",
            "无缺货",
            "没有缺口",
            "无缺口",
            "完全没有缺口",
            "完全无缺口",
            "不短缺",
            "不紧张",
        )
        shortage_markers = (
            "缺口",
            "最缺货",
            "缺货",
            "库存不足",
            "补货",
            "优先处理",
            "安全库存",
            "reorder",
            "不够",
            "不足",
            "缺少",
            "不太够",
            "紧张",
        )
        abundance_markers = (
            "充足",
            "最充足",
            "最足",
            "最丰富",
            "库存最高",
            "货物最充足",
            "most stock",
            "highest stock",
            "stockiest",
        )
        if any(marker in lowered for marker in non_shortage_markers):
            return "non_shortage"
        if any(marker in lowered for marker in abundance_markers):
            return "abundance"
        if any(marker in lowered for marker in shortage_markers):
            return "shortage"
        return None

    def _wants_location_breakdown(self, lowered: str, df: pd.DataFrame) -> bool:
        if not any(column in df.columns for column in ("warehouse", "city", "region", "province")):
            return False
        location_markers = (
            "仓库",
            "地区",
            "区域",
            "哪些地方",
            "哪个地方",
            "地方",
            "哪里",
            "地点",
        )
        return any(marker in lowered for marker in location_markers)

    def _looks_like_complete_non_shortage_query(self, lowered: str) -> bool:
        complete_markers = (
            "完全没有缺口",
            "完全无缺口",
            "没有任何缺口",
            "无任何缺口",
            "全部不缺",
            "都不缺",
        )
        existence_markers = (
            "是否存在",
            "有没有",
            "哪些",
            "哪个",
            "如果没有",
            "直接说没有",
        )
        return any(marker in lowered for marker in complete_markers) or (
            "没有缺口" in lowered and any(marker in lowered for marker in existence_markers)
        )


