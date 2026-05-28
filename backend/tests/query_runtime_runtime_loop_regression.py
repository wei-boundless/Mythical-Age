from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.models import QueryRequest
from runtime.shared.models import AgentRunResult, TaskRun
from tests.support.runtime_stubs import (
    SingleMessageModelRuntimeStub,
    build_query_runtime,
)


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    task_contract_seed: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"model-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "final_answer": final_answer,
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {"test_action_request": True},
    }


def test_direct_agent_response_does_not_start_task_run() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="respond",
                final_answer="直接回答，不进入任务生命周期。",
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-direct", message="介绍一下 harness。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" for event in events)
    assert any(event.get("type") == "runtime_assembly_compiled" for event in events)
    assert any(event.get("type") == "harness_run_started" for event in events)
    assert runtime.single_agent_runtime_host.list_session_traces("session-direct")["task_run_count"] == 1


def test_agent_action_request_launches_task_run_and_initializes_todo() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "goal": "交付一个真实可验证产物。",
                    "required_artifacts": [{"artifact_kind": "test_artifact", "user_visible_name": "测试交付物"}],
                    "required_verifications": [{"verification_kind": "test_verification"}],
                    "completion_criteria": ["交付物和验证证据都已记录"],
                },
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-taskrun", message="请交付产物。")):
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

    assert "runtime_assembly_compiled" in stream_types
    assert "model_action_request" in stream_types
    assert "task_run_lifecycle_started" in stream_types
    assert "task_run_lifecycle_event" in stream_types
    assert "agent_todo_initialized" in event_types
    assert any("任务执行器已接管" in str(event.get("content") or "") for event in events if event.get("type") == "done")


def test_global_live_monitor_groups_running_completed_and_failed_runs(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="turnrun:old-running",
        session_id="session-monitor",
        task_id="turn:old",
        status="running",
        created_at=100.0,
        updated_at=200.0,
        runtime_lane="single_agent_turn",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="turnrun:failed",
        session_id="session-monitor",
        task_id="turn:failed",
        status="failed",
        created_at=800.0,
        updated_at=900.0,
        runtime_lane="single_agent_turn",
        terminal_reason="internal_error",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:old-waiting-executor",
        session_id="session-monitor",
        task_id="task:old-waiting-executor",
        status="waiting_executor",
        created_at=300.0,
        updated_at=400.0,
        runtime_lane="single_agent_task",
        terminal_reason="task_executor_rebuild_pending",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:fresh-waiting-executor",
        session_id="session-monitor",
        task_id="task:fresh-waiting-executor",
        status="waiting_executor",
        created_at=940.0,
        updated_at=980.0,
        runtime_lane="single_agent_task",
        terminal_reason="waiting_executor",
    ))
    host.state_index.upsert_task_run(TaskRun(
        task_run_id="taskrun:waiting-approval",
        session_id="session-monitor",
        task_id="task:waiting-approval",
        status="waiting_approval",
        created_at=300.0,
        updated_at=400.0,
        runtime_lane="single_agent_task",
        terminal_reason="waiting_approval",
    ))

    monitor = host.list_global_live_monitor(limit=20)

    assert {item["task_run_id"] for item in monitor["task_runs"]} == {
        "taskrun:fresh-waiting-executor",
        "taskrun:old-waiting-executor",
        "taskrun:waiting-approval",
        "turnrun:old-running",
        "turnrun:failed",
    }
    buckets = {item["task_run_id"]: item["bucket"] for item in monitor["task_runs"]}
    assert {item["task_run_id"] for item in monitor["buckets"]["running"]} == {
        "taskrun:fresh-waiting-executor",
        "taskrun:waiting-approval",
    }
    assert {item["task_run_id"] for item in monitor["buckets"]["diagnostics"]} == {
        "taskrun:old-waiting-executor",
        "turnrun:old-running",
    }
    assert [item["task_run_id"] for item in monitor["buckets"]["failed"]] == ["turnrun:failed"]
    assert buckets["taskrun:fresh-waiting-executor"] == "running"
    assert buckets["turnrun:failed"] == "failed"
    assert buckets["taskrun:waiting-approval"] == "running"
    assert buckets["taskrun:old-waiting-executor"] == "diagnostics"
    assert buckets["turnrun:old-running"] == "diagnostics"
    assert monitor["summary"]["total"] == 5
    assert monitor["summary"]["running"] == 2
    assert monitor["summary"]["failed"] == 1
    assert monitor["summary"]["diagnostics"] == 2
    assert monitor["summary"]["action_required"] == 1


