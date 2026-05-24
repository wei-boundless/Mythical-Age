from __future__ import annotations

import time
import uuid
from typing import Any

from .models import ExecutionChannel


def create_execution_channel(
    *,
    order_id: str,
    order_run_id: str,
    session_id: str,
    channel_kind: str = "single_agent",
    diagnostics: dict[str, Any] | None = None,
) -> ExecutionChannel:
    now = time.time()
    return ExecutionChannel(
        channel_id=f"execchan:{uuid.uuid4().hex[:12]}",
        order_run_id=order_run_id,
        order_id=order_id,
        session_id=session_id,
        channel_kind=channel_kind,
        status="created",
        created_at=now,
        updated_at=now,
        diagnostics=dict(diagnostics or {}),
    )
