from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from bootstrap.app_runtime import app_runtime
from core.config import get_settings
from core.project_layout import ensure_project_storage


@asynccontextmanager
async def runtime_lifespan(_: FastAPI):
    settings = get_settings()
    ensure_project_storage(settings.backend_dir)
    app_runtime.initialize(settings.backend_dir)
    await app_runtime.start_background_services()
    try:
        yield
    finally:
        await app_runtime.shutdown()



