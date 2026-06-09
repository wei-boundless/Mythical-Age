from __future__ import annotations

from tests.support.harness_runtime_facade_support import *

def test_plain_single_agent_turn_releases_active_turn_before_next_message() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="自然对话回复。")
    )

    async def _collect(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain-followup",
                message=message,
                runtime_contract={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
            )
        ):
            events.append(event)
        return events

    first_events = asyncio.run(_collect("先随便聊一句。"))
    second_events = asyncio.run(_collect("再回答我一句。"))

    assert any(event.get("type") == "done" and event.get("content") == "自然对话回复。" for event in first_events)
    assert any(event.get("type") == "done" and event.get("content") == "自然对话回复。" for event in second_events)
    assert not any(event.get("type") == "error" and event.get("code") == "expected_turn_id_required" for event in second_events)
    assert runtime.single_agent_runtime_host.active_turn_registry.snapshot("session-plain-followup") is None

def test_entrypoint_error_preserves_bound_nonterminal_active_turn() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(content="不会到达模型。")
    )
    session_id = "session-entrypoint-error-active-turn"
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:entrypoint-error-active-turn",
        session_id=session_id,
        status="waiting_executor",
    )

    async def _failing_single_agent_turn(**kwargs):
        runtime._bind_current_turn_to_task_run(
            session_id=session_id,
            turn_id=str(kwargs.get("turn_id") or ""),
            task_run_id=task_run_id,
            state="waiting_executor",
        )
        raise RuntimeError("synthetic entrypoint failure")
        yield {}

    runtime._run_single_agent_turn = _failing_single_agent_turn  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="继续当前任务。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    active_turn = runtime.single_agent_runtime_host.active_turn_registry.snapshot(session_id)

    assert any(event.get("type") == "error" for event in events)
    assert active_turn is not None
    assert active_turn.bound_task_run_id == task_run_id

def test_waiting_executor_with_stale_running_diagnostics_is_resumable_not_running() -> None:
    from harness.loop.task_executor import is_task_run_executable, is_task_run_executor_claimed

    runtime = build_harness_runtime()
    session_id = "session-stale-running-waiting"
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:stale-running-waiting",
        session_id=session_id,
    )
    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    host.state_index.upsert_task_run(
        replace(
            task_run,
            status="waiting_executor",
            terminal_reason="waiting_executor",
            diagnostics={
                **dict(task_run.diagnostics or {}),
                "executor_status": "running",
                "runtime_control": {"state": "resume_requested", "authority": "orchestration.task_run_control"},
            },
        )
    )

    host.active_turn_registry.start(session_id=session_id, turn_id="turn:session-stale-running-waiting:1")
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id="turn:session-stale-running-waiting:1",
        task_run_id=task_run_id,
        state="waiting_executor",
    )
    context = runtime._active_work_context_from_active_turn(session_id)
    task_run = host.state_index.get_task_run(task_run_id)

    assert task_run is not None
    assert context is not None
    assert context.running is False
    assert context.resumable is True
    assert context.same_run_allowed is True
    assert is_task_run_executor_claimed(task_run) is False
    assert is_task_run_executable(task_run) is True

def test_latest_waiting_executor_without_active_turn_is_projected_as_current_work_context() -> None:
    runtime = build_harness_runtime()
    session_id = "session-latest-waiting-context"
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-latest-waiting-context:1:abc",
        session_id=session_id,
    )

    assert runtime._active_work_context_from_active_turn(session_id) is None
    context = runtime._current_work_context_from_latest_task(session_id)

    assert context is not None
    assert context.task_run_id == task_run_id
    assert context.resumable is True
    assert context.same_run_allowed is True
    assert context.running is False
    assert context.continuation_kind == "waiting"
    assert context.authority == "harness.runtime.current_session_task_context"

def test_terminal_latest_task_without_active_turn_is_not_projected_as_current_work_context() -> None:
    runtime = build_harness_runtime()
    session_id = "session-terminal-not-resumable-context"
    _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-terminal-not-resumable-context:1:abc",
        session_id=session_id,
        status="failed",
    )

    assert runtime._active_work_context_from_active_turn(session_id) is None
    assert runtime._current_work_context_from_latest_task(session_id) is None

