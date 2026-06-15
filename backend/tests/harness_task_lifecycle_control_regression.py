from __future__ import annotations

from tests.support.harness_runtime_facade_support import *
from harness.runtime.assembly import build_runtime_assembly_profile
from harness.loop.model_action_protocol import TaskExecutionModelActionRequest
from harness.loop.task_executor import _pause_executor_for_tool_approval
from harness.task_run_state_view import task_run_state_view
from runtime.shared.models import AgentRun


def test_assistant_task_run_final_commit_preserves_structural_lifecycle_fields() -> None:
    runtime = build_harness_runtime()

    runtime._apply_assistant_message_commit(
        "session-structural-taskrun",
        {
            "role": "assistant",
            "content": "final",
            "task_run_id": "taskrun:turn:session-structural-taskrun:1:abc",
            "task_id": "task:turn:session-structural-taskrun:1",
            "completion_state": "completed",
            "terminal_reason": "completed",
            "answer_channel": "final_answer",
            "answer_source": "harness.loop.task_executor.completed",
        },
    )

    messages = runtime.session_manager.load_session("session-structural-taskrun")

    assert len(messages) == 1
    assert messages[0]["task_run_id"] == "taskrun:turn:session-structural-taskrun:1:abc"
    assert messages[0]["task_id"] == "task:turn:session-structural-taskrun:1"
    assert messages[0]["completion_state"] == "completed"
    assert messages[0]["terminal_reason"] == "completed"
    assert messages[0]["answer_channel"] == "final_answer"


def test_task_run_success_commits_session_output_before_completed_lifecycle() -> None:
    final_answer = "Executor final answer."
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer=final_answer,
                    public_progress_note="Ready to complete.",
                ),
                ensure_ascii=False,
            )
        )
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-output-order:1:abc",
        session_id="session-output-order",
        status="running",
    )
    seeded = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            seeded,
            diagnostics={
                **dict(seeded.diagnostics or {}),
                "turn_id": "turn:session-output-order:1",
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    events = host.event_log.list_events(task_run_id)
    event_types = [str(event.event_type) for event in events]
    body_event = next(event for event in events if event.event_type == "assistant_text_final")
    ack_event = next(event for event in events if event.event_type == "session_output_commit_ack")
    completed_event = next(
        event
        for event in events
        if event.event_type == "task_run_lifecycle_finished"
        and dict(dict(event.payload or {}).get("lifecycle") or {}).get("status") == "completed"
    )
    messages = runtime.session_manager.load_session("session-output-order")
    finished_task = host.state_index.get_task_run(task_run_id)

    assert result["ok"] is True
    assert finished_task.status == "completed"
    assert dict(body_event.payload)["content"] == final_answer
    assert event_types.index("assistant_text_final") < event_types.index("session_output_commit_checked")
    assert event_types.index("session_output_commit_checked") < event_types.index("session_output_commit_ack")
    assert int(ack_event.offset) < int(completed_event.offset)
    assert dict(result["output_commit"])["state"] == "committed"
    assert dict(finished_task.diagnostics)["output_commit_status"] == "committed"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == final_answer
    assert messages[-1]["turn_id"] == "turn:session-output-order:1"


def test_task_run_tool_lifecycle_preserves_model_tool_call_id(tmp_path) -> None:
    model_tool_call_id = "call:task-read-custom"
    model = NativeToolCallSequenceModelRuntimeStub(
        [
            {
                "content": json.dumps(
                    _tool_calls_action_request(
                        tool_calls=[
                            {
                                "id": model_tool_call_id,
                                "tool_name": "read_file",
                                "args": {"path": "harness/loop/task_executor.py", "line_count": 1},
                            }
                        ],
                        public_progress_note="读取 task executor 入口。",
                    ),
                    ensure_ascii=False,
                )
            },
            {
                "content": json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="读取完成。",
                        public_progress_note="工具结果已经确认。",
                    ),
                    ensure_ascii=False,
                )
            },
        ]
    )
    runtime = build_harness_runtime(
        base_dir=_runtime_test_root(tmp_path),
        model_runtime=model,
        tool_runtime=_tool_runtime_for_names(_project_backend_dir(), {"read_file"}),
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-tool-id:1:abc",
        session_id="session-tool-id",
        status="running",
    )
    seeded = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            seeded,
            diagnostics={
                **dict(seeded.diagnostics or {}),
                "turn_id": "turn:session-tool-id:1",
            },
        )
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=3))
    events = host.event_log.list_events(task_run_id)
    admission_event = next(
        event
        for event in events
        if event.event_type == "model_action_admission_checked"
        and dict(dict(event.payload or {}).get("model_action_request") or {}).get("action_type") == "tool_call"
    )
    started_event = next(event for event in events if event.event_type == "tool_item_started")
    observation_event = next(event for event in events if event.event_type == "task_tool_observation_recorded")
    observation = dict(dict(observation_event.payload or {}).get("observation") or {})
    tool_payload = dict(observation.get("payload") or {})
    completed = _project_public_stream_event(
        "task_tool_observation_recorded",
        {"event": observation_event.to_dict()},
    )

    assert result["ok"] is True
    assert dict(dict(admission_event.payload or {}).get("model_action_request") or {})["tool_call"]["id"] == model_tool_call_id
    assert dict(started_event.payload)["tool_call_id"] == model_tool_call_id
    assert observation["tool_call_id"] == model_tool_call_id
    assert tool_payload["tool_call_id"] == model_tool_call_id
    assert [event_type for event_type, _ in completed] == ["tool_item_completed"]
    assert completed[0][1]["tool_call_id"] == model_tool_call_id


