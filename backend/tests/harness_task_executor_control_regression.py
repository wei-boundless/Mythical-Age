from __future__ import annotations

from tests.support.harness_runtime_facade_support import *

def test_task_executor_guards_duplicate_read_only_tool_call_without_rerunning_tool() -> None:
    action = ModelActionRequest(
        request_id="model-action:duplicate-read",
        turn_id="taskrun:duplicate-read",
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html"}},
    )
    previous = [
        {
            "observation_id": "toolobs:read:1",
            "payload": {
                "result_envelope": {
                    "tool_name": "read_file",
                    "tool_args": {"path": "artifacts/demo.html"},
                    "status": "ok",
                    "text": "<html></html>",
                }
            },
        }
    ]

    duplicate = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=action,
        previous_observations=previous,
    )
    same_default_window = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:same-default-read-window",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html", "start_line": 1}},
        ),
        previous_observations=previous,
    )
    old_window_args = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:old-read-window-args",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html", "offset": 0}},
        ),
        previous_observations=previous,
    )
    changed_args = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:changed-read",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/other.html"}},
        ),
        previous_observations=previous,
    )
    unsupported_arg = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:unsupported-read-arg",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "read_file", "args": {"path": "artifacts/demo.html", "max_chars": 200}},
        ),
        previous_observations=previous,
    )
    repeated_failed_search = _duplicate_read_only_tool_call_observation(
        task_run_id="taskrun:duplicate-read",
        packet_ref="packet:duplicate-read",
        action_request=ModelActionRequest(
            request_id="model-action:repeated-failed-search",
            turn_id="taskrun:duplicate-read",
            action_type="tool_call",
            tool_call={"tool_name": "search_text", "args": {"query": "needle", "roots": ["docs/plan.md"]}},
        ),
        previous_observations=[
            {
                "observation_id": "toolobs:search:failed:1",
                "source": "tool:search_text",
                "payload": {
                    "tool_name": "search_text",
                    "tool_args": {"query": "needle", "roots": ["docs/plan.md"]},
                    "error": "Search failed: roots accepts directories only.",
                },
                "error": "Search failed: roots accepts directories only.",
            }
        ],
    )

    assert duplicate is not None
    assert same_default_window is not None
    assert repeated_failed_search is not None
    assert duplicate["source"] == "system:duplicate_tool_call_guard"
    assert duplicate["payload"]["error_code"] == "duplicate_read_only_tool_call"
    assert duplicate["payload"]["previous_observation_refs"] == ["toolobs:read:1"]
    assert repeated_failed_search["payload"]["error_code"] == "duplicate_failed_read_only_tool_call"
    assert repeated_failed_search["payload"]["previous_observation_refs"] == ["toolobs:search:failed:1"]
    assert changed_args is None
    assert old_window_args is None
    assert unsupported_arg is None

def test_task_executor_repeated_admission_denial_fingerprint_is_runtime_scoped() -> None:
    action = ModelActionRequest(
        request_id="model-action:admission-repeat",
        turn_id="taskrun:admission-repeat",
        action_type="tool_call",
        tool_call={"tool_name": "missing_tool", "args": {"path": "tmp/demo.txt"}},
    )
    admission = {
        "decision": "deny",
        "system_reason": "tool_not_in_runtime_assembly",
        "user_visible_reason": "工具不在当前运行边界内。",
    }
    runtime_fingerprint = {
        "runtime_assembly_id": "rtasm:taskrun:admission-repeat",
        "agent_profile_id": "main_interactive_agent",
        "runtime_profile_ref": "runtime:default",
        "task_environment_id": "coding",
        "tool_registry_hash": "tools-a",
        "tool_config_hash": "config-a",
        "sandbox_policy_hash": "sandbox-a",
        "permission_policy_hash": "permission-a",
        "backend_config_hash": "backend-a",
        "permission_mode": "default",
    }
    previous = _model_action_admission_observation(
        task_run_id="taskrun:admission-repeat",
        packet_ref="packet:admission-repeat",
        action_request=action,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
        step_index=1,
    )
    changed_args = ModelActionRequest(
        request_id="model-action:admission-repeat-args",
        turn_id="taskrun:admission-repeat",
        action_type="tool_call",
        tool_call={"tool_name": "missing_tool", "args": {"path": "tmp/other.txt"}},
    )
    changed_environment = {**runtime_fingerprint, "task_environment_id": "writing"}

    same = _matching_model_action_admission_denial_observations(
        [previous],
        action_request=action,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )
    different_args = _matching_model_action_admission_denial_observations(
        [previous],
        action_request=changed_args,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )
    different_environment = _matching_model_action_admission_denial_observations(
        [previous],
        action_request=action,
        admission=admission,
        runtime_fingerprint=changed_environment,
    )
    legacy_previous = {
        **previous,
        "payload": {
            key: value
            for key, value in dict(previous.get("payload") or {}).items()
            if key != "admission_denial_fingerprint"
        },
    }
    legacy_without_fingerprint = _matching_model_action_admission_denial_observations(
        [legacy_previous],
        action_request=action,
        admission=admission,
        runtime_fingerprint=runtime_fingerprint,
    )

    assert len(same) == 1
    assert different_args == []
    assert different_environment == []
    assert legacy_without_fingerprint == []

