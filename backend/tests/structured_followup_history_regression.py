from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structured_data.catalog import StructuredDataCatalog
from query.planner import QueryPlanner
from query.tool_input_resolver import ToolInputResolver
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    assert StructuredDataCatalog.default_path_for_query("为我查找，谁是薪水最高的销售人员").endswith("employees.xlsx")

    planner = QueryPlanner(
        base_dir=ROOT,
        skill_registry=None,
        tool_runtime=type("RegistryStub", (), {"registry": None})(),
    )

    history = [
        {"role": "user", "content": "在数据库中为我查找缺货信息"},
        {"role": "assistant", "content": "数据源：knowledge/E-commerce Data/inventory.xlsx"},
    ]

    explicit_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="为我查找，谁是薪水最高的销售人员",
        history=history,
    )
    explicit_execution = explicit_plan.iter_executions()[0]
    assert explicit_execution.query_understanding.route == "rag"
    assert explicit_execution.query_understanding.tool_name is None
    assert explicit_execution.structured_binding is None
    assert not explicit_execution.tool_input.get("path", "")

    weak_followup_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="把那个表按仓库展开一下",
        history=history,
    )
    weak_followup_execution = weak_followup_plan.iter_executions()[0]
    assert weak_followup_execution.structured_binding is None
    assert not weak_followup_execution.tool_input.get("path", "")

    generic_followup_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="按仓库展开一下",
        history=history,
    )
    generic_followup_execution = generic_followup_plan.iter_executions()[0]
    assert generic_followup_execution.structured_binding is None
    assert not generic_followup_execution.tool_input.get("path", "")

    fresh_grouped_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="按仓库统计哪些商品缺货",
        history=history,
    )
    fresh_grouped_execution = fresh_grouped_plan.iter_executions()[0]
    assert fresh_grouped_execution.query_understanding.route == "rag"
    assert fresh_grouped_execution.query_understanding.tool_name is None
    assert fresh_grouped_execution.structured_binding is None
    assert not fresh_grouped_execution.tool_input.get("path", "")

    explicit_followup_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="把 knowledge/E-commerce Data/inventory.xlsx 按仓库展开一下",
        history=history,
    )
    explicit_followup_execution = explicit_followup_plan.iter_executions()[0]
    assert explicit_followup_execution.tool_input.get("path", "").endswith("inventory.xlsx")
    assert explicit_followup_execution.structured_binding is not None
    assert explicit_followup_execution.structured_binding.dataset_path.endswith("inventory.xlsx")

    unresolved_explicit_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="把 knowledge/E-commerce Data/missing.xlsx 按仓库展开一下",
        history=history,
    )
    unresolved_explicit_execution = unresolved_explicit_plan.iter_executions()[0]
    assert unresolved_explicit_execution.structured_binding is None
    assert unresolved_explicit_execution.tool_input.get("path", "").endswith("missing.xlsx")
    assert not unresolved_explicit_execution.tool_input.get("path", "").endswith("inventory.xlsx")

    resolver = ToolInputResolver(base_dir=ROOT)
    explicit_shortname_plan = type(
        "PlanStub",
        (),
        {
            "message": "给我 inventory.xlsx 最缺货的前三个仓库",
            "query_understanding": QueryUnderstanding(
                route="tool",
                tool_name="structured_data_analysis",
                tool_input={"query": "给我 inventory.xlsx 最缺货的前三个仓库", "path": "inventory.xlsx"},
            ),
            "structured_binding": type(
                "BindingStub",
                (),
                {"dataset_path": "knowledge/E-commerce Data/inventory.xlsx"},
            )(),
        },
    )()
    explicit_shortname_input = resolver.resolve(plan=explicit_shortname_plan, history=history)
    assert explicit_shortname_input["path"] == "knowledge/E-commerce Data/inventory.xlsx"

    explicit_only_shortname_plan = type(
        "PlanStub",
        (),
        {
            "message": "给我 inventory.xlsx 最缺货的前三个仓库",
            "query_understanding": QueryUnderstanding(
                route="tool",
                tool_name="structured_data_analysis",
                tool_input={"query": "给我 inventory.xlsx 最缺货的前三个仓库", "path": "inventory.xlsx"},
            ),
            "structured_binding": None,
        },
    )()
    explicit_only_shortname_input = resolver.resolve(plan=explicit_only_shortname_plan, history=history)
    assert explicit_only_shortname_input["path"] == "knowledge/E-commerce Data/inventory.xlsx"

    weak_followup_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="谁最高",
        history=history,
    )
    weak_followup_execution = weak_followup_plan.iter_executions()[0]
    assert weak_followup_execution.structured_binding is None
    assert not weak_followup_execution.tool_input.get("path", "")

    print("ALL PASSED (structured follow-up history regression)")


if __name__ == "__main__":
    main()
