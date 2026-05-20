from __future__ import annotations

import json
from pathlib import Path

from health_system.maintenance.harness.run import main as harness_main
from health_system.maintenance.experiments.runner import ExperimentRunner
from health_system.maintenance.test_system.service import TestSystemService
from health_system.verification_service import HealthVerificationService


def test_long_profile_harness_resolves_backend_root(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run(cmd, cwd=None, check=False):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["check"] = check
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setattr("sys.argv", ["run.py", "--profile", "long"])

    assert harness_main() == 0
    assert str(captured["cwd"]).endswith("backend")
    assert any("backend/tests/system_eval/long_runner.py" in str(item).replace("\\", "/") for item in captured["cmd"])


def test_harness_wrapper_writes_run_state_manifest_and_partial_result(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "harness-run"
    captured: dict[str, object] = {}

    def _fake_run(cmd, cwd=None, check=False):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["check"] = check
        (output_dir / "runner.log").write_text("simulated subprocess failure", encoding="utf-8")
        return type("Result", (), {"returncode": 7})()

    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["run.py", "--profile", "long", "--scenario", "sixty-turn-real-user-marathon", "--output-dir", str(output_dir)],
    )

    assert harness_main() == 7

    contract = json.loads((output_dir / "harness_contract.json").read_text(encoding="utf-8"))
    state = json.loads((output_dir / "harness_state.json").read_text(encoding="utf-8"))
    partial = json.loads((output_dir / "partial_result.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    run_result = json.loads((output_dir / "run_result.json").read_text(encoding="utf-8"))
    progress_lines = [
        json.loads(line)
        for line in (output_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert contract["authority"] == "health_system.harness_run_contract"
    assert contract["profile"] == "long"
    assert contract["scenario_refs"] == ["sixty-turn-real-user-marathon"]
    assert state["authority"] == "health_system.harness_run_state"
    assert state["status"] == "failed"
    assert state["returncode"] == 7
    assert partial["authority"] == "health_system.harness_partial_result"
    assert partial["failed_scenarios"] == 1
    assert manifest["authority"] == "health_system.harness_artifact_manifest"
    assert any(item["name"] == "run_result.json" and item["present"] for item in manifest["artifacts"])
    assert [item["event_type"] for item in progress_lines] == ["started", "finished"]
    assert run_result["metadata"]["failed"] == 1
    assert run_result["results"][0]["details"]["fallback_result"] is True
    assert "--output-dir" in captured["cmd"]


def test_experiment_runner_uses_formal_health_harness_module(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeProcess:
        pid = 4321

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

    runner = ExperimentRunner()
    state = runner.start("marathon")

    assert "health_system.maintenance.harness.run" in captured["cmd"]
    assert "harness.run" not in captured["cmd"]
    assert state["status"] == "running"


def test_verification_service_uses_harness_artifact_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    (output_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "authority": "health_system.harness_artifact_manifest",
                "created_at": 42.0,
                "artifacts": [
                    {
                        "name": "harness_state.json",
                        "artifact_type": "state",
                        "path": str(output_dir / "harness_state.json"),
                        "producer": "health_system.maintenance.harness",
                        "required": True,
                        "present": True,
                        "checksum": "abc",
                        "size_bytes": 12,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run = HealthVerificationService(tmp_path).record_verification_run(
        {
            "run_id": "manifest-backed",
            "profile": "functional",
            "status": "passed",
            "output_dir": str(output_dir),
            "summary": {"total": 1, "passed": 1, "failed": 0},
        }
    )

    assert run.artifact_refs == ("run/harness_state.json",)


def test_test_system_artifacts_include_stuck_diagnosis_and_evidence(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "stuck-run"
    turn_dir = output_dir / "artifacts" / "sixty-turn-real-user-marathon"
    turn_dir.mkdir(parents=True)
    turn_path = turn_dir / "turn-18-main.json"
    turn_path.write_text(
        json.dumps(
            {
                "result": {
                    "task_run_id": "taskrun:stuck-turn-18",
                    "response_text": "partial answer",
                    "passed": False,
                    "failed_checks": ["response.nonempty"],
                },
                "runtime_loop_events": [
                    {
                        "event_id": "evt:tool",
                        "task_run_id": "taskrun:stuck-turn-18",
                        "event_type": "tool_call_requested",
                        "offset": 1,
                        "payload": {
                            "action_request": {
                                "payload": {"tool_name": "search_text"}
                            }
                        },
                    },
                    {
                        "event_id": "evt:error",
                        "task_run_id": "taskrun:stuck-turn-18",
                        "event_type": "loop_error",
                        "offset": 2,
                        "payload": {"error": "model timeout"},
                    },
                ],
                "latest_checkpoint": {
                    "checkpoint_id": "checkpoint:turn-18",
                    "event_offset": 2,
                    "loop_state": {"status": "running"},
                },
                "coordination_runs": [
                    {
                        "coordination_run_id": "coordrun:turn-18",
                        "graph_ref": "graph:marathon",
                        "status": "running",
                        "latest_checkpoint_ref": "coordchk:turn-18",
                        "diagnostics": {
                            "coordination_flow": {"current_stage_id": "rag_recall"},
                            "task_graph_scheduler_state": {
                                "failed_nodes": ["rag_search"],
                                "node_statuses": {"rag_search": {"status": "failed"}},
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
                "run_id": "stuck-run",
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
                "run_id": "stuck-run",
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
    (output_dir / "run_result.json").write_text(
        json.dumps({"metadata": {"total": 1, "passed": 0, "failed": 1}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "health_system.maintenance.test_system.service.experiment_runner.get_run",
        lambda _run_id: {
            "run_id": "stuck-run",
            "profile": "long",
            "status": "failed",
            "output_dir": str(output_dir),
            "log_path": str(output_dir / "runner.log"),
            "summary": {"total": 1, "passed": 0, "failed": 1, "first_failure": "turn-18"},
        },
    )

    payload = TestSystemService().get_artifacts("stuck-run")

    assert payload["stuck_diagnosis"]["authority"] == "test_system.stuck_diagnosis"
    assert payload["stuck_diagnosis"]["last_task_run_id"] == "taskrun:stuck-turn-18"
    assert payload["stuck_diagnosis"]["last_checkpoint_ref"] == "checkpoint:turn-18"
    assert payload["stuck_diagnosis"]["last_coordination_checkpoint_ref"] == "coordchk:turn-18"
    assert any(item["kind"] == "task_graph_node_resume_candidate" for item in payload["stuck_diagnosis"]["recovery_handles"])
    assert payload["evidence_packet"]["authority"] == "health_system.evidence_packet"
    assert payload["evidence_packet"]["selected_evidence"]
