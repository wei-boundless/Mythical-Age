from __future__ import annotations

import time
import asyncio
from types import SimpleNamespace

import api.chat as chat_api
from runtime.shared.queued_user_input_dispatcher import (
    chat_run_execution_attached,
    has_active_primary_chat_run,
    queued_input_admission_target,
    validate_queued_steer,
)
from runtime.shared.queued_user_input_store import QueuedUserInputStore
from runtime.shared.runtime_run_registry import RuntimeRun


def _runtime_run(
    stream_run_id: str,
    *,
    session_id: str = "session:runs",
    status: str = "running",
    run_cell_id: str = "runcell:attached",
) -> RuntimeRun:
    now = time.time()
    return RuntimeRun(
        stream_run_id=stream_run_id,
        session_id=session_id,
        event_log_id=f"chatrun:{stream_run_id.replace(':', '_')}",
        root_request_ref=f"chatreq:{stream_run_id.replace(':', '_')}",
        status=status,
        created_at=now,
        updated_at=now,
        latest_event_offset=0,
        reconnectable_until=now + 3600,
        diagnostics={
            "run_cell_id": run_cell_id,
            "agent_cell_primary": True,
        },
    )


def _supervisor_attached_to(stream_run_id: str, *, session_id: str = "session:runs", run_cell_id: str = "runcell:attached") -> SimpleNamespace:
    expected_session_id = session_id

    def active_cell_for_stream_run(candidate_stream_run_id: str, *, session_id: str) -> SimpleNamespace | None:
        if candidate_stream_run_id != stream_run_id or session_id != expected_session_id:
            return None
        return SimpleNamespace(scope=SimpleNamespace(run_cell_id=run_cell_id))

    return SimpleNamespace(active_cell_for_stream_run=active_cell_for_stream_run)


def test_queued_user_input_store_persists_and_deduplicates_by_client_message_id(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)

    first = store.enqueue(
        session_id="session:queue",
        content="补充一个限制条件",
        client_message_id="user:client:1",
        input_policy="steer",
        expected_active_turn_id="turn:session:queue:1",
        task_run_id="taskrun:session:queue:1",
        environment_binding={"task_environment_id": "code"},
        model_selection={"provider": "openai"},
        permission_mode="full_access",
        editor_context={"active_file": "app.py"},
    )
    duplicate = store.enqueue(
        session_id="session:queue",
        content="重复提交不应改写正文",
        client_message_id="user:client:1",
        input_policy="auto",
    )

    assert duplicate.queue_item_id == first.queue_item_id
    assert duplicate.content == "补充一个限制条件"
    persisted = QueuedUserInputStore(tmp_path).list_session("session:queue")
    assert [item.queue_item_id for item in persisted] == [first.queue_item_id]
    assert persisted[0].input_policy == "steer"
    assert persisted[0].expected_active_turn_id == "turn:session:queue:1"
    assert persisted[0].task_run_id == "taskrun:session:queue:1"
    assert persisted[0].environment_binding == {"task_environment_id": "code"}
    assert persisted[0].model_selection == {"provider": "openai"}
    assert persisted[0].permission_mode == "full_access"
    assert persisted[0].editor_context == {"active_file": "app.py"}


def test_queued_user_input_store_state_transitions_are_ordered_and_terminal(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)
    first = store.enqueue(session_id="session:state", content="第一条", client_message_id="user:1")
    second = store.enqueue(session_id="session:state", content="第二条", client_message_id="user:2")

    claimed = store.claim_next("session:state")
    assert claimed is not None
    assert claimed.queue_item_id == first.queue_item_id
    assert claimed.status == "dispatching"

    dispatched = store.mark_dispatched("session:state", first.queue_item_id, stream_run_id="strun:first")
    assert dispatched is not None
    assert dispatched.status == "dispatched"
    assert dispatched.dispatch_stream_run_id == "strun:first"

    cancel_dispatched = store.cancel("session:state", first.queue_item_id)
    assert cancel_dispatched is not None
    assert cancel_dispatched.status == "dispatched"

    canceled = store.cancel("session:state", second.queue_item_id)
    assert canceled is not None
    assert canceled.status == "canceled"
    assert [item.status for item in store.list_session("session:state", include_terminal=False)] == []


