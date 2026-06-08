from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from typing import Any, Iterable, TextIO

from .client import AgentCliClient, AgentCliClientError
from .sse import ServerSentEvent
from .state import CliStateStore, DEFAULT_API_BASE


CONTENT_EVENTS = {"token", "content_delta", "answer_candidate"}
PROGRESS_EVENTS = {
    "input_commit_gate",
    "runtime_assembly_compiled",
    "runtime_assembly_bound",
    "runtime_invocation_packet",
    "model_action_request",
    "model_action_admission",
    "runtime_step_summary",
    "task_run_lifecycle_started",
    "task_run_lifecycle_event",
    "agent_turn_terminal",
    "tool_start",
    "tool_end",
    "debug_trace",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backend session CLI")
    parser.add_argument("--api-base", default="", help=f"Backend API base, default {DEFAULT_API_BASE}")
    parser.add_argument("--state-path", default="", help="CLI local state file path")
    parser.add_argument("--verbose", action="store_true", help="Print compact runtime event payloads")

    subparsers = parser.add_subparsers(dest="command")

    session_parser = subparsers.add_parser("session", help="Manage backend sessions")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)
    session_subparsers.add_parser("list", help="List sessions")
    create_parser = session_subparsers.add_parser("create", help="Create a session")
    create_parser.add_argument("--title", default="CLI Session")
    use_parser = session_subparsers.add_parser("use", help="Select an existing session")
    use_parser.add_argument("session_id")
    history_parser = session_subparsers.add_parser("history", help="Show session history")
    history_parser.add_argument("--session", default="")

    send_parser = subparsers.add_parser("send", help="Send a streamed message")
    send_parser.add_argument("message", nargs="+")
    send_parser.add_argument("--session", default="")
    send_parser.add_argument("--task-environment-id", default="")

    monitor_parser = subparsers.add_parser("monitor", help="Show session live monitor")
    monitor_parser.add_argument("--session", default="")

    task_run_parser = subparsers.add_parser("task-run", help="Execute or inspect TaskRuns")
    task_run_subparsers = task_run_parser.add_subparsers(dest="task_run_command", required=True)
    execute_parser = task_run_subparsers.add_parser("execute", help="Execute a waiting single-agent TaskRun")
    execute_parser.add_argument("task_run_id")
    execute_parser.add_argument("--max-steps", type=int, default=12)
    execute_parser.add_argument("--no-watch", action="store_true", help="Only schedule execution and print the accepted payload")
    pause_parser = task_run_subparsers.add_parser("pause", help="Pause a running TaskRun")
    pause_parser.add_argument("task_run_id")
    pause_parser.add_argument("--reason", default="cli_pause")
    pause_parser.add_argument("--no-watch", action="store_true", help="Only request pause and print the accepted payload")
    resume_parser = task_run_subparsers.add_parser("resume", help="Resume a paused or waiting TaskRun")
    resume_parser.add_argument("task_run_id")
    resume_parser.add_argument("--max-steps", type=int, default=12)
    resume_parser.add_argument("--no-watch", action="store_true", help="Only schedule resume and print the accepted payload")
    stop_parser = task_run_subparsers.add_parser("stop", help="Stop a running TaskRun")
    stop_parser.add_argument("task_run_id")
    stop_parser.add_argument("--reason", default="cli_stop")
    watch_parser = task_run_subparsers.add_parser("watch", help="Watch a TaskRun until it reaches a terminal state")
    watch_parser.add_argument("task_run_id")
    trace_parser = task_run_subparsers.add_parser("trace", help="Print a TaskRun trace")
    trace_parser.add_argument("task_run_id")
    trace_parser.add_argument("--include-payloads", action="store_true")

    config_parser = subparsers.add_parser("config", help="Show CLI config")
    config_parser.add_argument("config_command", choices=["show"])

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    store = CliStateStore(_path_or_none(args.state_path))
    state = store.load()
    api_base = str(args.api_base or state.api_base or DEFAULT_API_BASE).rstrip("/")
    client = AgentCliClient(api_base=api_base)
    if not args.command:
        return run_interactive(
            client=client,
            store=store,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            verbose=bool(args.verbose),
        )
    return run_command(args, client=client, store=store, stdout=sys.stdout, stderr=sys.stderr)


