from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.runtime_adapter import build_runtime_control
from orchestration.restore_context import RestoreAuthorityContextGate
from orchestration.execution_candidate import ExecutionCandidateGate


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
    assert control.diagnostics["execution_entries"][0]["eligible_for_primary_entry"] is True
    assert control.diagnostics["execution_entries"][0]["eligibility_reason"] == "eligible_low_risk_primary_entry"


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
    assert control.diagnostics["execution_entries"][0]["eligible_for_primary_entry"] is True
    assert control.diagnostics["entry_selection"]["state"] == "ready"
    assert control.diagnostics["entry_selection"]["selected_execution_ids"] == ["a"]
    assert control.diagnostics["primary_execution_preview"]["state"] == "ready"
    assert control.diagnostics["primary_execution_preview"]["output_source"] == "legacy_final_output"
    assert control.diagnostics["primary_execution_preview"]["execution_count"] == 1
    assert control.diagnostics["primary_execution_preview"]["executable_contract"]["state"] == "preview_ready"
    assert control.diagnostics["primary_execution_preview"]["executable_contract"]["runnable"] is False
    assert control.diagnostics["primary_entry_takeover"]["state"] == "disabled"
    assert control.diagnostics["phase7_readiness"]["state"] == "disabled"
    assert control.diagnostics["phase7_readiness"]["principle_alignment"]["phase"] == "7E"
    assert control.diagnostics["phase7_readiness"]["principle_alignment"]["state"] == "blocked"
    assert "doc66_output_specialty_only" in control.diagnostics["phase7_readiness"]["principle_alignment"]["blockers"]


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
    assert control.diagnostics["execution_entries"][0]["eligible_for_primary_entry"] is False
    assert "source_not_low_risk:web" in control.diagnostics["execution_entries"][0]["eligibility_blockers"]
    assert "risk_tag:external_network" in control.diagnostics["execution_entries"][0]["eligibility_blockers"]
    assert control.diagnostics["entry_selection"]["state"] == "disabled"


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
    assert control.diagnostics["execution_entries"][0]["eligible_for_primary_entry"] is False
    assert "source_not_low_risk:web" in control.diagnostics["execution_entries"][0]["eligibility_blockers"]


def test_runtime_control_entry_selection_blocks_preview_when_entries_are_not_eligible() -> None:
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
        primary_entry_selection_enabled=True,
    )

    assert control.source == "legacy_fallback"
    assert control.diagnostics["entry_selection"]["enabled"] is True
    assert control.diagnostics["entry_selection"]["state"] == "blocked"
    assert control.diagnostics["entry_selection"]["selected_execution_ids"] == []
    assert control.diagnostics["entry_selection"]["blocked_count"] == 1
    assert control.diagnostics["primary_execution_preview"]["state"] == "blocked"
    assert control.diagnostics["primary_execution_preview"]["execution_count"] == 0


def test_runtime_control_primary_execution_preview_maps_to_legacy_without_executing() -> None:
    executions = [
        RichLegacyExecution(
            "a",
            route="tool",
            execution_kind="direct_tool",
            tool_name="structured_data_analysis",
            skill_name="structured-data",
        )
    ]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "data_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["data"]},
            "execution_directives": [
                {
                    "step_id": "step_1",
                    "execution_id": "a",
                    "tool": "structured_data_analysis",
                    "skill": "structured-data",
                    "risk_tags": [],
                },
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "single_execution"},
            "executions": [
                {
                    "execution_id": "a",
                    "route": "tool",
                    "execution_kind": "direct_tool",
                    "tool_name": "structured_data_analysis",
                    "skill_name": "structured-data",
                }
            ],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
        primary_entry_selection_enabled=True,
    )

    preview = control.diagnostics["primary_execution_preview"]
    assert control.executions == executions
    assert preview["state"] == "ready"
    assert preview["reason"] == "primary_execution_preview_ready"
    assert preview["preview_executions"][0]["execution_id"] == "a"
    assert preview["preview_executions"][0]["tool"] == "structured_data_analysis"
    assert preview["preview_executions"][0]["legacy_tool"] == "structured_data_analysis"
    assert preview["preview_executions"][0]["output_source"] == "legacy_final_output"
    assert preview["mismatch_count"] == 0
    assert preview["executable_contract"]["phase"] == "7C"
    assert preview["executable_contract"]["state"] == "preview_ready"
    assert preview["executable_contract"]["execution_specs"][0]["tool"] == "structured_data_analysis"
    assert preview["executable_contract"]["execution_specs"][0]["runtime_bridge_required"] is True


