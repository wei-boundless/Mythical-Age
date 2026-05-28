from __future__ import annotations

import io
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


def test_client_stream_chat_posts_to_chat_api_and_yields_events() -> None:
    captured: dict[str, object] = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return _Response(
            [
                b'event: content_delta\ndata: {"content": "hello"}\n\n',
                b'event: done\ndata: {"content": ""}\n\n',
            ]
        )

    client = AgentCliClient(api_base="http://127.0.0.1:8003/api", timeout=12, opener=opener)

    events = list(client.stream_chat(session_id="session-1", message="hi"))

    assert captured["url"] == "http://127.0.0.1:8003/api/chat"
    assert captured["method"] == "POST"
    assert '"stream": true' in str(captured["body"])
    assert '"session_id": "session-1"' in str(captured["body"])
    assert captured["timeout"] == 12
    assert [event.event for event in events] == ["content_delta", "done"]


def test_client_stream_chat_rejects_missing_terminal_event() -> None:
    def opener(_request, timeout):
        assert timeout > 0
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
            url="http://127.0.0.1:8003/api/chat",
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


def test_send_command_forwards_runtime_mode_and_soul_id(tmp_path: Path) -> None:
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
    args = build_parser().parse_args(["send", "--runtime-mode", "role", "--soul-id", "hebo", "hello"])
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_command(args, client=client, store=store, stdout=stdout, stderr=stderr)  # type: ignore[arg-type]

    assert code == 0
    assert client.calls == [("session-cli", "hello", {"runtime_mode": "role", "soul_id": "hebo"})]


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
    forbidden = ("QueryRuntime", "HarnessServiceHost", "query.runtime", "runtime import")
    for path in cli_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} imports or names forbidden runtime authority {token!r}"


