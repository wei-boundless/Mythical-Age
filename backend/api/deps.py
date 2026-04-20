from __future__ import annotations

from fastapi import HTTPException

from runtime.app_runtime import app_runtime


def require_runtime():
    try:
        return app_runtime.require_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