def test_request_task_run_replaces_current_session_task_after_active_turn_is_lost() -> None:
    session_id = "session-current-task-guard"
    existing_task_run_id = "taskrun:turn:session-current-task-guard:1:old"
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "重新启动一个替换任务。",
                "task_run_goal": "旧任务应被新的 TaskRun 接管。",
                "completion_criteria": ["旧 current work 被边缘收口，新 TaskRun 被启动"],
                "active_work_relationship": "replace_current_work",
            },
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    _seed_active_work(
        runtime,
        task_run_id=existing_task_run_id,
        session_id=session_id,
        status="running",
    )
    existing = host.state_index.get_task_run(existing_task_run_id)
    assert existing is not None
    host.state_index.upsert_task_run(
        replace(
            existing,
            updated_at=2.0,
            diagnostics={
                **dict(existing.diagnostics or {}),
                "executor_status": "scheduled",
                "latest_step_summary": "旧任务仍是当前会话的进行中任务。",
            },
        )
    )
    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return SimpleNamespace()

    host.spawn_background_task = _capture_background_task

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    old_task = host.state_index.get_task_run(existing_task_run_id)
    new_tasks = [task for task in session_task_runs if task.task_run_id != existing_task_run_id]
    trace = host.get_trace(existing_task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    active_turn = host.active_turn_registry.snapshot(session_id)

    assert "task_run_lifecycle_reused_current" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert spawned
    assert old_task is not None
    assert dict(dict(old_task.diagnostics or {}).get("runtime_control") or {}).get("state") == "stop_requested"
    assert dict(old_task.diagnostics or {}).get("replacement")
    assert "task_run_stop_requested" in trace_event_types
    assert "task_run_replaced_by_new_task_request" in trace_event_types
    assert len(new_tasks) == 1
    assert new_tasks[0].status == "running"
    assert active_turn is not None
    assert active_turn.bound_task_run_id == new_tasks[0].task_run_id

def test_request_task_run_replaces_blocked_current_session_task_without_resuming_it() -> None:
    session_id = "session-current-task-blocked-resume"
    existing_task_run_id = "taskrun:turn:session-current-task-blocked-resume:1:old"
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "重启当前被阻塞的任务。",
                "task_run_goal": "旧阻塞 TaskRun 应被替换，新 TaskRun 接手执行。",
                "completion_criteria": ["旧阻塞任务不被恢复，新任务正常启动"],
                "active_work_relationship": "restart_current_work",
            },
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    _seed_active_work(
        runtime,
        task_run_id=existing_task_run_id,
        session_id=session_id,
        status="blocked",
    )
    existing = host.state_index.get_task_run(existing_task_run_id)
    assert existing is not None
    host.state_index.upsert_task_run(
        replace(
            existing,
            terminal_reason="model_call_recovery_required",
            diagnostics={
                **dict(existing.diagnostics or {}),
                "executor_status": "blocked",
                "latest_step": "task_executor_blocked",
                "latest_step_status": "blocked",
                "latest_step_summary": "旧阻塞信息不应该继续占据监控当前态。",
            },
        )
    )

    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return SimpleNamespace()

    host.spawn_background_task = _capture_background_task

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    task_run = host.state_index.get_task_run(existing_task_run_id)
    new_tasks = [task for task in session_task_runs if task.task_run_id != existing_task_run_id]
    monitor = host.monitor_projector.build_global_monitor(host.state_index.list_task_runs(), now=10.0, limit=20)
    visible = {item["task_run_id"]: item for item in monitor["task_runs"]}
    trace = host.get_trace(existing_task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert "task_run_lifecycle_resumed_current" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert spawned
    assert task_run is not None
    assert task_run.status == "aborted"
    assert task_run.terminal_reason == "user_aborted"
    diagnostics = dict(task_run.diagnostics or {})
    assert diagnostics["latest_step"] == "task_run_replaced_by_new_task_request"
    assert diagnostics["latest_step_status"] == "aborted"
    assert diagnostics["latest_step_summary"] != "旧阻塞信息不应该继续占据监控当前态。"
    assert diagnostics["replacement"]
    assert "task_run_replaced_by_new_task_request" in trace_event_types
    assert len(new_tasks) == 1
    assert new_tasks[0].status == "running"
    assert visible[new_tasks[0].task_run_id]["status"] == "running"
    assert visible[new_tasks[0].task_run_id]["bucket"] == "running"
    assert existing_task_run_id not in visible

def test_terminal_bound_active_turn_is_cleared_and_continue_starts_new_task_run() -> None:
    session_id = "session-terminal-bound-active-turn"
    old_task_run_id = "taskrun:terminal-bound-active-turn:old"
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="request_task_run",
            task_contract_seed={
                "user_visible_goal": "继续完成新的交付任务。",
                "task_run_goal": "基于当前用户请求建立新的 TaskRun。",
                "completion_criteria": ["新任务必须独立于 terminal 旧任务"],
            },
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    _seed_active_work(runtime, task_run_id=old_task_run_id, session_id=session_id, status="aborted")
    old_task = host.state_index.get_task_run(old_task_run_id)
    assert old_task is not None
    host.state_index.upsert_task_run(replace(old_task, terminal_reason="user_aborted"))
    host.active_turn_registry.start(session_id=session_id, turn_id="turn:terminal-bound-active-turn:old")
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id="turn:terminal-bound-active-turn:old",
        task_run_id=old_task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id=session_id, message="继续")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    admissions = _admission_payloads(events)
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    new_task_runs = [task for task in session_task_runs if task.task_run_id != old_task_run_id]
    old_trace = host.get_trace(old_task_run_id, include_payloads=True)
    old_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(old_trace or {}).get("events") or [])]

    assert "active_task_steer_accepted" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert admissions
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert len(new_task_runs) == 1
    new_task = new_task_runs[0]
    diagnostics = dict(new_task.diagnostics or {})
    assert diagnostics.get("origin_kind") == "single_agent_turn_json_action"
    assert diagnostics.get("parent_task_run_id") in {None, ""}
    assert "lineage" not in diagnostics
    assert "task_run_resume_requested" not in old_event_types

