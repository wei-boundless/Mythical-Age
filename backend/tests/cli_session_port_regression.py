from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cli.client import AgentCliClient, AgentCliClientError
from cli.main import build_parser, run_command, run_interactive
from cli.sse import SSEDecoder, decode_sse_text_chunks
from cli.state import CliStateStore


class _Response:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_sse_decoder_handles_chunk_boundaries_and_terminal_event() -> None:
    events = decode_sse_text_chunks(
        [
            'event: token\ndata: {"content": "你',
            '好"}\n\nevent: done\ndata: {"content": ""}\n\n',
        ]
    )

    assert [event.event for event in events] == ["token", "done"]
    assert events[0].data == {"content": "你好"}


def test_sse_decoder_rejects_unbounded_buffer() -> None:
    decoder = SSEDecoder()

    try:
        decoder.feed("x" * (1024 * 1024 + 1))
    except ValueError as exc:
        assert "SSE buffer exceeded" in str(exc)
    else:
        raise AssertionError("decoder accepted an unbounded SSE buffer")


def test_client_stream_chat_uses_chat_run_api_and_yields_events() -> None:
    calls: list[dict[str, object]] = []

    def opener(request, timeout):
        call = {
            "url": request.full_url,
            "method": request.get_method(),
            "body": request.data.decode("utf-8") if request.data else "",
            "timeout": timeout,
            "accept": request.get_header("Accept"),
        }
        calls.append(call)
        if call["method"] == "POST":
            return _Response(
                [
                    json.dumps(
                        {
                            "stream_run_id": "strun:cli",
                            "event_log_id": "chatrun:cli",
                            "latest_event_offset": -1,
                        }
                    ).encode("utf-8")
                ]
            )
        return _Response(
            [
                b'event: content_delta\ndata: {"content": "hello"}\n\n',
                b'event: done\ndata: {"content": ""}\n\n',
            ]
        )

    client = AgentCliClient(api_base="http://127.0.0.1:8003/api", timeout=12, stream_timeout=34, opener=opener)

    events = list(client.stream_chat(session_id="session-1", message="hi"))

    assert calls[0]["url"] == "http://127.0.0.1:8003/api/chat/runs"
    assert calls[0]["method"] == "POST"
    assert '"stream": true' in str(calls[0]["body"])
    assert '"session_id": "session-1"' in str(calls[0]["body"])
    assert calls[0]["timeout"] == 12
    assert calls[1]["url"] == "http://127.0.0.1:8003/api/chat/runs/strun%3Acli/events?after_offset=-1"
    assert calls[1]["method"] == "GET"
    assert calls[1]["accept"] == "text/event-stream"
    assert calls[1]["timeout"] == 34
    assert [event.event for event in events] == ["content_delta", "done"]


def test_client_stream_chat_uses_no_socket_timeout_by_default() -> None:
    timeouts: list[float | None] = []

    def opener(request, timeout):
        timeouts.append(timeout)
        if request.get_method() == "POST":
            return _Response([b'{"stream_run_id":"strun:cli","event_log_id":"chatrun:cli"}'])
        return _Response([b'event: done\ndata: {"content": ""}\n\n'])

    client = AgentCliClient(opener=opener)

    events = list(client.stream_chat(session_id="session-1", message="hi"))

    assert timeouts == [60.0, None]
    assert [event.event for event in events] == ["done"]


def test_client_stream_chat_rejects_missing_terminal_event() -> None:
    def opener(request, timeout):
        if request.get_method() == "POST":
            assert timeout == 60.0
            return _Response([b'{"stream_run_id":"strun:cli","event_log_id":"chatrun:cli"}'])
        assert timeout is None
        return _Response([b'event: token\ndata: {"content": "partial"}\n\n'])

    client = AgentCliClient(opener=opener)

    try:
        list(client.stream_chat(session_id="session-1", message="hi"))
    except AgentCliClientError as exc:
        assert "terminal event" in str(exc)
    else:
        raise AssertionError("stream without terminal event was accepted")


def test_client_reports_backend_http_error_detail() -> None:
    def opener(_request, timeout):
        assert timeout > 0
        raise HTTPError(
            url="http://127.0.0.1:8003/api/sessions",
            code=400,
            msg="bad request",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"Invalid session_id"}'),
        )

    client = AgentCliClient(opener=opener)

    try:
        client.list_sessions()
    except AgentCliClientError as exc:
        assert str(exc) == "Invalid session_id"
    else:
        raise AssertionError("HTTP error was not surfaced")