def test_queued_user_input_store_retargets_only_queued_dispatch_policy(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)
    item = store.enqueue(session_id="session:retarget", content="补充字体要求", client_message_id="user:retarget")

    retargeted = store.retarget_for_dispatch(
        "session:retarget",
        item.queue_item_id,
        input_policy="steer",
        expected_active_turn_id="turn:retarget",
        task_run_id="taskrun:retarget",
    )

    assert retargeted is not None
    assert retargeted.queue_item_id == item.queue_item_id
    assert retargeted.content == "补充字体要求"
    assert retargeted.input_policy == "steer"
    assert retargeted.expected_active_turn_id == "turn:retarget"
    assert retargeted.task_run_id == "taskrun:retarget"
    claimed = store.claim_next("session:retarget", policy="steer")
    assert claimed is not None
    assert claimed.queue_item_id == item.queue_item_id
    assert store.retarget_for_dispatch(
        "session:retarget",
        item.queue_item_id,
        input_policy="auto",
    ) is None


def test_queued_user_input_store_resets_stale_dispatching_without_touching_fresh_items(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)
    stale = store.enqueue(session_id="session:stale", content="旧 dispatching", client_message_id="user:old")
    fresh = store.enqueue(session_id="session:stale", content="新 dispatching", client_message_id="user:new")
    assert store.claim_next("session:stale").queue_item_id == stale.queue_item_id  # type: ignore[union-attr]
    assert store.claim_next("session:stale").queue_item_id == fresh.queue_item_id  # type: ignore[union-attr]

    items = store.list_session("session:stale")
    old_payload = [item.to_dict() for item in items]
    old_payload[0]["updated_at"] = time.time() - 1000
    store._write_items("session:stale", [store._items_from_payload({"items": old_payload}, "session:stale")[0], items[1]])  # type: ignore[attr-defined]

    reset = store.reset_stale_dispatching("session:stale", max_age_seconds=60)

    assert [item.queue_item_id for item in reset] == [stale.queue_item_id]
    statuses = {item.queue_item_id: item.status for item in store.list_session("session:stale")}
    assert statuses[stale.queue_item_id] == "queued"
    assert statuses[fresh.queue_item_id] == "dispatching"


def test_queued_input_admission_uses_live_active_turn_authority() -> None:
    host = SimpleNamespace(
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda session_id: SimpleNamespace(
                turn_id="turn:live",
                bound_task_run_id="taskrun:live",
                steerable=True,
            )
        )
    )

    target = queued_input_admission_target(host, session_id="session:live")

    assert target == {
        "input_policy": "steer",
        "expected_active_turn_id": "turn:live",
        "task_run_id": "taskrun:live",
        "authority": "runtime.queued_user_input_dispatcher.admission_target",
    }


def test_validate_queued_steer_fails_closed_for_missing_or_mismatched_active_turn(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)
    item = store.enqueue(
        session_id="session:steer",
        content="接入当前任务",
        client_message_id="user:steer",
        input_policy="steer",
        expected_active_turn_id="turn:expected",
        task_run_id="taskrun:expected",
    )

    missing_host = SimpleNamespace(active_turn_registry=SimpleNamespace(resolve_current=lambda _session_id: None))
    assert validate_queued_steer(missing_host, item) == (False, "active_turn_unavailable")

    mismatch_host = SimpleNamespace(
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:other",
                bound_task_run_id="taskrun:expected",
                steerable=True,
            )
        )
    )
    assert validate_queued_steer(mismatch_host, item) == (False, "expected_active_turn_mismatch")

    task_mismatch_host = SimpleNamespace(
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:expected",
                bound_task_run_id="taskrun:other",
                steerable=True,
            )
        )
    )
    assert validate_queued_steer(task_mismatch_host, item) == (False, "expected_task_run_mismatch")

    not_steerable_host = SimpleNamespace(
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:expected",
                bound_task_run_id="taskrun:expected",
                steerable=False,
            )
        )
    )
    assert validate_queued_steer(not_steerable_host, item) == (False, "active_turn_not_steerable")


def test_validate_queued_steer_accepts_only_matching_live_active_turn(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)
    item = store.enqueue(
        session_id="session:steer",
        content="接入当前任务",
        client_message_id="user:steer",
        input_policy="steer",
        expected_active_turn_id="turn:expected",
        task_run_id="taskrun:expected",
    )
    host = SimpleNamespace(
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:expected",
                bound_task_run_id="taskrun:expected",
                steerable=True,
            )
        )
    )

    assert validate_queued_steer(host, item) == (True, "")


