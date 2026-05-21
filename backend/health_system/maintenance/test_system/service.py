from __future__ import annotations

import re
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from health_system.maintenance.experiments import experiment_runner
from health_system.maintenance.experiments.artifacts import load_run_artifacts, read_json_file, read_text_tail, summarize_run_result
from health_system.maintenance.experiments.trace_graph import list_turns as list_experiment_turns
from orchestration import summarize_runtime_loop_trace

from .assertions import evaluate_turn_assertions
from .agent import test_agent_advisor
from .case_registry import case_registry_payload
from .contracts import TestArtifactBundle, TestRunState, TestRunSummary, TestScenarioContract, TestTurn, VerificationVerdict
from .harness_map import build_harness_map
from .harness_records import harness_record_store
from .profiles import list_profiles
from .runtime_loop_probe import runtime_loop_summary_from_turn_payload
from .task_graph_health import build_task_graph_health_projection
from health_system.evidence_extractor import build_turn_artifact_evidence_packet


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

    def regression_samples(self) -> dict[str, Any]:
        samples = harness_record_store.load().regression_samples
        return {
            "authority": "test_system.regression_samples",
            "samples": [sample.to_dict() for sample in samples],
            "summary": {
                "sample_count": len(samples),
                "active_count": sum(1 for sample in samples if sample.status == "active"),
                "candidate_count": sum(1 for sample in samples if sample.status == "candidate"),
            },
        }

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

    def create_regression_sample_from_turn(self, run_id: str, turn_id: str) -> dict[str, Any]:
        state = experiment_runner.get_run(run_id)
        output_dir = Path(str(state.get("output_dir") or ""))
        path = _find_turn_path(output_dir, turn_id)
        if path is None:
            raise ValueError("Turn artifact not found")
        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            raise ValueError("Turn artifact is invalid")

        turn = dict(payload.get("turn") or {})
        result = dict(payload.get("result") or {})
        checks = tuple(str(item) for item in list(turn.get("checks") or []) if str(item).strip())
        assertion_summary = tuple(item.to_dict() for item in evaluate_turn_assertions(payload, list(checks)))
        evidence_packet = build_turn_artifact_evidence_packet(
            path,
            question="这个真实失败样本为什么失败，复跑时应关注哪些运行证据和断言？",
        )
        scenario_id = path.parent.name
        session_alias = str(result.get("session_alias") or turn.get("session") or "")
        index = _turn_index_from_artifact(path, payload)
        turn_ref = f"turn-{index:02d}" if index > 0 else path.stem
        problem = self._problem_summary_for_turn(output_dir, path.stem)
        rerun_args = ("--profile", "long", "--scenario", scenario_id, "--turn", turn_ref)
        contract = TestScenarioContract(
            contract_id=f"contract.{_slug(scenario_id)}.{_slug(path.stem)}",
            title=f"{scenario_id} / {path.stem}",
            scenario_id=scenario_id,
            turn_id=path.stem,
            session_alias=session_alias,
            user_input=str(turn.get("content") or result.get("message") or ""),
            objective="复现真实长跑 turn 的失败或质量风险，并验证修复后满足原始路径、语义和证据断言。",
            source_ref=str(path),
            profile="long",
            preconditions=_sample_preconditions(payload),
            assertions=checks,
            expected_tools=_expected_tools_from_checks(checks),
            expected_events=_expected_events_from_checks(checks),
            evidence_policy={
                "required_sources": ["turn_artifact", "runtime_loop", "assertion_result"],
                "selected_evidence_limit": 8,
                "include_negative_evidence": True,
                "semantic_guard": "不能只以 response.nonempty 作为通过标准，必须同时检查用户意图、运行路径和失败证据。",
            },
            rerun_args=rerun_args,
        )
        sample = harness_record_store.create_regression_sample(
            {
                "sample_id": f"regression.{_slug(run_id)}.{_slug(path.parent.name)}.{_slug(path.stem)}",
                "title": _regression_sample_title(scenario_id, path.stem, payload),
                "source_run_id": run_id,
                "source_turn_id": path.stem,
                "source_artifact_path": str(path),
                "scenario_id": scenario_id,
                "session_alias": session_alias,
                "failure_summary": _failure_summary(payload, assertion_summary),
                "observed": _observed_summary(payload),
                "expected": _expected_summary(checks),
                "task_run_id": _task_run_id_from_turn_artifact(path),
                "problem_node_id": str(problem.get("problem_node_id") or ""),
                "problem_node_label": str(problem.get("problem_node_label") or ""),
                "contract": contract.to_dict(),
                "assertion_summary": list(assertion_summary),
                "evidence_packet": evidence_packet,
                "rerun_command": _rerun_command_for_args(rerun_args),
                "verification": VerificationVerdict(status="not_run", reason="样本已沉淀，尚未启动真实复跑。").to_dict(),
                "tags": ["regression_sample", "long_scenario", scenario_id],
            }
        )
        return sample.to_dict()

    def promote_failed_turns_to_regression_samples(self, run_id: str) -> dict[str, Any]:
        state = experiment_runner.get_run(run_id)
        output_dir = Path(str(state.get("output_dir") or ""))
        promoted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for turn in self._list_turns(output_dir):
            if turn.status != "failed":
                skipped.append({"turn_id": turn.turn_id, "status": turn.status, "reason": "not_failed"})
                continue
            try:
                promoted.append(self.create_regression_sample_from_turn(run_id, turn.turn_id))
            except ValueError as exc:
                skipped.append({"turn_id": turn.turn_id, "status": turn.status, "reason": str(exc)})
        return {
            "authority": "test_system.regression_sample_batch_promotion",
            "run_id": run_id,
            "promoted": promoted,
            "skipped": skipped,
            "summary": {
                "promoted_count": len(promoted),
                "skipped_count": len(skipped),
            },
        }

    def rerun_regression_sample(self, sample_id: str) -> dict[str, Any]:
        book = harness_record_store.load()
        sample = next((item for item in book.regression_samples if item.sample_id == sample_id), None)
        if sample is None:
            raise ValueError("Regression sample not found")
        if not sample.scenario_id:
            raise ValueError("Regression sample has no scenario_id")
        turn_ref = _turn_ref_for_sample(sample.to_dict())
        state = experiment_runner.start("long_core", scenario_ids=[sample.scenario_id], turn_refs=[turn_ref] if turn_ref else None)
        verdict = VerificationVerdict(
            status="running",
            reason="已通过 health harness 启动目标 turn 复跑；最终结论以 run_result 和 evidence packet 为准。",
            run_id=str(state.get("run_id") or ""),
            artifact_refs=tuple(str(item) for item in [state.get("output_dir")] if str(item or "").strip()),
            checked_at=time.time(),
        )
        updated = harness_record_store.update_regression_sample_verdict(sample.sample_id, verdict)
        return {
            "authority": "test_system.regression_sample_rerun",
            "sample": updated.to_dict(),
            "run": state,
            "verdict": verdict.to_dict(),
        }

    def refresh_regression_sample_verdict(self, sample_id: str) -> dict[str, Any]:
        book = harness_record_store.load()
        sample = next((item for item in book.regression_samples if item.sample_id == sample_id), None)
        if sample is None:
            raise ValueError("Regression sample not found")
        run_id = str(sample.verification.run_id or "").strip()
        if not run_id:
            verdict = VerificationVerdict(
                status="not_run",
                reason="样本尚未启动复跑，没有可裁决的 harness run。",
                checked_at=time.time(),
            )
            updated = harness_record_store.update_regression_sample_verdict(sample.sample_id, verdict)
            return {
                "authority": "test_system.regression_sample_verdict_refresh",
                "sample": updated.to_dict(),
                "run": {},
                "verdict": verdict.to_dict(),
            }

        try:
            state = experiment_runner.get_run(run_id)
        except ValueError as exc:
            verdict = VerificationVerdict(
                status="unsupported",
                reason=f"找不到复跑 run，无法裁决：{exc}",
                run_id=run_id,
                checked_at=time.time(),
            )
            updated = harness_record_store.update_regression_sample_verdict(sample.sample_id, verdict)
            return {
                "authority": "test_system.regression_sample_verdict_refresh",
                "sample": updated.to_dict(),
                "run": {},
                "verdict": verdict.to_dict(),
            }

        output_dir = Path(str(state.get("output_dir") or ""))
        run_result = read_json_file(output_dir / "run_result.json", {})
        summary = summarize_run_result(run_result if isinstance(run_result, dict) else {})
        status = str(state.get("status") or "").lower()
        failed = int(summary.get("failed") or 0)
        total = int(summary.get("total") or 0)
        if status == "running":
            verdict_status = "running"
            reason = "复跑仍在运行，等待 harness 写出最终 run_result。"
        elif status == "passed" and failed == 0 and total > 0:
            verdict_status = "passed"
            reason = "复跑 run_result 通过，且未发现 failed scenario。"
        elif status in {"failed", "stale", "cancelled", "detached"} or failed > 0:
            verdict_status = "failed"
            reason = str(summary.get("first_failure") or state.get("stale_reason") or "复跑 run_result 未通过。")
        elif (output_dir / "run_result.json").exists() and failed == 0:
            verdict_status = "passed"
            reason = "复跑已生成 run_result，未发现 failed scenario。"
        else:
            verdict_status = "unsupported"
            reason = "复跑尚无可裁决 run_result，且 run 状态不足以判定。"

        artifact_refs = tuple(
            str(path)
            for path in (
                output_dir / "run_result.json",
                output_dir / "harness_state.json",
                output_dir / "artifact_manifest.json",
            )
            if path.exists()
        )
        verdict = VerificationVerdict(
            status=verdict_status,
            reason=reason,
            run_id=run_id,
            artifact_refs=artifact_refs,
            checked_at=time.time(),
        )
        updated = harness_record_store.update_regression_sample_verdict(sample.sample_id, verdict)
        return {
            "authority": "test_system.regression_sample_verdict_refresh",
            "sample": updated.to_dict(),
            "run": state,
            "summary": summary,
            "verdict": verdict.to_dict(),
        }

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
        harness_state = _read_dict(output_dir / "harness_state.json")
        progress_events = _read_jsonl_dicts(output_dir / "progress.jsonl")
        stuck_diagnosis = self._build_stuck_diagnosis(output_dir, state=state, harness_state=harness_state, progress_events=progress_events)
        bundle = TestArtifactBundle(
            summary=summary,
            report=str(raw.get("report") or ""),
            trace_tail=str(raw.get("trace_tail") or ""),
            log_tail=str(state.get("log_tail") or read_text_tail(output_dir / "runner.log")),
            run_result=dict(raw.get("run_result") or {}),
            issues=list(raw.get("issues") or []),
            runtime_loop=self._run_runtime_loop_rollup(output_dir),
            harness_contract=_read_dict(output_dir / "harness_contract.json"),
            harness_state=harness_state,
            artifact_manifest=_read_dict(output_dir / "artifact_manifest.json"),
            partial_result=_read_dict(output_dir / "partial_result.json"),
            progress_events=progress_events,
            stuck_diagnosis=stuck_diagnosis,
            evidence_packet=dict(stuck_diagnosis.get("evidence_packet") or {}),
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

    def get_task_graph_health(self, task_run_id: str, *, runtime_loop=None) -> dict[str, Any]:
        if runtime_loop is None:
            raise ValueError("runtime_loop is required")
        if not hasattr(runtime_loop, "get_task_graph_run_monitor"):
            raise ValueError("runtime_loop does not expose TaskGraph monitor")
        monitor = runtime_loop.get_task_graph_run_monitor(task_run_id)
        if monitor is None:
            raise ValueError("TaskGraph monitor not found")
        trace = runtime_loop.get_trace(task_run_id, include_payloads=True, include_model_messages=False)
        return build_task_graph_health_projection(
            monitor,
            trace=trace,
            question="这个任务图运行当前有哪些健康风险、恢复边界和证据？",
        )

    def _list_turns(self, output_dir: Path) -> list[TestTurn]:
        experiment_turns = list_experiment_turns(output_dir)
        result: list[TestTurn] = []
        for experiment_turn in experiment_turns:
            artifact_path = Path(str(experiment_turn.get("artifact_path") or ""))
            path = artifact_path if artifact_path.is_absolute() else Path.cwd() / artifact_path
            payload = read_json_file(path, {})
            if not isinstance(payload, dict):
                payload = {}
            turn = dict(payload.get("turn") or {})
            checks = [str(item) for item in list(turn.get("checks") or [])]
            assertions = tuple(evaluate_turn_assertions(payload, checks))
            runtime_summary = runtime_loop_summary_from_turn_payload(payload)
            failed_assertions = [item for item in assertions if item.status == "failed"]
            status = str(experiment_turn.get("status") or "unknown")
            if failed_assertions:
                status = "failed"
            result.append(
                TestTurn(
                    turn_id=str(experiment_turn.get("turn_id") or ""),
                    index=int(experiment_turn.get("index") or 0),
                    scenario=str(experiment_turn.get("scenario") or ""),
                    session_alias=str(experiment_turn.get("session_alias") or ""),
                    status=status if status in {"passed", "warning", "failed"} else "unknown",
                    summary=str(experiment_turn.get("summary") or ""),
                    artifact_path=str(experiment_turn.get("artifact_path") or ""),
                    issue_count=int(experiment_turn.get("issue_count") or len(failed_assertions)),
                    assertions=assertions,
                    runtime_loop=_runtime_summary_dataclass(runtime_summary),
                    has_trace=bool(experiment_turn.get("has_trace")),
                    has_prompt_manifest=bool(experiment_turn.get("has_prompt_manifest")),
                    has_memory_trace=bool(experiment_turn.get("has_memory_trace")),
                    problem_node_id=str(experiment_turn.get("problem_node_id") or ""),
                    problem_node_label=str(experiment_turn.get("problem_node_label") or ""),
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
            heartbeat_at=float(state.get("heartbeat_at") or 0.0),
            last_progress_at=float(state.get("last_progress_at") or 0.0),
            last_progress_event_id=str(state.get("last_progress_event_id") or ""),
            last_artifact_mtime=float(state.get("last_artifact_mtime") or 0.0),
            stale_reason=str(state.get("stale_reason") or ""),
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

    def _build_stuck_diagnosis(
        self,
        output_dir: Path,
        *,
        state: dict[str, Any],
        harness_state: dict[str, Any],
        progress_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        status = str(harness_state.get("status") or state.get("status") or "unknown")
        summary = dict(state.get("summary") or {})
        if status not in {"running", "stale", "failed"} and int(summary.get("failed") or 0) == 0:
            return {}
        last_progress = progress_events[-1] if progress_events else {}
        last_turn = self._latest_turn_artifact(output_dir)
        evidence_packet: dict[str, Any] = {}
        if last_turn is not None:
            try:
                evidence_packet = build_turn_artifact_evidence_packet(
                    last_turn,
                    question="长跑卡住或失败前最后一个 turn 的关键运行证据是什么？",
                )
            except Exception:
                evidence_packet = {}
        return {
            "authority": "test_system.stuck_diagnosis",
            "status": status,
            "reason": str(harness_state.get("stale_reason") or state.get("stale_reason") or summary.get("first_failure") or ""),
            "last_progress_event": dict(last_progress),
            "last_turn_artifact": str(last_turn or ""),
            "last_task_run_id": _task_run_id_from_turn_artifact(last_turn) if last_turn is not None else "",
            "last_heartbeat_at": float(harness_state.get("heartbeat_at") or state.get("heartbeat_at") or 0.0),
            "last_progress_at": float(harness_state.get("last_progress_at") or state.get("last_progress_at") or 0.0),
            "recovery_handles": list(evidence_packet.get("recovery_handles") or []),
            "last_checkpoint_ref": _first_handle_ref(evidence_packet, kind="checkpoint"),
            "last_coordination_checkpoint_ref": _first_handle_ref(evidence_packet, kind="coordination_checkpoint"),
            "coordination_resume_candidates": [
                dict(item)
                for item in list(evidence_packet.get("recovery_handles") or [])
                if str(dict(item).get("kind") or "") in {"coordination_checkpoint", "task_graph_node_resume_candidate"}
            ],
            "evidence_packet": evidence_packet,
        }

    def _latest_turn_artifact(self, output_dir: Path) -> Path | None:
        paths = [
            path
            for path in output_dir.glob("artifacts/**/turn-*.json")
            if path.is_file()
        ]
        if not paths:
            return None
        return max(paths, key=lambda item: item.stat().st_mtime)

    def _problem_summary_for_turn(self, output_dir: Path, turn_id: str) -> dict[str, str]:
        for turn in self._list_turns(output_dir):
            if turn.turn_id == turn_id:
                return {
                    "problem_node_id": turn.problem_node_id,
                    "problem_node_label": turn.problem_node_label,
                }
        return {}


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
        authority=str(payload.get("authority") or "runtime_monitor"),
    )


def _run_status(status: str):
    normalized = str(status or "unknown")
    return normalized if normalized in {"unknown", "running", "passed", "failed", "cancelled", "stale", "detached"} else "unknown"


def _read_dict(path: Path) -> dict[str, Any]:
    payload = read_json_file(path, {})
    return dict(payload) if isinstance(payload, dict) else {}


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = __import__("json").loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _find_turn_path(output_dir: Path, turn_id: str) -> Path | None:
    normalized = str(turn_id or "").strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized.startswith("."):
        return None
    for path in output_dir.glob("artifacts/**/turn-*.json"):
        if path.stem == normalized or path.stem.startswith(f"{normalized}-"):
            return path
    return None


def _task_run_id_from_turn_artifact(path: Path | None) -> str:
    if path is None:
        return ""
    payload = read_json_file(path, {})
    if not isinstance(payload, dict):
        return ""
    result = dict(payload.get("result") or {})
    if result.get("task_run_id"):
        return str(result.get("task_run_id") or "")
    for item in list(payload.get("events") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("event") or "") == "runtime_loop_started":
            task_run = dict(dict(item.get("data") or {}).get("task_run") or {})
            if task_run.get("task_run_id"):
                return str(task_run.get("task_run_id") or "")
        if str(item.get("event") or "") == "runtime_loop_event":
            event = dict(dict(item.get("data") or {}).get("event") or {})
            if event.get("task_run_id"):
                return str(event.get("task_run_id") or "")
    return ""


def _first_handle_ref(packet: dict[str, Any], *, kind: str) -> str:
    for item in list(packet.get("recovery_handles") or []):
        handle = dict(item or {})
        if str(handle.get("kind") or "") == kind and str(handle.get("ref") or "").strip():
            return str(handle.get("ref") or "")
    return ""


def _turn_index_from_artifact(path: Path, payload: dict[str, Any]) -> int:
    result = dict(payload.get("result") or {})
    raw = result.get("index")
    if isinstance(raw, int):
        return raw
    match = re.search(r"turn-(\d+)", path.stem)
    return int(match.group(1)) if match else 0


def _regression_sample_title(scenario_id: str, turn_id: str, payload: dict[str, Any]) -> str:
    summary = _failure_summary(payload, ())
    suffix = f"：{summary}" if summary else ""
    return f"{scenario_id} / {turn_id}{suffix}"[:180]


def _failure_summary(payload: dict[str, Any], assertion_summary: tuple[dict[str, Any], ...]) -> str:
    result = dict(payload.get("result") or {})
    failed_checks = [str(item) for item in list(result.get("failed_checks") or []) if str(item).strip()]
    if failed_checks:
        return "; ".join(failed_checks[:3])
    failed_assertions = [
        str(item.get("reason") or item.get("expression") or "")
        for item in assertion_summary
        if str(item.get("status") or "") == "failed"
    ]
    if failed_assertions:
        return "; ".join(item for item in failed_assertions[:3] if item)
    fallback = str(result.get("answer_fallback_reason") or "")
    if fallback:
        return f"answer fallback: {fallback}"
    if result.get("passed") is False:
        return "turn result marked failed"
    return "真实 turn 已沉淀为回归样本"


def _observed_summary(payload: dict[str, Any]) -> str:
    result = dict(payload.get("result") or {})
    parts = [
        f"route={result.get('plan_route') or ''}",
        f"tool={result.get('plan_tool') or ''}",
        f"effective={result.get('runtime_effective_route') or ''}",
    ]
    response = str(result.get("response_text") or "").strip()
    if response:
        parts.append(f"response={_truncate(response, 800)}")
    return "; ".join(item for item in parts if item and not item.endswith("="))


def _expected_summary(checks: tuple[str, ...]) -> str:
    if checks:
        return "必须满足原始 turn checks：" + "; ".join(checks)
    return "必须回应用户原始意图，并保留可解释的运行路径和证据。"


def _sample_preconditions(payload: dict[str, Any]) -> tuple[str, ...]:
    result = dict(payload.get("result") or {})
    turn = dict(payload.get("turn") or {})
    preconditions = [
        "使用 health_system.maintenance.harness.run 作为执行入口。",
        "复跑结果必须以 run_result、turn artifact、runtime loop evidence 为准。",
    ]
    session = str(result.get("session_alias") or turn.get("session") or "")
    if session:
        preconditions.append(f"目标 session alias: {session}")
    if result.get("active_pdf"):
        preconditions.append(f"需要恢复或重新建立 active_pdf: {result.get('active_pdf')}")
    if result.get("active_dataset"):
        preconditions.append(f"需要恢复或重新建立 active_dataset: {result.get('active_dataset')}")
    if result.get("used_task_summary_refs") or result.get("followup_task_ids"):
        preconditions.append("该样本依赖前序任务摘要或 follow-up 目标，最小单轮复跑可能需要 prefix replay 才能完全复现。")
    return tuple(preconditions)


def _expected_tools_from_checks(checks: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for check in checks:
        if check.startswith("plan.tool=") or check.startswith("event.tool="):
            value = check.split("=", 1)[1].strip()
            if value and value not in result:
                result.append(value)
    return tuple(result)


def _expected_events_from_checks(checks: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for check in checks:
        if check.startswith("event=") or check.startswith("event.tool="):
            value = check.split("=", 1)[1].strip()
            if value and value not in result:
                result.append(value)
    return tuple(result)


def _rerun_command_for_args(args: tuple[str, ...]) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "health_system.maintenance.harness.run",
        *args,
        "--output-dir",
        "output/test_runs/<new-run-id>",
    )


def _turn_ref_for_sample(sample: dict[str, Any]) -> str:
    contract = dict(sample.get("contract") or {})
    rerun_args = [str(item) for item in list(contract.get("rerun_args") or sample.get("rerun_command") or [])]
    for index, item in enumerate(rerun_args):
        if item == "--turn" and index + 1 < len(rerun_args):
            return str(rerun_args[index + 1])
        if item.startswith("--turn="):
            return item.split("=", 1)[1]
    source_turn_id = str(sample.get("source_turn_id") or "")
    match = re.search(r"turn-(\d+)", source_turn_id)
    return f"turn-{int(match.group(1)):02d}" if match else source_turn_id


def _slug(value: str) -> str:
    chars: list[str] = []
    for char in str(value or "").lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("_")
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "item"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _profiles_for_scenario_sets(scenario_sets: list[str]) -> list[str]:
    profiles: list[str] = []
    if "core" in scenario_sets:
        profiles.append("long_core")
    if "task_acceptance" in scenario_sets:
        profiles.append("task_acceptance")
    if "sandbox" in scenario_sets:
        profiles.append("sandbox")
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
