from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.work_order_executor import _candidates_for_memory_edge


def test_review_advisories_are_structured_without_full_report_pollution() -> None:
    report = """审核裁决：通过

### 五、潜在风险与建议（非阻塞性）
1. 卷4荀霜背叛与卷5赎罪回归之间，建议在卷4末章或卷5前几章增加荀霜暗中提供情报的桥段，避免读者对角色产生不可逆的负面印象。
2. 卷8最终对决中，建议明确主角“以自身为代价改写规则”的具体代价和结果，避免结局模糊。

## 是否允许进入下一阶段
允许。上述建议为非阻塞性优化，可在分卷规划阶段细化处理。"""
    candidates = _candidates_for_memory_edge(
        edge={
            "edge_type": "memory_commit",
            "source_output_key": "review_advisories",
            "require_source_output_key": True,
            "record_kind": "planning_advisory",
        },
        candidates=[],
        task_run_payload={"diagnostics": {"final_answer": report}},
    )

    assert len(candidates) == 2
    assert {item["record_kind"] for item in candidates} == {"planning_advisory"}
    assert all(item["payload"]["severity"] == "non_blocking" for item in candidates)
    assert "是否允许进入下一阶段" not in candidates[0]["canonical_text"]
    assert "荀霜暗中提供情报" in candidates[0]["canonical_text"]


def test_review_advisories_do_not_commit_blocking_revision_text() -> None:
    report = """审核裁决：返修

### 五、潜在风险与建议（非阻塞性）
1. 必须修改卷4背叛线，否则不允许进入下一阶段。
"""
    candidates = _candidates_for_memory_edge(
        edge={
            "edge_type": "memory_commit",
            "source_output_key": "review_advisories",
            "require_source_output_key": True,
            "record_kind": "planning_advisory",
        },
        candidates=[],
        task_run_payload={"diagnostics": {"final_answer": report}},
    )

    assert candidates == []
