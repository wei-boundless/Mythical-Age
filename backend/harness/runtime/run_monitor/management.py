from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .retention_store import RuntimeMonitorRetentionStore


MANAGEMENT_AUTHORITY = "runtime_monitor.management"


@dataclass(frozen=True, slots=True)
class RuntimeMonitorManagementPolicy:
    active_max: int = 5
    attention_max: int = 12
    project_max: int = 8
    recent_max: int = 12
    recent_ttl_seconds: int = 30 * 60
    hidden_retention_seconds: int = 7 * 24 * 60 * 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": "runtime_monitor.management_policy",
            "active_max": self.active_max,
            "attention_max": self.attention_max,
            "project_max": self.project_max,
            "recent_max": self.recent_max,
            "recent_ttl_seconds": self.recent_ttl_seconds,
            "hidden_retention_seconds": self.hidden_retention_seconds,
        }


class RuntimeMonitorManagementProjector:
    def __init__(
        self,
        *,
        retention_store: RuntimeMonitorRetentionStore,
        policy: RuntimeMonitorManagementPolicy | None = None,
    ) -> None:
        self.retention_store = retention_store
        self.policy = policy or RuntimeMonitorManagementPolicy()

    def apply_management(
        self,
        envelope: dict[str, Any],
        *,
        now: float,
        source_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        revision = str(envelope.get("revision") or "")
        source_index = _source_index(source_items)
        hidden_index = self.retention_store.hidden_index(now=now)
        enriched = [
            self._enrich_signal(signal, source_index=source_index, hidden_index=hidden_index)
            for signal in list(envelope.get("signals") or [])
            if isinstance(signal, dict)
        ]
        enriched = self._apply_capacity(enriched, revision=revision, now=now)
        lanes = _lanes(enriched)
        managed = {
            **envelope,
            "signals": [signal for signal in enriched if _is_default_visible(signal)],
            "primary": [signal for signal in lanes["current"] if signal.get("state") == "active"],
            "attention": lanes["attention"],
            "recent": lanes["recent"],
            "projects": lanes["projects"],
            "management": {
                "authority": MANAGEMENT_AUTHORITY,
                "policy": self.policy.to_dict(),
                "summary": _summary(enriched),
                "lanes": lanes,
                "capacity": {
                    "active_max": self.policy.active_max,
                    "attention_max": self.policy.attention_max,
                    "project_max": self.policy.project_max,
                    "recent_max": self.policy.recent_max,
                    "hidden_count": len(lanes["hidden"]),
                    "visible_count": sum(1 for signal in enriched if _is_default_visible(signal)),
                },
                "updated_at": float(now),
            },
        }
        visible_signals = [signal for signal in enriched if _is_default_visible(signal)]
        managed["summary"] = {
            **dict(envelope.get("summary") or {}),
            "active": sum(1 for item in visible_signals if item.get("is_running") is True),
            "attention": len(managed["attention"]),
            "waiting": sum(1 for item in visible_signals if str(item.get("activity_state") or "") in {"waiting", "paused"}),
            "failed": sum(1 for item in visible_signals if str(item.get("activity_state") or "") == "failed" or item.get("state") == "failed"),
            "recent": len(managed["recent"]),
            "projects": len(managed["projects"]),
            "hidden": len(lanes["hidden"]),
            "total": len(visible_signals),
        }
        return managed

    def _enrich_signal(
        self,
        signal: dict[str, Any],
        *,
        source_index: dict[str, dict[str, Any]],
        hidden_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        signal_id = _signal_id(signal)
        source = source_index.get(signal_id) or source_index.get(str(signal.get("task_run_id") or "")) or {}
        hidden = hidden_index.get(signal_id)
        lane = _lane_for_signal(signal)
        visibility = {
            "visible": hidden is None,
            "lane": "hidden" if hidden else lane,
            "default_lane": lane,
            "hidden": hidden is not None,
            "hidden_reason": str((hidden or {}).get("hidden_reason") or ""),
            "hidden_at": float((hidden or {}).get("hidden_at") or 0.0),
            "expires_at": float((hidden or {}).get("expires_at") or 0.0),
        }
        return {
            **signal,
            "visibility": visibility,
            "actions": _actions_for_signal(signal, source=source, hidden=hidden is not None),
        }

    def _apply_capacity(self, signals: list[dict[str, Any]], *, revision: str, now: float) -> list[dict[str, Any]]:
        visible_recent = [
            signal
            for signal in signals
            if _is_default_visible(signal) and str(signal.get("visibility", {}).get("default_lane") or "") == "recent"
        ]
        if len(visible_recent) <= self.policy.recent_max:
            return signals
        visible_recent.sort(key=_last_activity, reverse=True)
        keep = {_signal_id(signal) for signal in visible_recent[: self.policy.recent_max]}
        evicted = [signal for signal in visible_recent[self.policy.recent_max :] if _signal_id(signal) not in keep]
        evicted_ids = {_signal_id(signal) for signal in evicted}
        result: list[dict[str, Any]] = []
        for signal in signals:
            signal_id = _signal_id(signal)
            if signal_id not in evicted_ids:
                result.append(signal)
                continue
            visibility = dict(signal.get("visibility") or {})
            result.append(
                {
                    **signal,
                    "visibility": {
                        **visibility,
                        "visible": False,
                        "lane": "hidden",
                        "hidden": True,
                        "hidden_reason": "capacity_evicted",
                        "hidden_at": float(now),
                        "expires_at": float(now) + self.policy.hidden_retention_seconds,
                    },
                    "actions": _actions_for_signal(signal, source={}, hidden=True),
                }
            )
        return result


def _source_index(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        for key in (
            str(item.get("task_instance_id") or ""),
            str(item.get("task_run_id") or ""),
            str(item.get("graph_run_id") or ""),
        ):
            normalized = key.strip()
            if normalized:
                result[normalized] = item
    return result


def _lanes(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lanes = {"current": [], "attention": [], "projects": [], "recent": [], "hidden": []}
    for signal in signals:
        visibility = dict(signal.get("visibility") or {})
        lane = str(visibility.get("lane") or _lane_for_signal(signal))
        if lane not in lanes:
            lane = "attention"
        lanes[lane].append(signal)
    for lane in lanes.values():
        lane.sort(key=lambda item: (int(item.get("priority") or 0), _last_activity(item)), reverse=True)
    return lanes


def _summary(signals: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "current": sum(1 for signal in signals if str(dict(signal.get("visibility") or {}).get("lane") or "") == "current"),
        "attention": sum(1 for signal in signals if str(dict(signal.get("visibility") or {}).get("lane") or "") == "attention"),
        "projects": sum(1 for signal in signals if str(dict(signal.get("visibility") or {}).get("lane") or "") == "projects"),
        "recent": sum(1 for signal in signals if str(dict(signal.get("visibility") or {}).get("lane") or "") == "recent"),
        "hidden": sum(1 for signal in signals if str(dict(signal.get("visibility") or {}).get("lane") or "") == "hidden"),
        "visible": sum(1 for signal in signals if _is_default_visible(signal)),
        "total": len(signals),
    }


def _lane_for_signal(signal: dict[str, Any]) -> str:
    if str(signal.get("work_kind") or "") == "graph_task":
        return "projects"
    if signal.get("is_running") is True:
        return "current"
    state = str(signal.get("state") or "")
    if state == "active":
        return "current"
    if state == "completed":
        return "recent"
    return "attention"


def _actions_for_signal(signal: dict[str, Any], *, source: dict[str, Any], hidden: bool) -> list[dict[str, Any]]:
    state = str(signal.get("state") or "")
    activity_state = str(signal.get("activity_state") or source.get("activity_state") or "")
    work_kind = str(signal.get("work_kind") or "")
    task_run_id = str(signal.get("task_run_id") or "").strip()
    graph_run_id = str(signal.get("graph_run_id") or dict(signal.get("graph_ref") or {}).get("graph_run_id") or "").strip()
    terminal = activity_state in {"completed", "failed", "stopped"} or state in {"completed", "failed"} or bool(source.get("terminal") is True)
    lifecycle = str(signal.get("lifecycle") or source.get("lifecycle") or "")
    stale = activity_state == "stale" or lifecycle == "stale" or bool(signal.get("stale") is True or source.get("stale") is True)
    running = False if stale else bool(signal.get("is_running") is True or source.get("is_running") is True)
    source_capability = dict(source.get("control_capability") or {})
    signal_capability = dict(signal.get("control_capability") or {})
    capability = {**source_capability, **signal_capability}
    pause_allowed = bool(capability.get("can_pause_task", signal.get("is_interruptible") is True or source.get("is_interruptible") is True))
    stop_allowed = bool(capability.get("can_stop_task", pause_allowed))
    graph_task = work_kind == "graph_task" or bool(graph_run_id)
    actions = [
        _action("open", "打开", True),
        _action("inspect", "详情", bool(task_run_id or graph_run_id)),
    ]
    if hidden:
        actions.append(_action("restore_to_monitor", "恢复显示", True))
    else:
        clear_enabled = (terminal or stale) and not running
        actions.append(_action("clear_from_monitor", "清出", clear_enabled, "" if clear_enabled else "active_or_waiting_runtime"))
    pause_enabled = bool(task_run_id) and pause_allowed and not terminal and not (stale and not running)
    stop_enabled = bool(task_run_id) and stop_allowed and not terminal and not (stale and not running)
    close_enabled = bool(task_run_id) and stop_allowed and not terminal and stale and not running
    actions.extend(
        [
            _action("pause_task", "暂停", pause_enabled, "" if pause_enabled else "not_active_task"),
            _action("stop_task", "停止", stop_enabled, "" if stop_enabled else "not_running_task"),
            _action(
                "close_runtime",
                "关闭运行",
                close_enabled,
                "" if close_enabled else "not_closeable_runtime",
            ),
        ]
    )
    if graph_task:
        actions.append(_action("preview_delete_graph_run", "删除预览", bool(graph_run_id), "" if graph_run_id else "missing_graph_run_id"))
        actions.append(_action("delete_record", "删除记录", False, "graph_run_requires_graph_lifecycle"))
    else:
        delete_enabled = bool(task_run_id) and terminal and not running
        actions.append(_action("preview_delete_record", "删除预览", bool(task_run_id) and not running, "" if task_run_id and not running else "active_or_missing_task_run"))
        actions.append(_action("delete_record", "删除记录", delete_enabled, "" if delete_enabled else "active_or_non_terminal_runtime"))
    return actions


def _action(action: str, label: str, enabled: bool, disabled_reason: str = "") -> dict[str, Any]:
    return {
        "action": action,
        "label": label,
        "enabled": bool(enabled),
        "disabled_reason": "" if enabled else disabled_reason,
    }


def _is_default_visible(signal: dict[str, Any]) -> bool:
    return not bool(dict(signal.get("visibility") or {}).get("hidden") is True)


def _signal_id(signal: dict[str, Any]) -> str:
    return str(signal.get("signal_id") or signal.get("task_instance_id") or signal.get("task_run_id") or "").strip()


def _last_activity(signal: dict[str, Any]) -> float:
    timestamps = dict(signal.get("timestamps") or {})
    return float(timestamps.get("last_activity_at") or timestamps.get("updated_at") or 0.0)