def test_task_tool_batch_group_returns_completed_results_before_interrupt(monkeypatch) -> None:
    signal = ExecutorControlSignal(
        kind="pause",
        task_run_id="taskrun:batch-interrupt",
        executor_epoch=1,
        reason="test pause",
        requested_by="test",
        requested_at=1.0,
    )

    async def _fake_execute_task_tool_call(_runtime_host, **kwargs):
        action_request = kwargs["action_request"]
        if action_request.request_id == "act:pause":
            raise TaskRunExecutorInterrupted(signal)
        return {
            "observation_id": "obs:completed-before-pause",
            "task_run_id": "taskrun:batch-interrupt",
            "observation_type": "tool_result",
            "source": "tool:read_file",
            "request_ref": action_request.request_id,
            "payload": {
                "tool_name": "read_file",
                "tool_args": {"path": "README.md"},
                "result": "ok",
            },
            "authority": "orchestration.runtime_observation",
        }

    monkeypatch.setattr(task_executor_module, "_execute_task_tool_call", _fake_execute_task_tool_call)
    group = ToolBatchGroup(
        group_index=0,
        execution_class="exclusive",
        item_indexes=(0, 1),
        parallel=False,
    )
    invocation_rows = [
        {
            "action_request": SimpleNamespace(
                request_id="act:completed",
                tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
            ),
            "admission": SimpleNamespace(decision="allow"),
            "tool_calls": [{"tool_name": "read_file", "args": {"path": "README.md"}}],
        },
        {
            "action_request": SimpleNamespace(
                request_id="act:pause",
                tool_call={"tool_name": "read_file", "args": {"path": "pyproject.toml"}},
            ),
            "admission": SimpleNamespace(decision="allow"),
            "tool_call": {"tool_name": "read_file", "args": {"path": "pyproject.toml"}},
        },
    ]

    result = asyncio.run(
        task_executor_module._execute_task_tool_batch_group(
            group,
            invocation_rows=invocation_rows,
            runtime_host=SimpleNamespace(),
            services=SimpleNamespace(),
            task_run=SimpleNamespace(task_run_id="taskrun:batch-interrupt", task_id="task:batch-interrupt", session_id="session:batch-interrupt", diagnostics={}),
            packet_ref="packet:batch-interrupt",
            runtime_assembly={},
            runtime_tool_plan=SimpleNamespace(),
        )
    )

    assert [observation["observation_id"] for _row, observation in result["results"]] == ["obs:completed-before-pause"]
    assert result["interrupt"].signal.kind == "pause"

def test_tool_execution_boundary_preserves_pause_signal_without_stopping_task() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:tool-boundary-pause")
    task_run = host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    host.state_index.upsert_task_run(
        replace(
            task_run,
            status="running",
            terminal_reason="",
            diagnostics={
                **dict(task_run.diagnostics or {}),
                "executor_status": "running",
                "executor_epoch": 7,
                "runtime_control": {
                    "state": "pause_requested",
                    "requested_by": "user",
                    "requested_at": 12.0,
                    "reason": "pause before tool",
                    "authority": "orchestration.task_run_control",
                },
            },
        )
    )
    action = ModelActionRequest(
        request_id="model-action:tool-boundary-pause",
        turn_id=task_run_id,
        action_type="tool_call",
        tool_call={"tool_name": "read_file", "args": {"path": "README.md"}},
    )

    async def _run_call() -> None:
        latest = host.state_index.get_task_run(task_run_id)
        assert latest is not None
        await task_executor_module._execute_task_tool_call(
            host,
            services=SimpleNamespace(),
            task_run=latest,
            packet_ref="packet:tool-boundary-pause",
            action_request=action,
            admission=SimpleNamespace(decision="allow"),
            runtime_assembly={},
            runtime_tool_plan=SimpleNamespace(),
        )

    try:
        asyncio.run(_run_call())
    except TaskRunExecutorInterrupted as exc:
        assert exc.signal.kind == "pause"
    else:
        raise AssertionError("pause control did not interrupt tool execution")

    latest = host.state_index.get_task_run(task_run_id)
    assert latest is not None
    assert latest.status == "running"
    assert latest.terminal_reason != "user_aborted"
    assert dict(dict(latest.diagnostics or {}).get("runtime_control") or {}).get("state") == "pause_requested"

def test_task_executor_schedule_missing_callback_blocks_task_run() -> None:
    runtime = build_harness_runtime()
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:missing-scheduler")

    async def _missing_executor(*_args, **_kwargs):
        raise RuntimeError("task_executor_callback_unavailable")

    runtime.execute_task_run = _missing_executor  # type: ignore[method-assign]

    async def _run_scheduler() -> None:
        runtime.schedule_task_run_executor(task_run_id, scheduler="test_missing_callback")
        for _ in range(50):
            task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
            if task_run is not None and task_run.status == "blocked":
                return
            await asyncio.sleep(0.01)
        raise AssertionError("scheduler failure was not recorded")

    asyncio.run(_run_scheduler())

    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "task_executor_schedule_failed"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True

def test_task_executor_scheduler_auto_continues_waiting_executor() -> None:
    runtime = build_harness_runtime()
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:auto-continue")
    calls = {"count": 0}

    async def _executor(task_run_id_arg: str, **_kwargs):
        calls["count"] += 1
        task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id_arg)
        assert task_run is not None
        if calls["count"] == 1:
            runtime.single_agent_runtime_host.state_index.upsert_task_run(
                replace(task_run, status="waiting_executor", terminal_reason="waiting_executor")
            )
            return {"ok": False, "error": "task_execution_step_budget_exhausted", "retryable": True}
        runtime.single_agent_runtime_host.state_index.upsert_task_run(
            replace(task_run, status="completed", terminal_reason="completed")
        )
        return {"ok": True}

    runtime.execute_task_run = _executor  # type: ignore[method-assign]

    async def _run_scheduler() -> None:
        runtime.schedule_task_run_executor(task_run_id, scheduler="test_auto_continue")
        for _ in range(20):
            if calls["count"] >= 2:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("scheduler did not auto-continue waiting_executor")

    asyncio.run(_run_scheduler())

    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=False)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    assert calls["count"] == 2
    assert "task_run_executor_rescheduled" in event_types

def test_task_executor_commits_final_answer_to_session_history() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _action_request(
                    action_type="respond",
                    final_answer="TaskRun 已完成并回写到会话。",
                )
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:session-final-commit",
        contract_source="test",
        user_visible_goal="验证 TaskRun final answer 会回写会话。",
        task_run_goal="完成后把 final answer 写回 session history。",
        completion_criteria=("final answer 已提交到会话历史",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:session-final-commit",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-final-commit",
            task_id="task:session-final-commit",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=2))

    messages = runtime.session_manager.load_session("session-final-commit")
    trace = host.get_trace(lifecycle.task_run_id, include_payloads=False)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert result["ok"] is True
    assert any(
        item.get("role") == "assistant" and item.get("content") == "TaskRun 已完成并回写到会话。"
        for item in messages
    )
    assert "task_run_final_message_commit_checked" in event_types

