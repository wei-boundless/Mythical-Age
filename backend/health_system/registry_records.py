from __future__ import annotations

import json
from pathlib import Path

from core.project_layout import ProjectLayout

from .models import HealthIssue


def _sample_health_issue() -> HealthIssue:
    return HealthIssue(
        issue_id="health:issue:sample-task-system-chain",
        title="任务系统链路权限样例问题",
        owner_system="task_system",
        severity="medium",
        status="triage_ready",
        source="system_bootstrap",
        conversation_ref="sample:conversation:task-system",
        runtime_trace_refs=("runtime-loop:sample",),
        prompt_manifest_refs=("prompt-manifest:sample",),
        memory_refs=("memory-runtime-view:sample",),
        assertion_refs=("assertion:sample",),
        metadata={"sample": True},
    )


def get_health_issue_by_id(base_dir: Path, issue_id: str) -> HealthIssue | None:
    target = str(issue_id or "").strip()
    if not target:
        return None
    if target == "health:issue:sample-task-system-chain":
        return _sample_health_issue()
    path = ProjectLayout.from_backend_dir(base_dir).health_system_dir / "issues.jsonl"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("issue_id") or "") != target:
            continue
        return HealthIssue(
            issue_id=str(payload.get("issue_id") or ""),
            title=str(payload.get("title") or ""),
            owner_system=str(payload.get("owner_system") or ""),
            severity=str(payload.get("severity") or "medium"),
            status=str(payload.get("status") or "triage_ready"),
            source=str(payload.get("source") or "manual"),
            conversation_ref=str(payload.get("conversation_ref") or ""),
            runtime_trace_refs=tuple(str(item) for item in list(payload.get("runtime_trace_refs") or [])),
            prompt_manifest_refs=tuple(str(item) for item in list(payload.get("prompt_manifest_refs") or [])),
            memory_refs=tuple(str(item) for item in list(payload.get("memory_refs") or [])),
            assertion_refs=tuple(str(item) for item in list(payload.get("assertion_refs") or [])),
            duplicate_of=str(payload.get("duplicate_of") or ""),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )
    return None



