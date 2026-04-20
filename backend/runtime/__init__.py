from __future__ import annotations

__all__ = ["AppRuntime", "app_runtime"]


def __getattr__(name: str):
    if name in {"AppRuntime", "app_runtime"}:
        from runtime.app_runtime import AppRuntime, app_runtime

        return {
            "AppRuntime": AppRuntime,
            "app_runtime": app_runtime,
        }[name]
    raise AttributeError(f"module 'runtime' has no attribute {name!r}")
