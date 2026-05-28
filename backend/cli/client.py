from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .sse import SSEDecoder, ServerSentEvent
from .state import DEFAULT_API_BASE


UrlOpen = Callable[..., Any]


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
            f"/orchestration/harness/sessions/{_quote_path(session_id)}/live-monitor",
        )
        if not isinstance(payload, dict):
            raise AgentCliClientError("Backend returned an invalid monitor payload.")
        return dict(payload)

    def get_task_run_monitor(self, task_run_id: str) -> dict[str, Any]:
        payload = self._json_request(
            "GET",
            f"/orchestration/harness/task-runs/{_quote_path(task_run_id)}/live-monitor",
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
            "ephemeral_system_messages": [],
            "task_selection": {},
            "model_selection": {},
            "image_generation": {},
        }
        if extra_payload:
            body.update(extra_payload)
        request = self._request("POST", "/chat", body)
        try:
            if self.stream_timeout is None:
                response = self._opener(request, timeout=None)
            else:
                response = self._opener(request, timeout=self.stream_timeout)
        except HTTPError as exc:
            raise AgentCliClientError(_read_http_error(exc)) from exc
        except URLError as exc:
            raise AgentCliClientError(str(exc.reason)) from exc

        decoder = SSEDecoder()
        terminal_event = ""
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            for event in decoder.feed(text):
                yield event
                if event.event in {"done", "error", "stopped"}:
                    terminal_event = event.event
                    break
            if terminal_event:
                break
        if not terminal_event:
            for event in decoder.flush():
                yield event
                if event.event in {"done", "error", "stopped"}:
                    terminal_event = event.event
        if not terminal_event:
            raise AgentCliClientError(
                "Chat stream ended without a terminal event. Check the backend log for a stream exception."
            )

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

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Request:
        data = None
        headers = {"Accept": "application/json"}
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