def test_user_aborted_work_rollout_records_breakpoint_but_not_active_work_context() -> None:
    from harness.loop.task_executor import stop_task_run
    from harness.loop.work_rollout import work_rollout_summary

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:rollout-breakpoint",
        contract_source="test",
        user_visible_goal="验证 rollout 断点。",
        task_run_goal="停止后只保留审计断点，不形成当前工作。",
        completion_criteria=("断点只作为历史事实",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.runtime_objects.put_object(
        "task_lifecycle",
        "taskrun:rollout-breakpoint",
        TaskLifecycleRecord(
            task_run_id="taskrun:rollout-breakpoint",
            contract_ref=contract_ref,
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
        ).to_dict(),
    )
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:rollout-breakpoint",
            session_id="session-rollout-breakpoint",
            task_id="task:rollout-breakpoint",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            latest_checkpoint_ref="rtchk:source:7",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    stop_result = stop_task_run(host, "taskrun:rollout-breakpoint", reason="用户停止")
    source_summary = work_rollout_summary(host, "taskrun:rollout-breakpoint")
    interrupted_items = [
        item for item in list(source_summary.get("model_visible_history") or [])
        if str(dict(item).get("type") or "") == "interrupted_boundary"
    ]

    assert stop_result["ok"] is True
    assert len(interrupted_items) == 1
    assert int(source_summary["breakpoint"]["event_offset"]) >= 0
    assert source_summary["breakpoint"]["checkpoint_ref"] == "rtchk:source:7"

    host.active_turn_registry.start(session_id="session-rollout-breakpoint", turn_id="turn:rollout-breakpoint:2")
    host.active_turn_registry.bind_task_run(
        session_id="session-rollout-breakpoint",
        turn_id="turn:rollout-breakpoint:2",
        task_run_id="taskrun:rollout-breakpoint",
        state="waiting_executor",
    )

    assert host.active_turn_registry.resolve_current("session-rollout-breakpoint") is None
    assert runtime._active_work_context_from_active_turn("session-rollout-breakpoint") is None

def test_active_work_turn_policy_repairs_control_only_to_reply_then_control() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "turn_response_policy": "active_work_only",
            "continuation_strategy": "same_run_resume",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "好，我接着处理。",
        },
        user_message="继续当前工作",
    )

    assert decision.action == "continue_active_work"
    assert decision.turn_response_policy == "answer_then_active_work"
    assert decision.answer_obligation == "acknowledgement_only"
    assert decision.continuation_strategy == "same_run_resume"

def test_active_work_turn_policy_does_not_rewrite_direct_answer_action() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "answer_obligation": "direct_answer_required",
            "continuation_strategy": "same_run_resume",
            "relation_to_current_work": "current_work",
            "evidence": "用户既问状态又要求继续",
            "response": "当前工作还在等待继续，我会接着处理。",
        },
        user_message="现在做到哪了？继续",
    )

    assert decision.accepted is True
    assert decision.action == "continue_active_work"
    assert decision.answer_obligation == "direct_answer_required"
    assert decision.continuation_strategy == "same_run_resume"
    assert decision.denied_reason == ""

def test_active_work_turn_policy_downgrades_non_control_subaction_to_answer() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "normal_response",
            "relation_to_current_work": "independent_turn",
            "response": "这应该作为普通回复，而不是当前工作控制。",
        },
        user_message="解释一下 checkpoint",
    )

    assert decision.accepted is True
    assert decision.action == "answer_about_active_work"
    assert decision.response == "这应该作为普通回复，而不是当前工作控制。"
    assert decision.denied_reason == ""
    assert decision.continuation_strategy == "none"

def test_active_work_turn_policy_accepts_intent_as_control_action_alias() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "intent": "continue_active_work",
            "relation_to_current_work": "current_work",
            "response": "好，我接着处理。",
        },
        user_message="继续",
    )

    assert decision.accepted is True
    assert decision.action == "continue_active_work"
    assert decision.denied_reason == ""

def test_active_work_relation_mismatch_blocks_without_control_side_effects() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "independent_turn",
            "evidence": "模型调用当前工作控制但声明独立请求",
            "response": "这不应该控制当前工作。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-relation-mismatch")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="解释一下 checkpoint",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert not any(event.get("type") == "active_task_steer_accepted" for event in events)
    assert any(
        event.get("type") == "done"
        and event.get("answer_channel") == "blocked"
        and event.get("terminal_reason") == "active_work_relation_declared_independent"
        and "没有控制当前工作" in str(event.get("content") or "")
        for event in events
    )
    assert any(
        event.get("type") == "agent_turn_terminal"
        and dict(dict(event.get("event") or {}).get("payload") or {}).get("terminal_reason") == "active_work_relation_declared_independent"
        for event in events
    )
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_resume_requested" not in event_types

def test_active_work_ambiguous_relation_is_rejected_as_inconsistent_control() -> None:
    from harness.loop.active_work import active_work_turn_decision_from_payload

    decision = active_work_turn_decision_from_payload(
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "ambiguous",
            "evidence": "",
            "response": "我会补充到当前工作。",
        },
        user_message="补充一下",
    )

    assert decision.accepted is False
    assert decision.action == "ask_user"
    assert decision.denied_reason == "active_work_relation_ambiguous"
    assert decision.appended_instruction == ""

def test_append_instruction_reports_resume_failure_without_accepting_steer(monkeypatch) -> None:
    import harness.entrypoint.runtime_facade as runtime_facade_module

    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户补充当前等待任务要求",
            "response": "收到，我会按这个补充方向继续处理。",
            "appended_instruction": "补充要求：优先检查调度失败。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:append-resume-failure")

    def _resume_failure(*_args, **_kwargs):
        return {"ok": False, "error": "task_run_waiting_approval_requires_grant"}

    monkeypatch.setattr(runtime_facade_module, "resume_paused_task_run", _resume_failure)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="补充要求：优先检查调度失败。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert "active_task_steer_recorded" in event_types
    assert "task_run_resume_requested" not in event_types
    assert "task_run_executor_scheduled" not in event_types
    assert not any(event.get("type") == "active_task_steer_accepted" for event in events)
    assert any(
        event.get("type") == "done"
        and event.get("answer_channel") == "blocked"
        and event.get("terminal_reason") == "active_work_resume_failed"
        and "当前工作没有成功恢复：task_run_waiting_approval_requires_grant" in str(event.get("content") or "")
        for event in events
    )

def test_append_instruction_to_waiting_approval_reports_queued_without_resume() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户补充等待确认任务要求",
            "response": "收到，我会按这个补充方向继续处理。",
            "appended_instruction": "确认前先补充验收标准。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:append-waiting-approval",
        status="waiting_approval",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="确认前先补充验收标准。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert "active_task_steer_recorded" in event_types
    assert "task_run_resume_requested" not in event_types
    assert "task_run_executor_scheduled" not in event_types
    assert any(event.get("type") == "active_task_steer_accepted" for event in events)
    assert any(
        event.get("type") == "done"
        and event.get("answer_channel") == "active_work_control"
        and "补充要求已记录" in str(event.get("content") or "")
        and "等待确认" in str(event.get("content") or "")
        and "按这个补充方向继续处理" not in str(event.get("content") or "")
        for event in events
    )

