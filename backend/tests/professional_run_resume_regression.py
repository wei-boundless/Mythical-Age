from __future__ import annotations

from types import SimpleNamespace

from runtime.shared.resume_decision import decide_runtime_resume


def test_runtime_resume_starts_new_without_checkpoint() -> None:
    decision = decide_runtime_resume(
        task_run_id="taskrun:new",
        checkpoint=None,
        current_obligation={"required_reads": [{"path": "report.json"}]},
        resume_intent="continue",
    )

    assert decision.decision == "start_new"
    assert decision.reason == "missing_checkpoint"
    assert decision.resume_from_checkpoint_ref == ""
    assert decision.current_obligation["required_reads"][0]["path"] == "report.json"


def test_runtime_resume_restarts_when_current_turn_requests_restart() -> None:
    checkpoint = SimpleNamespace(
        checkpoint_id="rtchk:taskrun:old:7",
        event_offset=7,
        loop_state=SimpleNamespace(status="running", terminal_reason=""),
    )

    decision = decide_runtime_resume(
        task_run_id="taskrun:old",
        checkpoint=checkpoint,
        current_obligation={"required_writes": [{"kind": "workspace_change"}]},
        resume_intent="restart",
    )

    assert decision.decision == "restart"
    assert decision.reason == "resume_intent_restart"
    assert decision.resume_from_checkpoint_ref == "rtchk:taskrun:old:7"
    assert decision.current_obligation["required_writes"]


def test_runtime_resume_reuses_completed_checkpoint_without_repeating_side_effects() -> None:
    checkpoint = SimpleNamespace(
        checkpoint_id="rtchk:taskrun:done:12",
        event_offset=12,
        loop_state=SimpleNamespace(status="completed", terminal_reason="completed"),
    )

    decision = decide_runtime_resume(
        task_run_id="taskrun:done",
        checkpoint=checkpoint,
        current_obligation={},
        user_goal="看一下结果",
    )

    assert decision.decision == "reuse_completed"
    assert decision.reason == "checkpoint_completed"
    assert decision.checkpoint_summary["status"] == "completed"
    assert decision.checkpoint_summary["event_offset"] == 12


def test_runtime_resume_waits_for_human_gate_before_continuing() -> None:
    checkpoint = SimpleNamespace(
        checkpoint_id="rtchk:taskrun:gate:4",
        event_offset=4,
        loop_state=SimpleNamespace(status="blocked", terminal_reason="waiting_approval"),
    )

    decision = decide_runtime_resume(
        task_run_id="taskrun:gate",
        checkpoint=checkpoint,
        current_obligation={},
        user_goal="查看当前状态",
        human_gate_state={"status": "pending", "stage_id": "stage:a"},
    )

    assert decision.decision == "wait_for_human"
    assert decision.reason == "human_gate_pending"
    assert decision.human_gate_summary["stage_id"] == "stage:a"


def test_runtime_resume_human_gate_continue_requires_structured_intent_not_keyword() -> None:
    checkpoint = SimpleNamespace(
        checkpoint_id="rtchk:taskrun:gate:5",
        event_offset=5,
        loop_state=SimpleNamespace(status="blocked", terminal_reason="waiting_approval"),
    )

    keyword_only = decide_runtime_resume(
        task_run_id="taskrun:gate",
        checkpoint=checkpoint,
        current_obligation={},
        user_goal="继续",
        human_gate_state={"status": "pending", "stage_id": "stage:a"},
    )
    structured_continue = decide_runtime_resume(
        task_run_id="taskrun:gate",
        checkpoint=checkpoint,
        current_obligation={},
        user_goal="继续",
        human_gate_state={"status": "pending", "stage_id": "stage:a"},
        resume_intent="continue",
    )
    structured_force_continue = decide_runtime_resume(
        task_run_id="taskrun:gate",
        checkpoint=checkpoint,
        current_obligation={},
        user_goal="继续",
        human_gate_state={"status": "pending", "stage_id": "stage:a"},
        resume_intent="force_continue",
    )

    assert keyword_only.decision == "wait_for_human"
    assert keyword_only.reason == "human_gate_pending"
    assert structured_continue.decision == "wait_for_human"
    assert structured_continue.reason == "human_gate_pending"
    assert structured_force_continue.decision == "continue"
    assert structured_force_continue.reason == "human_gate_force_continue_intent"