def test_global_live_monitor_exposes_step_summary_and_recent_terminal_status(monkeypatch) -> None:
    monkeypatch.setattr("harness.runtime.single_agent_host.time.time", lambda: 1000.0)
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:recent-completed",
        session_id="session-monitor",
        task_id="task:recent-completed",
        status="completed",
        created_at=600.0,
        updated_at=990.0,
        runtime_lane="single_agent_task",
        terminal_reason="completed",
        diagnostics={"artifact_refs": [{"path": "storage/task/result.md"}]},
    )
    host.state_index.upsert_task_run(task_run)
    host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "task_run_id": task_run.task_run_id,
            "step": "final_self_review",
            "status": "completed",
            "summary": "agent 已完成最终自检并确认交付物存在。",
        },
    )

    monitor = host.list_global_live_monitor(limit=20)
    item = monitor["task_runs"][0]

    assert item["task_run_id"] == task_run.task_run_id
    assert item["bucket"] == "completed"
    assert item["latest_step_name"] == "final_self_review"
    assert item["latest_step_status"] == "completed"
    assert item["latest_step_summary"] == "agent 已完成最终自检并确认交付物存在。"
    assert item["artifact_count"] == 1
    assert item["resource_class"] == "static"
    assert item["ended_at"] == 990.0
    assert item["duration_seconds"] == 390.0
    assert monitor["summary"]["completed"] == 1


def test_invalid_agent_action_request_reports_error_without_task_run() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request={
                "authority": "harness.loop.model_action_request",
                "request_id": "model-action:test:invalid",
                "turn_id": "",
                "action_type": "request_task_run",
                "task_contract_seed": {},
            }
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-invalid", message="请执行。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert any(event.get("type") == "harness_run_started" for event in events)


class _MalformedModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(content=json.dumps({"authority": "bad"}))


class _FailingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        raise TimeoutError("model timed out")


class _TaskExecutorSequenceModelRuntime:
    def __init__(self, task_actions: list[dict[str, object]], *, agent_turn_action_request: dict[str, object]) -> None:
        self.task_actions = list(task_actions)
        self.agent_turn_action_request = dict(agent_turn_action_request)
        self.task_invocation_count = 0

    async def invoke_messages(self, messages, **_kwargs):
        content = str(list(messages or [])[0].get("content") or "")
        if "正式 TaskRun 的执行 agent" in content:
            self.task_invocation_count += 1
            action = self.task_actions.pop(0) if self.task_actions else self.task_actions[-1]
            return SimpleNamespace(content=json.dumps(action, ensure_ascii=False))
        return SimpleNamespace(content=json.dumps(self.agent_turn_action_request, ensure_ascii=False))


def test_malformed_agent_action_request_fails_closed() -> None:
    runtime = build_query_runtime(model_runtime=_MalformedModelRuntime())

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(QueryRequest(session_id="session-malformed", message="继续。")):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "error" for event in events)
    assert any(event.get("type") == "harness_run_started" for event in events)