def test_active_turn_input_goes_through_model_turn_instead_of_registry_steer() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "answer_about_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户询问当前工作状态",
            "response": "当前工作还在等待继续执行。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-model-decision")

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="现在做到哪了？",
                expected_active_turn_id="turn:active:current",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    updated_task = host.state_index.get_task_run(task_run_id)

    assert "single_agent_turn_started" in event_types
    assert "active_task_steer_accepted" not in event_types
    assert model.active_work_decision_count == 1
    assert updated_task is not None
    assert int(dict(updated_task.diagnostics or {}).get("pending_user_steer_count") or 0) == 0
    assert any(event.get("type") == "done" and "当前工作还在等待继续执行" in str(event.get("content") or "") for event in events)

def test_running_active_turn_input_queues_steer_without_model_roundtrip() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户在当前运行任务中追加约束",
            "response": "已记录补充要求，会在当前执行中参考。",
            "appended_instruction": "不要生成临时假数据。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:active-turn-running-queue",
        status="running",
    )

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="running_task",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="新增一个限制：不要生成临时假数据。",
                expected_active_turn_id="turn:active:current",
                active_turn_input_policy="steer",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    updated_task = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    session_messages = runtime.session_manager.load_session("session-active-work")

    assert "single_agent_turn_started" not in event_types
    assert "runtime_assembly_compiled" not in event_types
    assert any(
        event.get("type") == "runtime_branch_decided"
        and dict(event.get("runtime_branch") or {}).get("branch_kind") == "active_turn_steer"
        for event in events
    )
    assert not any("boundary" in event_type for event_type in event_types)
    assert "active_task_steer_accepted" in event_types
    assert model.active_work_decision_count == 0
    assert updated_task is not None
    assert int(dict(updated_task.diagnostics or {}).get("pending_user_steer_count") or 0) == 1
    active_event = next(event for event in events if event.get("type") == "active_task_steer_accepted")
    assert active_event.get("runtime_task_run_id") == task_run_id
    assert active_event.get("active_turn_id") == "turn:active:current"
    assert dict(active_event.get("active_turn") or {}).get("bound_task_run_id") == task_run_id
    active_turn = host.active_turn_registry.snapshot("session-active-work")
    assert active_turn is not None
    assert active_turn.bound_task_run_id == task_run_id
    assert "active_task_steer_recorded" in trace_event_types
    assert any(
        event.get("type") == "done"
        and event.get("answer_source") == "harness.entrypoint.active_turn_steer"
        and event.get("terminal_reason") == "append_instruction_to_active_work"
        and event.get("completion_state") == "task_steer_accepted"
        and event.get("runtime_task_run_id") == task_run_id
        and dict(event.get("active_turn") or {}).get("bound_task_run_id") == task_run_id
        and "补充要求" in str(event.get("content") or "")
        for event in events
    )
    assert [str(item.get("role") or "") for item in session_messages] == ["user", "assistant"]

def test_auto_active_turn_input_uses_model_decision_even_when_task_running() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户在当前运行任务中追加约束",
            "response": "已记录补充要求，会在当前执行中参考。",
            "appended_instruction": "补充：先定位非 steer 边界。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:auto-active-turn-running-model-decision",
        status="running",
    )

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:auto-current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:auto-current",
        task_run_id=task_run_id,
        state="running_task",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="补充：先定位非 steer 边界。",
                expected_active_turn_id="turn:active:auto-current",
                active_turn_input_policy="auto",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    updated_task = host.state_index.get_task_run(task_run_id)

    assert "runtime_assembly_compiled" in event_types
    assert "single_agent_turn_started" in event_types
    assert "model_action_admission" in event_types
    assert any(
        event.get("type") == "runtime_branch_decided"
        and dict(event.get("runtime_branch") or {}).get("branch_kind") != "active_turn_steer"
        for event in events
    )
    assert "active_task_steer_accepted" in event_types
    assert model.active_work_decision_count == 1
    assert updated_task is not None
    assert int(dict(updated_task.diagnostics or {}).get("pending_user_steer_count") or 0) == 1
    assert any(
        event.get("type") == "done"
        and event.get("answer_source") == "harness.single_agent_turn.active_work_control"
        and event.get("completion_state") == "task_steer_accepted"
        for event in events
    )

def test_explicit_active_turn_steer_without_active_context_blocks_without_model_roundtrip() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "显式 steer 不应该进入模型判断。",
            "response": "不应出现。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    session_id = "session-explicit-steer-no-active-context"

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="补充：优先检查最新回答为什么慢。",
                expected_active_turn_id="turn:missing-active-context",
                active_turn_input_policy="steer",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    branch = next(event for event in events if event.get("type") == "runtime_branch_decided")
    done = next(event for event in events if event.get("type") == "done")

    assert "runtime_assembly_compiled" not in event_types
    assert "single_agent_turn_started" not in event_types
    assert "active_task_steer_accepted" not in event_types
    assert model.active_work_decision_count == 0
    assert dict(branch.get("runtime_branch") or {}).get("branch_kind") == "active_turn_steer"
    assert dict(branch.get("runtime_branch") or {}).get("reason") == "active_turn_steer_not_running"
    assert done.get("answer_channel") == "blocked"
    assert done.get("answer_source") == "harness.entrypoint.active_turn_steer"
    assert done.get("terminal_reason") == "active_turn_steer_not_running"
    assert done.get("completion_state") == "blocked"
    assert done.get("active_turn_id") == "turn:missing-active-context"
    assert dict(done.get("active_turn") or {}).get("state") == "unavailable"

