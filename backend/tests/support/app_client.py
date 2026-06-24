from __future__ import annotations

from contextlib import contextmanager
import os
import tempfile
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient


@contextmanager
def isolated_app_client(app: FastAPI) -> Iterator[TestClient]:
    """Start the real FastAPI app with project code but isolated runtime storage."""
    previous_storage_root = os.environ.get("APP_STORAGE_ROOT")
    with tempfile.TemporaryDirectory(prefix="langchain-agent-app-test-", ignore_cleanup_errors=True) as root:
        temp_root = Path(root).resolve()
        storage_root = temp_root / "storage"
        os.environ["APP_STORAGE_ROOT"] = str(storage_root)
        _clear_settings_cache()
        try:
            with TestClient(app) as client:
                setattr(client, "isolated_storage_root", storage_root)
                yield client
        finally:
            _restore_env("APP_STORAGE_ROOT", previous_storage_root)
            _clear_settings_cache()


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
        return
    os.environ[name] = value


def _clear_settings_cache() -> None:
    try:
        from core.config import get_settings
    except Exception:
        return
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()

