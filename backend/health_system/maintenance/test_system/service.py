from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from health_system.maintenance.experiments import experiment_runner
from health_system.maintenance.experiments.artifacts import load_run_artifacts, read_json_file, read_text_tail, summarize_run_result
from health_system.maintenance.experiments.trace_graph import list_turns as list_legacy_turns
from orchestration import summarize_runtime_loop_trace

from .assertions import evaluate_turn_assertions
from .agent import test_agent_advisor
from .case_registry import case_registry_payload
from .contracts import TestArtifactBundle, TestRunState, TestRunSummary, TestTurn
from .harness_map import build_harness_map
from .harness_records import harness_record_store
from .profiles import list_profiles
from .runtime_loop_probe import runtime_loop_summary_from_turn_payload


class TestSystemService:
    """Backend facade for the rebuilt test system.

    The harness still owns process execution. The test system owns test
    semantics, assertions, artifact normalization, and orchestration monitor
    projection.
    """

    def profiles(self) -> list[dict[str, Any]]:
        return [profile.to_dict() for profile in list_profiles()]

    def cases(self) -> dict[str, Any]:
        return case_registry_payload()

    def agent_report(self) -> dict[str, Any]:
        return test_agent_advisor.build_report()

    def harness_records(self) -> dict[str, Any]:
        return harness_record_store.load().to_dict()

    def case_templates(self) -> dict[str, Any]:
        return {
            "authority": "test_system.case_templates",
            "templates": [item.to_dict() for item in harness_record_store.templates()],
        }

    def long_scenarios(self) -> dict[str, Any]:
        try:
            from tests.conversation_scenario_catalog import SCENARIOS as catalog_scenarios
            from tests.system_eval.long_scenarios import SCENARIO_SETS, scenario_map
        except ImportError:
            return {"authority": "test_system.long_scenarios", "scenarios": [], "scenario_sets": {}}

        runner_scenarios = scenario_map()
        scenario_sets = {key: list(value) for key, value in SCENARIO_SETS.items()}
        set_index: dict[str, list[str]] = {}
        for set_name, scenario_ids in scenario_sets.items():
            for scenario_id in scenario_ids:
                set_index.setdefault(scenario_id, []).append(set_name)

        rows: list[dict[str, Any]] = []
        for scenario in catalog_scenarios:
            runner = runner_scenarios.get(scenario.id)
            turns = runner.turns if runner is not None else scenario.turns
            profile_refs = _profiles_for_scenario_sets(set_index.get(scenario.id, []))
            rows.append(
                {
                    "scenario_id": scenario.id,
                    "title": scenario.title,
                    "category": scenario.category,
                    "execution_mode": scenario.execution_mode,
                    "goal": scenario.goal,
                    "coverage": list(scenario.coverage),
                    "assertions": list(scenario.assertions),
                    "failure_modes": list(scenario.failure_modes),
                    "expected_artifacts": list(scenario.expected_artifacts),
                    "related_regressions": list(scenario.related_regressions),
                    "scenario_sets": set_index.get(scenario.id, []),
                    "profile_refs": profile_refs,
                    "turns": [_long_scenario_turn(index, turn) for index, turn in enumerate(turns, start=1)],
                    "stress_profile": _dataclass_payload(scenario.stress_profile),
                    "runner_source": "tests.system_eval.long_scenarios" if runner is not None else "tests.conversation_scenario_catalog",
                }
            )
        return {
            "authority": "test_system.long_scenarios",
            "scenario_sets": scenario_sets,
            "scenarios": rows,
        }

    def harness_map(self) -> dict[str, Any]:
        return build_harness_map(
            records=harness_record_store.load(),
            agent_report=self.agent_report(),
        )

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        return harness_record_store.create_issue(payload).to_dict()

    def create_case_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return harness_record_store.create_case_draft(payload).to_dict()

    def create_managed_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        return harness_record_store.create_managed_case(payload).to_dict()

    def delete_managed_case(self, case_id: str) -> dict[str, Any]:
        deleted = harness_record_store.delete_managed_case(case_id)
        if not deleted:
            raise ValueError("Managed test case not found")
        return {"ok": True, "case_id": case_id, "authority": "test_system.managed_cases"}

    def list_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self._state_from_experiment_state(state).to_dict()
            for state in experiment_runner.list_runs(limit=limit)
        ]

    def start(self, profile_id: str, *, scenario_ids: list[str] | None = None) -> dict[str, Any]:
        return self._state_from_experiment_state(
            experiment_runner.start(profile_id, scenario_ids=scenario_ids)
        ).to_dict()

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._state_from_experiment_state(experiment_runner.get_run(run_id)).to_dict()

    def cancel(self, run_id: str) -> dict[str, Any]:
        return self._state_from_experiment_state(experiment_runner.cancel(run_id)).to_dict()

    def get_artifacts(self, run_id: str) -> dict[str, Any]:
        state = experiment_runner.get_run(run_id)
        output_dir = Path(str(state.get("output_dir") or ""))
        raw = load_run_artifacts(output_dir)
        summary = _summary_from_raw(raw.get("run_result") if isinstance(raw, dict) else {})
        bundle = TestArtifactBundle(
            summary=summary,
            report=str(raw.get("report") or ""),
            trace_tail=str(raw.get("trace_tail") or ""),
            log_tail=str(state.get("log_tail") or read_text_tail(output_dir / "runner.log")),
            run_result=dict(raw.get("run_result") or {}),
            issues=list(raw.get("issues") or []),
            runtime_loop=self._run_runtime_loop_rollup(output_dir),
        )
        return bundle.to_dict()

    def get_turns(self, run_id: str) -> list[dict[str, Any]]:
        state = experiment_runner.get_run(run_id)
        output_dir = Path(str(state.get("output_dir") or ""))
        return [turn.to_dict() for turn in self._list_turns(output_dir)]

    def get_turn_runtime_loop(self, run_id: str, turn_id: str) -> dict[str, Any]:
        state = experiment_runner.get_run(run_id)
        output_dir = Path(str(state.get("output_dir") or ""))
        path = _find_turn_path(output_dir, turn_id)
        if path is None:
            raise ValueError("Turn artifact not found")
        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            raise ValueError("Turn artifact is invalid")
        return runtime_loop_summary_from_turn_payload(payload)

    def get_task_run_monitor(self, task_run_id: str, *, runtime_loop=None) -> dict[str, Any]:
        if runtime_loop is None:
            raise ValueError("runtime_loop is required")
        trace = runtime_loop.get_trace(task_run_id, include_payloads=True, include_model_messages=False)
        if trace is None:
            raise ValueError("TaskRun trace not found")
        return summarize_runtime_loop_trace(trace)

    def _list_turns(self, output_dir: Path) -> list[TestTurn]:
        legacy_turns = list_legacy_turns(output_dir)
        result: list[TestTurn] = []
        for legacy in legacy_turns:
            artifact_path = Path(str(legacy.get("artifact_path") or ""))
            path = artifact_path if artifact_path.is_absolute() else Path.cwd() / artifact_path
            payload = read_json_file(path, {})
            if not isinstance(payload, dict):
                payload = {}
            turn = dict(payload.get("turn") or {})
            checks = [str(item) for item in list(turn.get("checks") or [])]
            assertions = tuple(evaluate_turn_assertions(payload, checks))
            runtime_summary = runtime_loop_summary_from_turn_payload(payload)
            failed_assertions = [item for item in assertions if item.status == "failed"]
            status = str(legacy.get("status") or "unknown")
            if failed_assertions:
                status = "failed"
            result.append(
                TestTurn(
                    turn_id=str(legacy.get("turn_id") or ""),
                    index=int(legacy.get("index") or 0),
                    scenario=str(legacy.get("scenario") or ""),
                    session_alias=str(legacy.get("session_alias") or ""),
                    status=status if status in {"passed", "warning", "failed"} else "unknown",
                    summary=str(legacy.get("summary") or ""),
                    artifact_path=str(legacy.get("artifact_path") or ""),
                    issue_count=int(legacy.get("issue_count") or len(failed_assertions)),
                    assertions=assertions,
                    runtime_loop=_runtime_summary_dataclass(runtime_summary),
                    has_trace=bool(legacy.get("has_trace")),
                    has_prompt_manifest=bool(legacy.get("has_prompt_manifest")),
                    has_memory_trace=bool(legacy.get("has_memory_trace")),
                    problem_node_id=str(legacy.get("problem_node_id") or ""),
                    problem_node_label=str(legacy.get("problem_node_label") or ""),
                )
            )
        return result

    def _state_from_experiment_state(self, state: dict[str, Any]) -> TestRunState:
        summary = _summary_from_raw_summary(dict(state.get("summary") or {}))
        return TestRunState(
            run_id=str(state.get("run_id") or ""),
            profile=str(state.get("profile") or ""),
            status=_run_status(str(state.get("status") or "")),
            command=tuple(str(item) for item in list(state.get("command") or [])),
            output_dir=str(state.get("output_dir") or ""),
            log_path=str(state.get("log_path") or ""),
            started_at=float(state.get("started_at") or 0.0),
            ended_at=float(state.get("ended_at") or 0.0),
            duration_ms=float(state.get("duration_ms") or 0.0),
            returncode=state.get("returncode") if isinstance(state.get("returncode"), int) else None,
            pid=state.get("pid") if isinstance(state.get("pid"), int) else None,
            summary=summary,
            log_tail=str(state.get("log_tail") or ""),
        )

    def _run_runtime_loop_rollup(self, output_dir: Path) -> dict[str, Any]:
        turns = self._list_turns(output_dir)
        loop_summaries = [turn.runtime_loop.to_dict() for turn in turns if turn.runtime_loop.event_count > 0]
        return {
            "turn_count": len(turns),
            "runtime_loop_count": len(loop_summaries),
            "failed_runtime_loop_count": sum(1 for item in loop_summaries if item.get("status") not in {"completed"}),
            "tool_call_count": sum(int(dict(item.get("tools") or {}).get("call_count") or 0) for item in loop_summaries),
            "tool_result_count": sum(int(dict(item.get("tools") or {}).get("result_count") or 0) for item in loop_summaries),
            "assistant_commit_count": sum(
                1 for item in loop_summaries if bool(dict(item.get("commits") or {}).get("assistant_session_write_applied"))
            ),
            "memory_commit_count": sum(
                1 for item in loop_summaries if bool(dict(item.get("memory") or {}).get("memory_write_allowed"))
            ),
            "authority": "test_system.runtime_loop_rollup",
        }