def test_task_executor_admission_denial_becomes_model_visible_observation_and_continues() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                _tool_action_request(
                    tool_name="missing_tool_for_admission",
                    args={"path": "tmp/not-allowed.txt"},
                    public_progress_note="尝试调用未开放工具。",
                ),
                _action_request(action_type="respond", final_answer="已根据运行边界改为直接收口。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:executor-admission-observation",
        contract_source="test",
        user_visible_goal="验证 admission deny 不会阻塞 executor。",
        task_run_goal="executor 应把 admission deny 作为观察回灌给模型。",
        completion_criteria=("模型收到 admission observation 后可以继续收口",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:executor-admission-observation",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-executor-admission-observation",
            task_id="task:executor-admission-observation",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=3))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    event_types = [str(item.get("event_type") or "") for item in events]
    admission_observation_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_model_action_admission_observation_recorded"
    ]

    assert result["ok"] is True
    assert runtime.model_runtime.task_invocation_count == 2
    assert "task_model_action_admission_observation_recorded" in event_types
    assert "task_run_blocked" not in event_types
    observation = dict(admission_observation_events[0].get("observation") or {})
    assert observation["source"] == "system:model_action_admission"
    assert observation["needs_model_followup"] is True
    assert dict(observation.get("payload") or {}).get("error_code") == "tool_not_in_runtime_assembly"

def test_task_executor_executes_task_execution_tool_calls_batch() -> None:
    batch_action = _tool_calls_action_request(
        tool_calls=[
            {"tool_name": "read_file", "args": {"path": "harness/loop/model_action_protocol.py", "start_line": 1, "line_count": 8}},
            {"tool_name": "read_file", "args": {"path": "harness/runtime/compiler.py", "start_line": 1, "line_count": 8}},
        ],
        public_progress_note="准备并行读取两个文件。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                batch_action,
                _action_request(action_type="respond", final_answer="两个文件都已读取。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        ),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:executor-tool-calls-batch",
        session_id="session-executor-tool-calls-batch",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=3))

    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    batch_plans = [
        dict(dict(item.get("payload") or {}).get("tool_batch_plan") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_batch_planned"
    ]
    observations = [
        dict(dict(item.get("payload") or {}).get("observation") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_observation_recorded"
    ]

    assert result["ok"] is True
    assert batch_plans
    assert batch_plans[0]["diagnostics"]["item_count"] == 2
    assert len(observations) == 2
    assert {dict(item.get("payload") or {}).get("tool_name") for item in observations} == {"read_file"}
    assert runtime.model_runtime.task_invocation_count == 2

def test_task_executor_guards_duplicate_task_execution_tool_calls_batch_child() -> None:
    read_action = _tool_calls_action_request(
        tool_calls=[
            {"tool_name": "path_exists", "args": {"path": "artifacts/not-created-yet.txt"}},
        ],
        public_progress_note="检查目标路径是否存在。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [
                read_action,
                read_action,
                _action_request(action_type="respond", final_answer="已避免重复读取。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        ),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"path_exists"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:executor-duplicate-tool-call-batch-child",
        session_id="session-executor-duplicate-tool-call-batch-child",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))

    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    tool_observations = [
        dict(dict(item.get("payload") or {}).get("observation") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_observation_recorded"
    ]
    duplicate_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_duplicate_tool_call_guarded"
    ]

    assert result["ok"] is True
    assert runtime.model_runtime.task_invocation_count == 3
    assert len(tool_observations) == 1
    assert len(duplicate_events) == 1
    duplicate_payload = dict(dict(duplicate_events[0].get("observation") or {}).get("payload") or {})
    assert duplicate_payload.get("error_code") == "duplicate_read_only_tool_call"
    assert dict(duplicate_payload.get("tool_args") or {}).get("tool_name") == "path_exists"

def test_task_executor_blocks_repeated_tool_failure_after_guard_observation() -> None:
    failing_terminal = _tool_calls_action_request(
        tool_calls=[
            {
                "tool_name": "terminal",
                "args": {"command": "Write-Output 'repeat failure'; exit 7"},
            }
        ],
        public_progress_note="运行会失败的验证命令。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [failing_terminal, failing_terminal, failing_terminal, failing_terminal],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        ),
        permission_service=SimpleNamespace(
            current_mode=lambda: "full_access",
            supported_modes=lambda: ["default", "full_access"],
        ),
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"terminal"}),
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:repeated-tool-failure",
        session_id="session-repeated-tool-failure",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=8))

    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    guard_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_repeated_tool_failure_guarded"
    ]
    tool_observations = [
        dict(dict(item.get("payload") or {}).get("observation") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_tool_observation_recorded"
    ]

    assert result["error"] == "repeated_failure_limit_exceeded"
    assert runtime.model_runtime.task_invocation_count == 4
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "repeated_failure_limit_exceeded"
    recoverable = dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {})
    assert recoverable.get("error_code") == "repeated_failure_limit_exceeded"
    assert recoverable.get("repeat_count") == 4
    assert len(tool_observations) == 4
    assert [payload.get("repeat_count") for payload in guard_events] == [3]
    guard_payload = dict(dict(guard_events[0].get("observation") or {}).get("payload") or {})
    assert guard_payload.get("failure_fingerprint") == recoverable.get("failure_fingerprint")
    assert guard_payload.get("repeat_count") == 3

def test_task_executor_repeated_admission_denial_pauses_before_step_budget() -> None:
    denied_action = _tool_action_request(
        tool_name="missing_tool_for_repeated_admission",
        args={"path": "tmp/not-allowed.txt"},
        public_progress_note="尝试调用未开放工具。",
    )
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [denied_action, denied_action, denied_action],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:repeated-admission-denial",
        session_id="session-repeated-admission-denial",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=8))

    host = runtime.single_agent_runtime_host
    task_run = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    event_types = [str(item.get("event_type") or "") for item in events]
    normal_admission_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_model_action_admission_observation_recorded"
    ]
    guard_events = [
        dict(item.get("payload") or {})
        for item in events
        if str(item.get("event_type") or "") == "task_repeated_model_action_admission_guarded"
    ]

    assert result["error"] == "repeated_admission_denial"
    assert result["retryable"] is True
    assert runtime.model_runtime.task_invocation_count == 3
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    recoverable = dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {})
    assert recoverable.get("error_code") == "repeated_admission_denial"
    assert recoverable.get("repeat_count") == 3
    assert len(normal_admission_events) == 1
    assert [payload.get("repeat_count") for payload in guard_events] == [2, 3]
    assert dict(dict(guard_events[-1].get("observation") or {}).get("payload") or {}).get("pause_after_observation") is True
    assert "task_executor_repeated_admission_denial_paused" in event_types
    assert "task_executor_step_budget_exhausted" not in event_types

