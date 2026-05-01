from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.deps import require_runtime
from health_system.workbench import HealthWorkbenchBuilder

router = APIRouter()


@router.get("/health-workbench/overview")
async def health_workbench_overview() -> dict[str, Any]:
    runtime = require_runtime()
    return HealthWorkbenchBuilder(runtime.base_dir, settings_service=runtime.settings).build_overview()