def test_task_run_pending_approval_preserves_model_tool_call_id(tmp_path) -> None:
    runtime = build_harness_runtime(base_dir=_runtime_test_root(tmp_path))
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-tool-approval-id:1:abc",
        session_id="session-tool-approval-id",
        status="running",
    )
    task_run = host.state_index.get_task_run(task_run_id)
    agent_run = AgentRun(
        agent_run_id=f"agrun:{task_run_id}:main",
        task_run_id=task_run_id,
        agent_id="agent:main",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    action_request = TaskExecutionModelActionRequest(
        request_id="request:write-file",
        turn_id="turn:session-tool-approval-id:1",
        action_type="tool_call",
        tool_call={
            "id": "call:write-file-model",
            "tool_name": "write_file",
            "args": {"path": "README.md", "content": "updated"},
        },
        tool_calls=(
            {
                "id": "call:write-file-model",
                "tool_name": "write_file",
                "args": {"path": "README.md", "content": "updated"},
            },
        ),
    )

    result = _pause_executor_for_tool_approval(
        host,
        task_run=task_run,
        agent_run=agent_run,
        action_request=action_request,
        observation={
            "observation_id": "toolobs:approval:write",
            "directive_ref": "runtime-directive:approval:write",
            "payload": {
                "operation_id": "op.write_file",
                "operation_gate": {"decision": "requires_approval"},
                "execution_receipt": {"tool_call_id": "call:write-file-model"},
            },
        },
        observation_event=SimpleNamespace(offset=7),
        step_index=1,
    )
    updated_task = host.state_index.get_task_run(task_run_id)

    assert result["error"] == "waiting_approval"
    assert result["pending_approval"]["action_request_ref"] == "request:write-file"
    assert result["pending_approval"]["tool_call_id"] == "call:write-file-model"
    assert dict(updated_task.diagnostics)["pending_approval"]["tool_call_id"] == "call:write-file-model"


def test_task_run_final_output_without_turn_id_uses_task_run_output_turn_id() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer="This answer is committed with a task-run scoped output turn id.",
                    public_progress_note="Ready to complete.",
                ),
                ensure_ascii=False,
            )
        )
    )
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:turn:session-output-missing-turn:1:abc",
        session_id="session-output-missing-turn",
        status="running",
    )

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=2))
    events = host.event_log.list_events(task_run_id)
    ack_event = next(event for event in events if event.event_type == "session_output_commit_ack")
    lifecycle_event = next(event for event in events if event.event_type == "task_run_lifecycle_finished")
    ack_payload = dict(ack_event.payload or {})
    lifecycle_payload = dict(dict(lifecycle_event.payload or {}).get("lifecycle") or {})
    finished_task = host.state_index.get_task_run(task_run_id)
    messages = runtime.session_manager.load_session("session-output-missing-turn")

    assert result["ok"] is True
    assert finished_task.status == "completed"
    assert lifecycle_payload["status"] == "completed"
    assert int(ack_event.offset) < int(lifecycle_event.offset)
    assert ack_payload["reason"] == "committed"
    assert str(ack_payload["turn_id"]).startswith("taskrun-final:")
    assert dict(finished_task.diagnostics)["execution_result_status"] == "completed"
    assert dict(finished_task.diagnostics)["output_commit_status"] == "committed"
    assert messages[-1]["turn_id"] == ack_payload["turn_id"]