def _summary_from_raw(run_result: Any) -> TestRunSummary:
    return _summary_from_raw_summary(summarize_run_result(run_result if isinstance(run_result, dict) else {}))


def _summary_from_raw_summary(payload: dict[str, Any]) -> TestRunSummary:
    return TestRunSummary(
        total=int(payload.get("total") or 0),
        passed=int(payload.get("passed") or 0),
        failed=int(payload.get("failed") or 0),
        warning=int(payload.get("warning") or 0),
        first_failure=str(payload.get("first_failure") or ""),
    )


def _runtime_summary_dataclass(payload: dict[str, Any]):
    from .contracts import RuntimeLoopMonitorSummary

    return RuntimeLoopMonitorSummary(
        task_run_id=str(payload.get("task_run_id") or ""),
        status=str(payload.get("status") or "unknown"),
        terminal_reason=str(payload.get("terminal_reason") or ""),
        event_count=int(payload.get("event_count") or 0),
        latest_event_type=str(payload.get("latest_event_type") or ""),
        event_type_counts=dict(payload.get("event_type_counts") or {}),
        operation_gate=dict(payload.get("operation_gate") or {}),
        tools=dict(payload.get("tools") or {}),
        commits=dict(payload.get("commits") or {}),
        memory=dict(payload.get("memory") or {}),
        checkpoints=dict(payload.get("checkpoints") or {}),
        stages=list(payload.get("stages") or []),
        authority=str(payload.get("authority") or "orchestration.runtime_loop_monitor"),
    )


