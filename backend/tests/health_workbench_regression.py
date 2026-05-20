from __future__ import annotations

import asyncio
import json

from api import health_workbench
from health_system.models import VerificationRun
from health_system.store import HealthStore
from health_system.maintenance.test_system.harness_records import HarnessRecordStore
from health_system.workbench import HealthWorkbenchBuilder


def test_health_workbench_projects_user_task_overview(tmp_path):
    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert payload["authority"] == "health_system.workbench"
    assert set(payload["summary"]) >= {
        "inbox_count",
        "open_issue_count",
        "verification_resource_count",
        "evidence_gap_count",
        "failed_run_count",
        "feature_count",
    }
    assert isinstance(payload["inbox_items"], list)
    assert isinstance(payload["features"], list)
    assert isinstance(payload["verification_resources"], list)
    assert payload["source_refs"]["verification_resources"] == "health_system.verification_resources"
    assert payload["source_refs"]["gate_projection"] == "health_system.gate_projection"
    assert payload["recommended_actions"]


def test_health_workbench_inbox_items_have_navigation_contract(tmp_path):
    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert payload["inbox_items"]
    first_item = payload["inbox_items"][0]
    assert first_item["subject_type"] in {"health_issue", "verification_run"}
    assert first_item["subject_id"]
    assert first_item["primary_action"]
    assert first_item["evidence_state"] in {"linked", "missing"}


def test_health_workbench_uses_formal_verification_and_gate_objects(tmp_path):
    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert all(item.get("authority") != "test_system.harness_map" for item in payload.get("features", []))
    assert isinstance(payload["recent_runs"], list)
    if payload["recent_runs"]:
        assert payload["recent_runs"][0]["authority"] == "health_system.verification_run"


