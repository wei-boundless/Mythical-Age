from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .contracts import (
    HarnessArtifactManifest,
    HarnessArtifactRecord,
    HarnessPartialResult,
    HarnessProgressEvent,
    HarnessRunContract,
    HarnessRunState,
    RunResult,
)


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


def write_harness_run_contract(*, output_dir: Path, contract: HarnessRunContract) -> Path:
    path = output_dir / "harness_contract.json"
    _atomic_write_text(path, json.dumps(contract.to_dict(), ensure_ascii=False, indent=2))
    return path


def write_harness_run_state(*, output_dir: Path, state: HarnessRunState) -> Path:
    path = output_dir / "harness_state.json"
    _atomic_write_text(path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    return path


def write_harness_partial_result(*, output_dir: Path, partial: HarnessPartialResult) -> Path:
    path = output_dir / "partial_result.json"
    _atomic_write_text(path, json.dumps(partial.to_dict(), ensure_ascii=False, indent=2))
    return path


def append_harness_progress_event(*, output_dir: Path, event: HarnessProgressEvent) -> Path:
    path = output_dir / "progress.jsonl"
    output_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    return path


def write_harness_heartbeat(*, output_dir: Path, state: HarnessRunState) -> Path:
    path = output_dir / "heartbeat.json"
    payload = {
        "authority": "health_system.harness_heartbeat",
        "run_id": state.run_id,
        "profile": state.profile,
        "status": state.status,
        "pid": state.pid,
        "process_token": state.process_token,
        "heartbeat_at": state.heartbeat_at or time.time(),
        "last_progress_at": state.last_progress_at,
        "last_progress_event_id": state.last_progress_event_id,
        "last_artifact_mtime": state.last_artifact_mtime,
    }
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def build_harness_artifact_manifest(*, output_dir: Path, run_id: str) -> HarnessArtifactManifest:
    files = {
        "harness_contract.json": ("contract", True),
        "harness_state.json": ("state", True),
        "heartbeat.json": ("heartbeat", True),
        "partial_result.json": ("partial_result", True),
        "progress.jsonl": ("progress", True),
        "run_result.json": ("run_result", True),
        "issues.json": ("issues", True),
        "trace.jsonl": ("trace", True),
        "report.md": ("report", True),
        "runner.log": ("log", False),
    }
    artifacts = []
    for filename, (artifact_type, required) in files.items():
        path = output_dir / filename
        present = path.exists()
        artifacts.append(
            HarnessArtifactRecord(
                name=filename,
                artifact_type=artifact_type,
                path=str(path),
                relative_ref=_relative_ref(path, output_dir),
                required=bool(required),
                present=present,
                checksum=_checksum(path) if present else "",
                size_bytes=path.stat().st_size if present else 0,
                updated_at=path.stat().st_mtime if present else 0.0,
            )
        )
    return HarnessArtifactManifest(
        manifest_id=f"harness-artifact-manifest:{run_id}",
        run_id=run_id,
        artifacts=tuple(artifacts),
        created_at=time.time(),
        metadata={"output_dir": str(output_dir)},
    )


def write_harness_artifact_manifest(*, output_dir: Path, run_id: str) -> HarnessArtifactManifest:
    manifest = build_harness_artifact_manifest(output_dir=output_dir, run_id=run_id)
    _atomic_write_text(
        output_dir / "artifact_manifest.json",
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
    )
    return manifest


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
    write_harness_artifact_manifest(output_dir=output_dir, run_id=run_result.context.run_id)
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


def _relative_ref(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _checksum(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        digest.update(path.read_bytes())
    except OSError:
        return ""
    return digest.hexdigest()