def test_task_run_executor_keeps_model_call_failure_recoverable() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "goal": "需要长任务续跑。",
                    "completion_criteria": ["完成真实交付"],
                },
            )
        )
    )

    async def _create_task() -> str:
        task_run_id = ""
        async for event in runtime.astream(QueryRequest(session_id="session-recoverable-model-failure", message="做一个长任务。")):
            if event.get("type") == "harness_run_started":
                task_run = dict(event.get("task_run") or {})
                candidate = str(task_run.get("task_run_id") or "")
                if candidate.startswith("taskrun:"):
                    task_run_id = candidate
        return task_run_id

    task_run_id = asyncio.run(_create_task())
    runtime.model_runtime = _FailingModelRuntime()

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
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:test:invalid-task-step",
                    "turn_id": "",
                    "action_type": "",
                },
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:test:complete-after-repair",
                    "turn_id": "",
                    "action_type": "respond",
                    "final_answer": "已按合同完成。",
                    "diagnostics": {"artifacts": []},
                },
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"goal": "协议错误后继续执行。", "completion_criteria": ["允许无文件收口"]},
            ),
        )
    )

    async def _create_task() -> str:
        task_run_id = ""
        async for event in runtime.astream(QueryRequest(session_id="session-protocol-repair", message="做一个可恢复任务。")):
            if event.get("type") == "harness_run_started":
                candidate = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
                if candidate.startswith("taskrun:"):
                    task_run_id = candidate
        return task_run_id

    task_run_id = asyncio.run(_create_task())
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
    runtime = build_query_runtime(
        model_runtime=_TaskExecutorSequenceModelRuntime(
            task_actions=[
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-1", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-2", "turn_id": "", "action_type": ""},
                {"authority": "harness.loop.model_action_request", "request_id": "model-action:test:bad-3", "turn_id": "", "action_type": ""},
            ],
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={"goal": "连续协议错误后阻塞。", "completion_criteria": ["不应完成"]},
            ),
        )
    )

    async def _create_task() -> str:
        task_run_id = ""
        async for event in runtime.astream(QueryRequest(session_id="session-protocol-block", message="做一个会协议错误的任务。")):
            if event.get("type") == "harness_run_started":
                candidate = str(dict(event.get("task_run") or {}).get("task_run_id") or "")
                if candidate.startswith("taskrun:"):
                    task_run_id = candidate
        return task_run_id

    task_run_id = asyncio.run(_create_task())
    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=4))
    task_run = runtime.single_agent_runtime_host.state_index.get_task_run(task_run_id)

    assert result["ok"] is False
    assert result["error"] == "model_action_protocol_repair_required"
    assert task_run is not None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "model_action_protocol_repair_required"
    assert dict(dict(task_run.diagnostics or {}).get("recoverable_error") or {}).get("retryable") is True


def test_role_mode_allows_soul_prompt_but_blocks_task_lifecycle() -> None:
    runtime = build_query_runtime(
        model_runtime=SingleMessageModelRuntimeStub(
            agent_turn_action_request=_action_request(
                action_type="request_task_run",
                task_contract_seed={
                    "goal": "角色模式不应开启任务。",
                    "completion_criteria": ["不应执行"],
                },
            )
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-role",
                message="保持角色对话。",
                runtime_mode="role",
                soul_id="hebo",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})
    admission = dict(next(event for event in events if event.get("type") == "model_action_admission").get("event") or {})
    admission_payload = dict(admission.get("payload") or {}).get("admission") or {}

    assert profile["mode"] == "role"
    assert dict(assembly.get("soul_role_prompt") or {}).get("content")
    assert dict(admission_payload).get("decision") == "deny"
    assert dict(admission_payload).get("system_reason") == "task_lifecycle_disabled_by_runtime_profile"
    assert not any(
        event.get("type") == "task_run_lifecycle_started"
        for event in events
    )


def test_standard_mode_rejects_soul_prompt_without_persona_leakage() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-standard-soul",
                message="普通对话。",
                runtime_mode="standard",
                soul_id="hebo",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})

    assert dict(assembly.get("profile") or {}).get("mode") == "standard"
    assert dict(assembly.get("soul_role_prompt") or {}) == {}
    assert {"capability": "soul_role_prompt", "reason": "soul_prompt_only_allowed_in_role_mode"} in list(
        assembly.get("rejected_capabilities") or []
    )


def test_professional_mode_exposes_plan_policy_without_soul_prompt() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-professional",
                message="专业模式执行。",
                runtime_mode="professional",
                soul_id="hebo",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assembly = dict(next(event for event in events if event.get("type") == "runtime_assembly_compiled").get("runtime_assembly") or {})
    profile = dict(assembly.get("profile") or {})

    assert profile["mode"] == "professional"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is True
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.development.sandbox"
    assert dict(profile.get("soul_prompt_policy") or {}).get("enabled") is False
    assert dict(assembly.get("soul_role_prompt") or {}) == {}