def test_explicit_active_turn_steer_paused_context_blocks_without_model_roundtrip() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "append_instruction_to_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "暂停状态不应该被 steer 快路径改写。",
            "response": "不应出现。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    session_id = "session-explicit-steer-paused-context"
    task_run_id = _seed_active_work(
        runtime,
        session_id=session_id,
        task_run_id="taskrun:explicit-steer-paused-context",
        status="waiting_executor",
    )
    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    host.state_index.upsert_task_run(
        replace(
            task_run,
            diagnostics={
                **dict(task_run.diagnostics or {}),
                "runtime_control": {
                    "state": "paused",
                    "authority": "orchestration.task_run_control",
                },
            },
        )
    )
    host.active_turn_registry.start(session_id=session_id, turn_id="turn:explicit-steer-paused")
    host.active_turn_registry.bind_task_run(
        session_id=session_id,
        turn_id="turn:explicit-steer-paused",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="补充：继续前先检查慢回复。",
                expected_active_turn_id="turn:explicit-steer-paused",
                active_turn_input_policy="steer",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    trace = host.get_trace(task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    done = next(event for event in events if event.get("type") == "done")

    assert "runtime_assembly_compiled" not in event_types
    assert "single_agent_turn_started" not in event_types
    assert "active_task_steer_accepted" not in event_types
    assert "active_task_steer_recorded" not in trace_event_types
    assert model.active_work_decision_count == 0
    assert done.get("answer_channel") == "blocked"
    assert done.get("answer_source") == "harness.entrypoint.active_turn_steer"
    assert done.get("terminal_reason") == "active_turn_steer_control_state_paused"
    assert done.get("completion_state") == "blocked"
    assert done.get("runtime_task_run_id") == task_run_id
    assert dict(done.get("active_turn") or {}).get("bound_task_run_id") == task_run_id

def test_main_agent_active_work_control_resumes_waiting_executor_without_hidden_boundary() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "continuation_strategy": "same_run_resume",
            "evidence": "用户要求续接当前等待中的任务",
            "response": "好，我接着处理当前任务。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-control-resume")
    host = runtime.single_agent_runtime_host

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="接着处理刚才那个任务。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]
    trace = host.get_trace(task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    updated_task = host.state_index.get_task_run(task_run_id)
    active_turn = host.active_turn_registry.snapshot("session-active-work")

    assert not any("boundary" in event_type for event_type in event_types)
    assert "single_agent_turn_started" in event_types
    assert "model_action_admission" in event_types
    assert model.active_work_decision_count == 1
    assert "task_run_resume_requested" in trace_event_types
    assert "task_run_executor_scheduled" in trace_event_types
    assert updated_task is not None
    assert dict(updated_task.diagnostics or {}).get("latest_interaction_turn_id")
    assert active_turn is not None
    assert active_turn.bound_task_run_id == task_run_id
    assert any(
        event.get("type") == "done"
        and event.get("answer_source") == "harness.single_agent_turn.active_work_control"
        and event.get("terminal_reason") == "continue_active_work"
        and "接着处理" in str(event.get("content") or "")
        for event in events
    )

def test_main_agent_active_work_control_accepts_intent_alias_without_blocking() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "intent": "continue_active_work",
            "relation_to_current_work": "current_work",
            "continuation_strategy": "same_run_resume",
            "evidence": "用户要求续接当前等待中的任务",
            "response": "好，我接着处理当前任务。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-control-intent-alias")
    host = runtime.single_agent_runtime_host

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="继续。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = host.get_trace(task_run_id, include_payloads=True)
    trace_event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert "task_run_resume_requested" in trace_event_types
    assert not any(
        event.get("type") == "done"
        and event.get("answer_channel") == "blocked"
        and event.get("terminal_reason") == "active_work_control_action_not_allowed"
        for event in events
    )
    assert any(
        event.get("type") == "done"
        and event.get("answer_source") == "harness.single_agent_turn.active_work_control"
        and event.get("terminal_reason") == "continue_active_work"
        for event in events
    )

def test_independent_turn_uses_single_agent_turn_without_hidden_boundary() -> None:
    model = NativeToolCallModelRuntimeStub(
        agent_turn_action_request=_action_request(
            action_type="respond",
            final_answer="这是独立问题的回答。",
        )
    )
    runtime = build_harness_runtime(model_runtime=model)
    _seed_active_work(runtime, task_run_id="taskrun:active-control-independent")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="解释一下 Python 的闭包是什么。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [str(event.get("type") or "") for event in events]

    assert not any("boundary" in event_type for event_type in event_types)
    assert "single_agent_turn_started" in event_types
    assert "active_task_steer_accepted" not in event_types
    assert any(event.get("type") == "done" and event.get("content") == "这是独立问题的回答。" for event in events)

def test_active_turn_preserves_user_granted_new_turn_capabilities(tmp_path: Path) -> None:
    class RecordingCapabilityModelRuntime(NativeToolCallModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(content="普通回复。")
            self.last_messages: list[dict[str, object]] = []

        async def invoke_messages_with_tools(self, messages, tools, **kwargs):
            self.last_messages = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
            return await super().invoke_messages_with_tools(messages, tools, **kwargs)

    model = RecordingCapabilityModelRuntime()
    tool_base_dir = _project_backend_dir()
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(tool_base_dir, {"read_file", "write_file", "terminal"}),
    )
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-preserve-capabilities", session_id="session-active-preserve")
    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-preserve", turn_id="turn:active-preserve:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-preserve",
        turn_id="turn:active-preserve:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-preserve",
                message="这个先放着，检查一下项目文件。",
                runtime_contract={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "control_capabilities": {
                        "may_call_tools": True,
                        "may_request_task_run": True,
                        "may_control_active_work": True,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    start = dict(next(event for event in events if event.get("type") == "single_agent_turn_started"))
    stable_payload = _packet_payload_after_title(
        str(model.last_messages[1].get("content") or ""),
        "Single agent turn stable boundary",
    )
    packet_tools = {str(dict(tool).get("name") or "") for tool in list(model.seen_tools[0] or [])}
    capabilities = dict(assembly.get("control_capabilities") or {})
    effective_capabilities = dict(stable_payload.get("control_capabilities") or {})

    assert capabilities.get("may_call_tools") is True
    assert capabilities.get("may_request_task_run") is True
    assert "tool_call" in start.get("allowed_action_types")
    assert "request_task_run" in start.get("allowed_action_types")
    assert {"read_file", "write_file", "terminal"} <= packet_tools
    assert effective_capabilities.get("may_call_tools") is True
    assert effective_capabilities.get("may_request_task_run") is True
    assert dict(dict(assembly.get("runtime_contract") or {}).get("runtime_facts") or {}).get("active_turn_capability_policy") == "preserve_user_granted_capabilities"

def test_active_work_control_allows_missing_expected_active_turn_id_when_bound_task_matches() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "我会继续当前工作。",
            "continuation_strategy": "same_run_resume",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-missing-expected-allowed")

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="继续当前工作",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert "task_run_resume_requested" in event_types
    assert "task_run_executor_scheduled" in event_types
    assert any(event.get("type") == "done" and "继续当前工作" in str(event.get("content") or "") for event in events)

def test_active_work_control_rejects_missing_expected_id_when_bound_task_changed() -> None:
    from harness.loop.active_work import ActiveWorkContext

    runtime = build_harness_runtime(model_runtime=NativeToolCallModelRuntimeStub(content="unused"))
    original_task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-original")
    replacement_task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-replacement")
    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=replacement_task_run_id,
        state="waiting_executor",
    )

    guard = runtime._active_turn_control_guard(
        request=HarnessRuntimeRequest(session_id="session-active-work", message="继续当前工作"),
        active_work_context=ActiveWorkContext(
            session_id="session-active-work",
            active_work_id="turn:active:old",
            task_run_id=original_task_run_id,
            status="waiting_executor",
            authority="harness.runtime.active_turn_context",
        ),
    )

    assert guard is not None
    assert guard["status"] == "blocked"
    assert guard["terminal_reason"] == "expected_active_turn_mismatch"

def test_active_work_control_rejects_stale_expected_active_turn_id() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应继续。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-turn-expected-stale")

    host = runtime.single_agent_runtime_host
    host.active_turn_registry.start(session_id="session-active-work", turn_id="turn:active:current")
    host.active_turn_registry.bind_task_run(
        session_id="session-active-work",
        turn_id="turn:active:current",
        task_run_id=task_run_id,
        state="waiting_executor",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="继续当前工作",
                expected_active_turn_id="turn:active:stale",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 1
    assert any(event.get("type") == "done" and "当前任务状态已变化" in str(event.get("content") or "") for event in events)
    assert any(
        event.get("type") == "agent_turn_terminal"
        and dict(dict(event.get("event") or {}).get("payload") or {}).get("terminal_reason") == "expected_active_turn_mismatch"
        for event in events
    )
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_resume_requested" not in event_types

def test_single_agent_turn_does_not_control_active_work_without_native_action() -> None:
    class NoActiveWorkToolModelRuntime:
        def __init__(self) -> None:
            self.active_work_decision_count = 0

        async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
            return SimpleNamespace(content="普通回复。", tool_calls=[])

        async def invoke_messages(self, _messages, **_kwargs):
            return SimpleNamespace(content="普通回复。")

    model = NoActiveWorkToolModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-route-gate")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-active-work", message="解释一下 LangGraph 的 checkpoint 机制")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 0
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types

def test_capability_boundary_bypasses_active_work_control() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应该进入当前工作。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:capability-boundary-active-work")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="修复了吗",
                runtime_contract={
                    "control_capabilities": {
                        "may_call_tools": False,
                        "may_request_task_run": False,
                        "may_control_active_work": False,
                        "may_use_subagents": False,
                    }
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert model.active_work_decision_count == 0
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_executor_scheduled" not in event_types

def test_active_work_router_is_gated_by_runtime_assembly_context_policy() -> None:
    model = _ActiveWorkDecisionModelRuntime([
        {
            "authority": "harness.loop.active_work_turn_decision",
            "action": "continue_active_work",
            "relation_to_current_work": "current_work",
            "evidence": "用户说继续当前工作",
            "response": "不应该进入当前工作。",
        }
    ])
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-context-disabled")

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-active-work",
                message="继续当前工作",
                runtime_contract={
                    "runtime_policy": {
                        "task_lifecycle_policy": {"request_task_run": True},
                        "context_policy": {"task_context": "available", "active_work_context": "disabled"},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert dict(profile.get("context_policy") or {}).get("active_work_context") == "disabled"
    assert model.active_work_decision_count == 0
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "普通回复。" for event in events)
    assert "task_run_resume_requested" not in event_types
    assert "active_task_steer_recorded" not in event_types
    assert "task_run_executor_scheduled" not in event_types

def test_pending_active_task_steer_is_injected_into_task_execution_packet() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    model = _TaskExecutorSequenceModelRuntime(
        [
            _action_request(
                action_type="respond",
                final_answer="第一次不能完成。",
            ),
            _action_request(
                action_type="respond",
                final_answer="已按补充要求完成。",
                diagnostics={"consumed_steer_refs": []},
            ),
        ],
        agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
    )
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:active-work-steer-packet")
    steer_result = append_user_work_instruction(
        host,
        task_run_id,
        content="优先修复美术资源加载。",
        turn_id="turn:session-active-work:22",
        intent="conversation_instruction",
    )
    steer_id = str(dict(steer_result.get("steer") or {}).get("steer_id") or "")
    model.task_actions[1]["diagnostics"] = {
        "test_action_request": True,
        "consumed_steer_refs": [steer_id],
        "contract_revision_decisions": [
            {
                "steer_ref": steer_id,
                "status": "accepted",
                "reason": "补充要求作为当前修复优先级纳入执行。",
            }
        ],
    }

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    trace = host.get_trace(task_run_id, include_payloads=True)
    packet_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "runtime_invocation_packet_compiled"
    ]
    steer_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "active_task_steer_consumed"
    ]
    repair_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "task_completion_repair_required"
    ]
    payload = dict(packet_events[0].get("payload") or {})
    packet = dict(payload.get("packet") or {})
    messages = list(packet.get("model_messages") or [])
    message_text = json.dumps(messages, ensure_ascii=False)
    steering_messages = [
        dict(item)
        for item in messages
        if str(dict(item).get("role") or "") == "user"
        and str(dict(item).get("content") or "").startswith("User steering updates for this task\n")
    ]
    segment_kinds = [
        str(dict(item).get("kind") or "")
        for item in list(dict(packet.get("segment_plan") or {}).get("segments") or [])
        if isinstance(item, dict)
    ]
    revision_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "task_contract_revision_recorded"
    ]
    revision_decision_events = [
        dict(item)
        for item in list(dict(trace or {}).get("events") or [])
        if str(dict(item).get("event_type") or "") == "task_contract_revision_decided"
    ]

    assert result["ok"] is True
    assert packet["packet_id"].startswith(f"rtpacket:{task_run_id}:task_execution:1:")
    assert "user_steering_updates" in segment_kinds
    assert steering_messages
    assert "Do not action_type=respond while any listed steer is unhandled." in str(steering_messages[0].get("content") or "")
    assert "pending_user_steers" in message_text
    assert "active_contract_revisions" in message_text
    assert "优先修复美术资源加载。" in message_text
    assert repair_events
    assert revision_events
    assert revision_decision_events
    assert steer_events