def test_send_command_uses_selected_session_and_stream_client(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = CliStateStore(state_path)
    store.update(api_base="http://127.0.0.1:8003/api", selected_session_id="session-cli")

    class FakeClient:
        api_base = "http://127.0.0.1:8003/api"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object] | None]] = []

        def stream_chat(self, *, session_id: str, message: str, extra_payload=None):
            self.calls.append((session_id, message, extra_payload))
            yield SimpleNamespace(event="content_delta", data={"content": "ok"})
            yield SimpleNamespace(event="done", data={"content": ""})

    client = FakeClient()
    args = build_parser().parse_args(["send", "hello", "cli"])
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_command(args, client=client, store=store, stdout=stdout, stderr=stderr)  # type: ignore[arg-type]

    assert code == 0
    assert client.calls == [("session-cli", "hello cli", {})]
    assert stdout.getvalue() == "ok\n"


def test_send_command_forwards_environment(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = CliStateStore(state_path)
    store.update(api_base="http://127.0.0.1:8003/api", selected_session_id="session-cli")

    class FakeClient:
        api_base = "http://127.0.0.1:8003/api"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object] | None]] = []

        def stream_chat(self, *, session_id: str, message: str, extra_payload=None):
            self.calls.append((session_id, message, extra_payload))
            yield SimpleNamespace(event="done", data={"content": ""})

    client = FakeClient()
    args = build_parser().parse_args(
        [
            "send",
            "--task-environment-id",
            "env.development.sandbox",
            "hello",
        ]
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_command(args, client=client, store=store, stdout=stdout, stderr=stderr)  # type: ignore[arg-type]

    assert code == 0
    assert client.calls == [
        (
            "session-cli",
            "hello",
            {
                "environment_binding": {"task_environment_id": "env.development.sandbox"},
            },
        )
    ]


def test_task_run_watch_exits_on_waiting_executor() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.monitor_calls = 0

        def execute_task_run(self, task_run_id: str, *, max_steps: int = 12):
            assert task_run_id == "taskrun:test"
            assert max_steps == 1
            return {"ok": True}

        def get_task_run_monitor(self, task_run_id: str):
            self.monitor_calls += 1
            return {
                "status": "waiting_executor",
                "event_count": 3,
                "terminal_reason": "waiting_executor",
                "latest_event": {
                    "event_type": "step_summary_recorded",
                    "payload": {
                        "step": "task_executor_waiting_next_run",
                        "summary": "本轮执行步数预算已用尽，任务未失败，已等待下一次执行器续跑。",
                    },
                },
            }

        def get_task_run_trace(self, task_run_id: str, *, include_payloads: bool = False):
            return {
                "task_run": {
                    "status": "waiting_executor",
                    "terminal_reason": "waiting_executor",
                    "diagnostics": {
                        "recoverable_error": {
                            "user_message": "本轮执行步数预算已用尽，任务保持可续跑状态。"
                        }
                    },
                }
            }

    client = FakeClient()
    args = build_parser().parse_args(["task-run", "execute", "taskrun:test", "--max-steps", "1"])
    stdout = io.StringIO()

    code = run_command(args, client=client, store=CliStateStore(), stdout=stdout, stderr=io.StringIO())  # type: ignore[arg-type]

    assert code == 0
    assert client.monitor_calls == 1
    assert "任务保持可续跑状态" in stdout.getvalue()


def test_task_run_start_sends_explicit_contract_and_prints_task_id(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = CliStateStore(state_path)
    store.update(api_base="http://127.0.0.1:8003/api", selected_session_id="session-cli")
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "user_visible_goal": "完成 CLI 长任务启动测试。",
                "task_run_goal": "完成 CLI 长任务启动测试。",
                "completion_criteria": ["启动 TaskRun"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeClient:
        api_base = "http://127.0.0.1:8003/api"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object] | None]] = []

        def stream_chat(self, *, session_id: str, message: str, extra_payload=None):
            self.calls.append((session_id, message, extra_payload))
            yield SimpleNamespace(
                event="task_run_lifecycle_started",
                data={
                    "event": {
                        "payload": {
                            "task_run": {"task_run_id": "taskrun:cli-start"},
                        }
                    }
                },
            )
            yield SimpleNamespace(event="done", data={"content": ""})

    client = FakeClient()
    args = build_parser().parse_args(
        [
            "task-run",
            "start",
            "--contract-file",
            str(contract_path),
            "--task-environment-id",
            "env.development.sandbox",
            "--no-watch",
        ]
    )
    stdout = io.StringIO()

    code = run_command(args, client=client, store=store, stdout=stdout, stderr=io.StringIO())  # type: ignore[arg-type]

    assert code == 0
    assert client.calls[0][0] == "session-cli"
    assert client.calls[0][1] == "启动任务：完成 CLI 长任务启动测试。"
    extra_payload = dict(client.calls[0][2] or {})
    runtime_contract = dict(extra_payload["runtime_contract"])  # type: ignore[index]
    task_contract = dict(runtime_contract["task_contract"])  # type: ignore[index]
    assert runtime_contract["system_issued_contract"] is True
    assert runtime_contract["task_environment_id"] == "env.development.sandbox"
    assert task_contract["system_issued"] is True
    assert task_contract["task_environment_id"] == "env.development.sandbox"
    assert dict(extra_payload["environment_binding"])["task_environment_id"] == "env.development.sandbox"  # type: ignore[index]
    assert "task_run_id taskrun:cli-start" in stdout.getvalue()


