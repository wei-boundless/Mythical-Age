from __future__ import annotations

import time
from typing import Any

from .guards import compact, record, stable_id, text


PROMPT_PACKET_AUTHORITY = "harness.prompt_packet"


def build_prompt_packet(
    *,
    session_id: str,
    turn_id: str,
    turn_run_id: str = "",
    task_run_id: str = "",
    input_blocks: list[dict[str, Any]] | None = None,
    created_from_event_offset: int = 0,
) -> dict[str, Any]:
    packet_ref = stable_id("promptpkt", session_id, turn_id, turn_run_id, task_run_id, created_from_event_offset, time.time())
    blocks = [_input_block(block) for block in list(input_blocks or []) if isinstance(block, dict)]
    blocks = [block for block in blocks if block]
    return compact(
        {
            "authority": PROMPT_PACKET_AUTHORITY,
            "prompt_packet_ref": packet_ref,
            "session_id": text(session_id),
            "turn_id": text(turn_id),
            "turn_run_id": text(turn_run_id),
            "task_run_id": text(task_run_id),
            "created_from_event_offset": int(created_from_event_offset or 0),
            "input_blocks": blocks,
            "created_at": time.time(),
        }
    )


def _input_block(value: dict[str, Any]) -> dict[str, Any]:
    block = record(value)
    kind = text(block.get("kind"))
    if not kind:
        return {}
    return compact({"kind": kind, "ref": text(block.get("ref")), "summary": text(block.get("summary"))})

