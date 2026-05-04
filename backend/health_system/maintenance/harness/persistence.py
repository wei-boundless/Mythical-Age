from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import RunResult


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _planned_artifact_paths(
    *,
    output_dir: Path,
    include_report: bool,
    extra_files: dict[str, Any] | None = None,
) -> dict[str, str]:
    artifact_paths = {
        "run_result": str(output_dir / "run_result.json"),
        "issues": str(output_dir / "issues.json"),
        "trace": str(output_dir / "trace.jsonl"),
    }
    if include_report:
        artifact_paths["report"] = str(output_dir / "report.md")
    for name in dict(extra_files or {}):
        artifact_paths[name] = str(output_dir / name)
    return artifact_paths


def persist_run_result(
    *,
    output_dir: Path,
    run_result: RunResult,
    report_markdown: str = "",
    extra_files: dict[str, Any] | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_result_path = output_dir / "run_result.json"
    issues_path = output_dir / "issues.json"
    report_path = output_dir / "report.md"
    trace_path = output_dir / "trace.jsonl"
    artifact_paths = _planned_artifact_paths(
        output_dir=output_dir,
        include_report=bool(report_markdown),
        extra_files=extra_files,
    )
    run_result.artifacts.update(artifact_paths)

    _atomic_write_text(run_result_path, json.dumps(run_result.to_dict(), ensure_ascii=False, indent=2))
    _atomic_write_text(
        issues_path,
        json.dumps([issue.to_dict() for issue in run_result.issues], ensure_ascii=False, indent=2),
    )
    trace_lines = [json.dumps(trace.to_dict(), ensure_ascii=False) for trace in run_result.traces]
    _atomic_write_text(trace_path, "\n".join(trace_lines) + ("\n" if trace_lines else ""))
    if report_markdown:
        _atomic_write_text(report_path, report_markdown)

    for name, payload in dict(extra_files or {}).items():
        extra_path = output_dir / name
        if isinstance(payload, str):
            _atomic_write_text(extra_path, payload)
        else:
            _atomic_write_text(extra_path, json.dumps(payload, ensure_ascii=False, indent=2))

    _atomic_write_text(run_result_path, json.dumps(run_result.to_dict(), ensure_ascii=False, indent=2))
    return artifact_paths


def render_and_persist_run_result(
    *,
    output_dir: Path,
    run_result: RunResult,
    extra_files: dict[str, Any] | None = None,
) -> dict[str, str]:
    from .reporter import render_markdown

    planned = _planned_artifact_paths(
        output_dir=output_dir,
        include_report=True,
        extra_files=extra_files,
    )
    run_result.artifacts.update(planned)
    report_markdown = render_markdown(run_result)
    return persist_run_result(
        output_dir=output_dir,
        run_result=run_result,
        report_markdown=report_markdown,
        extra_files=extra_files,
    )
