from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["AppRuntime", "AppSettingsService", "app_runtime", "runtime_lifespan"]


def __getattr__(name: str) -> Any:
    if name == "AppRuntime":
        return getattr(import_module("bootstrap.app_runtime"), name)
    if name == "app_runtime":
        return getattr(import_module("bootstrap.app_runtime"), name)
    if name == "runtime_lifespan":
        return getattr(import_module("bootstrap.lifespan"), name)
    if name == "AppSettingsService":
        return getattr(import_module("bootstrap.settings"), name)
    raise AttributeError(name)
