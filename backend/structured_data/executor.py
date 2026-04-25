from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from structured_data.models import StructuredDataPlan, StructuredFilter, StructuredQueryPlan


@dataclass(slots=True)
class QueryExecutionResult:
    dataframe: pd.DataFrame
    sql: str


class StructuredQueryExecutor:
    def execute(self, plan: StructuredDataPlan, df: pd.DataFrame) -> QueryExecutionResult | None:
        if plan.query_plan is None:
            return None

        prepared = self._prepare_dataframe(df, plan.query_plan)
        sql, params = self._compile_sql(plan.query_plan)
        with sqlite3.connect(":memory:") as conn:
            prepared.to_sql(plan.query_plan.table_name, conn, index=False, if_exists="replace")
            result = pd.read_sql_query(sql, conn, params=params)
        return QueryExecutionResult(dataframe=result, sql=sql)

    def _prepare_dataframe(self, df: pd.DataFrame, query_plan: StructuredQueryPlan) -> pd.DataFrame:
        prepared = df.copy()
        if "shortage_qty" in query_plan.derived_metrics:
            required = {"stock_on_hand", "reorder_level"}
            if required.issubset(set(prepared.columns)):
                prepared["stock_on_hand"] = pd.to_numeric(prepared["stock_on_hand"], errors="coerce")
                prepared["reorder_level"] = pd.to_numeric(prepared["reorder_level"], errors="coerce")
                prepared["shortage_qty"] = (prepared["reorder_level"] - prepared["stock_on_hand"]).clip(lower=0)
        return prepared

    def _compile_sql(self, query_plan: StructuredQueryPlan) -> tuple[str, list[str]]:
        where_clause, params = self._compile_where(query_plan.filters)
        table_name = self._quote_identifier(query_plan.table_name)

        if query_plan.is_grouped:
            sql = self._compile_grouped_sql(query_plan, table_name, where_clause)
        else:
            sql = self._compile_record_sql(query_plan, table_name, where_clause)
        return sql, params

    def _compile_grouped_sql(
        self,
        query_plan: StructuredQueryPlan,
        table_name: str,
        where_clause: str,
    ) -> str:
        group_columns = query_plan.group_by or []
        quoted_group_columns = [self._quote_identifier(column) for column in group_columns]
        select_parts = [
            f"{quoted} AS {self._quote_identifier(column)}"
            for column, quoted in zip(group_columns, quoted_group_columns)
        ]
        metric_expr = self._metric_expression(query_plan)
        select_parts.append(f"{metric_expr} AS {self._quote_identifier('__metric__')}")
        group_clause = ", ".join(quoted_group_columns)
        having_clause = self._compile_having(query_plan)
        secondary_order = ", ".join(f"{quoted} ASC" for quoted in quoted_group_columns)
        order_clause = f"ORDER BY {self._quote_identifier('__metric__')} {query_plan.order_direction.upper()}"
        if secondary_order:
            order_clause += f", {secondary_order}"
        return (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {table_name} "
            f"{where_clause}"
            f"GROUP BY {group_clause} "
            f"{having_clause}"
            f"{order_clause} "
            f"LIMIT {int(query_plan.limit)}"
        )

    def _compile_record_sql(
        self,
        query_plan: StructuredQueryPlan,
        table_name: str,
        where_clause: str,
    ) -> str:
        select_columns = query_plan.select_columns or ([query_plan.order_by] if query_plan.order_by else ["*"])
        if select_columns == ["*"]:
            select_clause = "*"
        else:
            select_clause = ", ".join(self._quote_identifier(column) for column in select_columns)
        order_clause = ""
        if query_plan.order_by:
            order_expr = self._numeric_order_expression(query_plan.order_by)
            secondary_columns = [
                self._quote_identifier(column)
                for column in query_plan.select_columns
                if column != query_plan.order_by
            ]
            order_clause = f"ORDER BY {order_expr} {query_plan.order_direction.upper()}"
            if secondary_columns:
                order_clause += ", " + ", ".join(f"{column} ASC" for column in secondary_columns)
            order_clause += " "
        return (
            f"SELECT {select_clause} "
            f"FROM {table_name} "
            f"{where_clause}"
            f"{order_clause}"
            f"LIMIT {int(query_plan.limit)}"
        )

    def _compile_where(self, filters: list[StructuredFilter]) -> tuple[str, list[str]]:
        if not filters:
            return "", []
        clauses: list[str] = []
        params: list[str] = []
        for condition in filters:
            column = self._quote_identifier(condition.column)
            if condition.operator == "~":
                clauses.append(f"LOWER(CAST({column} AS TEXT)) LIKE LOWER(?)")
                params.append(f"%{condition.value}%")
            elif condition.operator == "in":
                values = [str(item) for item in list(condition.value or []) if str(item).strip()]
                if not values:
                    continue
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"CAST({column} AS TEXT) IN ({placeholders})")
                params.extend(values)
            else:
                clauses.append(f"CAST({column} AS TEXT) = ?")
                params.append(str(condition.value))
        return f"WHERE {' AND '.join(clauses)} ", params

    def _metric_expression(self, query_plan: StructuredQueryPlan) -> str:
        if query_plan.aggregate == "count":
            return "COUNT(*)"
        if not query_plan.metric:
            raise ValueError("Grouped query plan requires a metric unless aggregate=count")
        quoted_metric = self._quote_identifier(query_plan.metric)
        numeric_metric = f"CAST({quoted_metric} AS REAL)"
        aggregate = (query_plan.aggregate or "sum").upper()
        return f"{aggregate}({numeric_metric})"

    def _compile_having(self, query_plan: StructuredQueryPlan) -> str:
        if (
            query_plan.metric_condition_operator is None
            or query_plan.metric_condition_value is None
            or not query_plan.is_grouped
        ):
            return ""
        return (
            f"HAVING {self._quote_identifier('__metric__')} "
            f"{query_plan.metric_condition_operator} {float(query_plan.metric_condition_value)} "
        )

    def _numeric_order_expression(self, column: str) -> str:
        quoted_column = self._quote_identifier(column)
        return f"CAST({quoted_column} AS REAL)"

    def _quote_identifier(self, identifier: str) -> str:
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'
