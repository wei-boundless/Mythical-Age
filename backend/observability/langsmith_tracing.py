from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from project_layout import ProjectLayout

try:
    from langsmith import Client, tracing_context
    from langsmith.run_helpers import trace as langsmith_trace
except Exception:  # pragma: no cover - optional dependency
    Client = None
    tracing_context = None
    langsmith_trace = None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _resolve_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _truncate(value: Any, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _compact_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value, limit=400)
    if isinstance(value, Mapping):
        payload: dict[str, Any] = {}
        for key, item in value.items():
            normalized = _compact_value(item)
            if normalized is not None and normalized != "":
                payload[str(key)] = normalized
        return payload or None
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in list(value)[:8]:
            normalized = _compact_value(item)
            if normalized is not None and normalized != "":
                items.append(normalized)
        return items or None
    return _truncate(value, limit=200)


def _compact_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    compacted: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = _compact_value(value)
        if normalized is not None and normalized != "":
            compacted[str(key)] = normalized
    return compacted or None


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(value: str) -> str:
    parts: list[str] = []
    for char in str(value or "").strip():
        if char.isalnum():
            parts.append(char.lower())
        else:
            parts.append("-")
    slug = "".join(parts).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "trace"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _local_trace_root() -> Path:
    explicit = _first_env("APP_TRACE_DIR", "LOCAL_TRACE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1]).project_root / "output" / "local_traces"


@lru_cache(maxsize=1)
def _build_client() -> Any | None:
    if Client is None:
        return None
    kwargs: dict[str, Any] = {}
    api_key = _first_env("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")
    api_url = _first_env("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT")
    if api_key:
        kwargs["api_key"] = api_key
    if api_url:
        kwargs["api_url"] = api_url
    try:
        return Client(**kwargs)
    except Exception:
        return None


def _is_enabled() -> bool:
    if Client is None or tracing_context is None or langsmith_trace is None:
        return False
    if not _resolve_bool(_first_env("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"), default=False):
        return False
    return bool(_first_env("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"))


def is_langsmith_tracing_enabled() -> bool:
    if not _is_enabled():
        return False
    return _build_client() is not None


def is_local_trace_enabled() -> bool:
    return _resolve_bool(_first_env("APP_TRACE_LOCAL", "LOCAL_TRACE_ENABLED"), default=True)


def is_trace_capture_enabled() -> bool:
    return is_langsmith_tracing_enabled() or is_local_trace_enabled()


def current_trace_backend() -> str:
    if is_langsmith_tracing_enabled():
        return "langsmith"
    if is_local_trace_enabled():
        return "local"
    return "disabled"


def _project_name() -> str | None:
    return _first_env("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT")


def _is_development_environment() -> bool:
    value = _first_env("APP_ENV", "ENVIRONMENT", "RUNTIME_ENV", "NODE_ENV")
    normalized = str(value or "").strip().lower()
    return normalized in {"dev", "development", "local"}


def should_emit_dev_trace_link() -> bool:
    if not is_langsmith_tracing_enabled():
        return False
    if not _is_development_environment():
        return False
    return _resolve_bool(_first_env("LANGSMITH_DEV_TRACE_LINKS"), default=True)


def should_emit_local_trace_link() -> bool:
    if not is_local_trace_enabled():
        return False
    return _resolve_bool(_first_env("APP_TRACE_LOCAL_LINKS", "LOCAL_TRACE_LINKS"), default=True)


def _safe_add_metadata(run: Any, metadata: Mapping[str, Any] | None) -> None:
    compacted = _compact_mapping(metadata)
    if run is None or not compacted:
        return
    try:
        run.add_metadata(compacted)
    except Exception:
        return


@dataclass
class _LangSmithSpan:
    enabled: bool
    name: str
    parent: Any = None
    run_type: str = "chain"
    inputs: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    _trace_context: Any = field(default=None, init=False)
    _context_manager: Any = field(default=None, init=False)
    run: Any = field(default=None, init=False)

    def __enter__(self) -> Any | None:
        if not self.enabled or self.parent is None or tracing_context is None or langsmith_trace is None:
            return None
        try:
            self._trace_context = tracing_context(enabled=True)
            self._trace_context.__enter__()
            self._context_manager = langsmith_trace(
                self.name,
                run_type=self.run_type,
                parent=self.parent,
                inputs=_compact_mapping(self.inputs),
                metadata=_compact_mapping(self.metadata),
                tags=list(self.tags or []),
            )
            self.run = self._context_manager.__enter__()
            return self.run
        except Exception:
            self._close(None, None, None)
            self.run = None
            return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.run is not None:
            if exc is None:
                _safe_add_metadata(self.run, {"app.status": "ok"})
            else:
                _safe_add_metadata(
                    self.run,
                    {
                        "app.status": "error",
                        "app.error": _truncate(str(exc), limit=240),
                    },
                )
        self._close(exc_type, exc, tb)
        return False

    def _close(self, exc_type, exc, tb) -> None:
        if self._context_manager is not None:
            try:
                self._context_manager.__exit__(exc_type, exc, tb)
            except Exception:
                pass
            finally:
                self._context_manager = None
        if self._trace_context is not None:
            try:
                self._trace_context.__exit__(exc_type, exc, tb)
            except Exception:
                pass
            finally:
                self._trace_context = None


@dataclass
class _LocalTraceSpan:
    enabled: bool
    trace: Any
    name: str
    run_type: str = "chain"
    inputs: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    _started_at: str = field(default="", init=False)
    _started_perf: float = field(default=0.0, init=False)

    def __enter__(self) -> "_LocalTraceSpan | None":
        if not self.enabled:
            return None
        self._started_at = _iso_now()
        self._started_perf = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.enabled:
            return False
        self.trace._append_stage(
            {
                "name": self.name,
                "run_type": self.run_type,
                "status": "error" if exc is not None else "ok",
                "started_at": self._started_at or _iso_now(),
                "ended_at": _iso_now(),
                "latency_ms": round(max(time.perf_counter() - self._started_perf, 0.0) * 1000.0, 2),
                "inputs": _compact_mapping(self.inputs),
                "metadata": _compact_mapping(self.metadata),
                "tags": list(self.tags or []),
                "error": _truncate(str(exc), limit=240) if exc is not None else "",
            }
        )
        return False


@dataclass
class LangSmithTurnTrace:
    session_id: str
    user_message: str
    history_length: int
    metadata: Mapping[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    enabled: bool = field(default=False, init=False)
    trace_id: str = field(default="", init=False)
    trace_url: str = field(default="", init=False)
    trace_source: str = field(default="", init=False)
    _root_run: Any = field(default=None, init=False)
    _trace_context: Any = field(default=None, init=False)
    _context_manager: Any = field(default=None, init=False)

    def __enter__(self) -> "LangSmithTurnTrace":
        if not _is_enabled():
            return self
        client = _build_client()
        if client is None or tracing_context is None or langsmith_trace is None:
            return self
        try:
            self._trace_context = tracing_context(enabled=True)
            self._trace_context.__enter__()
            self._context_manager = langsmith_trace(
                "chat.turn",
                run_type="chain",
                client=client,
                project_name=_project_name(),
                inputs=_compact_mapping(
                    {
                        "session_id": self.session_id,
                        "user_message": self.user_message,
                        "history_length": self.history_length,
                    }
                ),
                metadata=_compact_mapping(self.metadata),
                tags=["chat-runtime", *list(self.tags or [])],
            )
            self._root_run = self._context_manager.__enter__()
            self.enabled = self._root_run is not None
            if self.enabled:
                self.trace_source = "langsmith"
                self.trace_id = str(getattr(self._root_run, "id", "") or "")
                try:
                    self.trace_url = str(self._root_run.get_url() or "")
                except Exception:
                    self.trace_url = ""
            return self
        except Exception:
            self._close(None, None, None)
            self.enabled = False
            self._root_run = None
            return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._root_run is not None:
            if exc is None:
                _safe_add_metadata(self._root_run, {"app.status": "ok"})
            else:
                _safe_add_metadata(
                    self._root_run,
                    {
                        "app.status": "error",
                        "app.error": _truncate(str(exc), limit=240),
                    },
                )
        self._close(exc_type, exc, tb)
        return False

    def stage(
        self,
        name: str,
        *,
        run_type: str = "chain",
        inputs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> _LangSmithSpan:
        return _LangSmithSpan(
            enabled=self.enabled,
            name=name,
            parent=self._root_run,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=list(tags or []),
        )

    def annotate(self, metadata: Mapping[str, Any] | None = None) -> None:
        _safe_add_metadata(self._root_run, metadata)

    def _close(self, exc_type, exc, tb) -> None:
        if self._context_manager is not None:
            try:
                self._context_manager.__exit__(exc_type, exc, tb)
            except Exception:
                pass
            finally:
                self._context_manager = None
        if self._trace_context is not None:
            try:
                self._trace_context.__exit__(exc_type, exc, tb)
            except Exception:
                pass
            finally:
                self._trace_context = None


@dataclass
class LocalTurnTrace:
    session_id: str
    user_message: str
    history_length: int
    metadata: Mapping[str, Any] | None = None
    tags: list[str] = field(default_factory=list)
    enabled: bool = field(default=False, init=False)
    trace_id: str = field(default="", init=False)
    trace_url: str = field(default="", init=False)
    trace_source: str = field(default="local", init=False)
    _started_at: str = field(default="", init=False)
    _started_perf: float = field(default=0.0, init=False)
    _annotations: dict[str, Any] = field(default_factory=dict, init=False)
    _stages: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __enter__(self) -> "LocalTurnTrace":
        if not is_local_trace_enabled():
            return self
        session_slug = _slug(self.session_id)[:16]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.trace_id = f"local-{stamp}-{session_slug}-{uuid4().hex[:8]}"
        trace_path = _local_trace_root() / datetime.now().strftime("%Y%m%d") / f"{self.trace_id}.json"
        self.trace_url = str(trace_path)
        self._started_at = _iso_now()
        self._started_perf = time.perf_counter()
        self.enabled = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.enabled:
            return False
        payload = {
            "trace_id": self.trace_id,
            "trace_source": self.trace_source,
            "status": "error" if exc is not None else "ok",
            "started_at": self._started_at or _iso_now(),
            "ended_at": _iso_now(),
            "latency_ms": round(max(time.perf_counter() - self._started_perf, 0.0) * 1000.0, 2),
            "session_id": self.session_id,
            "user_message": _truncate(self.user_message, limit=400),
            "history_length": self.history_length,
            "metadata": _compact_mapping(self.metadata),
            "annotations": _compact_mapping(self._annotations),
            "tags": list(self.tags or []),
            "stages": list(self._stages),
            "error": _truncate(str(exc), limit=240) if exc is not None else "",
        }
        _atomic_write_text(Path(self.trace_url), json.dumps(payload, ensure_ascii=False, indent=2))
        return False

    def stage(
        self,
        name: str,
        *,
        run_type: str = "chain",
        inputs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> _LocalTraceSpan:
        return _LocalTraceSpan(
            enabled=self.enabled,
            trace=self,
            name=name,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=list(tags or []),
        )

    def annotate(self, metadata: Mapping[str, Any] | None = None) -> None:
        compacted = _compact_mapping(metadata)
        if compacted:
            self._annotations.update(compacted)

    def _append_stage(self, payload: Mapping[str, Any]) -> None:
        self._stages.append(dict(payload))


def start_turn_trace(
    *,
    session_id: str,
    user_message: str,
    history_length: int,
    metadata: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
) -> LangSmithTurnTrace | LocalTurnTrace:
    if is_langsmith_tracing_enabled():
        return LangSmithTurnTrace(
            session_id=session_id,
            user_message=user_message,
            history_length=history_length,
            metadata=metadata,
            tags=list(tags or []),
        )
    if is_local_trace_enabled():
        return LocalTurnTrace(
            session_id=session_id,
            user_message=user_message,
            history_length=history_length,
            metadata=metadata,
            tags=list(tags or []),
        )
    return LangSmithTurnTrace(
        session_id=session_id,
        user_message=user_message,
        history_length=history_length,
        metadata=metadata,
        tags=list(tags or []),
    )


def build_debug_trace_event(trace: LangSmithTurnTrace | LocalTurnTrace) -> dict[str, Any] | None:
    if not (trace.trace_id or trace.trace_url):
        return None
    trace_source = str(getattr(trace, "trace_source", "") or "")
    if trace_source == "langsmith":
        if not should_emit_dev_trace_link():
            return None
        kind = "langsmith_trace"
    elif trace_source == "local":
        if not should_emit_local_trace_link():
            return None
        kind = "local_trace"
    else:
        return None
    return {
        "type": "debug",
        "kind": kind,
        "trace_source": trace_source,
        "trace_id": trace.trace_id,
        "trace_url": trace.trace_url,
    }