def test_late_active_task_steer_blocks_completion_before_next_packet() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    class LateSteerModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.wait_for(self.release.wait(), timeout=5)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
                return SimpleNamespace(
                    content=json.dumps(
                        _action_request(
                            action_type="respond",
                            final_answer="不应直接完成。",
                        ),
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = LateSteerModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:late-steer-before-completion")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=1))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        append_user_work_instruction(
            host,
            task_run_id,
            content="模型调用等待期间追加的要求也必须阻断完成。",
            turn_id="turn:late-steer:1",
            intent="conversation_steer_while_model_waiting",
        )
        model.release.set()
        result = await asyncio.wait_for(executor_task, timeout=10)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    trace = host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    task_run = host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "user_interrupt_replan_required"
    assert "active_task_steer_recorded" in event_types
    assert "task_run_replan_requested" in event_types
    assert "task_run_interrupted_for_replan" in event_types
    assert task_run is not None
    assert task_run.status == "waiting_executor"

def test_running_task_steer_cancels_inflight_model_call_and_replans() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    class InterruptibleModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = InterruptibleModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:running-steer-replan")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        append_user_work_instruction(
            host,
            task_run_id,
            content="推翻之前方向，先重新规划并优先处理新要求。",
            turn_id="turn:running-steer-replan:1",
            intent="conversation_steer_while_running",
        )
        result = await asyncio.wait_for(executor_task, timeout=5)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})

    assert result["ok"] is False
    assert result["error"] == "user_interrupt_replan_required"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert diagnostics["executor_status"] == "waiting_executor"
    assert diagnostics["recovery_action"] == "resume_task_run"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") == "interrupted_for_replan"
    assert "task_run_replan_requested" in event_types
    assert "task_run_interrupted_for_replan" in event_types

