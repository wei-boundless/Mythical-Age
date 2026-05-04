from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from health_system.maintenance.experiments.orchestration_trace import build_turn_orchestration_snapshot


def test_turn_replay_marks_orchestration_diff_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "run-a"
    artifact_dir = output_dir / "artifacts" / "scenario-a"
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "turn-01-main.json"
    artifact_path.write_text(
        json.dumps(
            {
                "turn": {"content": "查一下项目资料"},
                "plan": {"route": "rag", "execution_mode": "single_execution", "subqueries": ["查一下项目资料"]},
                "events": [{"event": "done", "data": {"content": "ok"}, "ts_ms": 10}],
                "orchestration_plan": {
                    "plan_id": "orch:test",
                    "topology": {"mode": "single_execution", "route": "rag", "execution_kind": "agent", "branch_count": 1},
                    "decisions": [
                        {
                            "node_id": "task-understanding",
                            "owner_module": "understanding.query_understanding",
                            "status": "selected",
                            "outputs": {"route": "rag", "execution_posture": "direct_rag", "task_kind": "lookup"},
                            "reasons": ["selected_rag"],
                        }
                    ],
                },
                "orchestration_diff": {
                    "plan_id": "orch:test",
                    "status": "mismatch",
                    "summary": "编排计划与实际执行存在关键字段差异。",
                    "items": [
                        {"field": "topology.route", "expected": "rag", "actual": "tool", "status": "mismatch"}
                    ],
                },
                "result": {"index": 1, "session_id": "s", "passed": False, "failed_checks": ["orchestration.diff=mismatch"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = build_turn_orchestration_snapshot(output_dir, "turn-01-main")
    by_id = {node["id"]: node for node in snapshot["nodes"]}

    assert snapshot["problem_node_id"] == "planner"
    assert by_id["planner"]["status"] == "failed"
    assert by_id["planner"]["refs"]["orchestration_plan_id"] == "orch:test"
    assert "topology.route" in by_id["planner"]["reasons"][0]