def test_runtime_control_primary_entry_takeover_activates_for_minimal_low_risk_sources() -> None:
    executions = [RichLegacyExecution("a", route="rag", execution_kind="worker", worker_route="retrieval")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "knowledge_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["rag"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "a", "worker_route": "retrieval", "risk_tags": []},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a", "route": "rag", "execution_kind": "worker", "worker_route": "retrieval"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
        primary_entry_selection_enabled=True,
        primary_entry_takeover_enabled=True,
    )

    assert control.source == "orchestration_primary_entry"
    assert control.executions == executions
    assert control.diagnostics["primary_entry_takeover_enabled"] is True
    assert control.diagnostics["primary_entry_takeover"]["state"] == "active"
    assert control.diagnostics["primary_entry_takeover"]["selected_execution_ids"] == ["a"]
    assert control.diagnostics["primary_entry_takeover"]["output_source"] == "primary_entry_controlled_legacy_execution"
    assert control.diagnostics["phase7_readiness"]["state"] == "ready"
    assert control.diagnostics["phase7_readiness"]["blockers"] == []
    assert control.diagnostics["phase7_readiness"]["legacy_decommission"]["state"] == "not_ready"
    assert control.diagnostics["phase7_readiness"]["legacy_decommission"]["delete_allowed"] is False
    assert control.diagnostics["phase7_readiness"]["principle_alignment"]["state"] == "blocked"
    assert "legacy_power_domain:decide" in control.diagnostics["phase7_readiness"]["principle_alignment"]["blockers"]
    assert control.diagnostics["phase7_readiness"]["principle_alignment"]["legacy_power_domains"][0]["module"] == "backend/query/planner.py"


def test_runtime_control_primary_entry_takeover_blocks_document_and_data_scope_initially() -> None:
    executions = [
        RichLegacyExecution(
            "a",
            route="tool",
            execution_kind="direct_tool",
            tool_name="structured_data_analysis",
        )
    ]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "data_query"},
            "memory_policy": {"read_mode": "none"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["data"]},
            "execution_directives": [
                {"step_id": "step_1", "execution_id": "a", "tool": "structured_data_analysis", "risk_tags": []},
            ],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "diagnostics": {
                "output_authority": {
                    "state": "candidate_projected",
                    "blockers": ["legacy_present_still_executes"],
                },
                "dispatch_authority": {
                    "state": "candidate_projected",
                    "blockers": ["legacy_decide_still_executes"],
                },
            },
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a", "route": "tool", "tool_name": "structured_data_analysis"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
        primary_entry_selection_enabled=True,
        primary_entry_takeover_enabled=True,
    )

    assert control.source == "orchestration_plan"
    assert control.diagnostics["primary_execution_preview"]["state"] == "ready"
    assert control.diagnostics["primary_entry_takeover"]["state"] == "blocked"
    assert control.diagnostics["primary_entry_takeover"]["reason"] == "source_not_in_takeover_scope"
    assert control.diagnostics["primary_entry_takeover"]["blocked_sources"] == ["data"]
    assert control.diagnostics["phase7_readiness"]["state"] == "blocked"
    assert "source_not_phase7_ready:data" in control.diagnostics["phase7_readiness"]["blockers"]
    assert control.diagnostics["phase7_readiness"]["output_authority"]["state"] == "candidate_projected"
    assert control.diagnostics["phase7_readiness"]["dispatch_authority"]["state"] == "candidate_projected"
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["state"] == "blocked"
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["delete_allowed"] is False
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["gate_blockers"]
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["top_blockers"]
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["domain_summaries"][0]["domain"] == "restore"
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["migration_tasks"][0]["task_id"].startswith("phase7m:")
    assert control.diagnostics["phase7_readiness"]["cutover_readiness"]["migration_tasks"][0]["scope"] == "diagnostic_only"
    assert "权力域" in control.diagnostics["phase7_readiness"]["cutover_readiness"]["human_summary"]


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
    assert control.diagnostics["execution_entries"][0]["eligible_for_primary_entry"] is False
    assert "system_execution:terminal" in control.diagnostics["execution_entries"][0]["eligibility_blockers"]


