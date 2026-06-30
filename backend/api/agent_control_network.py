from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from api.deps import require_runtime
from harness.runtime.context_contract import build_runtime_topology_projection


router = APIRouter()


@router.get("/agent-control-network")
async def get_agent_control_network() -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(build_runtime_topology_projection, runtime)


@router.get("/agent-control-network/session/{session_id}")
async def get_agent_control_network_session(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return await asyncio.to_thread(
        build_runtime_topology_projection,
        runtime,
        session_id=session_id,
    )
