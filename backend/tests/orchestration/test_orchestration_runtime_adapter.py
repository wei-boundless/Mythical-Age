from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.runtime_adapter import build_runtime_control


class LegacyPlan:
    execution_mode = "explicit_fanout"


class LegacyExecution:
    def __init__(self, subtask_id: str = "", bundle_item_id: str = "") -> None:
        self.subtask_id = subtask_id
        self.bundle_item_id = bundle_item_id


class RichLegacyExecution(LegacyExecution):
    def __init__(
        self,
        subtask_id: str = "",
        *,
        route: str = "",
        execution_kind: str = "worker",
        tool_name: str = "",
        worker_route: str = "",
        skill_name: str = "",
    ) -> None:
        super().__init__(subtask_id)
        self.execution_kind = execution_kind
        self.query_understanding = SimpleNamespace(
            route=route,
            tool_name=tool_name,
            skill_name=skill_name,
        )
        self.worker_plan = SimpleNamespace(worker_route=worker_route)
        self.active_skill = SimpleNamespace(name=skill_name) if skill_name else None


def test_runtime_control_plan_only_keeps_legacy_execution_order() -> None:
    executions = [LegacyExecution("b"), LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={"mode": "plan_only", "plan_id": "orch:test"},
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "orchestration_plan_only"
    assert control.primary_active is False
    assert control.executions == executions
    assert control.execution_mode == "explicit_fanout"


def test_runtime_control_plan_only_reports_validation_status() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "plan_only",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "orchestration_plan_only"
    assert control.diagnostics["validation_status"] == "passed"
    assert control.diagnostics["validation_issue_count"] == 0


def test_runtime_control_primary_uses_orchestration_execution_order() -> None:
    first = LegacyExecution("a")
    second = LegacyExecution("b")

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "intent_frame": {"intent": "general_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["general"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "b"},
                {"step_id": "step_2", "execution_id": "a"},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "validation": {"status": "passed", "issues": []},
            "topology": {"mode": "explicit_fanout"},
            "executions": [{"execution_id": "b"}, {"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=[first, second],
    )

    assert control.source == "orchestration_plan"
    assert control.primary_active is True
    assert control.executions == [second, first]
    assert control.execution_mode == "explicit_fanout"
    assert control.warnings == []
    assert control.diagnostics["entry_strategy"] == "reuse_legacy_execution"
    assert [item["execution_id"] for item in control.diagnostics["execution_entries"]] == ["b", "a"]


def test_runtime_control_primary_falls_back_when_plan_cannot_match_legacy_execution() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "intent_frame": {"intent": "general_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["general"]},
            "execution_directives": [{"step_id": "step_1", "execution_id": "missing"}],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "validation": {"status": "passed", "issues": []},
            "topology": {"mode": "explicit_fanout"},
            "executions": [{"execution_id": "missing"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert control.executions == executions
    assert "primary_fallback_legacy_execution_mismatch" in control.warnings


def test_runtime_control_primary_falls_back_when_execution_fields_conflict() -> None:
    execution = RichLegacyExecution(
        "a",
        route="worker",
        execution_kind="worker",
        tool_name="pdf_analysis",
        worker_route="pdf",
        skill_name="pdf-reading",
    )

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "intent_frame": {"intent": "document_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["document"]},
            "execution_directives": [
                {
                    "step_id": "step_1",
                    "execution_id": "a",
                    "tool": "structured_data_analysis",
                    "worker_route": "structured_data",
                    "skill": "data-analysis",
                },
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "validation": {"status": "passed", "issues": []},
            "topology": {"mode": "single_execution"},
            "executions": [
                {
                    "execution_id": "a",
                    "route": "worker",
                    "execution_kind": "worker",
                    "tool_name": "structured_data_analysis",
                    "worker_route": "structured_data",
                    "skill_name": "data-analysis",
                },
            ],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=[execution],
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert "primary_fallback_legacy_field_mismatch" in control.warnings
    assert {
        "execution_id": "a",
        "field": "tool",
        "planned": "structured_data_analysis",
        "legacy": "pdf_analysis",
    } in control.diagnostics["execution_mismatches"]


def test_runtime_control_primary_falls_back_when_validation_blocks_plan() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {
                "status": "blocked",
                "issues": [{"code": "tool_source_not_allowed"}],
            },
            "topology": {"mode": "explicit_fanout"},
            "executions": [{"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert control.executions == executions
    assert "primary_fallback_validation_blocked" in control.warnings
    assert control.diagnostics["validation_status"] == "blocked"


def test_runtime_control_primary_falls_back_for_incomplete_contract() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert control.executions == executions
    assert "primary_fallback_incomplete_contract" in control.warnings
    assert "missing:validation" in control.diagnostics["contract_blockers"]


def test_runtime_control_primary_allows_low_risk_directive_sources() -> None:
    first = LegacyExecution("a")
    second = LegacyExecution("b")

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "document_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["rag", "local_files", "document", "data", "general"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "b", "tool": "pdf_analysis", "risk_tags": ["delegated_execution"]},
                {"step_id": "step_2", "execution_id": "a", "risk_tags": []},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "explicit_fanout"},
            "executions": [{"execution_id": "b"}, {"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=[first, second],
    )

    assert control.source == "orchestration_plan"
    assert control.primary_active is True
    assert control.executions == [second, first]
    assert control.diagnostics["execution_entries"][0]["entry_kind"] == "direct_tool"
    assert control.diagnostics["execution_entries"][0]["source"] == "document"
    assert control.diagnostics["execution_entries"][0]["strategy"] == "reuse_legacy_execution"


def test_runtime_control_primary_entry_selection_flag_changes_entry_strategy() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "document_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["document"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "a", "tool": "pdf_analysis", "risk_tags": []},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a", "tool_name": "pdf_analysis"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
        primary_entry_selection_enabled=True,
    )

    assert control.primary_active is True
    assert control.diagnostics["primary_entry_selection_enabled"] is True
    assert control.diagnostics["entry_strategy"] == "primary_entry_selection_preview"
    assert control.diagnostics["execution_entries"][0]["strategy"] == "primary_entry_selection_preview"


def test_runtime_control_primary_falls_back_for_non_allowlisted_sources() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "web_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["web", "general"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "a", "tool": "web_search", "risk_tags": ["external_network"]},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert control.executions == executions
    assert "primary_fallback_allowlist_blocked" in control.warnings
    assert "web" in control.diagnostics["allowlist_blockers"]
    assert control.diagnostics["execution_entries"][0]["source"] == "web"


def test_runtime_control_marks_realtime_specialized_tools_as_web_sources() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "weather_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["web", "general"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "a", "tool": "get_weather", "risk_tags": ["external_network"]},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a", "tool_name": "get_weather"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.diagnostics["execution_entries"][0]["source"] == "web"


def test_runtime_control_primary_falls_back_for_system_execution_tools() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "system_execution"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["general"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "a", "tool": "terminal", "risk_tags": ["high_risk_tool"]},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert "primary_fallback_allowlist_blocked" in control.warnings
    assert "high_risk_tool:terminal" in control.diagnostics["allowlist_blockers"]