def test_restore_shadow_consumer_observe_only_stays_read_only() -> None:
    executions = [RichLegacyExecution("a", route="knowledge", execution_kind="agent")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "validation": {"status": "passed", "issues": []},
            "intent_frame": {"intent": "followup"},
            "memory_policy": {"read_mode": "session"},
            "context_policy": {"mode": "runtime"},
            "resource_policy": {"allowed_sources": ["general"]},
            "execution_directives": [{"step_id": "step_1", "execution_id": "a", "risk_tags": []}],
            "answer_policy": {"answer_channel": "runtime_output_boundary"},
            "diagnostics": {
                "restore_authority": {
                    "state": "candidate_projected",
                    "restore_authority_context_gate": {
                        "state": "orchestration_filtered",
                        "mode": "observe_only",
                        "filtered_keys": ["active_pdf"],
                    },
                    "restore_shadow_consumer_contract": {
                        "state": "contract_ready",
                        "candidate_count": 1,
                        "state_write_allowed": False,
                        "takeover_allowed": False,
                        "delete_allowed": False,
                        "contract_candidates": [
                            {
                                "candidate_id": "restore:1",
                                "replacement_point": "context_handle_restore",
                                "legacy_consumer": "query.runtime_context_state",
                                "comparison": "shadow_matches_legacy_observation",
                                "consumer_state": "observe_only_ready",
                                "state_write_allowed": False,
                                "takeover_allowed": False,
                            }
                        ],
                    },
                }
            },
            "topology": {"mode": "single_execution"},
            "executions": [{"execution_id": "a", "route": "knowledge"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
        restore_shadow_consumer_enabled=True,
        restore_shadow_consumer_mode="observe_only",
    )

    restore_authority = control.diagnostics["phase7_readiness"]["restore_authority"]
    shadow_control = restore_authority["restore_shadow_consumer_control"]
    shadow_observation = restore_authority["restore_shadow_consumer_observation"]
    legacy_decommission = restore_authority["restore_legacy_decommission_plan"]
    assert shadow_control["state"] == "observe_only_active"
    assert shadow_control["state_write_allowed"] is False
    assert shadow_control["takeover_allowed"] is False
    assert shadow_observation["state"] == "observed"
    assert shadow_observation["observations"][0]["observation_state"] == "captured_observe_only"
    assert shadow_observation["observations"][0]["state_write_allowed"] is False
    assert shadow_observation["observations"][0]["takeover_allowed"] is False
    assert legacy_decommission["state"] == "first_cut_removed"
    assert legacy_decommission["delete_allowed"] is False
    assert legacy_decommission["targets"][0]["state"] == "removed"
    assert legacy_decommission["targets"][0]["first_cut"] is True
    assert legacy_decommission["targets"][1]["state"] == "removed"


def test_restore_authority_context_gate_legacy_passthrough_when_disabled() -> None:
    gate = RestoreAuthorityContextGate()

    result = gate.filter_for_planner(
        restore_candidates={
            "active_pdf": "files/a.pdf",
            "active_dataset": "tables/a.csv",
            "untrusted_extra": "ignored-by-normalizer",
        },
        restore_shadow_consumer_enabled=False,
        restore_shadow_consumer_mode="observe_only",
    )

    assert result.context == {
        "active_pdf": "files/a.pdf",
        "active_dataset": "tables/a.csv",
    }
    assert result.diagnostics["state"] == "legacy_passthrough"
    assert result.diagnostics["mode"] == "observe_only"
    assert result.diagnostics["candidate_keys"] == ["active_dataset", "active_pdf"]
    assert result.diagnostics["state_write_allowed"] is False
    assert result.diagnostics["takeover_allowed"] is False
    assert result.diagnostics["delete_allowed"] is False


def test_restore_authority_context_gate_filters_for_planner_in_observe_only() -> None:
    gate = RestoreAuthorityContextGate()

    result = gate.filter_for_planner(
        restore_candidates={
            "active_pdf": "files/a.pdf",
            "active_dataset": "",
            "active_result_handle_id": "result-1",
            "legacy_decision_hint": "must_not_reach_planner",
        },
        restore_shadow_consumer_enabled=True,
        restore_shadow_consumer_mode="observe_only",
    )

    assert result.context == {
        "active_pdf": "files/a.pdf",
        "active_result_handle_id": "result-1",
    }
    assert result.diagnostics["phase"] == "8I"
    assert result.diagnostics["state"] == "orchestration_filtered"
    assert result.diagnostics["candidate_keys"] == ["active_pdf", "active_result_handle_id"]
    assert result.diagnostics["filtered_keys"] == ["active_pdf", "active_result_handle_id"]
    assert "legacy_decision_hint" not in result.diagnostics["legacy_keys"]
    assert result.diagnostics["replacement_seam"] == "orchestration.restore_context.RestoreAuthorityContextGate"


def test_execution_candidate_gate_projects_legacy_execution_without_takeover() -> None:
    execution = RichLegacyExecution(
        "a",
        route="tool",
        execution_kind="direct_tool",
        tool_name="pdf_analysis",
        worker_route="pdf",
        skill_name="pdf-reading",
    )

    candidate = ExecutionCandidateGate().build_candidate(execution)

    assert candidate.diagnostics["phase"] == "8M"
    assert candidate.diagnostics["state"] == "execution_candidate_projected"
    assert candidate.diagnostics["execution_id"] == "a"
    assert candidate.diagnostics["execution_kind"] == "direct_tool"
    assert candidate.diagnostics["tool"] == "pdf_analysis"
    assert candidate.diagnostics["takeover_allowed"] is False
    assert candidate.diagnostics["delete_allowed"] is False
