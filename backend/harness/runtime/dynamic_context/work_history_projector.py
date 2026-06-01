from __future__ import annotations

from typing import Any

from .models import compact_text, drop_empty
from .tool_result_projector import model_visible_artifact_refs


class WorkHistoryProjector:
    def project(self, work_rollout: dict[str, Any] | None, *, projection_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        rollout = dict(work_rollout or {})
        if not rollout:
            return {}
        policy = dict(projection_policy or {})
        limit = int(policy.get("recent_work_step_limit") or 8)
        summary_limit = int(policy.get("work_step_summary_chars") or 500)
        progress_limit = int(policy.get("work_progress_chars") or 500)
        history = [dict(item) for item in list(rollout.get("model_visible_history") or []) if isinstance(item, dict)]
        recent_steps = [
            drop_empty(
                {
                    "type": str(item.get("type") or ""),
                    "title": compact_text(item.get("title") or "", limit=160),
                    "status": str(item.get("status") or ""),
                    "summary": compact_text(item.get("summary") or "", limit=max(200, summary_limit)),
                    "agent_brief_output": compact_text(item.get("agent_brief_output") or "", limit=300),
                }
            )
            for item in history[-limit:]
        ]
        artifacts = model_visible_artifact_refs(rollout.get("artifact_refs"))
        latest_progress = compact_text(rollout.get("latest_progress") or "", limit=max(200, progress_limit))
        return drop_empty(
            {
                "latest_progress": latest_progress,
                "latest_step_title": compact_text(rollout.get("latest_step_title") or "", limit=160),
                "active_facts": _active_facts(history),
                "recent_steps": recent_steps,
                "active_artifacts": artifacts,
                "historical_work_summary": drop_empty(
                    {
                        "status": _summary_status(history),
                        "public_result_summary": latest_progress,
                        "usable_artifact_refs": _summary_artifact_refs(artifacts),
                        "non_control_context": True,
                    }
                ),
                "omitted_work_history": {
                    "count": max(0, len(history) - len(recent_steps)),
                    "reason": "recent_work_step_limit",
                }
                if len(history) > len(recent_steps)
                else {},
                "authority": "harness.runtime.dynamic_context.work_history_projection",
            }
        )


def _active_facts(history: list[dict[str, Any]]) -> list[str]:
    facts: list[str] = []
    for item in history[-12:]:
        status = str(item.get("status") or "")
        if status not in {"completed", "success", "waiting_executor", "running"}:
            continue
        text = compact_text(item.get("summary") or item.get("title") or "", limit=220)
        if text and text not in facts:
            facts.append(text)
    return facts[-6:]


def _summary_status(history: list[dict[str, Any]]) -> str:
    for item in reversed(history):
        status = str(item.get("status") or "").strip()
        if status:
            return status
    return ""


def _summary_artifact_refs(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        drop_empty(
            {
                "path": str(item.get("path") or ""),
                "kind": str(item.get("kind") or ""),
                "summary": compact_text(item.get("summary") or "", limit=180),
                "mime_type": str(item.get("mime_type") or ""),
                "exists": item.get("exists") if isinstance(item.get("exists"), bool) else None,
                "published": item.get("published") if isinstance(item.get("published"), bool) else None,
            }
        )
        for item in artifacts
        if str(item.get("path") or "")
    ]
