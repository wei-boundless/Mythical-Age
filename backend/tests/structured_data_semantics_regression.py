from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from structured_data.catalog import StructuredDataCatalog
from structured_data.planner import StructuredDataPlanner


def _load_tool_module():
    tool_path = ROOT / "tools" / "structured_data_analysis_tool.py"

    callbacks_manager = types.ModuleType("langchain_core.callbacks.manager")
    callbacks_manager.AsyncCallbackManagerForToolRun = object
    callbacks_manager.CallbackManagerForToolRun = object
    tools_module = types.ModuleType("langchain_core.tools")

    class _BaseTool:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    tools_module.BaseTool = _BaseTool

    sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    sys.modules["langchain_core.callbacks"] = types.ModuleType("langchain_core.callbacks")
    sys.modules["langchain_core.callbacks.manager"] = callbacks_manager
    sys.modules["langchain_core.tools"] = tools_module

    spec = importlib.util.spec_from_file_location("structured_data_analysis_tool_test", tool_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load structured_data_analysis_tool.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_employees_df() -> pd.DataFrame:
    path = ROOT / "knowledge" / "E-commerce Data" / "employees.xlsx"
    df = pd.read_excel(path)
    return StructuredDataPlanner().normalize_columns(df)


def _load_inventory_df() -> pd.DataFrame:
    path = ROOT / "knowledge" / "E-commerce Data" / "inventory.xlsx"
    df = pd.read_excel(path)
    return StructuredDataPlanner().normalize_columns(df)


def main() -> None:
    planner = StructuredDataPlanner()
    employees_df = _load_employees_df()
    inventory_df = _load_inventory_df()
    employees_rel_path = "knowledge/E-commerce Data/employees.xlsx"
    inventory_rel_path = "knowledge/E-commerce Data/inventory.xlsx"

    plan_top_n = planner.build_plan(
        query="给我薪水前五的名单",
        df=employees_df,
        dataset_rel_path=employees_rel_path,
    )
    assert plan_top_n.analysis_type == "top_n"
    assert plan_top_n.metric == "base_salary"
    assert plan_top_n.group_by is None
    assert plan_top_n.filters == []
    assert plan_top_n.query_mode == "record"
    assert plan_top_n.order_by == "base_salary"
    assert plan_top_n.entity_column == "name"
    assert plan_top_n.query_plan is not None
    assert plan_top_n.query_plan.query_kind == "record"

    plan_grouped = planner.build_plan(
        query="按部门汇总薪水前五",
        df=employees_df,
        dataset_rel_path=employees_rel_path,
    )
    assert plan_grouped.analysis_type == "top_n"
    assert plan_grouped.group_by == "department"
    assert plan_grouped.query_mode == "grouped"
    assert plan_grouped.query_plan is not None
    assert plan_grouped.query_plan.query_kind == "grouped"

    plan_diagnostic = planner.build_plan(
        query="不对吧，为什么许晨是第一，但前五里面是第五",
        df=employees_df,
        dataset_rel_path=employees_rel_path,
    )
    assert plan_diagnostic.filters == []
    assert plan_diagnostic.diagnostic is True

    plan_inventory_abundance = planner.build_plan(
        query="分析一下货物情况，哪些仓库货物最充足",
        df=inventory_df,
        dataset_rel_path=inventory_rel_path,
    )
    assert plan_inventory_abundance.analysis_type == "top_n"
    assert plan_inventory_abundance.metric == "stock_on_hand"
    assert plan_inventory_abundance.group_by == "warehouse"
    assert plan_inventory_abundance.query_mode == "grouped"
    assert plan_inventory_abundance.query_plan is not None
    assert plan_inventory_abundance.query_plan.metric == "stock_on_hand"

    correction_inventory_abundance = planner.build_plan(
        query="我不是要知道缺货情况，我要你分析哪些地方货物最充足",
        df=inventory_df,
        dataset_rel_path=inventory_rel_path,
    )
    assert correction_inventory_abundance.analysis_type == "top_n"
    assert correction_inventory_abundance.metric == "stock_on_hand"
    assert correction_inventory_abundance.group_by == "warehouse"
    assert correction_inventory_abundance.query_mode == "grouped"
    assert correction_inventory_abundance.query_plan is not None

    location_shortage_plan = planner.build_plan(
        query="哪些地方货物不够",
        df=inventory_df,
        dataset_rel_path=inventory_rel_path,
    )
    assert location_shortage_plan.analysis_type == "top_n"
    assert location_shortage_plan.metric == "shortage_qty"
    assert location_shortage_plan.group_by == "warehouse"
    assert location_shortage_plan.query_mode == "grouped"
    assert location_shortage_plan.query_plan is not None
    assert "shortage_qty" in location_shortage_plan.query_plan.derived_metrics

    non_shortage_plan = planner.build_plan(
        query="哪些地方不缺货",
        df=inventory_df,
        dataset_rel_path=inventory_rel_path,
    )
    assert non_shortage_plan.analysis_type == "top_n"
    assert non_shortage_plan.metric == "shortage_qty"
    assert non_shortage_plan.group_by == "warehouse"
    assert non_shortage_plan.query_mode == "grouped"
    assert non_shortage_plan.query_plan is not None
    assert non_shortage_plan.query_plan.metric_condition_operator == "="
    assert non_shortage_plan.query_plan.metric_condition_value == 0.0

    hinted_plan = planner.build_plan(
        query="帮我看看这些地方",
        df=inventory_df,
        dataset_rel_path=inventory_rel_path,
        requested_analysis_type="top_n",
        semantic_hints={
            "analysis_type_hint": "top_n",
            "state_kind": "non_shortage",
            "group_hint": "warehouse",
            "metric_hint": "shortage_qty",
            "query_mode_hint": "grouped",
        },
    )
    assert hinted_plan.metric == "shortage_qty"
    assert hinted_plan.group_by == "warehouse"
    assert hinted_plan.query_mode == "grouped"
    assert hinted_plan.query_plan is not None
    assert hinted_plan.query_plan.metric_condition_operator == "="

    assert StructuredDataCatalog.default_path_for_query("为我查找，谁是薪水最高的销售人员").endswith("employees.xlsx")

    tool_module = _load_tool_module()
    tool = tool_module.StructuredDataAnalysisTool(root_dir=ROOT)

    output = tool._run("给我薪水前五的名单", path=employees_rel_path)
    assert "数据源：employees.xlsx" in output
    assert "查询模式：记录排序" in output
    assert "排名维度：" not in output
    assert "姓名" in output
    assert "薪水" in output

    grouped_output = tool._run("按部门汇总薪水前五", path=employees_rel_path)
    assert "查询模式：分组聚合排名" in grouped_output
    assert "排名维度：部门" in grouped_output

    inventory_output = tool._run("分析一下货物情况，哪些仓库货物最充足", path=inventory_rel_path)
    assert "数据源：inventory.xlsx" in inventory_output
    assert "查询模式：分组聚合排名" in inventory_output
    assert "排名维度：仓库" in inventory_output

    override_output = tool._run("我不是要知道缺货情况，我要你分析哪些地方货物最充足", path=inventory_rel_path)
    assert "缺货商品（前" not in override_output
    assert "查询模式：分组聚合排名" in override_output
    assert "排名维度：仓库" in override_output

    shortage_places_output = tool._run("哪些地方货物不够", path=inventory_rel_path)
    assert "数据源：inventory.xlsx" in shortage_places_output
    assert "缺货商品（前" not in shortage_places_output
    assert "查询模式：分组聚合排名" in shortage_places_output
    assert "排名维度：仓库" in shortage_places_output
    assert "排序依据：总和（缺口）" in shortage_places_output

    non_shortage_places_output = tool._run("哪些地方不缺货", path=inventory_rel_path)
    assert "数据源：inventory.xlsx" in non_shortage_places_output
    assert "当前没有完全不缺货的仓库" in non_shortage_places_output

    print("ALL PASSED (structured data semantics regression)")


if __name__ == "__main__":
    main()