def test_task_executor_wait_heartbeat_does_not_repeat_visible_step_summary(monkeypatch) -> None:
    monkeypatch.setattr("harness.loop.task_executor._TASK_MODEL_ACTION_WAIT_STATUS_INTERVAL_SECONDS", 0.001)
    runtime = build_harness_runtime(model_runtime=_SlowTaskExecutorModelRuntime())
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:slow-task-wait",
        contract_source="test",
        user_visible_goal="验证慢任务等待状态。",
        task_run_goal="慢模型返回后完成。",
        completion_criteria=("慢任务完成",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:turn:session-slow-task:1:abc",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-slow-task",
            task_id="task:turn:session-slow-task:1",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"turn_id": "turn:session-slow-task:1", "contract": contract.to_dict()},
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=1))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = list(dict(trace or {}).get("events") or [])
    visible_wait_steps = [
        event
        for event in events
        if str(dict(event).get("event_type") or "") == "step_summary_recorded"
        and str(dict(dict(event).get("payload") or {}).get("step") or "").startswith("task_model_action_waiting:")
    ]
    wait_heartbeats = [
        event
        for event in events
        if str(dict(event).get("event_type") or "") == "task_model_action_wait_heartbeat"
    ]

    visible_invocation_steps = [
        event
        for event in events
        if str(dict(event).get("event_type") or "") == "step_summary_recorded"
        and str(dict(dict(event).get("payload") or {}).get("step") or "").startswith("task_model_action_invocation_started:")
    ]
    summaries = "\n".join(
        str(dict(dict(event).get("payload") or {}).get("summary") or "")
        for event in events
        if str(dict(event).get("event_type") or "") == "step_summary_recorded"
    )

    assert result["ok"] is True
    assert visible_invocation_steps == []
    assert visible_wait_steps == []
    assert wait_heartbeats
    assert "正在根据最新进展" not in summaries
    assert "思考下一步处理方式" not in summaries

def test_running_task_run_is_not_externally_executable_unless_executor_claimed() -> None:
    from harness.loop.task_executor import is_task_run_executable, is_task_run_executor_claimed

    plain_running = TaskRun(
        task_run_id="taskrun:plain-running",
        session_id="session-executor-lease",
        task_id="task:plain-running",
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={},
    )
    claimed_running = replace(
        plain_running,
        task_run_id="taskrun:claimed-running",
        diagnostics={"executor_status": "scheduled"},
    )
    waiting = replace(
        plain_running,
        task_run_id="taskrun:waiting",
        status="waiting_executor",
        terminal_reason="waiting_executor",
    )

    assert is_task_run_executable(waiting) is True
    assert is_task_run_executable(plain_running) is False
    assert is_task_run_executor_claimed(plain_running) is False
    assert is_task_run_executor_claimed(claimed_running) is True

def test_execute_task_run_rejects_duplicate_running_claim() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused")
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:duplicate-running-claim",
        contract_source="test",
        user_visible_goal="防止重复执行器。",
        task_run_goal="防止重复执行器。",
        completion_criteria=("重复执行器必须被拒绝",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    task_run = TaskRun(
        task_run_id="taskrun:duplicate-running-claim",
        session_id="session-duplicate-running-claim",
        task_id="task:duplicate-running-claim",
        task_contract_ref=contract_ref,
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={"executor_status": "running", "executor_epoch": 1},
    )
    host.state_index.upsert_task_run(task_run)

    result = asyncio.run(runtime.execute_task_run(task_run.task_run_id, max_steps=1))

    assert result["ok"] is False
    assert result["error"] == "task_run_executor_already_running"
    trace = host.get_trace(task_run.task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]
    assert "runtime_invocation_packet_compiled" not in event_types

def test_execute_task_run_accepts_scheduled_claim_start() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [_action_request(action_type="respond", final_answer="调度接管完成。")],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:scheduled-claim-start",
        contract_source="test",
        user_visible_goal="允许调度器接管。",
        task_run_goal="允许调度器接管。",
        completion_criteria=("调度器接管后可以执行",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    task_run = TaskRun(
        task_run_id="taskrun:scheduled-claim-start",
        session_id="session-scheduled-claim-start",
        task_id="task:scheduled-claim-start",
        task_contract_ref=contract_ref,
        execution_runtime_kind="single_agent_task",
        status="running",
        diagnostics={"executor_status": "scheduled"},
    )
    host.state_index.upsert_task_run(task_run)

    result = asyncio.run(runtime.execute_task_run(task_run.task_run_id, max_steps=1))

    assert result["ok"] is True

def test_task_executor_uses_task_bound_model_selection_for_runtime_packet_and_invocation(monkeypatch) -> None:
    from harness.loop import task_executor as task_executor_module

    model_selection = {
        "provider": "test-provider",
        "model": "task-bound-test-model",
        "timeout_seconds": 11,
    }
    captured_timeout_selection: dict[str, object] = {}
    original_timeout = task_executor_module.model_action_timeout_seconds

    def _capturing_timeout(model_runtime, *, model_selection):
        captured_timeout_selection.update(dict(model_selection or {}))
        return original_timeout(model_runtime, model_selection=model_selection)

    monkeypatch.setattr(task_executor_module, "model_action_timeout_seconds", _capturing_timeout)

    class _CapturingModelRuntime:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def invoke_messages(self, messages, **kwargs):
            self.calls.append({"messages": list(messages or []), "kwargs": dict(kwargs)})
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(action_type="respond", final_answer="绑定模型配置执行完成。"),
                    ensure_ascii=False,
                )
            )

    model_runtime = _CapturingModelRuntime()
    runtime = build_harness_runtime(model_runtime=model_runtime)
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:model-selection-binding",
        contract_source="test",
        user_visible_goal="验证单节点任务绑定模型配置。",
        task_run_goal="执行器必须使用 task 创建时冻结的模型配置。",
        completion_criteria=("执行器使用 task-bound model_selection",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:model-selection-binding",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-model-selection-binding",
            task_id="task:model-selection-binding",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "turn_id": "turn:session-model-selection-binding:1",
                "contract": contract.to_dict(),
                "model_selection": model_selection,
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=1))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    started_payload = dict(
        next(
            item
            for item in events
            if str(item.get("event_type") or "") == "task_run_executor_started"
        ).get("payload") or {}
    )
    packet_payload = dict(
        next(
            item
            for item in events
            if str(item.get("event_type") or "") == "runtime_invocation_packet_compiled"
        ).get("payload") or {}
    )
    envelope = dict(packet_payload.get("envelope") or {})

    assert result["ok"] is True
    assert model_runtime.calls
    assert dict(dict(model_runtime.calls[0]).get("kwargs") or {}).get("model_spec") == model_selection
    assert captured_timeout_selection == model_selection
    assert dict(dict(started_payload.get("runtime_assembly") or {}).get("model_selection") or {}) == model_selection
    assert dict(dict(envelope.get("diagnostics") or {}).get("model_selection") or {}) == model_selection