def test_task_run_watch_exits_on_aborted() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.monitor_calls = 0

        def get_task_run_monitor(self, task_run_id: str):
            self.monitor_calls += 1
            return {
                "status": "aborted",
                "event_count": 4,
                "terminal_reason": "user_aborted",
                "latest_event": {
                    "event_type": "step_summary_recorded",
                    "payload": {"step": "task_run_stopped", "summary": "任务已按用户要求停止。"},
                },
            }

        def get_task_run_trace(self, task_run_id: str, *, include_payloads: bool = False):
            return {"task_run": {"status": "aborted", "terminal_reason": "user_aborted", "diagnostics": {}}}

    client = FakeClient()
    args = build_parser().parse_args(["task-run", "watch", "taskrun:test"])
    stdout = io.StringIO()

    code = run_command(args, client=client, store=CliStateStore(), stdout=stdout, stderr=io.StringIO())  # type: ignore[arg-type]

    assert code == 1
    assert client.monitor_calls == 1
    assert "user_aborted" in stdout.getvalue()


def test_task_run_control_commands_call_backend_client() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object]]] = []

        def pause_task_run(self, task_run_id: str, *, reason: str = ""):
            self.calls.append(("pause", task_run_id, {"reason": reason}))
            return {"ok": True, "task_run_id": task_run_id}

        def resume_task_run(self, task_run_id: str, *, max_steps: int = 12):
            self.calls.append(("resume", task_run_id, {"max_steps": max_steps}))
            return {"ok": True, "task_run_id": task_run_id}

        def stop_task_run(self, task_run_id: str, *, reason: str = ""):
            self.calls.append(("stop", task_run_id, {"reason": reason}))
            return {"ok": True, "task_run_id": task_run_id}

        def get_task_run_monitor(self, task_run_id: str):
            return {
                "status": "waiting_executor",
                "event_count": 1,
                "terminal_reason": "waiting_executor",
                "latest_event": {"event_type": "step_summary_recorded", "payload": {"step": "task_run_paused", "summary": "已暂停。"}},
            }

        def get_task_run_trace(self, task_run_id: str, *, include_payloads: bool = False):
            return {"task_run": {"status": "waiting_executor", "terminal_reason": "waiting_executor", "diagnostics": {"recoverable_error": {"user_message": "已暂停。"}}}}

    client = FakeClient()
    stdout = io.StringIO()
    store = CliStateStore()

    assert run_command(build_parser().parse_args(["task-run", "pause", "taskrun:test", "--reason", "p", "--no-watch"]), client=client, store=store, stdout=stdout, stderr=io.StringIO()) == 0  # type: ignore[arg-type]
    assert run_command(build_parser().parse_args(["task-run", "resume", "taskrun:test", "--max-steps", "3", "--no-watch"]), client=client, store=store, stdout=stdout, stderr=io.StringIO()) == 0  # type: ignore[arg-type]
    assert run_command(build_parser().parse_args(["task-run", "stop", "taskrun:test", "--reason", "s"]), client=client, store=store, stdout=stdout, stderr=io.StringIO()) == 0  # type: ignore[arg-type]

    assert client.calls == [
        ("pause", "taskrun:test", {"reason": "p"}),
        ("resume", "taskrun:test", {"max_steps": 3}),
        ("stop", "taskrun:test", {"reason": "s"}),
    ]