def test_validate_queued_steer_accepts_unbound_live_active_turn_without_task_requirement(tmp_path) -> None:
    store = QueuedUserInputStore(tmp_path)
    item = store.enqueue(
        session_id="session:steer-unbound",
        content="这是当前 active turn 的补充上下文",
        client_message_id="user:steer-unbound",
        input_policy="steer",
        expected_active_turn_id="turn:expected",
    )
    host = SimpleNamespace(
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:expected",
                bound_task_run_id="",
                steerable=True,
            )
        )
    )

    assert validate_queued_steer(host, item) == (True, "")


def test_active_chat_run_detection_requires_attached_runtime_cell() -> None:
    attached = _runtime_run("strun:attached")
    orphan = _runtime_run("strun:orphan")
    terminal = _runtime_run("strun:terminal", status="completed")
    host = SimpleNamespace(
        agent_run_supervisor=_supervisor_attached_to("strun:attached"),
        run_registry=SimpleNamespace(list_session_runs=lambda _session_id: [orphan, terminal, attached]),
    )

    terminal_statuses = {"completed", "failed", "stopped", "canceled", "cancelled"}
    assert chat_run_execution_attached(host, attached, terminal_statuses=terminal_statuses) is True
    assert chat_run_execution_attached(host, orphan, terminal_statuses=terminal_statuses) is False
    assert chat_run_execution_attached(host, terminal, terminal_statuses=terminal_statuses) is False
    assert has_active_primary_chat_run(host, session_id="session:runs", terminal_statuses=terminal_statuses) is True


def test_latest_chat_run_active_only_hides_orphan_runtime_run(monkeypatch) -> None:
    session_id = "session-runs"
    orphan = _runtime_run("strun:orphan", session_id=session_id)
    host = SimpleNamespace(
        agent_run_supervisor=_supervisor_attached_to("strun:other", session_id=session_id),
        run_registry=SimpleNamespace(list_session_runs=lambda _session_id: [orphan]),
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=host))
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)

    response = asyncio.run(chat_api.get_latest_chat_run_for_session(session_id, active_only=True))

    assert response.status_code == 204


def test_latest_chat_run_active_only_returns_attached_execution_signal(monkeypatch) -> None:
    session_id = "session-runs"
    attached = _runtime_run("strun:attached", session_id=session_id)
    host = SimpleNamespace(
        agent_run_supervisor=_supervisor_attached_to("strun:attached", session_id=session_id),
        run_registry=SimpleNamespace(list_session_runs=lambda _session_id: [attached]),
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=host))
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)

    response = asyncio.run(chat_api.get_latest_chat_run_for_session(session_id, active_only=True))

    assert response["stream_run_id"] == "strun:attached"
    assert response["chat_run_execution_attached"] is True
    assert response["is_reconnectable"] is True


def test_dispatch_retargets_auto_queue_item_to_live_active_turn_authority(tmp_path, monkeypatch) -> None:
    store = QueuedUserInputStore(tmp_path)
    item = store.enqueue(
        session_id="session:dispatch",
        content="主题还应该加入字体",
        client_message_id="user:dispatch",
        input_policy="auto",
    )
    monkeypatch.setattr(
        chat_api,
        "_create_and_schedule_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retargeted active-turn steer must not start a second run")),
    )
    session_manager = SimpleNamespace(
        get_history=lambda _session_id: {"scope": {"workspace_view": "chat", "task_environment_id": "", "project_id": ""}},
    )
    host = SimpleNamespace(
        queued_user_inputs=store,
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:dispatch",
                bound_task_run_id="taskrun:dispatch",
                steerable=True,
            )
        ),
        run_registry=SimpleNamespace(list_session_runs=lambda _session_id: []),
    )
    runtime = SimpleNamespace(
        session_manager=session_manager,
        harness_runtime=SimpleNamespace(single_agent_runtime_host=host),
    )

    run = asyncio.run(chat_api._dispatch_next_queued_input(runtime, "session:dispatch", reason="test"))

    assert run is None
    stored = store.get_item("session:dispatch", item.queue_item_id)
    assert stored is not None
    assert stored.status == "queued"
    assert stored.input_policy == "steer"
    assert stored.expected_active_turn_id == "turn:dispatch"
    assert stored.task_run_id == "taskrun:dispatch"


