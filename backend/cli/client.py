from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .sse import ServerSentEvent, TERMINAL_STREAM_EVENTS
from .state import DEFAULT_API_BASE


UrlOpen = Callable[..., Any]


DEFAULT_CHAT_STREAM_MODEL_SELECTION: dict[str, Any] = {
    "stream_policy": {
        "enabled": True,
        "emit_assistant_text_delta": True,
        "upstream_reconnect_enabled": True,
        "partial_stream_recovery": "continue_from_visible_prefix",
        "chunk_strategy": "adaptive_buffer",
        "first_flush_delay_ms": 70,
        "target_buffer_delay_ms": 150,
        "adaptive_min_buffer_delay_ms": 80,
        "adaptive_max_buffer_delay_ms": 240,
        "release_tick_ms": 16,
        "max_buffer_delay_ms": 320,
        "max_flush_interval_ms": 80,
        "max_pending_utf8_bytes": 1536,
        "max_release_utf8_bytes": 192,
        "max_pending_line_count": 1,
        "min_event_interval_ms": 16,
        "event_budget_per_second": 45,
        "source": "backend.cli.chat_stream_default",
    }
}


class AgentCliClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StreamResult:
    terminal_event: str


class AgentCliClient:
    def __init__(
        self,
        *,
        api_base: str = DEFAULT_API_BASE,
        timeout: float | None = 60.0,
        stream_timeout: float | None = None,
        opener: UrlOpen = urlopen,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.stream_timeout = stream_timeout
        self._opener = opener

    def list_sessions(self) -> list[dict[str, Any]]:
        payload = self._json_request("GET", "/sessions")
        if not isinstance(payload, list):
            raise AgentCliClientError("Backend returned an invalid session list.")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def create_session(self, title: str = "CLI Session") -> dict[str, Any]:
        payload = self._json_request("POST", "/sessions", {"title": title})
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid session.")
        return dict(payload)

    def get_history(self, session_id: str) -> dict[str, Any]:
        payload = self._json_request("GET", f"/sessions/{_quote_path(session_id)}/history")
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid session history.")
        return dict(payload)

    def get_session_monitor(self, session_id: str) -> dict[str, Any]:
        payload = self._json_request(
            "GET",
            f"/orchestration/runtime-monitor/sessions/{_quote_path(session_id)}",
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid monitor payload.")
        return dict(payload)

    def get_task_run_monitor(self, task_run_id: str) -> dict[str, Any]:
        payload = self._json_request(
            "GET",
            f"/orchestration/runtime-monitor/task-runs/{_quote_path(task_run_id)}",
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid TaskRun monitor payload.")
        return dict(payload)

    def get_task_run_trace(self, task_run_id: str, *, include_payloads: bool = False) -> dict[str, Any]:
        suffix = "?include_payloads=true" if include_payloads else ""
        payload = self._json_request(
            "GET",
            f"/orchestration/harness/task-runs/{_quote_path(task_run_id)}{suffix}",
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid TaskRun trace payload.")
        return dict(payload)

    def execute_task_run(self, task_run_id: str, *, max_steps: int = 12) -> dict[str, Any]:
        payload = self._json_request(
            "POST",
            f"/orchestration/harness/task-runs/{_quote_path(task_run_id)}/execute",
            {"max_steps": max_steps},
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid task execution payload.")
        return dict(payload)

    def pause_task_run(self, task_run_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._task_run_control_request(task_run_id, "pause", reason=reason)

    def resume_task_run(self, task_run_id: str, *, max_steps: int = 12) -> dict[str, Any]:
        payload = self._json_request(
            "POST",
            f"/orchestration/harness/task-runs/{_quote_path(task_run_id)}/resume",
            {"max_steps": max_steps},
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid task resume payload.")
        return dict(payload)

    def stop_task_run(self, task_run_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._task_run_control_request(task_run_id, "stop", reason=reason)

    def _task_run_control_request(self, task_run_id: str, action: str, *, reason: str = "") -> dict[str, Any]:
        payload = self._json_request(
            "POST",
            f"/orchestration/harness/task-runs/{_quote_path(task_run_id)}/{action}",
            {"reason": reason},
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError(f"Backend returned an invalid task {action} payload.")
        return dict(payload)

    def get_config(self) -> dict[str, Any]:
        return {"api_base": self.api_base}

    def stream_chat(
        self,
        *,
        session_id: str,
        message: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> Iterator[ServerSentEvent]:
        body = {
            "session_id": session_id,
            "message": message,
            "stream": True,
            "environment_binding": {},
            "model_selection": _merge_model_selection(
                DEFAULT_CHAT_STREAM_MODEL_SELECTION,
                dict(extra_payload.get("model_selection") or {}) if isinstance(extra_payload, dict) else {},
            ),
            "image_generation": {},
        }
        if extra_payload:
            for key, value in extra_payload.items():
                if key == "model_selection":
                    continue
                body[key] = value
        run = self._json_request("POST", "/chat/runs", body)
        if not isinstance(run, dict):
            raise AgentCliClientError("Backend returned an invalid chat run.")
        stream_run_id = str(run.get("stream_run_id") or "").strip()
        if not stream_run_id:
            raise AgentCliClientError("Backend returned a chat run without stream_run_id.")
        latest_offset = -1
        terminal_event = ""
        deadline = time.monotonic() + float(self.stream_timeout) if self.stream_timeout is not None else None
        while not terminal_event:
            if deadline is not None and time.monotonic() > deadline:
                raise AgentCliClientError("Chat stream replay polling timed out before a terminal event.")
            replay = self._json_request(
                "GET",
                f"/chat/runs/{_quote_path(stream_run_id)}/events/replay?after_offset={latest_offset}&limit=500",
            )
            if not isinstance(replay, dict):
                raise AgentCliClientError("Backend returned an invalid chat replay payload.")
            emitted = False
            for envelope in list(replay.get("events") or []):
                if not isinstance(envelope, dict):
                    continue
                event_name = str(envelope.get("public_event_type") or "message")
                data = dict(envelope.get("data") or {})
                event_offset = int(envelope.get("event_offset") or latest_offset)
                latest_offset = max(latest_offset, event_offset)
                emitted = True
                event = ServerSentEvent(
                    event=event_name,
                    data=data,
                    event_id=str(envelope.get("event_id") or ""),
                )
                yield event
                if event.event in TERMINAL_STREAM_EVENTS or envelope.get("terminal") is True:
                    terminal_event = event.event
                    break
            if terminal_event:
                break
            if not emitted:
                time.sleep(0.05)

    def _json_request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = self._request(method, path, body)
        try:
            response = self._opener(request, timeout=self.timeout)
            raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise AgentCliClientError(_read_http_error(exc)) from exc
        except URLError as exc:
            raise AgentCliClientError(str(exc.reason)) from exc
        if not raw.strip():
            return None
        return json.loads(raw)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        accept: str = "application/json",
    ) -> Request:
        data = None
        headers = {"Accept": accept}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return Request(f"{self.api_base}{path}", data=data, headers=headers, method=method)


def _read_http_error(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        raw = ""
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("error")
            if detail:
                return str(detail)
    return f"HTTP {exc.code}"


def _quote_path(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _merge_model_selection(default_selection: dict[str, Any], override_selection: dict[str, Any]) -> dict[str, Any]:
    selection = {**dict(default_selection or {}), **dict(override_selection or {})}
    default_policy = dict(dict(default_selection or {}).get("stream_policy") or {})
    override_policy = dict(dict(override_selection or {}).get("stream_policy") or {})
    if default_policy or override_policy:
        selection["stream_policy"] = {**default_policy, **override_policy}
    return selection


