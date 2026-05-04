from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from health_system.maintenance.harness.contracts import RunContext, RunResult, ScenarioResult, TimingSnapshot
from health_system.maintenance.harness.persistence import render_and_persist_run_result


def test_render_and_persist_run_result_includes_artifacts_in_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "run-output"
    run_result = RunResult(
        context=RunContext(
            run_id="run-1",
            profile="long",
            mode="inprocess",
            repo_root=str(tmp_path),
            backend_root=str(tmp_path / "backend"),
            frontend_root=str(tmp_path / "frontend"),
            output_dir=str(output_dir),
            generated_at="2026-04-20T12:00:00",
            python_version="3.12.0",
            langsmith_enabled=False,
        ),
        results=[
            ScenarioResult(
                name="sample-scenario",
                category="long_scenario",
                passed=True,
                status="passed",
                summary="ok",
                timing=TimingSnapshot(
                    started_at="2026-04-20T12:00:00",
                    ended_at="2026-04-20T12:00:01",
                    duration_ms=1000.0,
                    terminal_event="scenario_complete",
                ),
            )
        ],
    )

    artifact_paths = render_and_persist_run_result(output_dir=output_dir, run_result=run_result)

    report_path = output_dir / "report.md"
    report_text = report_path.read_text(encoding="utf-8")

    assert artifact_paths["report"] == str(report_path)
    assert "`run_result`" in report_text
    assert "`issues`" in report_text
    assert "`trace`" in report_text
    assert "`report`" in report_text
