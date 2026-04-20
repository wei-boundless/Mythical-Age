from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from structured_data.catalog import StructuredDataCatalog
from query.planner import QueryPlanner


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
    assert explicit_execution.tool_input.get("path", "").endswith("employees.xlsx")
    assert explicit_execution.structured_binding is not None
    assert explicit_execution.structured_binding.dataset_path.endswith("employees.xlsx")

    followup_plan = planner.build_plan(
        session_id="structured-followup-regression",
        message="谁最高",
        history=history,
    )
    followup_execution = followup_plan.iter_executions()[0]
    assert followup_execution.tool_input.get("path", "").endswith("inventory.xlsx")
    assert followup_execution.structured_binding is not None
    assert followup_execution.structured_binding.dataset_path.endswith("inventory.xlsx")

    print("ALL PASSED (structured follow-up history regression)")


if __name__ == "__main__":
    main()
