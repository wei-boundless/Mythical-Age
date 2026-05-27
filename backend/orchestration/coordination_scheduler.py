from __future__ import annotations

from typing import Any


def _schedule_stage_execution_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    node_work_order: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del runtime, session_id, source, stage_execution_request, node_work_order, current_turn_context
    raise RuntimeError("TaskGraph coordination scheduler is not available in the rebuilt single-agent runtime")