def test_task_run_pause_watches_until_waiting_by_default() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.pause_calls = 0
            self.monitor_calls = 0

        def pause_task_run(self, task_run_id: str, *, reason: str = ""):
            self.pause_calls += 1
            return {"ok": True, "task_run_id": task_run_id}

        def get_task_run_monitor(self, task_run_id: str):
            self.monitor_calls += 1
            return {
                "status": "waiting_executor",
                "event_count": 2,
                "terminal_reason": "waiting_executor",
                "latest_event": {"event_type": "step_summary_recorded", "payload": {"step": "task_run_paused", "summary": "已暂停。"}},
            }

        def get_task_run_trace(self, task_run_id: str, *, include_payloads: bool = False):
            return {"task_run": {"status": "waiting_executor", "terminal_reason": "waiting_executor", "diagnostics": {"recoverable_error": {"user_message": "已暂停。"}}}}

    client = FakeClient()
    stdout = io.StringIO()

    code = run_command(build_parser().parse_args(["task-run", "pause", "taskrun:test"]), client=client, store=CliStateStore(), stdout=stdout, stderr=io.StringIO())  # type: ignore[arg-type]

    assert code == 0
    assert client.pause_calls == 1
    assert client.monitor_calls == 1
    assert "pause requested taskrun:test" in stdout.getvalue()
    assert "已暂停" in stdout.getvalue()


def test_task_run_trace_prints_backend_trace() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object]]] = []

        def get_task_run_trace(self, task_run_id: str, *, include_payloads: bool = False):
            self.calls.append(("trace", task_run_id, {"include_payloads": include_payloads}))
            return {"task_run": {"task_run_id": task_run_id, "status": "aborted"}}

    client = FakeClient()
    stdout = io.StringIO()

    code = run_command(
        build_parser().parse_args(["task-run", "trace", "taskrun:test", "--include-payloads"]),
        client=client,
        store=CliStateStore(),
        stdout=stdout,
        stderr=io.StringIO(),
    )  # type: ignore[arg-type]

    assert code == 0
    assert client.calls == [("trace", "taskrun:test", {"include_payloads": True})]
    assert json.loads(stdout.getvalue()) == {"task_run": {"task_run_id": "taskrun:test", "status": "aborted"}}


def test_interactive_mode_sends_plain_text_and_exits(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = CliStateStore(state_path)
    store.update(api_base="http://127.0.0.1:8003/api", selected_session_id="session-cli")

    class FakeClient:
        api_base = "http://127.0.0.1:8003/api"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object] | None]] = []

        def stream_chat(self, *, session_id: str, message: str, extra_payload=None):
            self.calls.append((session_id, message, extra_payload))
            yield SimpleNamespace(event="content_delta", data={"content": "收到"})
            yield SimpleNamespace(event="done", data={"content": ""})

    client = FakeClient()
    stdin = io.StringIO("你好\n/exit\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_interactive(
        client=client,  # type: ignore[arg-type]
        store=store,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert client.calls == [("session-cli", "你好", None)]
    assert "Backend CLI session: session-cli" in stdout.getvalue()
    assert "收到" in stdout.getvalue()
    assert "bye" in stdout.getvalue()


def test_interactive_mode_creates_session_when_none_is_selected(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    store = CliStateStore(state_path)

    class FakeClient:
        api_base = "http://127.0.0.1:8003/api"

        def __init__(self) -> None:
            self.created = 0

        def create_session(self, title: str):
            self.created += 1
            return {"id": "session-created", "title": title}

    client = FakeClient()
    stdin = io.StringIO("/q\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_interactive(
        client=client,  # type: ignore[arg-type]
        store=store,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert client.created == 1
    assert store.load().selected_session_id == "session-created"
    assert "bye" in stdout.getvalue()


def test_cli_modules_do_not_import_runtime_internals() -> None:
    cli_dir = BACKEND_DIR / "cli"
    forbidden = ("HarnessRuntimeFacade", "HarnessServiceHost", "query.runtime", "runtime import")
    for path in cli_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} imports or names forbidden runtime authority {token!r}"


