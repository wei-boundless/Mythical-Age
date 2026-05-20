from __future__ import annotations

import json
from pathlib import Path

from health_system.maintenance.experiments.runner import ExperimentRunner
from health_system.maintenance.test_system.assertions import evaluate_turn_assertions
from health_system.maintenance.test_system.harness_map import build_harness_map
from health_system.maintenance.test_system.harness_records import HarnessRecordStore
from health_system.maintenance.test_system.service import TestSystemService


def _write_failed_turn(output_dir: Path) -> Path:
    turn_dir = output_dir / "artifacts" / "sixty-turn-real-user-marathon"
    turn_dir.mkdir(parents=True)
    turn_path = turn_dir / "turn-03-main.json"
    turn_path.write_text(
        json.dumps(
            {
                "turn": {
                    "session": "main",
                    "speaker": "user",
                    "content": "基于本地知识库，先告诉我 AI 治理里最常见的三类风险。",
                    "checks": ["plan.tool=search_text", "event=retrieval", "response.nonempty"],
                },
                "plan": {"tool": "search_text", "route": "rag"},
                "events": [{"event": "done", "data": {"content": ""}}],
                "runtime_loop_events": [
                    {
                        "event_id": "evt:started",
                        "task_run_id": "taskrun:turn-03",
                        "event_type": "loop_started",
                        "offset": 1,
                        "payload": {},
                    },
                    {
                        "event_id": "evt:tool",
                        "task_run_id": "taskrun:turn-03",
                        "event_type": "tool_call_requested",
                        "offset": 2,
                        "payload": {"action_request": {"payload": {"tool_name": "search_text"}}},
                    },
                    {
                        "event_id": "evt:error",
                        "task_run_id": "taskrun:turn-03",
                        "event_type": "loop_error",
                        "offset": 3,
                        "payload": {"error": "retrieval returned empty answer"},
                    },
                ],
                "latest_checkpoint": {
                    "checkpoint_id": "checkpoint:turn-03",
                    "event_offset": 3,
                    "loop_state": {"status": "running"},
                },
                "result": {
                    "index": 3,
                    "session_alias": "main",
                    "message": "基于本地知识库，先告诉我 AI 治理里最常见的三类风险。",
                    "plan_route": "rag",
                    "plan_tool": "search_text",
                    "runtime_effective_route": "rag",
                    "response_text": "",
                    "passed": False,
                    "failed_checks": ["response.nonempty (actual=)"],
                    "task_run_id": "taskrun:turn-03",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return turn_path


def test_failed_turn_can_be_promoted_to_regression_sample(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "sample-run"
    turn_path = _write_failed_turn(output_dir)
    store = HarnessRecordStore(tmp_path / "harness_records.json")
    service = TestSystemService()

    monkeypatch.setattr("health_system.maintenance.test_system.service.harness_record_store", store)
    monkeypatch.setattr(
        "health_system.maintenance.test_system.service.experiment_runner.get_run",
        lambda _run_id: {
            "run_id": "sample-run",
            "profile": "long",
            "status": "failed",
            "output_dir": str(output_dir),
            "summary": {"total": 1, "passed": 0, "failed": 1, "first_failure": "turn-03"},
        },
    )

    sample = service.create_regression_sample_from_turn("sample-run", "turn-03-main")

    assert sample["authority"] == "test_system.regression_sample"
    assert sample["source_artifact_path"] == str(turn_path)
    assert sample["contract"]["authority"] == "test_system.scenario_contract"
    assert sample["contract"]["assertions"] == ["plan.tool=search_text", "event=retrieval", "response.nonempty"]
    assert sample["contract"]["expected_tools"] == ["search_text"]
    assert sample["verification"]["status"] == "not_run"
    assert sample["evidence_packet"]["authority"] == "health_system.evidence_packet"
    assert any(item["status"] == "failed" for item in sample["assertion_summary"])
    assert "--turn" in sample["rerun_command"]

    records = service.regression_samples()
    assert records["summary"]["sample_count"] == 1

    harness_map = build_harness_map(records=store.load(), agent_report={"findings": [], "summary": {}})
    assert harness_map["summary"]["regression_sample_count"] == 1
    assert harness_map["scenario_contracts"][0]["scenario_id"] == "sixty-turn-real-user-marathon"


def test_regression_sample_rerun_uses_harness_turn_filter(monkeypatch, tmp_path: Path) -> None:
    store = HarnessRecordStore(tmp_path / "harness_records.json")
    store.create_regression_sample(
        {
            "sample_id": "regression.sixty.turn03",
            "title": "turn 03 sample",
            "source_run_id": "source-run",
            "source_turn_id": "turn-03-main",
            "source_artifact_path": str(tmp_path / "turn-03-main.json"),
            "scenario_id": "sixty-turn-real-user-marathon",
            "session_alias": "main",
            "contract": {
                "contract_id": "contract.sixty.turn03",
                "title": "turn 03",
                "scenario_id": "sixty-turn-real-user-marathon",
                "turn_id": "turn-03-main",
                "session_alias": "main",
                "user_input": "基于本地知识库。",
                "rerun_args": ["--profile", "long", "--scenario", "sixty-turn-real-user-marathon", "--turn", "turn-03"],
            },
        }
    )
    captured: dict[str, object] = {}

    def _fake_start(profile_id: str, *, scenario_ids=None, turn_refs=None):
        captured["profile_id"] = profile_id
        captured["scenario_ids"] = list(scenario_ids or [])
        captured["turn_refs"] = list(turn_refs or [])
        return {
            "run_id": "rerun-1",
            "profile": profile_id,
            "status": "running",
            "output_dir": str(tmp_path / "rerun-1"),
        }

    monkeypatch.setattr("health_system.maintenance.test_system.service.harness_record_store", store)
    monkeypatch.setattr("health_system.maintenance.test_system.service.experiment_runner.start", _fake_start)

    payload = TestSystemService().rerun_regression_sample("regression.sixty.turn03")

    assert captured == {
        "profile_id": "long_core",
        "scenario_ids": ["sixty-turn-real-user-marathon"],
        "turn_refs": ["turn-03"],
    }
    assert payload["verdict"]["status"] == "running"
    assert payload["sample"]["verification"]["run_id"] == "rerun-1"


def test_failed_turns_can_be_batch_promoted_without_duplicate_samples(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "sample-run"
    _write_failed_turn(output_dir)
    store = HarnessRecordStore(tmp_path / "harness_records.json")
    service = TestSystemService()

    monkeypatch.setattr("health_system.maintenance.test_system.service.harness_record_store", store)
    monkeypatch.setattr(
        "health_system.maintenance.test_system.service.experiment_runner.get_run",
        lambda _run_id: {
            "run_id": "sample-run",
            "profile": "long",
            "status": "failed",
            "output_dir": str(output_dir),
            "summary": {"total": 1, "passed": 0, "failed": 1, "first_failure": "turn-03"},
        },
    )

    first = service.promote_failed_turns_to_regression_samples("sample-run")
    second = service.promote_failed_turns_to_regression_samples("sample-run")

    assert first["summary"]["promoted_count"] == 1
    assert second["summary"]["promoted_count"] == 1
    samples = store.load().regression_samples
    assert len(samples) == 1
    assert samples[0].sample_id == "regression.sample_run.sixty_turn_real_user_marathon.turn_03_main"


def test_regression_sample_verdict_refresh_reads_real_run_result(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "rerun-1"
    output_dir.mkdir()
    (output_dir / "run_result.json").write_text(
        json.dumps(
            {
                "metadata": {"total": 1, "passed": 0, "failed": 1},
                "results": [{"name": "Target turn rerun", "passed": False, "summary": "turn 03 still failed"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "harness_state.json").write_text(json.dumps({"status": "failed"}, ensure_ascii=False), encoding="utf-8")
    store = HarnessRecordStore(tmp_path / "harness_records.json")
    sample = store.create_regression_sample(
        {
            "sample_id": "regression.sixty.turn03",
            "title": "turn 03 sample",
            "source_run_id": "source-run",
            "source_turn_id": "turn-03-main",
            "source_artifact_path": str(tmp_path / "turn-03-main.json"),
            "scenario_id": "sixty-turn-real-user-marathon",
            "session_alias": "main",
            "verification": {"status": "running", "run_id": "rerun-1"},
        }
    )

    monkeypatch.setattr("health_system.maintenance.test_system.service.harness_record_store", store)
    monkeypatch.setattr(
        "health_system.maintenance.test_system.service.experiment_runner.get_run",
        lambda _run_id: {
            "run_id": "rerun-1",
            "profile": "long_core",
            "status": "failed",
            "output_dir": str(output_dir),
            "summary": {"total": 1, "passed": 0, "failed": 1, "first_failure": "turn 03 still failed"},
        },
    )

    payload = TestSystemService().refresh_regression_sample_verdict(sample.sample_id)

    assert payload["verdict"]["status"] == "failed"
    assert payload["summary"]["first_failure"] == "Target turn rerun"
    assert payload["sample"]["verification"]["run_id"] == "rerun-1"
    assert any(ref.endswith("run_result.json") for ref in payload["sample"]["verification"]["artifact_refs"])


def test_experiment_runner_passes_turn_filter_to_formal_harness(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeProcess:
        pid = 9876

        def poll(self):
            return None

    def _fake_popen(cmd, cwd=None, stdout=None, stderr=None, text=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        if stdout is not None:
            stdout.write("started\n")
        return _FakeProcess()

    monkeypatch.setattr("health_system.maintenance.experiments.runner.OUTPUT_ROOT", tmp_path / "runs")
    monkeypatch.setattr("subprocess.Popen", _fake_popen)

    state = ExperimentRunner().start(
        "long_core",
        scenario_ids=["sixty-turn-real-user-marathon"],
        turn_refs=["turn-03"],
    )

    assert state["status"] == "running"
    assert "health_system.maintenance.harness.run" in captured["cmd"]
    assert "--scenario" in captured["cmd"]
    assert "--turn" in captured["cmd"]
    assert "turn-03" in captured["cmd"]


def test_scenario_contract_assertions_cover_runtime_path_and_negative_evidence() -> None:
    payload = {
        "turn": {"checks": ["plan.tool=search_text", "event=retrieval", "negative.absent_event=agent_delegation_requested"]},
        "plan": {"tool": "search_text", "route": "rag"},
        "events": [{"event": "retrieval", "data": {}}],
        "runtime_loop_events": [
            {
                "event_type": "tool_call_requested",
                "payload": {"action_request": {"payload": {"tool_name": "search_text"}}},
            }
        ],
        "result": {"plan_tool": "search_text", "response_text": "ok"},
    }

    results = evaluate_turn_assertions(
        payload,
        ["plan.tool=search_text", "event=retrieval", "event.tool=search_text", "negative.absent_event=agent_delegation_requested"],
    )

    assert [item.status for item in results] == ["passed", "passed", "passed", "passed"]


def test_long_runner_turn_filter_replays_prefix_but_only_grades_target(monkeypatch, tmp_path: Path) -> None:
    from tests.system_eval import long_runner
    from tests.system_eval.long_scenarios import LongScenario, LongScenarioTurn

    calls: list[int] = []

    def _fake_user_turn(*, turn_index, turn, **_kwargs):
        calls.append(turn_index)
        return long_runner.TurnResult(
            index=turn_index,
            session_alias=turn.session,
            session_id=f"session-{turn_index}",
            message=turn.content,
            plan_route="chat",
            plan_tool="",
            plan_mcp="",
            plan_skill="",
            subquery_count=0,
            event_types=[],
            tool_names=[],
            mcp_names=[],
            response_text="prefix failed" if turn_index == 1 else "",
            passed=False,
            failed_checks=["response.nonempty"],
        )

    def _fake_operator_turn(**_kwargs):
        return {"ok": True, "action": "noop"}

    monkeypatch.setattr(long_runner, "_execute_user_turn", _fake_user_turn)
    monkeypatch.setattr(long_runner, "_execute_operator_turn", _fake_operator_turn)
    monkeypatch.setattr(long_runner, "_cleanup_session", lambda _runtime, _session_id: True)
    monkeypatch.setattr(long_runner, "_write_long_progress", lambda **_kwargs: None)
    scenario = LongScenario(
        id="sample-scenario",
        title="Sample Scenario",
        goal="Verify target turn rerun semantics.",
        coverage=("sample",),
        turns=(
            LongScenarioTurn(session="main", speaker="user", content="prefix"),
            LongScenarioTurn(session="main", speaker="user", content="target"),
            LongScenarioTurn(session="main", speaker="user", content="after"),
        ),
    )
    result = long_runner._execute_scenario(
        client=object(),
        runtime=object(),
        scenario=scenario,
        output_dir=tmp_path,
        target_turns={2},
    )

    assert calls == [1, 2]
    assert result.status == "failed"
    assert result.details["rerun_mode"] == "target_turn_with_prefix_replay"
    assert result.details["rerun_skipped_turns"] == [3]
    assert result.details["turn_results"][0]["passed"] is True
    assert result.details["turn_results"][1]["passed"] is False