def test_running_stop_signal_is_observed_by_agent_before_closeout() -> None:
    from harness.loop.task_executor import stop_task_run

    class InterruptibleStopModelRuntime:
        def __init__(self) -> None:
            self.calls = 0
            self.seen_messages: list[list[object]] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.calls += 1
            self.seen_messages.append(list(messages or []))
            if self.calls == 1:
                await asyncio.sleep(60)
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="respond",
                        final_answer="agent-authored stop closeout",
                    ),
                    ensure_ascii=False,
                )
            )

    model = InterruptibleStopModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:stop-signal",
        session_id="session-stop-signal",
        status="running",
    )

    async def _run() -> tuple[dict[str, object], dict[str, object]]:
        execution = asyncio.create_task(runtime.execute_task_run(task_run_id, max_steps=4))
        for _ in range(100):
            task = host.state_index.get_task_run(task_run_id)
            diagnostics = dict(getattr(task, "diagnostics", {}) or {}) if task is not None else {}
            if diagnostics.get("executor_status") == "running":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("executor did not enter running state")
        stop_result = stop_task_run(host, task_run_id, reason="user_stop_test", requested_by="user")
        result = await asyncio.wait_for(execution, timeout=3)
        return stop_result, result

    stop_result, result = asyncio.run(_run())
    task = host.state_index.get_task_run(task_run_id)
    trace = host.get_trace(task_run_id, include_payloads=True)
    events = [dict(item) for item in list(dict(trace or {}).get("events") or [])]
    event_types = [str(event.get("event_type") or "") for event in events]
    control_observations = [
        dict(dict(event.get("payload") or {}).get("observation") or {})
        for event in events
        if event.get("event_type") == "task_runtime_control_signal_observed"
    ]
    second_model_payload = json.dumps(model.seen_messages[1:], ensure_ascii=False, default=str)

    assert stop_result["accepted"] is True
    assert result["error"] == "user_aborted"
    assert result["final_answer"] == "agent-authored stop closeout"
    assert task is not None
    assert task.status == "aborted"
    assert task.terminal_reason == "user_aborted"
    assert event_types.count("task_runtime_control_signal_observed") == 1
    assert "task_run_stopped" not in event_types
    assert control_observations
    assert control_observations[0]["source"] == "system:runtime_control_signal"
    assert dict(control_observations[0]["payload"])["signal_kind"] == "stop"
    assert "runtime_control_signal" in second_model_payload
    assert "signal_kind" in second_model_payload


def test_runtime_start_recovery_marks_network_interrupted_executor_resumable() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:network-interrupted",
        session_id="session-network-interrupted",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
            },
        )
    )

    result = runtime.task_executor_controller.recover_interrupted_executor_leases()
    recovered = host.state_index.get_task_run(task_run_id)
    events = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert result["recovered_count"] == 1
    assert result["task_run_ids"] == [task_run_id]
    assert recovered.status == "waiting_executor"
    assert recovered.terminal_reason == ""
    assert dict(recovered.diagnostics)["executor_status"] == "waiting_executor"
    assert dict(recovered.diagnostics)["wait_reason"] == "task_executor_interrupted_by_runtime_restart"
    assert dict(recovered.diagnostics)["recovery_action"] == "rerun_task_executor"
    assert dict(dict(recovered.diagnostics)["recoverable_error"])["error_code"] == "task_executor_interrupted_by_runtime_restart"
    assert "task_run_executor_recovered_after_runtime_start" in events
    state_view = task_run_state_view(recovered)
    assert state_view["task_work_state"] == "ready_to_continue"
    assert state_view["recovery_cause"] == "runtime_restart"
    assert state_view["control_reason"] == "runtime_restart_waiting_resume"
    assert state_view["activity"]["activity_label"] == "运行时重启后待续跑"
    assert "后端运行时已重启" in state_view["activity"]["detail"]


def test_runtime_start_recovery_does_not_auto_schedule_recovered_executor() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:restart-recovered-no-autoschedule",
        session_id="session-restart-recovered-no-autoschedule",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
            },
        )
    )
    runtime.task_executor_controller.recover_interrupted_executor_leases()

    result = runtime.task_executor_controller.schedule(
        task_run_id,
        scheduler="runtime_start_recovery",
        max_steps=4,
        recovered_from="runtime_start_recovery",
    )
    unchanged = host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["scheduled"] is False
    assert result["reason"] == "runtime_start_recovery_does_not_auto_schedule"
    assert unchanged.status == "waiting_executor"
    assert dict(unchanged.diagnostics)["executor_status"] == "waiting_executor"

    recover_result = runtime.task_executor_controller.recover_scheduled(
        task_run_id,
        scheduler="runtime_start_recovery",
        max_steps=4,
        recovered_from="runtime_start_recovery",
    )

    assert recover_result["ok"] is False
    assert recover_result["scheduled"] is False
    assert recover_result["reason"] == "runtime_start_recovery_does_not_auto_schedule"


def test_runtime_start_recovery_does_not_reconnect_user_controlled_interruption() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = _seed_active_work(
        runtime,
        task_run_id="taskrun:user-replan-interrupted",
        session_id="session-user-replan-interrupted",
        status="running",
    )
    task = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task,
            diagnostics={
                **dict(task.diagnostics or {}),
                "executor_status": "running",
                "runtime_control": {
                    "state": "replan_requested",
                    "requested_by": "user",
                    "reason": "new_user_instruction",
                },
            },
        )
    )

    result = runtime.task_executor_controller.recover_interrupted_executor_leases()
    unchanged = host.state_index.get_task_run(task_run_id)
    events = [event.event_type for event in host.event_log.list_events(task_run_id)]

    assert result["recovered_count"] == 0
    assert result["task_run_ids"] == []
    assert unchanged.status == "running"
    assert dict(unchanged.diagnostics)["executor_status"] == "running"
    assert "task_run_executor_recovered_after_runtime_start" not in events