def test_running_task_pause_cancels_inflight_model_call_without_auto_replan() -> None:
    from harness.loop.task_executor import request_task_run_pause

    class InterruptibleModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = InterruptibleModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:running-pause")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        request_task_run_pause(host, task_run_id, reason="test_pause", requested_by="user")
        result = await asyncio.wait_for(executor_task, timeout=5)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})

    assert result["ok"] is False
    assert result["error"] == "task_run_paused"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert diagnostics["executor_status"] == "waiting_executor"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") == "paused"

def test_running_task_stop_cancels_inflight_model_call_and_finishes_aborted() -> None:
    from harness.loop.task_executor import stop_task_run

    class InterruptibleModelRuntime:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source == "harness.loop.task_executor.model_action":
                self.started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))

    model = InterruptibleModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:running-stop")

    async def _run() -> dict[str, object]:
        executor_task = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=2))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        stop_task_run(host, task_run_id, reason="test_stop", requested_by="user")
        result = await asyncio.wait_for(executor_task, timeout=5)
        await asyncio.wait_for(model.cancelled.wait(), timeout=1)
        return result

    result = asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})

    assert result["ok"] is False
    assert result["error"] == "user_aborted"
    assert task_run is not None
    assert task_run.status == "aborted"
    assert diagnostics["executor_status"] == "stopped"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") == "stopped"
    assert "recovery_action" not in diagnostics
    assert "recoverable_error" not in diagnostics
    assert "pending_user_steer_count" not in diagnostics
    assert "active_contract_revision_count" not in diagnostics

