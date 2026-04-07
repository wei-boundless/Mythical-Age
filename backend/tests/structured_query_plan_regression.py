from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structured_data.executor import StructuredQueryExecutor
from structured_data.planner import StructuredDataPlanner


def _load_df(relative_path: str) -> pd.DataFrame:
    df = pd.read_excel(ROOT / relative_path)
    return StructuredDataPlanner().normalize_columns(df)


def main() -> None:
    planner = StructuredDataPlanner()
    executor = StructuredQueryExecutor()

    employees_path = "knowledge/E-commerce Data/employees.xlsx"
    inventory_path = "knowledge/E-commerce Data/inventory.xlsx"
    employees_df = _load_df(employees_path)
    inventory_df = _load_df(inventory_path)

    salary_plan = planner.build_plan(
        query="给我薪水前五的名单",
        df=employees_df,
        dataset_rel_path=employees_path,
    )
    assert salary_plan.query_plan is not None
    assert salary_plan.query_plan.query_kind == "record"
    assert salary_plan.query_plan.order_by == "base_salary"
    salary_result = executor.execute(salary_plan, employees_df)
    assert salary_result is not None
    oracle_salary = (
        employees_df.assign(base_salary=pd.to_numeric(employees_df["base_salary"], errors="coerce"))
        .dropna(subset=["base_salary"])
        .sort_values("base_salary", ascending=False)
        .head(5)
        .reset_index(drop=True)
    )
    assert salary_result.dataframe["base_salary"].tolist() == oracle_salary["base_salary"].tolist()
    assert salary_result.dataframe["name"].tolist() == oracle_salary["name"].tolist()

    grouped_plan = planner.build_plan(
        query="按部门汇总薪水前五",
        df=employees_df,
        dataset_rel_path=employees_path,
    )
    assert grouped_plan.query_plan is not None
    assert grouped_plan.query_plan.query_kind == "grouped"
    assert grouped_plan.query_plan.group_by == ["department"]
    grouped_result = executor.execute(grouped_plan, employees_df)
    assert grouped_result is not None
    oracle_grouped = (
        employees_df.assign(base_salary=pd.to_numeric(employees_df["base_salary"], errors="coerce"))
        .dropna(subset=["base_salary"])
        .groupby("department")["base_salary"]
        .sum()
        .reset_index()
        .sort_values(["base_salary", "department"], ascending=[False, True])
        .head(5)
        .reset_index(drop=True)
    )
    assert grouped_result.dataframe["department"].tolist() == oracle_grouped["department"].tolist()
    assert grouped_result.dataframe["__metric__"].round(6).tolist() == oracle_grouped["base_salary"].round(6).tolist()

    abundance_plan = planner.build_plan(
        query="分析一下货物情况，哪些仓库货物最充足",
        df=inventory_df,
        dataset_rel_path=inventory_path,
    )
    assert abundance_plan.query_plan is not None
    assert abundance_plan.query_plan.query_kind == "grouped"
    assert abundance_plan.query_plan.metric == "stock_on_hand"
    abundance_result = executor.execute(abundance_plan, inventory_df)
    assert abundance_result is not None
    oracle_abundance = (
        inventory_df.assign(stock_on_hand=pd.to_numeric(inventory_df["stock_on_hand"], errors="coerce"))
        .dropna(subset=["stock_on_hand"])
        .groupby("warehouse")["stock_on_hand"]
        .sum()
        .reset_index()
        .sort_values(["stock_on_hand", "warehouse"], ascending=[False, True])
        .head(10)
        .reset_index(drop=True)
    )
    assert abundance_result.dataframe["warehouse"].tolist() == oracle_abundance["warehouse"].tolist()
    assert abundance_result.dataframe["__metric__"].round(6).tolist() == oracle_abundance["stock_on_hand"].round(6).tolist()

    shortage_plan = planner.build_plan(
        query="哪些地方货物不够",
        df=inventory_df,
        dataset_rel_path=inventory_path,
    )
    assert shortage_plan.query_plan is not None
    assert shortage_plan.query_plan.metric == "shortage_qty"
    assert "shortage_qty" in shortage_plan.query_plan.derived_metrics
    shortage_result = executor.execute(shortage_plan, inventory_df)
    assert shortage_result is not None
    oracle_shortage = inventory_df.copy()
    oracle_shortage["stock_on_hand"] = pd.to_numeric(oracle_shortage["stock_on_hand"], errors="coerce")
    oracle_shortage["reorder_level"] = pd.to_numeric(oracle_shortage["reorder_level"], errors="coerce")
    oracle_shortage = oracle_shortage.dropna(subset=["stock_on_hand", "reorder_level"])
    oracle_shortage["shortage_qty"] = (oracle_shortage["reorder_level"] - oracle_shortage["stock_on_hand"]).clip(lower=0)
    oracle_shortage = (
        oracle_shortage[oracle_shortage["shortage_qty"] > 0]
        .groupby("warehouse")["shortage_qty"]
        .sum()
        .reset_index()
        .sort_values(["shortage_qty", "warehouse"], ascending=[False, True])
        .head(10)
        .reset_index(drop=True)
    )
    assert shortage_result.dataframe["warehouse"].tolist() == oracle_shortage["warehouse"].tolist()
    assert shortage_result.dataframe["__metric__"].round(6).tolist() == oracle_shortage["shortage_qty"].round(6).tolist()

    non_shortage_plan = planner.build_plan(
        query="哪些地方不缺货",
        df=inventory_df,
        dataset_rel_path=inventory_path,
    )
    assert non_shortage_plan.query_plan is not None
    assert non_shortage_plan.query_plan.metric_condition_operator == "="
    assert non_shortage_plan.query_plan.metric_condition_value == 0.0
    non_shortage_result = executor.execute(non_shortage_plan, inventory_df)
    assert non_shortage_result is not None
    assert non_shortage_result.dataframe.empty

    print("ALL PASSED (structured query plan regression)")


if __name__ == "__main__":
    main()