def run_command(
    args: argparse.Namespace,
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        if args.command == "session":
            return _run_session_command(args, client=client, store=store, stdout=stdout)
        if args.command == "send":
            return _run_send(args, client=client, store=store, stdout=stdout, stderr=stderr)
        if args.command == "monitor":
            return _run_monitor(args, client=client, store=store, stdout=stdout)
        if args.command == "task-run":
            return _run_task_run_command(args, client=client, stdout=stdout)
        if args.command == "config":
            _print_json({"api_base": client.api_base, "selected_session_id": store.load().selected_session_id}, stdout)
            return 0
    except AgentCliClientError as exc:
        print(f"error: {exc}", file=stderr)
        return 1
    print("error: unknown command", file=stderr)
    return 2


def run_interactive(
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool = False,
) -> int:
    try:
        session_id = _ensure_interactive_session(client=client, store=store)
    except AgentCliClientError as exc:
        print(f"error: {exc}", file=stderr)
        return 1

    print(f"Backend CLI session: {session_id}", file=stdout)
    print("Type a message to send. Slash commands: /help /new /sessions /use /history /monitor /exit", file=stdout)

    while True:
        if _is_tty(stdin):
            print(f"\n{_short_session_id(store.load().selected_session_id)}> ", end="", flush=True, file=stdout)
        line = stdin.readline()
        if line == "":
            print("", file=stdout)
            return 0
        text = line.strip()
        if not text:
            continue
        try:
            if text.startswith("/"):
                should_exit = _run_interactive_slash_command(
                    text,
                    client=client,
                    store=store,
                    stdout=stdout,
                    stderr=stderr,
                    verbose=verbose,
                )
                if should_exit:
                    return 0
                continue
            _send_message_text(text, client=client, store=store, stdout=stdout, stderr=stderr, verbose=verbose)
        except AgentCliClientError as exc:
            print(f"error: {exc}", file=stderr)


def _ensure_interactive_session(*, client: AgentCliClient, store: CliStateStore) -> str:
    state = store.load()
    if state.selected_session_id:
        return state.selected_session_id
    session = client.create_session("CLI Session")
    session_id = str(session.get("id") or "")
    if not session_id:
        raise AgentCliClientError("Backend created a session without an id.")
    store.update(api_base=client.api_base, selected_session_id=session_id)
    return session_id


def _run_interactive_slash_command(
    text: str,
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool,
) -> bool:
    parts = shlex.split(text)
    command = parts[0].lower()
    rest = parts[1:]
    if command in {"/exit", "/quit", "/q"}:
        print("bye", file=stdout)
        return True
    if command in {"/help", "/h"}:
        print("/new [title]        create and switch to a new session", file=stdout)
        print("/sessions           list backend sessions", file=stdout)
        print("/use <session_id>   switch session", file=stdout)
        print("/history            show current session history", file=stdout)
        print("/monitor            show current session live monitor", file=stdout)
        print("/config             show CLI config", file=stdout)
        print("/exit               leave the CLI", file=stdout)
        return False
    if command == "/new":
        title = " ".join(rest).strip() or "CLI Session"
        session = client.create_session(title)
        session_id = str(session.get("id") or "")
        store.update(api_base=client.api_base, selected_session_id=session_id)
        print(f"created {session_id}", file=stdout)
        return False
    if command in {"/sessions", "/session"}:
        _print_sessions(client.list_sessions(), selected_session_id=store.load().selected_session_id, stdout=stdout)
        return False
    if command == "/use":
        if not rest:
            raise AgentCliClientError("Usage: /use <session_id>")
        store.update(api_base=client.api_base, selected_session_id=rest[0])
        print(f"using {rest[0]}", file=stdout)
        return False
    if command == "/history":
        _print_history(client.get_history(_resolve_session_id("", store)), stdout)
        return False
    if command == "/monitor":
        _print_json(client.get_session_monitor(_resolve_session_id("", store)), stdout)
        return False
    if command == "/config":
        _print_json({"api_base": client.api_base, "selected_session_id": store.load().selected_session_id}, stdout)
        return False
    if command == "/send":
        message = " ".join(rest).strip()
        if not message:
            raise AgentCliClientError("Usage: /send <message>")
        _send_message_text(message, client=client, store=store, stdout=stdout, stderr=stderr, verbose=verbose)
        return False
    raise AgentCliClientError(f"Unknown slash command: {command}")


def _run_session_command(
    args: argparse.Namespace,
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdout: TextIO,
) -> int:
    if args.session_command == "list":
        _print_sessions(client.list_sessions(), selected_session_id=store.load().selected_session_id, stdout=stdout)
        return 0
    if args.session_command == "create":
        session = client.create_session(args.title)
        session_id = str(session.get("id") or "")
        store.update(api_base=client.api_base, selected_session_id=session_id)
        print(f"created {session_id}", file=stdout)
        return 0
    if args.session_command == "use":
        store.update(api_base=client.api_base, selected_session_id=args.session_id)
        print(f"using {args.session_id}", file=stdout)
        return 0
    if args.session_command == "history":
        session_id = _resolve_session_id(args.session, store)
        _print_history(client.get_history(session_id), stdout)
        return 0
    return 2


def _run_send(
    args: argparse.Namespace,
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    session_id = _resolve_session_id(args.session, store)
    message = " ".join(args.message).strip()
    extra_payload = _runtime_extra_payload(
        task_environment_id=str(getattr(args, "task_environment_id", "") or ""),
    )
    _send_message_text(
        message,
        client=client,
        store=store,
        stdout=stdout,
        stderr=stderr,
        verbose=bool(args.verbose),
        session_id=session_id,
        extra_payload=extra_payload,
    )
    return 0


def _send_message_text(
    message: str,
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool,
    session_id: str = "",
    extra_payload: dict[str, Any] | None = None,
) -> None:
    resolved_session_id = session_id or _resolve_session_id("", store)
    terminal = ""
    for event in client.stream_chat(session_id=resolved_session_id, message=message, extra_payload=extra_payload):
        terminal = _render_stream_event(event, stdout=stdout, stderr=stderr, verbose=verbose) or terminal
    if terminal == "error":
        raise AgentCliClientError("Backend returned an error event.")


def _run_monitor(
    args: argparse.Namespace,
    *,
    client: AgentCliClient,
    store: CliStateStore,
    stdout: TextIO,
) -> int:
    session_id = _resolve_session_id(args.session, store)
    monitor = client.get_session_monitor(session_id)
    _print_json(monitor, stdout)
    return 0


def _run_task_run_command(
    args: argparse.Namespace,
    *,
    client: AgentCliClient,
    stdout: TextIO,
) -> int:
    if args.task_run_command == "execute":
        result = client.execute_task_run(
            args.task_run_id,
            max_steps=max(1, int(args.max_steps or 12)),
        )
        if bool(getattr(args, "no_watch", False)):
            _print_json(result, stdout)
            return 0 if result.get("ok") else 1
        print(f"scheduled {args.task_run_id}", file=stdout)
        return _watch_task_run(args.task_run_id, client=client, stdout=stdout)
    if args.task_run_command == "pause":
        result = client.pause_task_run(args.task_run_id, reason=str(args.reason or "cli_pause"))
        if bool(getattr(args, "no_watch", False)):
            _print_json(result, stdout)
            return 0 if result.get("ok") else 1
        if not result.get("ok"):
            _print_json(result, stdout)
            return 1
        print(f"pause requested {args.task_run_id}", file=stdout)
        return _watch_task_run(args.task_run_id, client=client, stdout=stdout)
    if args.task_run_command == "resume":
        result = client.resume_task_run(args.task_run_id, max_steps=max(1, int(args.max_steps or 12)))
        if bool(getattr(args, "no_watch", False)):
            _print_json(result, stdout)
            return 0 if result.get("ok") else 1
        print(f"resumed {args.task_run_id}", file=stdout)
        return _watch_task_run(args.task_run_id, client=client, stdout=stdout)
    if args.task_run_command == "stop":
        result = client.stop_task_run(args.task_run_id, reason=str(args.reason or "cli_stop"))
        _print_json(result, stdout)
        return 0 if result.get("ok") else 1
    if args.task_run_command == "watch":
        return _watch_task_run(args.task_run_id, client=client, stdout=stdout)
    if args.task_run_command == "trace":
        _print_json(
            client.get_task_run_trace(
                args.task_run_id,
                include_payloads=bool(getattr(args, "include_payloads", False)),
            ),
            stdout,
        )
        return 0
    return 2


def _watch_task_run(task_run_id: str, *, client: AgentCliClient, stdout: TextIO) -> int:
    seen_event_count = -1
    seen_step = ""
    while True:
        monitor = client.get_task_run_monitor(task_run_id)
        event_count = int(monitor.get("event_count") or 0)
        status = str(monitor.get("status") or "")
        latest = dict(monitor.get("latest_event") or {})
        payload = dict(latest.get("payload") or {})
        step = str(payload.get("step") or "")
        summary = str(payload.get("summary") or "")
        if event_count != seen_event_count or step != seen_step:
            if step or summary:
                print(f"[{status}] {step or latest.get('event_type')}: {summary}", file=stdout)
            else:
                print(f"[{status}] {latest.get('event_type') or 'monitor'}", file=stdout)
            seen_event_count = event_count
            seen_step = step
        if status in {"completed", "failed", "aborted", "cancelled", "error", "blocked", "waiting_executor"}:
            trace = client.get_task_run_trace(task_run_id, include_payloads=False)
            final_task = dict(trace.get("task_run") or {})
            diagnostics = dict(final_task.get("diagnostics") or {})
            artifact_refs = diagnostics.get("artifact_refs") or []
            final_answer = str(diagnostics.get("final_answer") or "")
            terminal_reason = str(final_task.get("terminal_reason") or monitor.get("terminal_reason") or "")
            recoverable_error = dict(diagnostics.get("recoverable_error") or {})
            if artifact_refs:
                print("artifacts:", file=stdout)
                for item in list(artifact_refs):
                    print(f"- {item}", file=stdout)
            if final_answer:
                print(final_answer, file=stdout)
            elif status == "waiting_executor":
                message = str(recoverable_error.get("user_message") or terminal_reason or "waiting_executor")
                print(message, file=stdout)
            elif terminal_reason:
                print(terminal_reason, file=stdout)
            return 0 if status in {"completed", "waiting_executor"} else 1
        time.sleep(2.0)


def _render_stream_event(
    event: ServerSentEvent,
    *,
    stdout: TextIO,
    stderr: TextIO,
    verbose: bool,
) -> str:
    if event.event in CONTENT_EVENTS:
        content = str(event.data.get("content") or "")
        if content:
            print(content, end="", flush=True, file=stdout)
        return ""
    if event.event == "done":
        content = str(event.data.get("content") or "")
        if content:
            print(content, end="", flush=True, file=stdout)
        print("", file=stdout)
        return "done"
    if event.event == "error":
        error = str(event.data.get("error") or "unknown error")
        code = str(event.data.get("code") or "").strip()
        suffix = f" ({code})" if code else ""
        print(f"\nerror: {error}{suffix}", file=stderr)
        return "error"
    if event.event == "stopped":
        print("\nstopped", file=stderr)
        return "stopped"
    if verbose:
        print(f"\n[{event.event}] {_compact_json(event.data)}", file=stderr)
    elif event.event in PROGRESS_EVENTS:
        print(f"\n[{event.event}]", file=stderr)
    return ""


def _resolve_session_id(explicit: str, store: CliStateStore) -> str:
    session_id = str(explicit or store.load().selected_session_id or "").strip()
    if not session_id:
        raise AgentCliClientError("No session selected. Run `session create` or `session use <session_id>` first.")
    return session_id


def _print_json(payload: Any, stdout: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stdout)


def _print_sessions(sessions: list[dict[str, Any]], *, selected_session_id: str, stdout: TextIO) -> None:
    if not sessions:
        print("No sessions.", file=stdout)
        return
    for item in sessions:
        marker = "*" if item.get("id") == selected_session_id else " "
        print(
            f"{marker} {item.get('id', '')}  {item.get('title', '')}  messages={item.get('message_count', 0)}",
            file=stdout,
        )


def _print_history(history: dict[str, Any], stdout: TextIO) -> None:
    for message in list(history.get("messages") or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "message")
        content = str(message.get("content") or "")
        print(f"{role}: {content}", file=stdout)


def _compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _path_or_none(value: str):
    if not value:
        return None
    from pathlib import Path

    return Path(value)


def _runtime_extra_payload(*, task_environment_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {}
    environment_id = str(task_environment_id or "").strip()
    if environment_id:
        payload["environment_binding"] = {"task_environment_id": environment_id}
    return payload


def _is_tty(stream: TextIO) -> bool:
    return bool(getattr(stream, "isatty", lambda: False)())


def _short_session_id(session_id: str) -> str:
    if len(session_id) <= 14:
        return session_id or "session"
    return f"{session_id[:10]}..."


if __name__ == "__main__":
    raise SystemExit(main())