def test_explicit_contract_task_starts_lifecycle_without_model_action_loop() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content="单轮收口回答",
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="不应调用模型动作协议。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-explicit-contract",
                message="按合同启动任务。",
                runtime_contract={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "allowed_operations": ["op.model_response", "op.read_file"],
                    "system_issued_contract": True,
                    "task_contract": {
                        "contract_id": "contract:explicit:test",
                        "user_visible_goal": "交付显式合同任务。",
                        "task_run_goal": "根据显式合同创建并执行任务。",
                        "working_scope": {
                            "target_objects": ["显式合同任务"],
                            "workspace_refs": [],
                            "source_refs": [],
                            "excluded_scope": [],
                            "known_constraints": ["任务生命周期必须由系统直接启动"],
                        },
                        "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "可运行页面"}],
                        "completion_criteria": ["任务生命周期必须由系统直接启动"],
                        "capability_intent": {
                            "needed_capability_groups": ["file_work", "artifact_generation"],
                            "preferred_tool_namespaces": [],
                            "requires_deferred_tool_loading": True,
                            "reason": "显式合同要求交付可运行页面并保留执行证据。",
                        },
                        "skill_intent": {
                            "selected_skill_ids": [],
                            "candidate_skill_ids": [],
                            "required_capability_tags": [],
                            "reason": "",
                        },
                        "observation_contract": {
                            "evidence_policy": "observation_required",
                            "progress_granularity": "step",
                            "finalization_requires_evidence": True,
                        },
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    lifecycle = [
        event
        for event in events
        if event.get("type") == "task_run_lifecycle_started"
    ][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    contract = dict(runtime.single_agent_runtime_host.runtime_objects.get_object(str(getattr(stored_task, "task_contract_ref", "") or "")) or {})

    assert branch.get("branch_kind") == "explicit_contract_task"
    assert branch.get("invocation_kind") == "task_execution_start"
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "model_action_admission" not in stream_types
    assert "harness_run_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert contract["contract_source"] == "explicit_contract"
    assert contract["source_contract_ref"] == "contract:explicit:test"
    assert contract["task_environment_id"] == "env.coding.vibe_workspace"
    assert contract["runtime_profile"]["execution_permit"]["allowed_operations"] == ["op.model_response", "op.read_file"]
    runtime_contract = dict(dict(getattr(stored_task, "diagnostics", {}) or {}).get("runtime_contract") or {})
    assert runtime_contract["allowed_operations"] == ["op.model_response", "op.read_file"]
    assert dict(runtime_contract["runtime_profile"])["execution_permit"]["allowed_operations"] == ["op.model_response", "op.read_file"]
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "explicit_contract"
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_authority") == "harness.explicit_contract_task"

def test_plain_task_contract_selection_does_not_bypass_agent_turn() -> None:
    runtime = build_harness_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            content="我会先判断是否需要启动任务。",
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="我会先判断是否需要启动任务。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-plain-contract-selection",
                message="这个只是普通会话输入，不能直接启动任务。",
                runtime_contract={
                    "task_environment_id": "env.coding.vibe_workspace",
                    "task_contract": {
                        "contract_id": "contract:plain:test",
                        "user_visible_goal": "普通输入里的合同片段。",
                        "task_run_goal": "不应由路由直接启动。",
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})

    assert branch.get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "task_run_lifecycle_started" not in stream_types

def test_agent_action_request_launches_task_run_and_initializes_todo() -> None:
    model_selection = {
        "provider": "test-provider",
        "model": "turn-bound-test-model",
        "timeout_seconds": 7,
    }
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            content="",
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed=_canonical_task_contract_seed({
                    "user_visible_goal": "交付一个真实可验证产物。",
                    "task_run_goal": "交付一个真实可验证产物。",
                    "required_artifacts": [{"artifact_kind": "test_artifact", "user_visible_name": "测试交付物"}],
                    "required_verifications": [{"verification_kind": "test_verification"}],
                    "completion_criteria": ["交付物和验证证据都已记录"],
                }),
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-taskrun",
                message="请交付产物。",
                model_selection=model_selection,
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    started = [
        event
        for event in events
        if event.get("type") == "harness_run_started"
        and str(dict(event.get("task_run") or {}).get("task_run_id") or "").startswith("taskrun:")
    ][0]
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    trace = runtime.single_agent_runtime_host.get_trace(task_run_id, include_payloads=True)
    event_types = [
        str(dict(item).get("event_type") or "")
        for item in list(dict(trace or {}).get("events") or [])
    ]
    stream_types = [str(event.get("type") or "") for event in events]
    branch_events = [dict(event.get("runtime_branch") or {}) for event in events if event.get("type") == "runtime_branch_decided"]

    assert "runtime_assembly_compiled" in stream_types
    assert branch_events and branch_events[0].get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "model_action_request" not in stream_types
    admissions = _admission_payloads(events)
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert "task_run_lifecycle_started" in stream_types
    assert "task_run_lifecycle_event" in stream_types
    assert not any(event.get("type") == "assistant_text" and event.get("answer_channel") == "task_control" for event in events)
    assert "agent_todo_initialized" in event_types
    assert "task_run_executor_scheduled" in event_types
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    assert dict(task_run.diagnostics or {}).get("origin_kind") == "single_agent_turn_json_action"
    assert dict(dict(task_run.diagnostics or {}).get("origin") or {}).get("origin_authority") == "harness.loop.single_agent_turn"
    assert dict(task_run.diagnostics or {}).get("model_selection") == model_selection
    assert dict(dict(task_run.diagnostics or {}).get("model_selection_binding") or {}).get("scope") == "task_run"
    contract = runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref)
    assert dict(contract or {}).get("origin", {}).get("origin_kind") == "single_agent_turn_json_action"

def test_invalid_single_agent_task_request_reports_error_without_task_run() -> None:
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            tool_calls=[
                {
                    "id": "invalid-request-task-run",
                    "name": "request_task_run",
                    "args": {},
                }
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(HarnessRuntimeRequest(session_id="session-invalid", message="请执行。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    done = next(event for event in events if event.get("type") == "done")

    assert not any(event.get("type") == "task_run_lifecycle_started" for event in events)
    assert any(dict(signal or {}).get("signal_kind") == "model_protocol_violation" for signal in control_signals)
    assert str(done.get("content") or "").strip()
    assert any(event.get("type") == "single_agent_turn_started" for event in events)

def test_task_lifecycle_start_does_not_rewrite_request_to_current_session_handoff() -> None:
    session_id = "session-lifecycle-no-current-handoff"
    existing_task_run_id = "taskrun:lifecycle-no-current-handoff:old"
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    _seed_active_work(
        runtime,
        task_run_id=existing_task_run_id,
        session_id=session_id,
        status="waiting_executor",
    )
    spawned: list[str] = []

    def _capture_background_task(coro, *, name: str = ""):
        spawned.append(name)
        coro.close()
        return SimpleNamespace()

    host.spawn_background_task = _capture_background_task
    committed: list[dict[str, object]] = []

    async def _commit(_session_id: str, message: dict[str, object]) -> None:
        committed.append(dict(message))

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        action_request = ModelActionRequest(
            request_id="model-action:lifecycle-no-current-handoff",
            turn_id="turn:lifecycle-no-current-handoff",
            action_type="request_task_run",
            public_progress_note="我会开始处理新的持续任务。",
            task_contract_seed=_canonical_task_contract_seed({
                "user_visible_goal": "启动一个新的持续任务。",
                "task_run_goal": "验证 lifecycle 层不把模型请求改写成 current-session handoff。",
                "completion_criteria": ["必须创建新的 TaskRun"],
            }),
        )
        async for event in start_task_lifecycle_from_action_request(
            runtime_host=host,
            session_id=session_id,
            turn_id="turn:lifecycle-no-current-handoff",
            runtime_contract={"task_id": "task:lifecycle-no-current-handoff"},
            model_selection={},
            action_request=action_request,
            agent_runtime_profile=SimpleNamespace(agent_profile_id="main_interactive_agent"),
            runtime_assembly=SimpleNamespace(
                to_dict=lambda: {
                    "profile": {"task_lifecycle_policy": {"request_task_run": True}},
                    "permission_mode": "default",
                    "task_environment": {},
                }
            ),
            runtime_branch={"branch_kind": "single_agent_turn"},
            answer_source="test.lifecycle",
            scheduler="test_lifecycle",
            max_steps=1,
            commit_assistant_message=_commit,
            initialize_task_todo=lambda **_kwargs: None,
            schedule_task_run_executor=runtime.schedule_task_run_executor,
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    session_task_runs = host.state_index.list_session_task_runs(session_id)
    new_tasks = [task for task in session_task_runs if task.task_run_id != existing_task_run_id]
    old_task = host.state_index.get_task_run(existing_task_run_id)

    assert "task_run_lifecycle_reused_current" not in stream_types
    assert not any(str(event.get("terminal_reason") or "") == "session_active_task_exists" for event in events)
    assert "task_run_lifecycle_started" in stream_types
    assert len(new_tasks) == 1
    assert new_tasks[0].status == "running"
    assert old_task is not None
    assert old_task.status == "waiting_executor"
    assert spawned
    assert committed == []

def test_task_contract_preserves_runtime_fields_without_goal_aliases() -> None:
    from harness.loop.model_action_protocol import ModelActionRequest
    from harness.loop.task_lifecycle import contract_from_action_request

    invalid, errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:contract-fields:invalid",
            turn_id="turn-contract-fields",
            action_type="request_task_run",
            task_contract_seed={
                "goal": "旧字段不能替代正式合同字段",
                "completion_criteria": ["需要真实验收"],
            },
        ),
        packet_ref="rtpacket:contract-fields",
    )

    assert invalid is None
    assert "task_goal_required" in errors
    assert "task_run_goal_required" in errors

    contract, contract_errors = contract_from_action_request(
        ModelActionRequest(
            request_id="model-action:contract-fields:valid",
            turn_id="turn-contract-fields",
            action_type="request_task_run",
                task_contract_seed=_canonical_task_contract_seed({
                    "user_visible_goal": "交付可运行示例",
                    "task_run_goal": "创建并验证可运行示例",
                    "completion_criteria": ["示例可以被验证"],
                    "task_environment_id": "env.coding.vibe_workspace",
                    "runtime_profile": {"runtime_policy": {"planning_policy": {"plan_mode": "available"}}},
                    "source_contract_ref": "contract.demo",
                    "external_plan_ref": "plan.demo",
                    "prompt_contract": {"role_prompt": "你是执行者。"},
                }),
            ),
        packet_ref="rtpacket:contract-fields",
        task_environment_id="env.office.file_search",
    )

    assert contract_errors == []
    assert contract is not None
    assert contract.user_visible_goal == "交付可运行示例"
    assert contract.task_run_goal == "创建并验证可运行示例"
    assert contract.task_environment_id == "env.office.file_search"
    assert contract.runtime_profile["runtime_policy"]["planning_policy"]["plan_mode"] == "available"
    assert contract.source_contract_ref == "contract.demo"
    assert contract.external_plan_ref == "plan.demo"

def test_agent_requested_task_run_inherits_selected_runtime_environment() -> None:
    runtime = build_harness_runtime(
        model_runtime=NativeToolCallModelRuntimeStub(
            content="",
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed=_canonical_task_contract_seed({
                    "user_visible_goal": "交付开发环境产物。",
                    "task_run_goal": "在用户选择的开发环境中交付产物。",
                    "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "可运行页面"}],
                    "completion_criteria": ["产物位于所选任务环境的 artifact 区域"],
                    "task_environment_id": "env.general.workspace",
                }),
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-selected-env-taskrun",
                message="开发一个可运行页面。",
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = [
        event
        for event in events
        if event.get("type") == "harness_run_started"
        and str(dict(event.get("task_run") or {}).get("task_run_id") or "").startswith("taskrun:")
    ][0]
    task_run_id = str(dict(started.get("task_run") or {}).get("task_run_id") or "")
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    assert task_run is not None
    contract = dict(runtime.single_agent_runtime_host.runtime_objects.get_object(task_run.task_contract_ref) or {})
    runtime_contract = dict(dict(task_run.diagnostics or {}).get("runtime_contract") or {})

    assert contract["task_environment_id"] == "env.coding.vibe_workspace"
    assert runtime_contract["task_environment_id"] == "env.coding.vibe_workspace"

def test_task_run_permission_without_tools_uses_single_agent_turn_for_direct_answer() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [_action_request(action_type="respond", final_answer="可以直接回答。")]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-native-direct",
                message="这个问题可以直接回答。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})

    assert branch.get("branch_kind") == "single_agent_turn"
    assert "single_agent_turn_started" in stream_types
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" not in stream_types
    assert any(event.get("type") == "done" and str(event.get("content") or "") == "可以直接回答。" for event in events)

def test_single_agent_turn_native_request_task_run_repairs_to_json_before_lifecycle() -> None:
    task_seed = _canonical_task_contract_seed(
        {
            "user_visible_goal": "交付一个真实页面。",
            "task_run_goal": "创建并验证一个真实 HTML 页面。",
            "working_scope": {
                "target_objects": ["真实 HTML 页面"],
                "workspace_refs": [],
                "source_refs": [],
                "excluded_scope": [],
                "known_constraints": ["页面文件必须真实存在"],
            },
            "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "页面"}],
            "required_verifications": [{"verification_kind": "file_exists"}],
            "completion_criteria": ["页面文件真实存在"],
        },
        capability_groups=["file_work", "artifact_generation"],
    )
    model = _UnexpectedNativeToolCallModelRuntime(
        tool_calls=[
            {
                "id": "call-request-task-run",
                "name": "request_task_run",
                "args": {
                    "user_visible_goal": "交付一个真实页面。",
                    "task_run_goal": "创建并验证一个真实 HTML 页面。",
                    "public_progress_note": "我先把页面目标转成可执行任务，然后推进实现和文件验证。",
                },
            }
        ],
        recovery_action=_action_request(
            action_type="request_task_run",
            public_progress_note="我先把页面目标转成可执行任务，然后推进实现和文件验证。",
            task_contract_seed=task_seed,
        ),
    )
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-native-taskrun",
                message="帮我做一个页面。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {"may_request_task_run": True, "may_use_subagents": False},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    branch = dict(next(event for event in events if event.get("type") == "runtime_branch_decided").get("runtime_branch") or {})
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert branch.get("branch_kind") == "single_agent_turn"
    admissions = _admission_payloads(events)
    control_signals = [
        dict(dict(event.get("event") or {}).get("payload") or {}).get("runtime_control_signal")
        for event in events
        if event.get("type") == "turn_runtime_control_signal_observed"
    ]
    assert admissions
    assert dict(admissions[0].get("admission") or {}).get("decision") == "allow"
    admitted_action = dict(admissions[0].get("model_action_request") or {})
    assert admitted_action.get("action_type") == "request_task_run"
    assert any(
        dict(signal or {}).get("signal_kind") == "model_protocol_violation"
        and dict(dict(signal or {}).get("protocol_error") or {}).get("code") == "single_agent_turn_invalid_native_action"
        for signal in control_signals
    )
    assert "runtime_invocation_packet" not in stream_types
    assert "model_action_request" not in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_json_action"

def test_single_agent_turn_json_request_task_run_starts_real_task_lifecycle() -> None:
    runtime = build_harness_runtime(
        model_runtime=_TurnActionSequenceModelRuntime(
            [
                _action_request(
                    action_type="request_task_run",
                    public_progress_note="我先把 JSON 页面目标转成持续任务，然后推进实现和验证。",
                    task_contract_seed=_canonical_task_contract_seed({
                        "user_visible_goal": "交付一个 JSON 协议页面。",
                        "task_run_goal": "通过 JSON action 创建页面任务。",
                        "required_artifacts": [{"artifact_kind": "html_app", "user_visible_name": "页面"}],
                        "required_verifications": [{"verification_kind": "file_exists"}],
                        "completion_criteria": ["页面文件真实存在"],
                    }, capability_groups=["file_work", "artifact_generation"]),
                )
            ]
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-json-taskrun",
                message="帮我做一个页面。",
                runtime_contract={
                    "allowed_operations": ["op.model_response"],
                    "control_capabilities": {
                        "may_request_task_run": True,
                        "requires_json_action_protocol": True,
                        "may_use_subagents": False,
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    stream_types = [str(event.get("type") or "") for event in events]
    lifecycle = [event for event in events if event.get("type") == "task_run_lifecycle_started"][0]
    task_run_event = dict(lifecycle.get("event") or {})
    payload = dict(task_run_event.get("payload") or {})
    task_run = dict(payload.get("task_run") or {})
    task_run_id = str(task_run.get("task_run_id") or "")
    stored_task = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)
    admissions = _admission_payloads(events)

    assert "task_run_lifecycle_started" in stream_types
    assert admissions
    assert dict(admissions[0].get("model_action_request") or {}).get("action_type") == "request_task_run"
    assert task_run_id.startswith("taskrun:")
    assert stored_task is not None
    assert dict(getattr(stored_task, "diagnostics", {}) or {}).get("origin_kind") == "single_agent_turn_json_action"

def test_default_runtime_policy_uses_main_profile_for_standard_chat() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-standard-chat",
                message="普通对话。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})

    assert dict(assembly.get("profile") or {}).get("profile_ref") == "main_interactive_agent"

def test_default_runtime_policy_exposes_plan_policy() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-default-policy",
                message="执行需要真实产物的任务。",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is True
    prompt_policy = dict(profile.get("prompt_policy") or {})
    assert prompt_policy.get("template_id") == "prompt_template.general.agent_runtime"
    assert prompt_policy.get("template_selection_source") == "agent_runtime_profile.metadata.prompt_template_id"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.general.workspace"

def test_prompt_template_is_not_injected_without_explicit_selection() -> None:
    profile = build_runtime_assembly_profile(agent_runtime_profile=None, runtime_contract={})

    assert profile.prompt_policy == {}

    explicit = build_runtime_assembly_profile(
        agent_runtime_profile=None,
        runtime_contract={"prompt_template_id": "prompt_template.general.agent_runtime"},
    )

    assert explicit.prompt_policy["template_id"] == "prompt_template.general.agent_runtime"
    assert explicit.prompt_policy["template_selection_source"] == "runtime_contract.prompt_template_id"

def test_runtime_policy_can_override_default_runtime_assembly() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-specific-mode-policy",
                message="按特定任务配置运行。",
                runtime_contract={
                    "task_environment_id": "env.office.file_search",
                    "runtime_policy": {
                        "planning_policy": {"plan_mode": "disabled", "specified_plan_allowed": False},
                        "task_lifecycle_policy": {"request_task_run": True, "requires_completion_evidence": True},
                        "self_review_policy": {"enabled": True, "checkpoints": ["before_final"]},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is False
    assert dict(profile.get("self_review_policy") or {}).get("checkpoints") == ["before_final"]
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.office.file_search"

def test_runtime_profile_uses_explicit_runtime_policy_and_environment() -> None:
    runtime = build_harness_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-custom-mode-policy",
                message="按显式运行策略执行。",
                runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
                runtime_profile={
                    "runtime_policy": {
                        "interaction_policy": {"style": "custom_review"},
                        "planning_policy": {"plan_mode": "disabled"},
                        "task_lifecycle_policy": {"request_task_run": False},
                        "tool_exposure_policy": {
                            "read_only_tools_only": True,
                            "operation_ceiling": ["op.model_response", "op.read_file"],
                        },
                        "self_review_policy": {"enabled": True, "before_final": "strict_review"},
                    },
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["profile_ref"] == "main_interactive_agent"
    assert dict(profile.get("interaction_policy") or {}).get("style") == "custom_review"
    assert dict(profile.get("task_lifecycle_policy") or {}).get("request_task_run") is False
    assert dict(profile.get("self_review_policy") or {}).get("before_final") == "strict_review"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.coding.vibe_workspace"

def test_turn_packet_does_not_expose_obsolete_task_goal_type_from_selection() -> None:
    class CaptureModelRuntime:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.messages = list(messages)
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="ok")))

    model = CaptureModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)

    async def _collect() -> None:
        async for _event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session-no-legacy-goal-type",
                message="做一个小游戏。",
                runtime_contract={"task_goal_type": "code_fix_execution", "selected_task_id": "legacy"},
            )
        ):
            pass

    asyncio.run(_collect())
    packet_payload = json.dumps(model.messages, ensure_ascii=False)

    assert "task_selection" not in packet_payload
    assert "code_fix_execution" not in packet_payload

def test_main_session_model_action_writes_prompt_accounting_ledger() -> None:
    class AccountingModelRuntime(SingleMessageModelRuntimeStub):
        def __init__(self) -> None:
            super().__init__(
                agent_turn_action_request=_action_request(
                    action_type="respond",
                    final_answer="ok",
                )
            )
            self.ledger = None
            self.serializer = CanonicalPromptSerializer()
            self.cache_planner = PromptCachePlanner()

        def attach_prompt_accounting_ledger(self, ledger):
            self.ledger = ledger

        async def invoke_messages(self, messages, **kwargs):
            response = await super().invoke_messages(messages, **kwargs)
            context = dict(kwargs.get("accounting_context") or {})
            if self.ledger is not None and context:
                request_id = str(context.get("request_id") or "modelreq:test")
                run_id = str(context.get("run_id") or context.get("task_run_id") or "")
                task_run_id = str(context.get("task_run_id") or "")
                segment_map = self.serializer.build_segment_map(
                    request_id=request_id,
                    messages=list(messages),
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=str(context.get("session_id") or ""),
                    provider="stub",
                    model="stub-model",
                )
                self.ledger.record_segment_map(segment_map)
                self.ledger.record_token_usage(
                    ModelTokenUsageRecord(
                        usage_id=f"tokuse:{request_id}:local_prediction",
                        request_id=request_id,
                        run_id=run_id,
                        task_run_id=task_run_id,
                        session_id=str(context.get("session_id") or ""),
                        provider="stub",
                        model="stub-model",
                        source="local_prediction",
                        prompt_tokens=segment_map.predicted_prompt_tokens,
                        total_tokens=segment_map.predicted_prompt_tokens,
                        created_at=1.0,
                    )
                )
                provider_response = SimpleNamespace(
                    content=response.content,
                    usage_metadata={"input_tokens": 12, "output_tokens": 3},
                )
                provider_usage = extract_provider_usage(
                    provider_response,
                    request_id=request_id,
                    run_id=run_id,
                    task_run_id=task_run_id,
                    session_id=str(context.get("session_id") or ""),
                    provider="stub",
                    model="stub-model",
                    created_at=2.0,
                )
                self.ledger.record_token_usage(provider_usage)
                self.ledger.record_prompt_cache(
                    self.cache_planner.with_provider_usage(self.cache_planner.plan(segment_map), provider_usage)
                )
            return response

    runtime = build_harness_runtime(model_runtime=AccountingModelRuntime())

    async def _collect() -> None:
        async for _event in runtime.astream(HarnessRuntimeRequest(session_id="session-accounting", message="hello")):
            pass

    asyncio.run(_collect())
    turn_run_id = runtime.single_agent_runtime_host.list_session_traces("session-accounting")["turn_runs"][0]["turn_run_id"]
    summary = runtime.single_agent_runtime_host.prompt_accounting_ledger.summarize_run(turn_run_id)

    assert summary["exact_total_tokens"] == 15
    assert summary["provider_usage_record_count"] == 1
    assert summary["local_prediction_record_count"] == 1