def test_specific_task_runtime_policy_can_override_builtin_mode_preset() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-specific-mode-policy",
                message="按特定任务配置运行。",
                runtime_mode="professional",
                task_selection={
                    "specific_task_runtime_policy": {
                        "default_environment_id": "env.creation.writing",
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

    assert profile["mode"] == "professional"
    assert dict(profile.get("planning_policy") or {}).get("specified_plan_allowed") is False
    assert dict(profile.get("self_review_policy") or {}).get("checkpoints") == ["before_final"]
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.creation.writing"


def test_custom_mode_uses_explicit_runtime_policy_and_environment() -> None:
    runtime = build_query_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-custom-mode-policy",
                message="自定义模式运行。",
                runtime_mode="custom",
                runtime_profile={
                    "runtime_mode_policy": {
                        "interaction_mode": "custom_review_mode",
                        "runtime_lane": "custom_review_lane",
                        "default_environment_id": "env.development.readonly",
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

    assert profile["mode"] == "custom"
    assert profile["interaction_mode"] == "custom_review_mode"
    assert profile["runtime_lane"] == "custom_review_lane"
    assert dict(profile.get("task_lifecycle_policy") or {}).get("request_task_run") is False
    assert dict(profile.get("self_review_policy") or {}).get("before_final") == "strict_review"
    assert dict(assembly.get("task_environment") or {}).get("environment_id") == "env.development.readonly"


def test_turn_packet_does_not_expose_legacy_task_goal_type_from_selection() -> None:
    class CaptureModelRuntime:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def invoke_messages(self, messages, **_kwargs):
            self.messages = list(messages)
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer="ok")))

    model = CaptureModelRuntime()
    runtime = build_query_runtime(model_runtime=model)

    async def _collect() -> None:
        async for _event in runtime.astream(
            QueryRequest(
                session_id="session-no-legacy-goal-type",
                message="做一个小游戏。",
                task_selection={"task_goal_type": "code_fix_execution", "selected_task_id": "legacy"},
            )
        ):
            pass

    asyncio.run(_collect())
    packet_user_payload = json.loads(str(dict(model.messages[-1]).get("content") or "{}"))

    assert "task_selection" not in packet_user_payload
    assert "code_fix_execution" not in json.dumps(packet_user_payload, ensure_ascii=False)


def test_required_artifact_completion_requires_existing_file() -> None:
    from harness.loop.task_executor import _verify_completion

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    contract = {"required_artifacts": [{"artifact_kind": "html_game", "user_visible_name": "游戏"}]}
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }

    missing = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id="taskrun:test:missing",
        contract=contract,
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/artifacts/game.html"}],
    )

    real_path = project_root / "storage/task_environments/development/sandbox/artifacts/game.html"
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text("<!doctype html><title>game</title>", encoding="utf-8")
    present = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id="taskrun:test:present",
        contract=contract,
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/artifacts/game.html"}],
    )

    assert missing["ok"] is False
    assert missing["missing"] == ["required_artifacts"]
    assert present["ok"] is True
    assert present["verified_artifacts"][0]["exists"] is True


def test_sandbox_artifact_is_published_before_completion() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:publish"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_file = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/game.html"
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.write_text("<!doctype html><canvas></canvas>", encoding="utf-8")
    published_file = project_root / "storage/task_environments/development/sandbox/artifacts/game.html"

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game"}]},
        artifact_refs=[
            {
                "path": "storage/task_environments/development/sandbox/artifacts/game.html",
                "absolute_path": str(sandbox_file),
                "sandbox_path": "storage/task_environments/development/sandbox/artifacts/game.html",
            }
        ],
    )

    assert verdict["ok"] is True
    assert published_file.exists()
    assert verdict["verified_artifacts"][0]["path"] == "storage/task_environments/development/sandbox/artifacts/game.html"


def test_task_sandbox_workspace_root_is_project_root() -> None:
    from harness.loop.task_executor import _task_sandbox_policy

    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    policy = _task_sandbox_policy(
        {"task_environment": {"storage_space": {}, "sandbox_policy": {}}},
        runtime_host=runtime.single_agent_runtime_host,
        task_run_id="taskrun:test:workspace-root",
    )

    assert Path(str(policy["workspace_root"])).resolve() == project_root


