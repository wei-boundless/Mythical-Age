from __future__ import annotations

from typing import Any

from .models import compact_text, dict_tuple, drop_empty
from .tool_result_projector import model_visible_artifact_refs


class WorkHistoryProjector:
    def project(self, work_rollout: dict[str, Any] | None, *, projection_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        rollout = dict(work_rollout or {})
        if not rollout:
            return {}
        policy = dict(projection_policy or {})
        limit = int(policy.get("recent_work_step_limit") or 8)
        history = [dict(item) for item in list(rollout.get("model_visible_history") or []) if isinstance(item, dict)]
        recent_steps = [
            drop_empty(
                {
                    "type": str(item.get("type") or ""),
                    "title": compact_text(item.get("title") or "", limit=160),
                    "status": str(item.get("status") or ""),
                    "summary": compact_text(item.get("summary") or "", limit=500),
                    "agent_brief_output": compact_text(item.get("agent_brief_output") or "", limit=300),
                    "event_offset": item.get("event_offset"),
                    "refs": dict(item.get("refs") or {}),
                }
            )
            for item in history[-limit:]
        ]
        return drop_empty(
            {
                "latest_progress": compact_text(rollout.get("latest_progress") or "", limit=500),
                "latest_step_title": compact_text(rollout.get("latest_step_title") or "", limit=160),
                "active_facts": _active_facts(history),
                "recent_steps": recent_steps,
                "active_artifacts": model_visible_artifact_refs(rollout.get("artifact_refs")),
                "checkpoint": dict(rollout.get("breakpoint") or {}),
                "lineage": dict(rollout.get("lineage") or {}),
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
