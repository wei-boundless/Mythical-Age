from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import get_settings
from runtime.app_runtime import app_runtime


@asynccontextmanager
async def runtime_lifespan(_: FastAPI):
    settings = get_settings()
    app_runtime.initialize(settings.backend_dir)
    yield