def test_health_workbench_projects_failure_chain_evidence_and_recovery_inboxes(tmp_path):
    output_dir = tmp_path / "output" / "test_runs" / "failed-run"
    turn_dir = output_dir / "artifacts" / "sixty-turn-real-user-marathon"
    turn_dir.mkdir(parents=True)
    turn_path = turn_dir / "turn-18-main.json"
    turn_path.write_text(
        json.dumps(
            {
                "result": {"task_run_id": "taskrun:wb:turn-18", "response_text": "partial", "passed": False},
                "runtime_loop_events": [
                    {
                        "event_id": "evt:wb:tool",
                        "task_run_id": "taskrun:wb:turn-18",
                        "event_type": "tool_call_requested",
                        "offset": 1,
                        "payload": {"action_request": {"payload": {"tool_name": "search_text"}}},
                    },
                    {
                        "event_id": "evt:wb:error",
                        "task_run_id": "taskrun:wb:turn-18",
                        "event_type": "loop_error",
                        "offset": 2,
                        "payload": {"error": "timeout"},
                    },
                    {
                        "event_id": "evt:wb:checkpoint",
                        "task_run_id": "taskrun:wb:turn-18",
                        "event_type": "checkpoint_written",
                        "offset": 3,
                        "payload": {"checkpoint_id": "checkpoint:wb", "event_offset": 3, "loop_state": {"status": "running"}},
                    },
                ],
                "coordination_runs": [
                    {
                        "coordination_run_id": "coordrun:wb",
                        "graph_ref": "graph:wb",
                        "status": "running",
                        "latest_checkpoint_ref": "coordchk:wb",
                        "diagnostics": {
                            "coordination_flow": {"current_stage_id": "search"},
                            "task_graph_scheduler_state": {
                                "node_statuses": {"search": {"status": "blocked"}},
                            },
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "harness_state.json").write_text(
        json.dumps(
            {
                "authority": "health_system.harness_run_state",
                "run_id": "failed-run",
                "profile": "long",
                "status": "failed",
                "heartbeat_at": 100.0,
                "last_progress_at": 99.0,
                "last_progress_event_id": "progress:turn-18",
                "stale_reason": "harness heartbeat stale",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "progress.jsonl").write_text(
        json.dumps(
            {
                "event_id": "progress:turn-18",
                "event_type": "turn_completed",
                "run_id": "failed-run",
                "status": "failed",
                "scenario_ref": "sixty-turn-real-user-marathon",
                "turn_ref": "turn-18",
                "artifact_ref": str(turn_path),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    HealthStore(tmp_path).upsert_verification_run(
        VerificationRun(
            verification_run_id="health-verify:failed-run",
            profile_id="marathon",
            status="failed",
            source_run_ref="failed-run",
            output_dir=str(output_dir),
            summary={"total": 1, "passed": 0, "failed": 1, "first_failure": "turn-18"},
            started_at=100.0,
            ended_at=120.0,
        )
    )

    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert payload["summary"]["diagnosis_inbox_count"] >= 1
    assert payload["summary"]["recovery_inbox_count"] >= 1
    assert payload["summary"]["failure_chain_count"] >= 1
    assert payload["summary"]["evidence_packet_count"] >= 1
    assert payload["diagnosis_inbox"]
    assert any(item["handle_kind"] == "coordination_checkpoint" for item in payload["recovery_inbox"])
    assert payload["failure_chains"][0]["last_task_run_id"] == "taskrun:wb:turn-18"
    assert payload["failure_chains"][0]["last_coordination_checkpoint_ref"] == "coordchk:wb"
    assert payload["evidence_packets"][0]["authority"] == "health_system.evidence_packet"


def test_health_workbench_projects_regression_samples_from_existing_harness_records(tmp_path):
    store = HarnessRecordStore(tmp_path / "storage" / "health_system" / "maintenance" / "test_system" / "harness_records.json")
    store.create_regression_sample(
        {
            "sample_id": "regression.sixty.turn03",
            "title": "六十轮 turn 03 RAG 失败样本",
            "source_run_id": "run:source",
            "source_turn_id": "turn-03-main",
            "source_artifact_path": str(tmp_path / "turn-03-main.json"),
            "scenario_id": "sixty-turn-real-user-marathon",
            "session_alias": "main",
            "failure_summary": "RAG turn returned empty answer",
            "task_run_id": "taskrun:sample:turn-03",
            "problem_node_id": "retrieval",
            "problem_node_label": "检索服务",
            "contract": {
                "contract_id": "contract.sixty.turn03",
                "title": "turn 03 RAG contract",
                "scenario_id": "sixty-turn-real-user-marathon",
                "turn_id": "turn-03-main",
                "session_alias": "main",
                "user_input": "基于本地知识库，告诉我 AI 治理风险。",
                "assertions": ["plan.tool=search_text", "event=retrieval", "response.nonempty"],
                "expected_tools": ["search_text"],
                "rerun_args": ["--profile", "long", "--scenario", "sixty-turn-real-user-marathon", "--turn", "turn-03"],
            },
            "evidence_packet": {
                "authority": "health_system.evidence_packet",
                "packet_id": "packet:sample",
                "question": "为什么 turn 03 失败？",
                "summary": "search_text 被调用但回答为空。",
                "selected_evidence": [{"candidate_id": "evcand:sample", "summary": "tool=search_text"}],
                "recovery_handles": [],
                "test_handles": [],
            },
            "rerun_command": ["python", "-m", "health_system.maintenance.harness.run", "--profile", "long", "--scenario", "sixty-turn-real-user-marathon", "--turn", "turn-03"],
        }
    )

    payload = HealthWorkbenchBuilder(tmp_path).build_overview()

    assert payload["summary"]["regression_sample_count"] == 1
    assert payload["summary"]["scenario_contract_count"] == 1
    assert payload["summary"]["pending_regression_verification_count"] == 1
    assert payload["summary"]["regression_sample_inbox_count"] == 1
    assert payload["test_governance"]["authority"] == "health_system.workbench.test_governance_projection"
    assert payload["regression_sample_inbox"][0]["sample_id"] == "regression.sixty.turn03"
    assert payload["regression_sample_inbox"][0]["evidence_state"] == "packet"
    assert payload["regression_sample_inbox"][0]["metadata"]["expected_tools"] == ["search_text"]
    assert any(item.get("packet_id") == "packet:sample" for item in payload["evidence_packets"])


def test_health_workbench_projection_endpoints(monkeypatch, tmp_path):
    class _Runtime:
        base_dir = tmp_path
        settings = None

    store = HarnessRecordStore(tmp_path / "storage" / "health_system" / "maintenance" / "test_system" / "harness_records.json")
    store.create_regression_sample(
        {
            "sample_id": "regression.endpoint.sample",
            "title": "endpoint sample",
            "source_run_id": "run:endpoint",
            "source_turn_id": "turn-01-main",
            "source_artifact_path": str(tmp_path / "turn-01-main.json"),
            "scenario_id": "endpoint-scenario",
            "session_alias": "main",
            "contract": {
                "contract_id": "contract.endpoint.sample",
                "title": "endpoint contract",
                "scenario_id": "endpoint-scenario",
                "turn_id": "turn-01-main",
                "session_alias": "main",
                "user_input": "hello",
            },
        }
    )
    monkeypatch.setattr("api.health_workbench.require_runtime", lambda: _Runtime())

    evidence = asyncio.run(health_workbench.health_workbench_evidence_packets())
    diagnosis = asyncio.run(health_workbench.health_workbench_diagnosis_inbox())
    recovery = asyncio.run(health_workbench.health_workbench_recovery_inbox())
    samples = asyncio.run(health_workbench.health_workbench_regression_samples())

    assert evidence["authority"] == "health_system.workbench.evidence_packets"
    assert diagnosis["authority"] == "health_system.workbench.diagnosis_inbox"
    assert recovery["authority"] == "health_system.workbench.recovery_inbox"
    assert samples["authority"] == "health_system.workbench.regression_samples"
    assert samples["summary"]["regression_sample_count"] == 1
    assert samples["scenario_contracts"][0]["contract_id"] == "contract.endpoint.sample"
