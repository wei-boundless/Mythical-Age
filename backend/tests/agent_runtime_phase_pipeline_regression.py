from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime import build_agent_runtime_config
from harness.loop.agent_phase_pipeline import append_pre_model_phase_events, apply_post_model_phases


@dataclass(slots=True)
class _EventRecord:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "refs": dict(self.refs),
        }


class _EventLog:
    def __init__(self) -> None:
        self.events: list[_EventRecord] = []

    def append(
        self,
        task_run_id: str,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
    ) -> _EventRecord:
        event = _EventRecord(
            event_type=event_type,
            payload=dict(payload or {}),
            refs={"task_run_id": task_run_id, **dict(refs or {})},
            event_id=f"evt:{len(self.events) + 1}",
        )
        self.events.append(event)
        return event

    def list_events(self, task_run_id: str) -> list[_EventRecord]:
        return [event for event in self.events if event.refs.get("task_run_id") == task_run_id]


@dataclass(slots=True)
class _RuntimeHost:
    event_log: _EventLog = field(default_factory=_EventLog)


def test_professional_config_enables_phase_pipeline_without_runner_metadata() -> None:
    selected_recipe = {
        "task_mode": "professional_mode",
        "metadata": {
            "interaction_mode": "professional_mode",
            "task_requirement_contract": {
                "task_goal_type": "test_report_triage",
                "deliverables": ["failure_classification", "evidence_limits"],
            },
        },
    }

    config = build_agent_runtime_config(selected_recipe_payload=selected_recipe)
    payload = config.to_dict()

    assert config.interaction_mode == "professional_mode"
    assert payload["enabled_phases"] == [
        "planning",
        "model_turn",
        "tool_followup",
        "evidence",
        "verification",
        "closeout",
    ]
    assert "control_runner" not in selected_recipe["metadata"]


def test_phase_pipeline_emits_only_agent_runtime_phase_events() -> None:
    host = _RuntimeHost()
    selected_recipe = {
        "task_mode": "professional_mode",
        "metadata": {
            "interaction_mode": "professional_mode",
            "task_requirement_contract": {
                "task_goal_type": "test_report_triage",
                "deliverables": ["failure_classification", "evidence_limits"],
                "execution_obligation": {"requires_evidence": True},
            },
        },
    }
    config = build_agent_runtime_config(selected_recipe_payload=selected_recipe)

    pre = append_pre_model_phase_events(
        runtime_host=host,
        task_run_id="taskrun:phase",
        task_contract_ref="contract:phase",
        task_id="task.phase",
        selected_recipe_payload=selected_recipe,
        agent_runtime_config=config,
    )
    outcome, post_events = apply_post_model_phases(
        runtime_host=host,
        task_run_id="taskrun:phase",
        task_id="task.phase",
        user_message="分析失败报告并给出证据边界。",
        task_contract_ref="contract:phase",
        selected_recipe_payload=selected_recipe,
        agent_runtime_config=config,
        final_content="失败归类：输出边界。证据边界：本轮没有读取报告，不能声称完整诊断。",
        final_answer_metadata={},
        terminal_reason="completed",
        tool_call_count=0,
        tool_observation_count=0,
    )

    event_types = [event.event_type for event in host.event_log.events]
    assert event_types == [
        "agent_runtime_planning_phase_checked",
        "agent_runtime_closeout_phase_checked",
    ]
    assert pre.runtime_execution_facts["agent_runtime_phase_pipeline"]["authority"] == "harness.loop.agent_phase_pipeline"
    assert len(pre.events) == 1
    assert len(post_events) == 1
    assert outcome.run_outcome["authority"] == "harness.loop.agent_phase_pipeline"
    assert outcome.terminal_reason in {"partial_contract_failed", "agent_phase_validation_failed"}


