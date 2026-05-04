from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from health_system.maintenance.experiments.graph_mapping import attach_graph_refs


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def read_text_tail(path: Path, *, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-limit:]


def summarize_run_result(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    results = list(payload.get("results") or [])
    total = int(metadata.get("total", len(results)) or 0)
    passed = int(metadata.get("passed", sum(1 for item in results if item.get("passed"))) or 0)
    failed = int(metadata.get("failed", max(total - passed, 0)) or 0)
    first_failure = ""
    for item in results:
        if not bool(item.get("passed", False)):
            first_failure = str(item.get("name") or item.get("summary") or "")
            break
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "first_failure": first_failure,
    }


def load_run_artifacts(output_dir: Path) -> dict[str, Any]:
    run_result = read_json_file(output_dir / "run_result.json", {})
    issues = read_json_file(output_dir / "issues.json", [])
    report = read_text_tail(output_dir / "report.md", limit=20000)
    trace_tail = read_text_tail(output_dir / "trace.jsonl", limit=20000)
    return {
        "run_result": run_result,
        "issues": attach_graph_refs(issues if isinstance(issues, list) else []),
        "report": report,
        "trace_tail": trace_tail,
        "summary": summarize_run_result(run_result if isinstance(run_result, dict) else {}),
    }
