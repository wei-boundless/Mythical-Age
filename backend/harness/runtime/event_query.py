from __future__ import annotations

from typing import Any


def list_runtime_events(
    source: Any,
    run_id: str,
    *,
    limit: int,
    include_payloads: bool = True,
    prefer_window: bool = True,
) -> list[Any]:
    """Read a bounded event window without interpreting runtime semantics."""
    event_log = getattr(source, "event_log", source)
    event_limit = _positive_limit(limit, default=160)
    if prefer_window:
        window_reader = getattr(event_log, "list_event_window", None)
        if callable(window_reader):
            try:
                return list(window_reader(run_id, limit=event_limit, include_payloads=include_payloads))
            except TypeError:
                try:
                    return list(window_reader(run_id, limit=event_limit))
                except Exception:
                    pass
            except Exception:
                pass
    recent_reader = getattr(event_log, "list_recent_events", None)
    if callable(recent_reader):
        try:
            return list(recent_reader(run_id, limit=event_limit))
        except TypeError:
            try:
                return list(recent_reader(run_id))
            except Exception:
                return []
        except Exception:
            return []
    all_events_reader = getattr(event_log, "list_events", None)
    if callable(all_events_reader):
        try:
            return list(all_events_reader(run_id))[-event_limit:]
        except Exception:
            return []
    return []


def runtime_event_count(source: Any, run_id: str, *, fallback: int) -> int:
    event_log = getattr(source, "event_log", source)
    fallback_count = _int_value(fallback, default=0)
    estimator = getattr(event_log, "estimated_event_count", None)
    if callable(estimator):
        try:
            return int(estimator(run_id))
        except Exception:
            return fallback_count
    counter = getattr(event_log, "event_count", None)
    if callable(counter):
        try:
            return int(counter(run_id))
        except Exception:
            return fallback_count
    return fallback_count


def _positive_limit(value: Any, *, default: int) -> int:
    return max(1, _int_value(value, default=default))


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