def test_execute_task_run_uses_task_bound_agent_profile_for_runtime_assembly() -> None:
    class _CapturingModelRuntime:
        async def invoke_messages(self, messages, **kwargs):
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(action_type="respond", final_answer="绑定 profile 执行完成。"),
                    ensure_ascii=False,
                )
            )

    runtime = build_harness_runtime(model_runtime=_CapturingModelRuntime())
    runtime.agent_runtime_registry.upsert_profile(
        agent_id="agent:3",
        agent_profile_id="custom_single_agent_task_profile",
        allowed_operations=("op.model_response",),
        metadata={},
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:profile-binding",
        contract_source="test",
        user_visible_goal="验证单节点任务绑定 profile。",
        task_run_goal="执行器必须使用 task_run.agent_profile_id 组装 runtime。",
        completion_criteria=("执行器使用 task-bound agent profile",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:profile-binding",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-profile-binding",
            task_id="task:profile-binding",
            task_contract_ref=contract_ref,
            agent_id="agent:3",
            agent_profile_id="custom_single_agent_task_profile",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "turn_id": "turn:session-profile-binding:1",
                "contract": contract.to_dict(),
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=1))

    trace = host.get_trace(lifecycle.task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    started_payload = dict(
        next(
            item
            for item in events
            if str(item.get("event_type") or "") == "task_run_executor_started"
        ).get("payload") or {}
    )
    assembly = dict(started_payload.get("runtime_assembly") or {})
    agent_runs = host.state_index.list_task_agent_runs(lifecycle.task_run_id)
    agent_run_results = host.state_index.list_task_agent_run_results(lifecycle.task_run_id)

    assert result["ok"] is True
    assert assembly["agent_profile_ref"] == "custom_single_agent_task_profile"
    assert assembly["agent_prompt_refs"] == []
    assert assembly["agent_prompt_refs_by_invocation"] == {}
    assert agent_runs[-1].agent_id == "agent:3"
    assert agent_run_results[-1].agent_id == "agent:3"

def test_schedule_task_run_executor_marks_startup_exception_blocked() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:schedule-failure",
        contract_source="test",
        user_visible_goal="验证调度异常落盘。",
        task_run_goal="调度器必须把 executor 启动异常写回 TaskRun。",
        completion_criteria=("启动异常被标记为 blocked",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:schedule-failure",
            session_id="session-schedule-failure",
            task_id="task:schedule-failure",
            task_contract_ref=contract_ref,
            agent_profile_id="missing_single_agent_profile",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            diagnostics={"contract": contract.to_dict()},
        )
    )

    async def _run() -> dict[str, object]:
        scheduled = runtime.schedule_task_run_executor(
            "taskrun:schedule-failure",
            scheduler="test_schedule_failure",
            max_steps=1,
        )
        for _ in range(10):
            await asyncio.sleep(0)
            current = host.state_index.get_task_run("taskrun:schedule-failure")
            if current is not None and current.status == "blocked":
                break
        return scheduled

    scheduled = asyncio.run(_run())

    task_run = host.state_index.get_task_run("taskrun:schedule-failure")
    diagnostics = dict(task_run.diagnostics or {}) if task_run is not None else {}
    events = [item.event_type for item in host.event_log.list_events("taskrun:schedule-failure")]

    assert scheduled["ok"] is True
    assert scheduled["scheduled"] is True
    assert task_run is not None
    assert task_run.status == "blocked"
    assert diagnostics["latest_step"] == "task_executor_schedule_failed"
    assert diagnostics["recoverable_error"]["retryable"] is True
    assert "missing_single_agent_profile" in diagnostics["recoverable_error"]["detail"]
    assert "task_run_executor_schedule_failed" in events

def test_task_executor_services_include_backend_config_for_runtime_fingerprint() -> None:
    from harness.loop.task_executor import _safe_backend_config

    class _SettingsWithBackendConfig(PrimarySettingsStub):
        def task_executor_backend_config(self) -> dict[str, object]:
            return {
                "image_assets": {
                    "base_url": "https://image.example.test/v1",
                    "model": "image-test-model",
                    "api_key_present": True,
                }
            }

    runtime = build_harness_runtime(settings_service=_SettingsWithBackendConfig())

    services = runtime._task_executor_services()
    config = _safe_backend_config(services.backend_config)

    assert config["image_generation"] == {
        "base_url": "https://image.example.test/v1",
        "model": "image-test-model",
        "api_key_present": True,
    }

def test_runtime_start_recovers_interrupted_task_executor_lease() -> None:
    from harness.loop.task_executor_controller import TaskExecutorController

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:interrupted-executor",
            session_id="session-interrupted-executor",
            task_id="task:interrupted-executor",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={
                "executor_status": "scheduled",
                "latest_step": "task_executor_scheduled",
                "latest_step_summary": "正在根据最新进展思考下一步处理方式。",
                "latest_public_progress_note": "正在根据最新进展思考下一步处理方式。",
            },
        )
    )

    result = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run).recover_interrupted_executor_leases()
    task_run = host.state_index.get_task_run("taskrun:interrupted-executor")

    assert result["recovered_count"] == 1
    assert result["authority"] == "harness.loop.task_executor_controller.runtime_start_recovery"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    diagnostics = dict(task_run.diagnostics or {})
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert diagnostics.get("latest_step_summary") == "后端运行时已重启，当前工作已恢复为可继续状态。"
    assert diagnostics.get("latest_public_progress_note") == "后端运行时已重启，当前工作已恢复为可继续状态。"

