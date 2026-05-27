from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import ControlKernel, TaskContract


def test_control_kernel_reports_empty_graph_after_wiring_clear() -> None:
    task = TaskContract(task_id="task-1", user_goal="重新梳理架构", session_id="s")

    result = ControlKernel().collect(task=task)

    assert result.status == "blocked"
    assert result.reason == "wiring_cleared_pending_control_kernel"
    assert result.execution_graph is not None
    assert result.execution_graph.nodes == ()
    assert result.diagnostics["cleared_old_wiring"] is True