def _run_status(status: str):
    normalized = str(status or "unknown")
    return normalized if normalized in {"unknown", "running", "passed", "failed", "cancelled"} else "unknown"


def _find_turn_path(output_dir: Path, turn_id: str) -> Path | None:
    normalized = str(turn_id or "").strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized.startswith("."):
        return None
    for path in output_dir.glob("artifacts/**/turn-*.json"):
        if path.stem == normalized:
            return path
    return None


def _profiles_for_scenario_sets(scenario_sets: list[str]) -> list[str]:
    profiles: list[str] = []
    if "core" in scenario_sets:
        profiles.append("long_core")
    if "batches" in scenario_sets or "extended" in scenario_sets:
        profiles.append("long_batches")
    if "mega" in scenario_sets:
        profiles.append("marathon")
    return profiles or ["long_core"]


def _long_scenario_turn(index: int, turn: Any) -> dict[str, Any]:
    speaker = str(getattr(turn, "speaker", "user") or "user")
    session = str(getattr(turn, "session", "") or "")
    action = getattr(turn, "action", None)
    content = str(getattr(turn, "content", "") or "")
    checks = [str(item) for item in list(getattr(turn, "checks", None) or getattr(turn, "checkpoints", None) or [])]
    params = getattr(turn, "params", None)
    return {
        "turn_id": f"turn-{index}",
        "index": index,
        "session": session,
        "speaker": speaker,
        "content": content or (str(action) if action else ""),
        "action": str(action or ""),
        "params": dict(params or {}) if isinstance(params, dict) else {},
        "checks": checks,
    }


def _dataclass_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return dict(asdict(value))
    return dict(value) if isinstance(value, dict) else None


test_system_service = TestSystemService()