def test_runtime_start_recovery_reschedules_recovered_executor() -> None:
    from harness.loop.task_executor_controller import TaskExecutorController

    class _SpawnedTask:
        def done(self) -> bool:
            return False

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:runtime-start-reschedule"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-runtime-start-reschedule",
            task_id="task:runtime-start-reschedule",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={
                "executor_status": "scheduled",
                "latest_step": "task_executor_scheduled",
                "latest_step_summary": "执行器在上一进程中持有运行权。",
            },
        )
    )
    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run)
    recovery = controller.recover_interrupted_executor_leases()
    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return _SpawnedTask()

    host.spawn_background_task = _capture_background_task

    schedule = controller.schedule_runtime_start_recovered_executors(recovery["task_run_ids"], scheduler="test_runtime_start")
    task_run = host.state_index.get_task_run(task_run_id)

    assert schedule["scheduled_count"] == 1
    assert schedule["scheduled_task_run_ids"] == [task_run_id]
    assert spawned == [f"task-run-executor:{task_run_id}"]
    assert task_run is not None
    assert task_run.status == "running"
    diagnostics = dict(task_run.diagnostics or {})
    assert diagnostics.get("executor_status") == "scheduled"
    assert diagnostics.get("executor_recovered_from") == "runtime_start_recovery"

def test_runtime_start_recovery_does_not_reschedule_paused_executor() -> None:
    from harness.loop.task_executor_controller import TaskExecutorController

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:runtime-start-paused"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-runtime-start-paused",
            task_id="task:runtime-start-paused",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            terminal_reason="waiting_executor",
            diagnostics={
                "executor_status": "waiting_executor",
                "recovery_action": "rerun_task_executor",
                "recoverable_error": {
                    "error_code": "task_executor_interrupted_by_runtime_restart",
                    "retryable": True,
                    "user_message": "后端运行时已重启，任务可以继续续跑。",
                },
                "runtime_control": {
                    "state": "paused",
                    "requested_by": "user",
                    "requested_at": 100.0,
                    "reason": "用户暂停",
                    "authority": "orchestration.task_run_control",
                },
            },
        )
    )
    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run)
    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return object()

    host.spawn_background_task = _capture_background_task

    schedule = controller.schedule_runtime_start_recovered_executors(scheduler="test_runtime_start")
    task_run = host.state_index.get_task_run(task_run_id)

    assert schedule["scheduled_count"] == 0
    assert schedule["skipped"] == [{"task_run_id": task_run_id, "reason": "not_executable:waiting_executor"}]
    assert spawned == []
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert dict(dict(task_run.diagnostics or {}).get("runtime_control") or {}).get("state") == "paused"

def test_scheduled_executor_recovery_does_not_spawn_duplicate_live_runner() -> None:
    from harness.loop.task_executor_controller import TaskExecutorController

    class _LiveTask:
        def done(self) -> bool:
            return False

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:scheduled-live-runner"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-scheduled-live-runner",
            task_id="task:scheduled-live-runner",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={
                "executor_status": "scheduled",
                "latest_step": "task_executor_scheduled",
                "latest_step_summary": "执行器刚被调度，后台任务仍在当前进程中。",
            },
        )
    )
    host._background_tasks_by_name[f"task-run-executor:{task_run_id}"] = {_LiveTask()}
    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return _LiveTask()

    host.spawn_background_task = _capture_background_task

    result = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run).recover_scheduled(
        task_run_id,
        scheduler="test_duplicate_recovery",
    )

    assert result["ok"] is True
    assert result["scheduled"] is False
    assert result["reason"] == "already_running"
    assert spawned == []

def test_runtime_start_recovery_skips_graph_node_assigned_task_run() -> None:
    from harness.loop.task_executor_controller import TaskExecutorController

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="gtask:graph:node:work",
            session_id="session-graph-node-recovery",
            task_id="task:graph-node",
            execution_runtime_kind="single_agent_task",
            status="running",
            diagnostics={
                "executor_status": "scheduled",
                "origin_kind": "graph_node_assigned",
                "origin": {
                    "origin_kind": "graph_node_assigned",
                    "origin_authority": "harness.graph_loop",
                    "origin_ref": "gwork:graph:node",
                    "parent_run_ref": "grun:graph",
                },
                "graph_node_id": "draft",
                "graph_work_order_id": "gwork:graph:node",
            },
        )
    )

    result = TaskExecutorController(runtime_host=host, execute_task_run_callback=runtime.execute_task_run).recover_interrupted_executor_leases()
    task_run = host.state_index.get_task_run("gtask:graph:node:work")

    assert result["recovered_count"] == 0
    assert result["task_run_ids"] == []
    assert result["skipped_graph_node_task_run_ids"] == ["gtask:graph:node:work"]
    assert task_run is not None
    assert task_run.status == "running"
    assert dict(task_run.diagnostics or {}).get("executor_status") == "scheduled"

def test_task_run_executor_keeps_model_call_failure_recoverable() -> None:
    runtime = build_harness_runtime(model_runtime=_FailingModelRuntime())
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:recoverable-model-failure",
        session_id="session-recoverable-model-failure",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    monitor = runtime.single_agent_runtime_host.get_task_run_live_monitor(task_run_id)

    assert result["error"] == "model_call_recovery_required"
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "model_call_recovery_required"
    assert dict(task_run.diagnostics or {}).get("recovery_action") == "rerun_task_executor"
    assert monitor is not None
    assert monitor["latest_step_status"] == "blocked"
    assert "模型调用失败" in monitor["latest_step_summary"]

