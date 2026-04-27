from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OutputCommitPlan:
    projection: dict[str, Any]
    assistant_messages: list[dict[str, Any]]
    post_turn: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class OutputCommitGate:
    """Candidate seam for final answer persistence and post-turn writeback."""

    def build_plan(
        self,
        *,
        done_event: dict[str, Any],
        assistant_messages: list[dict[str, Any]],
        segment_count: int,
        title_seed: str | None,
    ) -> OutputCommitPlan:
        projection = {
            "main_context": done_event.get("main_context"),
            "task_summary_refs": list(done_event.get("task_summary_refs") or []),
        }
        post_turn = {
            "refresh_session_memory": True,
            "schedule_durable_memory_extraction": True,
            "title_seed": str(title_seed or ""),
        }
        candidates = [
            {
                "candidate_id": "persist:session_memory_projection",
                "candidate_type": "state_memory_projection",
                "target": "memory_facade.refresh_session_memory_from_context_state",
                "present": bool(projection["main_context"] or projection["task_summary_refs"]),
                "apply_mode": "legacy_runtime_apply",
            },
            {
                "candidate_id": "persist:assistant_messages",
                "candidate_type": "session_transcript",
                "target": "session_manager.append_messages",
                "present": bool(assistant_messages),
                "message_count": len(assistant_messages),
                "apply_mode": "legacy_runtime_apply",
            },
            {
                "candidate_id": "persist:post_turn_tasks",
                "candidate_type": "post_turn_refresh",
                "target": "QueryRuntime._run_post_turn_tasks",
                "present": True,
                "title_generation": bool(title_seed),
                "apply_mode": "legacy_runtime_apply",
            },
        ]
        diagnostics = {
            "phase": "8L",
            "state": "commit_candidates_projected",
            "mode": "legacy_runtime_apply",
            "canonical_owner": "orchestration.output_commit",
            "legacy_owner": "query.runtime.astream",
            "candidate_count": len(candidates),
            "segment_count": max(int(segment_count or 0), 0),
            "assistant_message_count": len(assistant_messages),
            "answer_channel": str(done_event.get("answer_channel") or ""),
            "answer_source": str(done_event.get("answer_source") or ""),
            "persist_policy": str(done_event.get("answer_persist_policy") or ""),
            "candidates": candidates,
            "state_write_allowed": True,
            "takeover_allowed": False,
            "delete_allowed": False,
            "safe_rule": "8L 只把最终答案与写回动作候选化；真实写回仍由 legacy runtime apply，后续再接入 MemoryPolicy 写回校验。",
        }
        return OutputCommitPlan(
            projection=projection,
            assistant_messages=list(assistant_messages),
            post_turn=post_turn,
            diagnostics=diagnostics,
        )