def test_task_run_artifact_view_returns_only_existing_files() -> None:
    runtime = build_query_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    existing = project_root / "storage/task_environments/development/sandbox/artifacts/final.html"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("<!doctype html><title>final</title>", encoding="utf-8")
    runtime.single_agent_runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id="agresult:test-artifacts",
            agent_run_id="agrun:test-artifacts",
            task_run_id="taskrun:test-artifacts",
            agent_id="agent:0",
            status="completed",
            artifact_refs=(
                "storage/task_environments/development/sandbox/artifacts/final.html",
                "storage/task_environments/development/sandbox/artifacts/missing.html",
            ),
        )
    )

    view = runtime.single_agent_runtime_host.get_task_run_artifacts("taskrun:test-artifacts")

    assert view["created_files"] == ["storage/task_environments/development/sandbox/artifacts/final.html"]
    assert view["artifact_refs"][0]["exists"] is True


def test_task_observation_projection_separates_stale_and_active_failures() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-projection"
    stale_fingerprint = {
        "tool_registry_hash": "tools-v1",
        "tool_config_hash": "image-config-v1",
        "sandbox_policy_hash": "sandbox-v1",
        "permission_policy_hash": "permission-v1",
        "backend_config_hash": "backend-v1",
    }
    current_fingerprint = {
        **stale_fingerprint,
        "tool_config_hash": "image-config-v2",
        "backend_config_hash": "backend-v2",
    }
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:stale-image",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "hero"},
                    "error": "old config failure",
                    "runtime_fingerprint": stale_fingerprint,
                },
                "error": "old config failure",
            }
        },
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:active-read",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:read_file",
                "payload": {
                    "tool_name": "read_file",
                    "tool_args": {"path": "missing.md"},
                    "error": "file missing",
                    "runtime_fingerprint": current_fingerprint,
                },
                "error": "file missing",
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=current_fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["current_runtime_fact"] is False
    assert projection["active_failures"][0]["tool_name"] == "read_file"
    assert projection["active_failures"][0]["error"]["message"] == "file missing"


def test_task_observation_projection_treats_missing_fingerprint_failure_as_historical() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:missing-fingerprint"
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:legacy-error",
                "task_run_id": task_run_id,
                "observation_type": "executor_error",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "tool_args": {"prompt": "hero"},
                    "error": "legacy failure without runtime fingerprint",
                },
                "error": "legacy failure without runtime fingerprint",
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint={"tool_config_hash": "current"})
    projection = context["execution_state"]["system_projection"]

    assert projection["active_failures"] == []
    assert projection["historical_failures"][0]["tool_name"] == "image_generate"
    assert projection["historical_failures"][0]["reason"] == "missing_runtime_fingerprint"


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


def test_task_observation_projection_keeps_success_artifact_evidence() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:test:observation-artifact"
    fingerprint = {"tool_config_hash": "current"}
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "observation_id": "obs:image-ok",
                "task_run_id": task_run_id,
                "observation_type": "tool_result",
                "source": "tool:image_generate",
                "payload": {
                    "tool_name": "image_generate",
                    "runtime_fingerprint": fingerprint,
                    "result_envelope": {
                        "tool_name": "image_generate",
                        "tool_args": {"prompt": "hero"},
                        "status": "ok",
                        "text": "generated",
                        "artifact_refs": [{"path": "frontend/public/souls/generated/hero.png", "kind": "image"}],
                        "structured_payload": {
                            "artifact_refs": [{"path": "frontend/public/souls/generated/hero.png", "kind": "image"}]
                        },
                    },
                },
            }
        },
    )

    context = _observations_for_packet(host, task_run_id, current_fingerprint=fingerprint)
    projection = context["execution_state"]["system_projection"]

    assert projection["current_facts"][0]["tool_name"] == "image_generate"
    assert projection["artifact_evidence"][0]["path"] == "frontend/public/souls/generated/hero.png"
    assert context["artifact_refs"][0]["kind"] == "image"


def test_task_observation_projection_ignores_already_projected_records() -> None:
    from harness.loop.task_executor import _observations_for_packet

    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    context = _observations_for_packet(
        host,
        "taskrun:test:projected-record",
        current_fingerprint={"tool_config_hash": "current"},
        pending_observations=[
            {
                "observation_ref": "rtobs:already-projected",
                "tool_name": "read_file",
                "status": "ok",
                "runtime_freshness": {"visibility": "active"},
                "authority": "orchestration.tool_observation_record",
            }
        ],
    )

    assert context["raw_observations"] == []
    assert context["packet_observations"] == []
