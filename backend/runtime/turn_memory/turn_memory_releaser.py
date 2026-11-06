from __future__ import annotations

from .turn_memory_models import TurnMemoryRecord
from .turn_memory_store import TurnMemoryStore


def release_turn_memory(
    store: TurnMemoryStore,
    *,
    session_id: str,
    turn_id: str,
    reason: str = "confirmed_frame_consumed",
) -> TurnMemoryRecord:
    return store.release_turn(session_id=session_id, turn_id=turn_id, reason=reason)