def test_queued_input_api_round_trips_store_projection_without_dispatching_active_session(tmp_path, monkeypatch) -> None:
    store = QueuedUserInputStore(tmp_path)
    session_manager = SimpleNamespace(
        get_history=lambda _session_id: {"scope": {"workspace_view": "chat", "task_environment_id": "", "project_id": ""}},
        get_project_binding=lambda _session_id: {},
        bind_project=lambda *_args, **_kwargs: None,
    )
    host = SimpleNamespace(
        queued_user_inputs=store,
        active_turn_registry=SimpleNamespace(resolve_current=lambda _session_id: None),
        agent_run_supervisor=_supervisor_attached_to("strun:session-api", session_id="session-api"),
        run_registry=SimpleNamespace(
            list_session_runs=lambda _session_id: [
                _runtime_run("strun:session-api", session_id="session-api")
            ]
        ),
    )
    runtime = SimpleNamespace(
        base_dir=tmp_path,
        session_manager=session_manager,
        harness_runtime=SimpleNamespace(single_agent_runtime_host=host),
    )
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)

    response = asyncio.run(
        chat_api.enqueue_queued_chat_input(
            "session-api",
            chat_api.QueuedChatInputRequest(
                message="排队输入",
                client_message_id="user:api",
                environment_binding={"task_environment_id": "code"},
                model_selection={"provider": "openai"},
                permission_mode="full_access",
            ),
        )
    )

    assert response["authority"] == "api.chat.queued_user_inputs"
    assert response["item"]["status"] == "queued"
    assert response["item"]["client_message_id"] == "user:api"
    assert response["item"]["input_policy"] == "auto"
    assert response["item"]["environment_binding"] == {"task_environment_id": "code"}
    assert response["item"]["model_selection"] == {"provider": "openai"}
    assert response["item"]["permission_mode"] == "full_access"

    listed = asyncio.run(
        chat_api.list_queued_chat_inputs(
            "session-api",
            include_terminal=True,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )
    assert [item["queue_item_id"] for item in listed["items"]] == [response["item"]["queue_item_id"]]

    canceled = asyncio.run(
        chat_api.cancel_queued_chat_input(
            "session-api",
            response["item"]["queue_item_id"],
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )
    assert canceled["authority"] == "api.chat.queued_user_inputs"
    assert canceled["item"]["status"] == "canceled"


def test_queued_input_api_targets_live_active_turn_without_starting_second_run(tmp_path, monkeypatch) -> None:
    store = QueuedUserInputStore(tmp_path)
    session_manager = SimpleNamespace(
        get_history=lambda _session_id: {"scope": {"workspace_view": "chat", "task_environment_id": "", "project_id": ""}},
        get_project_binding=lambda _session_id: {},
        bind_project=lambda *_args, **_kwargs: None,
    )
    host = SimpleNamespace(
        queued_user_inputs=store,
        active_turn_registry=SimpleNamespace(
            resolve_current=lambda _session_id: SimpleNamespace(
                turn_id="turn:session-api-live:1",
                bound_task_run_id="",
                steerable=True,
            )
        ),
        run_registry=SimpleNamespace(
            list_session_runs=lambda _session_id: [
                SimpleNamespace(status="running", diagnostics={"active_turn_input_policy": "auto"})
            ]
        ),
    )
    runtime = SimpleNamespace(
        base_dir=tmp_path,
        session_manager=session_manager,
        harness_runtime=SimpleNamespace(single_agent_runtime_host=host),
    )
    monkeypatch.setattr(chat_api, "require_runtime", lambda: runtime)
    monkeypatch.setattr(
        chat_api,
        "_create_and_schedule_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("active turn steer must not start a second run")),
    )

    response = asyncio.run(
        chat_api.enqueue_queued_chat_input(
            "session-api-live",
            chat_api.QueuedChatInputRequest(
                message="补充：设置页已有字体选项。",
                client_message_id="user:api-live",
            ),
        )
    )

    assert response["item"]["status"] == "queued"
    assert response["item"]["input_policy"] == "steer"
    assert response["item"]["expected_active_turn_id"] == "turn:session-api-live:1"
    assert response["item"]["task_run_id"] == ""
    assert response["item"]["dispatch_stream_run_id"] == ""
