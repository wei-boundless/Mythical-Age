from __future__ import annotations

import asyncio
import inspect
from typing import Any


class CallbackManagerForToolRun:
    """Compatibility type for tool method signatures."""


class AsyncCallbackManagerForToolRun:
    """Compatibility type for async tool method signatures."""


class BaseTool:
    name: str = ""
    description: str = ""
    args_schema: Any = None

    def __init__(self, **kwargs: Any) -> None:
        for key, value in dict(kwargs or {}).items():
            setattr(self, key, value)

    def invoke(self, input: Any = None, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        _ = config
        args = self._normalize_args(input, kwargs)
        return self._call_run(args)

    async def ainvoke(self, input: Any = None, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        _ = config
        args = self._normalize_args(input, kwargs)
        arun = getattr(self, "_arun", None)
        if callable(arun):
            result = arun(**args)
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(self._call_run, args)

    def _normalize_args(self, input: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        if isinstance(input, dict):
            payload = dict(input)
        elif input is None:
            payload = {}
        else:
            payload = {"input": input}
        payload.update(dict(kwargs or {}))
        schema = getattr(self, "args_schema", None)
        validator = getattr(schema, "model_validate", None)
        if callable(validator):
            validated = validator(payload)
            dumper = getattr(validated, "model_dump", None)
            if callable(dumper):
                return dict(dumper())
        return payload

    def _call_run(self, args: dict[str, Any]) -> Any:
        run = getattr(self, "_run", None)
        if not callable(run):
            raise NotImplementedError(f"{self.__class__.__name__} must implement _run or _arun")
        return run(**dict(args or {}))