def test_stopped_task_cannot_be_revived_by_stale_executor_or_write_tool() -> None:
    from harness.loop.task_executor import stop_task_run

    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _tool_action_request(
                    tool_name="write_file",
                    args={"path": "storage/task_environments/general/workspace/artifacts/should_not_exist.txt", "content": "bad"},
                    public_progress_note="准备写入测试文件。",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:stopped-no-write")
    host = runtime.single_agent_runtime_host
    stop_task_run(host, task_run_id, reason="user_stop", requested_by="user")

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    written_path = Path(runtime.base_dir) / "storage/task_environments/general/workspace/artifacts/should_not_exist.txt"

    assert result["ok"] is False
    assert result["error"] == "user_aborted"
    assert task_run is not None
    assert task_run.status == "aborted"
    assert task_run.terminal_reason == "user_aborted"
    assert diagnostics["executor_status"] == "stopped"
    assert not written_path.exists()
    assert not any(
        dict(event.payload or {}).get("model_action_request")
        for event in host.event_log.list_events(task_run_id)
        if event.event_type == "model_action_request_received"
    )

def test_scheduler_restarts_after_running_steer_and_next_packet_contains_instruction() -> None:
    from harness.loop.task_executor import append_user_work_instruction

    class ReplanningModelRuntime:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.first_cancelled = asyncio.Event()
            self.second_started = asyncio.Event()
            self.messages_by_call: list[str] = []
            self.host = None
            self.task_run_id = ""

        async def invoke_messages(self, messages, **kwargs):
            source = str(dict(kwargs.get("accounting_context") or {}).get("source") or "")
            if source != "harness.loop.task_executor.model_action":
                return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="unused")))
            self.messages_by_call.append(json.dumps(messages, ensure_ascii=False))
            if len(self.messages_by_call) == 1:
                self.first_started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.first_cancelled.set()
                    raise
            self.second_started.set()
            steer_refs: list[str] = []
            if self.host is not None:
                from harness.loop.task_steering import list_pending_task_steers
                from harness.loop.task_contract_revision import list_active_task_contract_revisions

                steer_refs = [
                    str(item.get("steer_id") or "")
                    for item in list_pending_task_steers(self.host, self.task_run_id)
                    if str(item.get("steer_id") or "")
                ]
                revision_decisions = [
                    {"revision_id": str(item.get("revision_id") or ""), "status": "accepted"}
                    for item in list_active_task_contract_revisions(self.host, self.task_run_id)
                    if str(item.get("revision_id") or "")
                ]
            else:
                revision_decisions = []
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="已按新要求完成。",
                        diagnostics={
                            "consumed_steer_refs": list(dict.fromkeys(steer_refs)),
                            "contract_revision_decisions": revision_decisions,
                        },
                    ),
                    ensure_ascii=False,
                )
            )

    model = ReplanningModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:scheduler-replan")
    model.host = host
    model.task_run_id = task_run_id

    async def _run() -> None:
        schedule_result = runtime._schedule_active_task_run_executor(task_run_id, scheduler="test_scheduler_replan", max_steps=2)
        assert schedule_result["scheduled"] is True
        await asyncio.wait_for(model.first_started.wait(), timeout=5)
        append_user_work_instruction(
            host,
            task_run_id,
            content="自然语言改方向：先做稳定性高压验证。",
            turn_id="turn:scheduler-replan:1",
            intent="conversation_steer_while_running",
        )
        await asyncio.wait_for(model.first_cancelled.wait(), timeout=5)
        await asyncio.wait_for(model.second_started.wait(), timeout=5)
        for _ in range(100):
            task_run = host.state_index.get_task_run(task_run_id)
            if task_run is not None and task_run.status == "completed":
                return
            await asyncio.sleep(0.02)
        raise AssertionError("scheduler did not complete restarted task run")

    asyncio.run(_run())
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert task_run is not None
    assert task_run.status == "completed"
    assert model.first_cancelled.is_set()
    assert len(model.messages_by_call) >= 2
    assert "自然语言改方向：先做稳定性高压验证。" in model.messages_by_call[1]
    assert "task_run_interrupted_for_replan" in event_types
    assert "task_run_executor_rescheduled" in event_types
    assert "active_task_steer_consumed" in event_types

def test_native_request_task_run_preserves_active_work_relationship_for_replacement() -> None:
    session_id = "session-native-taskrun-replace"
    old_task_run_id = "taskrun:session-native-taskrun-replace:old"
    model = _UnexpectedNativeToolCallModelRuntime(
        tool_calls=[
            {
                "id": "call-request-task-run-replace",
                "name": "request_task_run",
                "args": {
                    "user_visible_goal": "从头重做页面。",
                    "task_run_goal": "替换旧任务并重新创建页面。",
                    "completion_criteria": ["新页面文件真实存在"],
                    "active_work_relationship": "replace_current_work",
                    "public_progress_note": "我会按新的要求重建任务。",
                },
            }
        ]
    )
    runtime = build_harness_runtime(model_runtime=model)
    _seed_active_work(runtime, session_id=session_id, task_run_id=old_task_run_id)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id=session_id,
                message="不要沿用刚才的进度，从头重做页面。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    admissions = _admission_payloads(events)
    old_task = runtime.single_agent_runtime_host.state_index.get_task_run(old_task_run_id)
    old_diagnostics = dict(getattr(old_task, "diagnostics", {}) or {})
    replacement = dict(old_diagnostics.get("replacement") or {})

    assert admissions
    assert dict(dict(admissions[0].get("model_action_request") or {}).get("task_contract_seed") or {}).get("active_work_relationship") == "replace_current_work"
    assert replacement.get("relationship") == "replace_current_work"
    assert any(event.get("type") == "task_run_lifecycle_started" for event in events)
