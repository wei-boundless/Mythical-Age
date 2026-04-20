from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structured_data.catalog import StructuredDataCatalog
from query.planner import QueryPlanner
from understanding.query_understanding import QueryUnderstanding


def main() -> None:
    assert StructuredDataCatalog.default_path_for_query("为我查找，谁是薪水最高的销售人员").endswith("employees.xlsx")

    planner = QueryPlanner(
        base_dir=ROOT,
        skill_registry=None,
        tool_runtime=SimpleNamespace(registry=None),
    )

    history = [
        {"role": "user", "content": "在数据库中为我查找缺货信息"},
        {"role": "assistant", "content": "数据源：knowledge/E-commerce Data/inventory.xlsx"},
    ]

    explicit_new_query = QueryUnderstanding(
        intent="structured_dataset_extreme_record",
        target_object="employee",
        tool_name="structured_data_analysis",
        tool_input={"query": "为我查找，谁是薪水最高的销售人员"},
    )
    explicit_input = planner.resolve_tool_input_from_history(
        SimpleNamespace(
            message="为我查找，谁是薪水最高的销售人员",
            query_understanding=explicit_new_query,
        ),
        history,
    )
    assert "path" not in explicit_input

    followup_query = QueryUnderstanding(
        intent="structured_followup_query",
        target_object=None,
        tool_name="structured_data_analysis",
        tool_input={"query": "谁最高"},
    )
    followup_input = planner.resolve_tool_input_from_history(
        SimpleNamespace(
            message="谁最高",
            query_understanding=followup_query,
        ),
        history,
    )
    assert followup_input.get("path", "").endswith("inventory.xlsx")

    print("ALL PASSED (structured follow-up history regression)")


if __name__ == "__main__":
    main()