def test_task_run_executor_recovers_invalid_model_action_as_observation() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:test:invalid-task-step",
                    "turn_id": "",
                    "action_type": "",
                },
                    _action_request(
                        action_type="respond",
                        public_progress_note="已修正上一步输出格式，正在收口结果。",
                        final_answer="已按合同完成。",
                        diagnostics={"artifacts": []},
                    ),
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "协议错误后继续执行。", "task_run_goal": "协议错误后继续执行。", "completion_criteria": ["允许无文件收口"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:protocol-repair",
        session_id="session-protocol-repair",
    )
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=3))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [str(dict(item).get("event_type") or "") for item in list(dict(trace or {}).get("events") or [])]

    assert result["ok"] is True
    assert task_run is not None
    assert task_run.status == "completed"
    assert runtime.model_runtime.task_invocation_count == 2
    assert "task_model_action_protocol_repair_required" in event_types

def test_task_run_executor_blocks_repeated_invalid_model_actions_as_recoverable() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-1", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-2", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-3", "turn_id": "", "action_type": ""},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "连续协议错误后阻塞。", "task_run_goal": "连续协议错误后阻塞。", "completion_criteria": ["不应完成"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:protocol-block",
        session_id="session-protocol-block",
    )
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "model_action_protocol_repair_required"
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "model_action_protocol_repair_required"
    assert dict(task_run.diagnostics or {}).get("executor_status") == "waiting_executor"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True

def test_recoverable_terminal_closeout_clears_stale_running_executor_status() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-1", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-2", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-3", "turn_id": "", "action_type": ""},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "清理运行态。", "task_run_goal": "清理运行态。", "completion_criteria": ["可恢复阻塞不残留 running"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:recoverable-closeout-clears-running",
        session_id="session-recoverable-closeout-clears-running",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert task_run is not None
    diagnostics = dict(task_run.diagnostics or {})
    assert task_run.status == "waiting_executor"
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert dict(diagnostics.get("runtime_control") or {}).get("state") != "running"
    assert diagnostics.get("recovery_action") == "rerun_task_executor"

def test_ask_user_blocks_as_waiting_executor_without_running_lease() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                _action_request(
                    action_type="ask_user",
                    public_progress_note="需要用户确认下一步。",
                    diagnostics={},
                )
                | {"user_question": "请确认下一步。"},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "等待用户输入。", "task_run_goal": "等待用户输入。", "completion_criteria": ["必须等待用户"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:ask-user-waiting",
        session_id="session-ask-user-waiting",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "user_input_required"
    assert task_run is not None
    diagnostics = dict(task_run.diagnostics or {})
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "user_input_required"
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert diagnostics.get("recovery_action") == "resume_task_run"

def test_resume_recoverable_blocked_task_preserves_recovery_and_becomes_schedulable() -> None:
    from harness.loop.task_executor import is_task_run_executable, resume_paused_task_run

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:resume-recoverable-blocked",
        contract_source="test",
        user_visible_goal="恢复可恢复阻塞。",
        task_run_goal="恢复可恢复阻塞。",
        completion_criteria=("可恢复阻塞可以被继续调度",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.runtime_objects.put_object(
        "task_lifecycle",
        "taskrun:resume-recoverable-blocked",
        TaskLifecycleRecord(
            task_run_id="taskrun:resume-recoverable-blocked",
            contract_ref=contract_ref,
            status="blocked",
            created_at=1.0,
            updated_at=1.0,
            terminal_reason="model_call_recovery_required",
        ).to_dict(),
    )
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:resume-recoverable-blocked",
            session_id="session-resume-recoverable-blocked",
            task_id="task:resume-recoverable-blocked",
            task_contract_ref=contract_ref,
            execution_runtime_kind="single_agent_task",
            status="blocked",
            terminal_reason="model_call_recovery_required",
            diagnostics={
                "contract": contract.to_dict(),
                "executor_status": "blocked",
                "recoverable_error": {"error_code": "model_call_failed", "retryable": True},
                "recovery_action": "rerun_task_executor",
            },
        )
    )

    result = resume_paused_task_run(host, "taskrun:resume-recoverable-blocked", reason="继续")
    task_run = host.state_index.get_task_run("taskrun:resume-recoverable-blocked")

    assert result["ok"] is True
    assert task_run is not None
    diagnostics = dict(task_run.diagnostics or {})
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    assert diagnostics.get("executor_status") == "waiting_executor"
    assert diagnostics.get("recovery_action") == "rerun_task_executor"
    assert dict(diagnostics.get("recoverable_error") or {}).get("retryable") is True
    assert is_task_run_executable(task_run) is True

def test_waiting_approval_task_run_requires_bound_grant_before_resume() -> None:
    from harness.loop.task_executor import (
        approve_task_run_tool_call,
        is_task_run_executable,
        resume_paused_task_run,
    )
    from harness.loop.task_tool_approval import tool_args_hash

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:resume-tool-approval"
    contract = TaskRunContract(
        contract_id="task-contract:resume-tool-approval",
        contract_source="test",
        user_visible_goal="恢复等待审批的工具调用。",
        task_run_goal="恢复等待审批的工具调用。",
        completion_criteria=("审批后同一个 TaskRun 可以继续调度",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    host.runtime_objects.put_object(
        "task_lifecycle",
        task_run_id,
        TaskLifecycleRecord(
            task_run_id=task_run_id,
            contract_ref=contract_ref,
            status="waiting_approval",
            created_at=1.0,
            updated_at=1.0,
            terminal_reason="waiting_approval",
        ).to_dict(),
    )
    pending_approval = {
        "status": "pending",
        "task_run_id": task_run_id,
        "action_request_ref": "model-action:test:browser",
        "approval_request_id": "approval-request:test:browser",
        "tool_call_id": "call:browser",
        "tool_name": "browser_control",
        "operation_id": "op.browser_control",
        "directive_ref": f"runtime-directive:{task_run_id}:tool:model-action:test:browser",
        "approval_risk_fingerprint": "risk:browser:approved-url",
        "tool_args_hash": tool_args_hash({"action": "open", "url": "https://example.com"}),
        "action_request": {
            "request_id": "model-action:test:browser",
            "action_type": "tool_call",
            "tool_call": {
                "tool_name": "browser_control",
                "operation_id": "op.browser_control",
                "args": {"action": "open", "url": "https://example.com"},
            },
        },
    }
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-resume-tool-approval",
            task_id="task:resume-tool-approval",
            task_contract_ref=contract_ref,
            execution_runtime_kind="single_agent_task",
            status="waiting_approval",
            terminal_reason="waiting_approval",
            diagnostics={
                "contract": contract.to_dict(),
                "executor_status": "waiting_approval",
                "pending_approval": pending_approval,
            },
        )
    )

    initial_task = host.state_index.get_task_run(task_run_id)
    denied_resume = resume_paused_task_run(host, task_run_id, reason="未审批直接继续")

    assert initial_task is not None
    assert is_task_run_executable(initial_task) is False
    assert denied_resume["ok"] is False
    assert denied_resume["error"] == "task_run_waiting_approval_requires_grant"

    approval_result = approve_task_run_tool_call(host, task_run_id, reason="允许打开此 URL")
    approved_task = host.state_index.get_task_run(task_run_id)

    assert approval_result["ok"] is True
    assert approved_task is not None
    assert approved_task.status == "waiting_approval"
    assert dict(dict(approved_task.diagnostics or {}).get("pending_approval") or {}).get("status") == "approved"
    assert is_task_run_executable(approved_task) is True

    resume_result = resume_paused_task_run(host, task_run_id, reason="审批后继续")
    resumed_task = host.state_index.get_task_run(task_run_id)

    assert resume_result["ok"] is True
    assert resumed_task is not None
    assert resumed_task.status == "waiting_executor"
    assert resumed_task.terminal_reason == "waiting_executor"
    assert dict(resumed_task.diagnostics or {}).get("executor_status") == "waiting_executor"
    assert dict(dict(resumed_task.diagnostics or {}).get("runtime_control") or {}).get("state") == "resume_requested"
    assert dict(dict(resumed_task.diagnostics or {}).get("pending_approval") or {}).get("status") == "approved"
    assert dict(dict(resumed_task.diagnostics or {}).get("approval_state") or {}).get("status") == "approved"
    assert is_task_run_executable(resumed_task) is True

