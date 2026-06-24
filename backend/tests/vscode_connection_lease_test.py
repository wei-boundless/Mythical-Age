from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api import project_workspaces as project_workspaces_api
from api import vscode as vscode_api
from api.sessions import _get_session_history_coalesced
from integrations.vscode_connection.context_store import VSCodeConnectionStore
from integrations.vscode_connection.models import VSCodeConnectionLeaseConflict
from project_workspaces.service import project_workspace_key


def test_vscode_connection_lease_rejects_duplicate_owner(tmp_path: Path) -> None:
    store = VSCodeConnectionStore()
    session_manager = _SessionManagerStub(tmp_path)

    owner = store.acquire_connection(
        session_manager=session_manager,
        session_id="session-lease",
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:owner",
    )

    with pytest.raises(VSCodeConnectionLeaseConflict) as exc_info:
        store.acquire_connection(
            session_manager=session_manager,
            session_id="session-lease",
            workspace_roots=[str(tmp_path)],
            connection_id="vscode:duplicate",
        )

    assert exc_info.value.code == "lease_owned"
    assert exc_info.value.status_code == 429
    assert exc_info.value.owner["connection_id"] == owner.connection_id
    status = store.status("session-lease", session_manager=session_manager)
    assert status.connection_id == owner.connection_id
    assert status.duplicate_rejected_count == 1


def test_vscode_connection_lease_allows_takeover_after_expiry(tmp_path: Path) -> None:
    store = VSCodeConnectionStore()
    session_manager = _SessionManagerStub(tmp_path)

    owner = store.acquire_connection(
        session_manager=session_manager,
        session_id="session-takeover",
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:old",
    )
    key = f"session-takeover::{project_workspace_key(str(tmp_path.resolve()))}"
    store._leases_by_key[key] = replace(owner, expires_at=time.time() - 1)

    next_owner = store.acquire_connection(
        session_manager=session_manager,
        session_id="session-takeover",
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:new",
    )

    assert next_owner.connection_id == "vscode:new"
    assert store.status("session-takeover", session_manager=session_manager).connection_id == "vscode:new"


def test_vscode_command_poll_is_owner_only(tmp_path: Path) -> None:
    store = VSCodeConnectionStore()
    session_manager = _SessionManagerStub(tmp_path)
    store.acquire_connection(
        session_manager=session_manager,
        session_id="session-command",
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:owner",
    )

    with pytest.raises(VSCodeConnectionLeaseConflict) as exc_info:
        store.begin_command_poll(
            session_id="session-command",
            connection_id="vscode:other",
            session_manager=session_manager,
        )

    assert exc_info.value.code == "lease_owned"

    lease = store.begin_command_poll(
        session_id="session-command",
        connection_id="vscode:owner",
        session_manager=session_manager,
    )
    try:
        assert lease.connection_id == "vscode:owner"
        assert store.status("session-command", session_manager=session_manager).poller_count == 1
        with pytest.raises(VSCodeConnectionLeaseConflict) as duplicate_poll:
            store.begin_command_poll(
                session_id="session-command",
                connection_id="vscode:owner",
                session_manager=session_manager,
            )
        assert duplicate_poll.value.code == "duplicate_poller"
    finally:
        store.end_command_poll("vscode:owner")


def test_vscode_session_resolve_requires_launch_intent(tmp_path: Path) -> None:
    store = VSCodeConnectionStore()

    missing = store.resolve_launch_intent(
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:resolver",
    )
    store.register_launch_intent(session_id="session-launch", workspace_root=str(tmp_path))
    matched = store.resolve_launch_intent(
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:resolver",
    )

    assert missing == {"session_id": "", "reason": "no_matching_launch_intent"}
    assert matched["session_id"] == "session-launch"
    assert matched["authority"] == "integrations.vscode_connection.launch_intent"


def test_vscode_editor_context_requires_current_session_owner_lease(tmp_path: Path) -> None:
    store = VSCodeConnectionStore()
    session_manager = _SessionManagerStub(tmp_path)
    lease = store.acquire_connection(
        session_manager=session_manager,
        session_id="session-owner",
        workspace_roots=[str(tmp_path)],
        connection_id="vscode:owner",
    )
    store.record_context(
        session_manager=session_manager,
        session_id="session-owner",
        connection_id=lease.connection_id,
        editor_context={
            "workspace_roots": [str(tmp_path)],
            "active_file": {"path": "src/app.py"},
        },
    )

    owner_context = store.latest_editor_context("session-owner", session_manager=session_manager)
    other_status = store.status("session-other", session_manager=session_manager)
    other_context = store.latest_editor_context("session-other", session_manager=session_manager)
    store.release_connection(
        session_manager=session_manager,
        session_id="session-owner",
        connection_id=lease.connection_id,
    )
    released_owner_context = store.latest_editor_context("session-owner", session_manager=session_manager)

    assert owner_context["active_file"]["path"] == "src/app.py"
    assert other_status.connected is False
    assert other_status.connection_id == ""
    assert other_context == {}
    assert released_owner_context == {}


def test_removed_vscode_legacy_routes_are_not_registered() -> None:
    paths = {str(route.path) for route in [*vscode_api.router.routes, *project_workspaces_api.router.routes]}

    assert "/vscode/sessions/{session_id}/context/latest" not in paths
    assert "/project-workspaces/{project_key}/open-vscode" not in paths


def test_session_history_coalesces_concurrent_reads() -> None:
    manager = _HistoryManagerStub()

    async def run() -> list[dict]:
        return await asyncio.gather(
            *[
                _get_session_history_coalesced(manager, "session-history")
                for _ in range(8)
            ]
        )

    payloads = asyncio.run(run())

    assert manager.read_count == 1
    assert [payload["id"] for payload in payloads] == ["session-history"] * 8


def test_session_history_waiter_cancel_does_not_cancel_shared_read() -> None:
    manager = _HistoryManagerStub()

    async def run() -> dict:
        first = asyncio.create_task(_get_session_history_coalesced(manager, "session-history"))
        await asyncio.sleep(0)
        second = asyncio.create_task(_get_session_history_coalesced(manager, "session-history"))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await second

    payload = asyncio.run(run())

    assert manager.read_count == 1
    assert payload["id"] == "session-history"


class _SessionManagerStub:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = str(workspace_root.resolve())

    def get_project_binding(self, session_id: str) -> dict:
        return {"workspace_root": self.workspace_root, "source": "test"}

    def bind_project(self, session_id: str, *, workspace_root: str, source: str) -> dict:
        return {"workspace_root": self.workspace_root, "source": source}


class _HistoryManagerStub:
    read_count = 0

    def session_storage_signature(self, session_id: str) -> tuple[int, int]:
        return (1, 10)

    def get_history(self, session_id: str) -> dict:
        self.read_count += 1
        time.sleep(0.05)
        return {"id": session_id, "messages": []}