def test_task_run_executor_step_budget_exhaustion_waits_for_next_run() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:test:budget-invalid",
                    "turn_id": "",
                    "action_type": "",
                },
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"user_visible_goal": "预算耗尽后续跑。", "task_run_goal": "预算耗尽后续跑。", "completion_criteria": ["需要下一轮继续"]},
            ),
        )
    )
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:budget-wait",
        session_id="session-budget-wait",
    )
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["error"] == "task_execution_step_budget_exhausted"
    assert result["retryable"] is True
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert task_run.terminal_reason == "waiting_executor"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True

def test_task_run_pause_resume_and_stop_control_plane() -> None:
    from harness.loop.task_executor import (
        request_task_run_pause,
        resume_paused_task_run,
        stop_task_run,
        task_run_control_state,
    )

    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                _action_request(action_type="respond", final_answer="暂停后继续完成。"),
            ],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:pause-resume",
        contract_source="test",
        user_visible_goal="验证暂停继续控制。",
        task_run_goal="验证暂停继续控制。",
        completion_criteria=("可以暂停并从同一个 TaskRun 继续",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:pause-resume",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-pause-resume",
            task_id="task:pause-resume",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    pause_result = request_task_run_pause(host, lifecycle.task_run_id, reason="先暂停")
    paused_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert pause_result["ok"] is True
    assert paused_task is not None
    assert paused_task.status == "waiting_executor"
    assert task_run_control_state(paused_task) == "paused"

    resume_result = resume_paused_task_run(host, lifecycle.task_run_id, reason="继续")
    resumed_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert resume_result["ok"] is True
    assert resumed_task is not None
    assert task_run_control_state(resumed_task) == "resume_requested"

    result = asyncio.run(runtime.execute_task_run(lifecycle.task_run_id, max_steps=2))
    completed_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert result["ok"] is True
    assert completed_task is not None
    assert completed_task.status == "completed"

    stop_result = stop_task_run(host, lifecycle.task_run_id, reason="已完成后停止无效")
    assert stop_result["ok"] is True
    assert stop_result["accepted"] is False

def test_task_run_stop_before_executor_marks_user_aborted() -> None:
    from harness.loop.task_executor import stop_task_run, task_run_control_state

    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id="task-contract:stop-before-executor",
        contract_source="test",
        user_visible_goal="验证停止控制。",
        task_run_goal="验证停止控制。",
        completion_criteria=("停止后进入用户终态",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id="taskrun:stop-before-executor",
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", lifecycle.task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=lifecycle.task_run_id,
            session_id="session-stop-before-executor",
            task_id="task:stop-before-executor",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={"contract": contract.to_dict()},
        )
    )

    result = stop_task_run(host, lifecycle.task_run_id, reason="用户停止")
    stopped_task = host.state_index.get_task_run(lifecycle.task_run_id)

    assert result["ok"] is True
    assert stopped_task is not None
    assert stopped_task.status == "aborted"
    assert stopped_task.terminal_reason == "user_aborted"
    assert task_run_control_state(stopped_task) == "stopped"

def test_task_executor_records_task_action_without_cross_context_fields() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            [_action_request(action_type="respond", final_answer="已完成当前任务。")],
            agent_turn_action_request=_action_request(action_type="respond", final_answer="unused"),
        )
    )
    task_run_id = _seed_active_work(runtime, task_run_id="taskrun:slim-task-action")
    host = runtime.single_agent_runtime_host

    asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    event = next(
        event
        for event in host.event_log.list_events(task_run_id)
        if event.event_type == "model_action_request_received"
    )
    action_payload = dict(dict(event.payload or {}).get("model_action_request") or {})

    assert action_payload["action_type"] == "respond"
    assert "task_contract_seed" not in action_payload
    assert "completion_contract" not in action_payload
    assert "permission_request" not in action_payload
    assert "engagement_request" not in action_payload
    assert "active_work_control" not in action_payload
    assert "selected_skill_ids" not in action_payload

def test_terminal_diagnostics_are_stripped_before_task_resume_packet() -> None:
    from harness.loop.task_executor import _strip_terminal_diagnostics

    cleaned = _strip_terminal_diagnostics(
        {
            "contract": {"user_visible_goal": "继续任务"},
            "action_request": {"action_type": "block", "blocking_reason": "old blocker"},
            "terminal_reason": "old blocker",
            "recoverable_error": {"detail": "old model error"},
            "recovery_action": "rerun_task_executor",
            "latest_step_summary": "old blocked summary",
        }
    )

    assert cleaned == {"contract": {"user_visible_goal": "继续任务"}}
