from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from query.models import QueryRequest
from query.runtime import _task_selection_for_runtime
from capability_system.tool_runtime import ToolRuntime
from harness.runtime import AgentRunRequest
from runtime.agent_assembly import NodeWorkOrder, build_agent_invocation
from harness.loop.task_run_finalizer import FinishedTaskRunResult
from task_system import TaskFlowRegistry
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    StreamingMessageModelRuntimeStub,
    isolated_backend_root,
)


class _FailingDecisionModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        raise RuntimeError("simulated provider unavailable")


class _InspectionDecisionModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "agent_runtime.model_turn_decision",
                    "decision_id": "model-turn-decision:tool-followup",
                    "user_message": "请检查当前目录是否存在后回答。",
                    "interaction_intent": "inspect",
                    "action_intent": "read_context",
                    "work_mode": "read_only_analysis",
                    "task_goal_type": "inspection",
                    "domain_mismatch_signal": {},
                    "target_objects": ["."],
                    "desired_outcome": "检查当前目录是否存在，并根据工具观察回答。",
                    "deliverables": ["inspection_findings"],
                    "constraints": [],
                    "forbidden_actions": [],
                    "selected_skill_ids": [],
                    "resource_contract": {},
                    "context_binding_decision": {"mode": "use_runtime_tools"},
                    "planning_required": False,
                    "todo_required": False,
                    "completion_criteria": ["工具观察已回灌到最终回答"],
                    "needs_clarification": False,
                    "clarification_question": "",
                    "confidence": 0.95,
                    "ambiguity": [],
                    "diagnostics": {"test_decision": True},
                },
                ensure_ascii=False,
            )
        )


class _ToolThenCompletionExecutor:
    def __init__(self) -> None:
        self.model_runtime = _InspectionDecisionModelRuntime()
        self.turn_count = 0
        self.followup_observed = False

    async def stream(self, *, model_messages, directive, **_kwargs):
        self.turn_count += 1
        if self.turn_count == 1:
            yield {
                "type": "tool_call_requested",
                "tool_call": {
                    "id": "tool-call:path-exists",
                    "name": "path_exists",
                    "args": {"path": "."},
                    "type": "tool_call",
                },
                "tool_name": "path_exists",
                "operation_id": "op.path_exists",
                "directive_ref": directive.directive_id,
                "assistant_content": "",
            }
            return

        self.followup_observed = any(
            message.__class__.__name__ == "ToolMessage"
            for message in list(model_messages or [])
        )
        completion = {
            "completed": True,
            "source_turn": "tool_followup",
            "observed_tool_result": self.followup_observed,
            "authority": "test.followup_completion",
        }
        yield {
            "type": "done",
            "content": "工具观察后的最终回答",
            "answer_channel": "final_answer",
            "answer_source": "runtime_directive:model_response",
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
            "answer_fallback_reason": "",
            "completion": completion,
        }


class _ArtifactDeliveryDecisionModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "agent_runtime.model_turn_decision",
                    "decision_id": "model-turn-decision:artifact-e2e",
                    "user_message": "请交付真实文件并验证。",
                    "interaction_intent": "create",
                    "action_intent": "edit_workspace",
                    "work_mode": "implementation",
                    "task_goal_type": "artifact_delivery",
                    "domain_mismatch_signal": {},
                    "target_objects": ["output/e2e_completion_artifact.md"],
                    "desired_outcome": "写入指定 artifact，运行真实文件存在性验证，并基于证据收口。",
                    "deliverables": ["artifact_refs", "completion_status", "limitations"],
                    "constraints": [],
                    "forbidden_actions": [],
                    "selected_skill_ids": [],
                    "resource_contract": {
                        "required_write_files": ["output/e2e_completion_artifact.md"],
                    },
                    "context_binding_decision": {"mode": "use_runtime_tools"},
                    "planning_required": False,
                    "todo_required": False,
                    "completion_criteria": ["verify_command"],
                    "needs_clarification": False,
                    "clarification_question": "",
                    "confidence": 0.97,
                    "ambiguity": [],
                    "diagnostics": {"test_decision": True},
                },
                ensure_ascii=False,
            )
        )


class _WriteVerifyCompletionExecutor:
    def __init__(self) -> None:
        self.model_runtime = _ArtifactDeliveryDecisionModelRuntime()
        self.turn_count = 0

    async def stream(self, *, model_messages, directive, **_kwargs):
        self.turn_count += 1
        if self.turn_count == 1:
            yield {
                "type": "tool_call_requested",
                "tool_call": {
                    "id": "tool-call:e2e-write",
                    "name": "write_file",
                    "args": {
                        "path": "output/e2e_completion_artifact.md",
                        "content": "completion evidence e2e",
                    },
                    "type": "tool_call",
                },
                "tool_name": "write_file",
                "operation_id": "op.write_file",
                "directive_ref": directive.directive_id,
                "assistant_content": "",
            }
            return
        if self.turn_count == 2:
            yield {
                "type": "tool_call_requested",
                "tool_call": {
                    "id": "tool-call:e2e-verify",
                    "name": "terminal",
                    "args": {
                        "command": "test -f output/e2e_completion_artifact.md",
                        "verification_intent": {
                            "stage": "verify_output",
                            "obligation": "verify_command",
                            "target_path": "output/e2e_completion_artifact.md",
                            "authority": "test.harness_real_tool_e2e",
                        },
                    },
                    "type": "tool_call",
                },
                "tool_name": "terminal",
                "operation_id": "op.shell",
                "directive_ref": directive.directive_id,
                "assistant_content": "",
            }
            return
        assert any(message.__class__.__name__ == "ToolMessage" for message in list(model_messages or []))
        yield {
            "type": "done",
            "content": (
                "已交付 artifact output/e2e_completion_artifact.md；"
                "完成状态由系统 closeout 的结构化写入证据和验证 receipt 裁决；限制：仅覆盖文件存在性。"
            ),
            "answer_channel": "final_answer",
            "answer_source": "runtime_directive:model_response",
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
            "answer_fallback_reason": "",
            "completion": {"completed": True, "authority": "test.model_final_claim"},
        }


def _build_stream_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-loop-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )


def _build_game_generation_runtime() -> QueryRuntime:
    return _build_stream_runtime()


def _build_arcade_bundle_runtime(_tmp_path: Path) -> QueryRuntime:
    return _build_stream_runtime()


def _main_agent_mode_task_selection(
    *,
    interaction_mode: str,
    runtime_lane: str,
    recipe_id: str,
    professional: bool = False,
) -> dict[str, object]:
    mode_policy: dict[str, object] = {
        "interaction_mode": interaction_mode,
        "runtime_lane": runtime_lane,
        "recipe_id": recipe_id,
    }
    if professional:
        mode_policy["execution_strategy"] = "interaction_mode_run"
    return {
        "agent_id": "agent:0",
        "agent_profile_id": "main_interactive_agent",
        "interaction_mode": interaction_mode,
        "runtime_interaction_mode": interaction_mode,
        "runtime_lane": runtime_lane,
        "mode_policy": mode_policy,
    }


def test_astream_specific_light_web_game_task_can_write_new_file(tmp_path: Path) -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-light-game",
                message="请生成一个可运行的轻量网页小游戏。",
                history=[],
                task_selection={"selected_task_id": "task.dev.light_web_game"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "done" for event in events)
    assert any(
        dict(event.get("event") or {}).get("event_type") == "task_contract_built"
        for event in events
        if event.get("type") == "harness_loop_event"
    )


def test_agent_runtime_emits_stream_delta_once() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-stream-dedup-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=StreamingMessageModelRuntimeStub(chunks=["final answer：流式片段"]),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.agent_harness.run_stream(
            AgentRunRequest(
                session_id="session-stream-dedup",
                task_id="taskinst:session-stream-dedup:general",
                user_message="请流式回答。",
                history=[],
                source="regression",
                agent_runtime_chain=runtime.agent_runtime_chain,
                model_response_executor=runtime.model_response_executor,
                runtime_context_manager=runtime.runtime_context_manager,
                task_selection={
                    "turn_id": "turn:session-stream-dedup:1",
                    "stream_policy": {"enabled": True, "mode": "model_text_stream"},
                },
                tool_runtime_executor=runtime.tool_runtime_executor,
                tool_instances=runtime._all_tool_instances(),
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    deltas = [
        event
        for event in events
        if event.get("type") == "content_delta" and event.get("content") == "final answer：流式片段"
    ]

    assert len(deltas) == 1
    assert any(event.get("type") == "done" for event in events)


def test_agent_runtime_tool_followup_completion_becomes_task_result_completion() -> None:
    base_dir = isolated_backend_root("query-runtime-tool-followup-")
    tool_runtime = ToolRuntime(base_dir)
    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=tool_runtime,
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )
    model_response_executor = _ToolThenCompletionExecutor()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.agent_harness.run_stream(
            AgentRunRequest(
                session_id="session-tool-followup-completion",
                task_id="taskinst:session-tool-followup-completion:general",
                user_message="请检查当前目录是否存在后回答。",
                history=[],
                source="regression",
                agent_runtime_chain=runtime.agent_runtime_chain,
                model_response_executor=model_response_executor,
                runtime_context_manager=runtime.runtime_context_manager,
                task_selection={
                    "operation_policy": {
                        "allowed_operations": ["op.path_exists"],
                        "required_operations": ["op.path_exists"],
                    },
                },
                tool_runtime_executor=runtime.tool_runtime_executor,
                tool_instances=runtime._all_tool_instances(),
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done_event = next(event for event in events if event.get("type") == "done")
    completion = dict(done_event.get("completion") or {})
    task_result_completion = dict(dict(done_event.get("task_result") or {}).get("completion") or {})

    assert model_response_executor.turn_count == 2
    assert model_response_executor.followup_observed is True
    assert any(event.get("type") == "tool_call_requested" for event in events)
    assert done_event["content"] == "工具观察后的最终回答"
    assert completion["source_turn"] == "tool_followup"
    assert completion["observed_tool_result"] is True
    assert task_result_completion == completion


def test_professional_harness_real_tools_gate_completion_on_artifact_evidence() -> None:
    base_dir = isolated_backend_root("query-runtime-artifact-e2e-")
    tool_runtime = ToolRuntime(base_dir)
    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=tool_runtime,
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )
    model_response_executor = _WriteVerifyCompletionExecutor()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.agent_harness.run_stream(
            AgentRunRequest(
                session_id="session-artifact-e2e",
                task_id="taskinst:session-artifact-e2e:artifact",
                user_message=(
                    "请创建文件 output/e2e_completion_artifact.md，内容写入 completion evidence e2e，"
                    "然后验证这个文件真实存在并告诉我结果。"
                ),
                history=[],
                source="regression",
                agent_runtime_chain=runtime.agent_runtime_chain,
                model_response_executor=model_response_executor,
                runtime_context_manager=runtime.runtime_context_manager,
                task_selection={
                    "interaction_mode": "professional_mode",
                    "runtime_interaction_mode": "professional_mode",
                    "runtime_lane": "professional_task",
                    "mode_policy": {
                        "interaction_mode": "professional_mode",
                        "runtime_lane": "professional_task",
                        "recipe_id": "runtime.recipe.professional_task",
                    },
                    "operation_policy": {
                        "allowed_operations": ["op.write_file", "op.shell"],
                        "required_operations": ["op.write_file", "op.shell"],
                    },
                    "sandbox_policy": {
                        "enabled": True,
                        "workspace_key": "artifact-e2e",
                        "approval_policy": "sandboxed_side_effects",
                    },
                },
                tool_runtime_executor=runtime.tool_runtime_executor,
                tool_instances=runtime._all_tool_instances(),
                agent_runtime_profile=runtime.agent_runtime_registry.get_profile("agent:0"),
                search_policy=["workspace"],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    artifact_path = (
        base_dir.parent
        / "output"
        / "sandbox_runs"
        / "artifact-e2e"
        / "workspace"
        / "output"
        / "e2e_completion_artifact.md"
    )
    assert artifact_path.read_text(encoding="utf-8") == "completion evidence e2e"

    closeout_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "harness_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "agent_runtime_closeout_phase_checked"
    )
    verification = dict(dict(closeout_event.get("payload") or {}).get("verification") or {})
    ledger = dict(verification.get("tool_observation_ledger") or {})
    summary = {
        "records": [dict(item) for item in list(ledger.get("records") or [])],
        "completion_judgment": dict(verification.get("completion_judgment") or {}),
    }
    write_record = next(item for item in summary["records"] if item.get("tool_name") == "write_file")
    verify_record = next(item for item in summary["records"] if item.get("tool_name") == "terminal")
    judgment = summary["completion_judgment"]
    terminal_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "harness_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "loop_terminal"
    )
    terminal_payload = dict(terminal_event.get("payload") or {})

    assert model_response_executor.turn_count == 3
    assert "write_output" in write_record["satisfies"]
    assert "output/e2e_completion_artifact.md" in write_record["observed_paths"]
    assert write_record["evidence_source"] == "structured_envelope"
    assert "verify_command" in verify_record["satisfies"]
    assert dict(verify_record["command_receipt"])["passed"] is True
    assert verify_record["evidence_source"] == "structured_envelope"
    assert verification["passed"] is True
    assert judgment["completion_allowed"] is True
    assert terminal_payload["status"] == "completed"
    assert dict(terminal_payload["task_result"])["status"] == "completed"


def test_query_runtime_assembles_compressed_context_before_model_history() -> None:
    session_manager = InMemorySessionManagerStub()
    session_manager.compressed_context = "旧历史已经压缩为项目审查摘要。"
    session_manager.messages = [
        {"role": "user", "content": f"old-{index}"}
        for index in range(14)
    ]
    model_runtime = SingleMessageModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-history-assembly-"),
        settings_service=PrimarySettingsStub(),
        session_manager=session_manager,
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=model_runtime,
    )

    captured_history: list[dict[str, object]] = []
    original_run = runtime.agent_harness.run_stream

    async def _capture(request: AgentRunRequest):
        captured_history.extend(list(request.history or []))
        if False:
            yield {}
        return

    runtime.agent_harness.run_stream = _capture  # type: ignore[method-assign]

    async def _collect() -> None:
        async for _event in runtime.astream(
            QueryRequest(
                session_id="session-history-assembly",
                message="继续",
                history=[],
            )
        ):
            pass

    try:
        asyncio.run(_collect())
    finally:
        runtime.agent_harness.run_stream = original_run  # type: ignore[method-assign]

    assert captured_history[0]["role"] == "assistant"
    assert "旧历史已经压缩为项目审查摘要" in str(captured_history[0]["content"])
    assert [item["content"] for item in captured_history[1:]] == [f"old-{index}" for index in range(2, 14)]


def test_runtime_task_selection_preserves_request_resource_contract() -> None:
    projected_selection = {
        "interaction_mode": "professional_mode",
        "resource_contract": {
            "source_projects": [
                {"path": "D:/AI应用/agent-vibe-sandboxes/langchain-mini-clean", "role": "source"}
            ]
        },
        "sandbox_policy": {"enabled": True, "workspace_key": "langchain-mini-clean-agent-smoke"},
    }
    task_selection = _task_selection_for_runtime(
        request_task_selection={
            **projected_selection,
        },
        turn_id="turn:session:1",
    )

    assert task_selection["turn_id"] == "turn:session:1"
    assert task_selection["sandbox_policy"]["workspace_key"] == "langchain-mini-clean-agent-smoke"
    assert task_selection["resource_contract"]["source_projects"][0]["path"].endswith("langchain-mini-clean")


def test_astream_reports_prestart_failure_without_task_order_chain() -> None:
    runtime = QueryRuntime(
        base_dir=isolated_backend_root("query-runtime-prestart-failure-"),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=_FailingDecisionModelRuntime(),
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-prestart-failure",
                message="请检查 backend/api/chat.py 并写一份代码审查报告。",
                history=[],
                task_selection={
                    "interaction_mode": "professional_mode",
                    "runtime_lane": "professional_task",
                    "sandbox_policy": {"enabled": True, "workspace_key": "prestart-failure"},
                },
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assert any(
        dict(event.get("event") or {}).get("event_type") == "model_turn_decision_unresolved"
        for event in events
        if event.get("type") == "harness_loop_event"
    )
    error = next(event for event in events if event.get("type") == "error")
    assert error["code"] == "model_turn_decision_unresolved"


def test_astream_does_not_hard_block_write_from_natural_language_marker() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-action-permit-denied",
                message="请修改 backend/api/chat.py，但不要写任何文件。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assert not any(
        dict(event.get("event") or {}).get("event_type") == "runtime_blocked_before_assembly"
        for event in events
        if event.get("type") == "harness_loop_event"
    )
    assert any(event.get("type") == "harness_run_started" for event in events)


def test_removed_health_task_selection_falls_back_to_general_runtime() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.agent_harness.run_stream(
            AgentRunRequest(
                session_id="session-health-task-config",
                task_id="taskinst:session-health-task-config:health",
                user_message="请分诊这个健康问题。",
                history=[],
                source="regression",
                agent_runtime_chain=runtime.agent_runtime_chain,
                model_response_executor=runtime.model_response_executor,
                runtime_context_manager=runtime.runtime_context_manager,
                task_selection={"selected_task_id": "task.health.issue_triage"},
                tool_runtime_executor=runtime.tool_runtime_executor,
                tool_instances=runtime._all_tool_instances(),
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = next(event for event in events if event.get("type") == "harness_run_started")
    task_run = dict(started["task_run"])
    task_contract_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "harness_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )

    payload = dict(task_contract_event["payload"])
    assembly = dict(payload.get("task_execution_assembly") or {})

    assert task_run["agent_id"] == "agent:0"
    assert task_run["agent_profile_id"] == "main_interactive_agent"
    assert "task_family" not in assembly
    assert assembly["flow_contract_id"] == ""


def test_graph_node_assembly_contract_overrides_stale_task_selection_agent() -> None:
    runtime = _build_stream_runtime()
    work_order = NodeWorkOrder(
        work_order_id="workorder:assembly-authority",
        task_ref="task.dev.light_web_game",
        coordination_run_id="coordrun:assembly-authority",
        root_task_run_id="taskrun:root",
        stage_id="prototype",
        node_id="prototype",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        runtime_lane="game_delivery",
        executor_type="agent",
        explicit_inputs={"goal": "做一个小游戏"},
        input_package={"package_id": "nodeinput:assembly-authority"},
        dispatch_context={"dispatch_event_id": "tlevent:assembly-authority"},
    )
    invocation = build_agent_invocation(work_order, base_dir=runtime.base_dir).to_dict()
    assembly = dict(invocation["assembly_contract"])

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.agent_harness.run_stream(
            AgentRunRequest(
                session_id="session-assembly-authority",
                task_id="taskinst:session-assembly-authority:triage",
                user_message="请分诊这个健康问题。",
                history=[],
                source="regression",
                agent_runtime_chain=runtime.agent_runtime_chain,
                model_response_executor=runtime.model_response_executor,
                runtime_context_manager=runtime.runtime_context_manager,
                task_selection={
                    "selected_task_id": "task.dev.light_web_game",
                    "agent_id": "agent:pdf_reader",
                    "agent_profile_id": "pdf_analysis_agent",
                    "runtime_lane": "pdf_delegate",
                    "agent_invocation": invocation,
                },
                tool_runtime_executor=runtime.tool_runtime_executor,
                tool_instances=runtime._all_tool_instances(),
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    started = next(event for event in events if event.get("type") == "harness_run_started")
    task_run = dict(started["task_run"])
    task_contract_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "harness_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )
    payload = dict(task_contract_event["payload"])
    refs = dict(task_contract_event["refs"])

    assert task_run["agent_id"] == "agent:0"
    assert task_run["agent_profile_id"] == "main_interactive_agent"
    assert task_run["runtime_lane"] == "game_delivery"
    assert payload["agent_runtime_spec"]["agent_id"] == "agent:0"
    assert payload["agent_invocation"]["invocation_id"] == invocation["invocation_id"]
    assert payload["agent_assembly_contract"]["assembly_id"] == assembly["assembly_id"]
    assert "prompt_assembly" not in payload["agent_assembly_contract"]
    assert "runtime_control" not in payload["agent_invocation"]
    assert refs["agent_invocation_ref"] == invocation["invocation_id"]
    assert refs["agent_assembly_contract_ref"] == assembly["assembly_id"]
    assert refs["work_order_ref"] == work_order.work_order_id
    assert refs["agent_invocation_object_ref"].startswith("rtobj:agent_invocation:")
    assert refs["agent_assembly_object_ref"].startswith("rtobj:agent_assembly_contract:")
    assert refs["execution_permit_object_ref"].startswith("rtobj:execution_permit:")


def test_main_agent_assembly_modes_select_expected_runtime_lanes() -> None:
    cases = {
        "role": ("role_mode", "role_interaction", "runtime.recipe.role_interaction"),
        "standard": ("standard_mode", "standard_task", "runtime.recipe.standard_task"),
        "professional": ("professional_mode", "professional_task", "runtime.recipe.professional_task"),
    }

    for mode, (interaction_mode, runtime_lane, recipe_id) in cases.items():
        runtime = _build_stream_runtime()
        task_selection = _main_agent_mode_task_selection(
            interaction_mode=interaction_mode,
            runtime_lane=runtime_lane,
            recipe_id=recipe_id,
            professional=mode == "professional",
        )

        async def _collect() -> list[dict[str, object]]:
            events: list[dict[str, object]] = []
            async for event in runtime.astream(
                QueryRequest(
                    session_id=f"session-main-agent-{mode}",
                    message="请确认当前主 Agent 装配模式。",
                    history=[],
                    task_selection=task_selection,
                )
            ):
                events.append(event)
            return events

        events = asyncio.run(_collect())
        started = next(event for event in events if event.get("type") == "harness_run_started")
        task_run = dict(started["task_run"])
        task_contract_event = next(
            dict(event.get("event") or {})
            for event in events
            if event.get("type") == "harness_loop_event"
            and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
        )
        payload = dict(task_contract_event.get("payload") or {})
        agent_runtime_spec = dict(payload.get("agent_runtime_spec") or {})
        agent_assembly_contract = dict(payload.get("agent_assembly_contract") or {})
        agent_invocation = dict(payload.get("agent_invocation") or {})
        selected_recipe = dict(payload.get("selected_recipe") or {})
        selected_metadata = dict(selected_recipe.get("metadata") or {})
        mode_policy = dict(selected_metadata.get("mode_policy") or {})
        agent_runtime_config = dict(payload.get("agent_runtime_config") or {})
        control_policy = dict(agent_runtime_config.get("control_policy") or {})

        assert task_run["agent_id"] == "agent:0"
        assert task_run["agent_profile_id"] == "main_interactive_agent"
        assert task_run["runtime_lane"] == runtime_lane
        assert agent_runtime_spec["agent_id"] == "agent:0"
        assert agent_runtime_spec["runtime_lane"] == runtime_lane
        assert agent_assembly_contract["agent_id"] == "agent:0"
        assert agent_assembly_contract["agent_profile_id"] == "main_interactive_agent"
        assert agent_assembly_contract["runtime_lane"] == runtime_lane
        assert agent_invocation["agent_profile_id"] == "main_interactive_agent"
        assert selected_recipe["recipe_id"] == recipe_id
        assert mode_policy["interaction_mode"] == interaction_mode
        assert mode_policy["runtime_lane"] == runtime_lane
        assert dict(agent_runtime_config.get("mode_policy") or {}).get("interaction_mode") == interaction_mode
        if mode == "professional":
            assert selected_recipe["execution_kind"] == interaction_mode
            assert control_policy["planning_required"] is True
            assert agent_runtime_config["enabled_phases"] == [
                "planning",
                "model_turn",
                "tool_followup",
                "evidence",
                "verification",
                "closeout",
            ]
        else:
            assert control_policy["planning_required"] is False
            assert agent_runtime_config["enabled_phases"] == ["model_turn", "tool_followup"]


def test_query_runtime_enters_agent_runtime_boundary_before_legacy_loop() -> None:
    runtime = _build_stream_runtime()
    captured: list[AgentRunRequest] = []
    original_run = runtime.agent_harness.run_stream

    async def _capture(request: AgentRunRequest):
        captured.append(request)
        if False:
            yield {}
        return

    runtime.agent_harness.run_stream = _capture  # type: ignore[method-assign]

    async def _collect() -> None:
        async for _event in runtime.astream(
            QueryRequest(
                session_id="session-agent-runtime-boundary",
                message="请确认 runtime 边界。",
                history=[],
            )
        ):
            pass

    try:
        asyncio.run(_collect())
    finally:
        runtime.agent_harness.run_stream = original_run  # type: ignore[method-assign]

    assert len(captured) == 1
    assert isinstance(captured[0], AgentRunRequest)
    assert captured[0].source == "query_runtime.adapter"
    assert captured[0].task_selection is not None


def test_runtime_trace_exposes_worker_spawn_trace_for_light_web_game(tmp_path: Path) -> None:
    base_dir = isolated_backend_root("query-runtime-loop-")
    registry = TaskFlowRegistry(base_dir)
    registry.upsert_task_execution_policy(
        task_id="task.dev.light_web_game",
        execution_mode="coordinated_agents",
        default_agent_id="agent:0",
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
        worker_agent_naming_rule="game-worker-{n}",
        notes="trace regression",
    )
    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-trace-light-game",
                message="请开发一个轻量网页小游戏原型。",
                history=[],
                task_selection={"selected_task_id": "task.dev.light_web_game", "task_mode": "light_web_game"},
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "harness_run_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    trace = runtime.harness_service_host.get_trace(task_run_id)
    event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "harness_loop_event"
    ]

    assert trace is not None
    assert "worker_agent_spawn_requested" in event_types
    assert "worker_agent_spawn_completed" in event_types
    assert trace["worker_spawn_requests"]
    assert trace["worker_spawn_results"]


def test_delegate_mode_does_not_start_system_retrieval_phase() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-delegate-phase",
                message="请分析 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的核心结论。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "harness_loop_event"
    ]
    built_event = next(
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "harness_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )
    payload = dict(built_event.get("payload") or {})
    recipe = dict(payload.get("selected_recipe") or {})
    assert str(recipe.get("recipe_id") or "")
    assert str(recipe.get("execution_kind") or "") in {
        "conversation",
        "professional",
        "standard_mode",
        "capability",
        "role_mode",
    }

    executor_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "harness_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "executor_started"
    ]
    assert not any(
        str(dict(event.get("payload") or {}).get("runtime_channel") or "") == "system_retrieval"
        for event in executor_events
    )


def test_terminal_state_index_failure_still_yields_done() -> None:
    runtime = _build_stream_runtime()

    def _raise_state_index_failure(*_args, **_kwargs):
        raise PermissionError("simulated state_index replace failure")

    runtime.harness_service_host.task_run_finalizer.upsert_finished_task_run = _raise_state_index_failure  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-state-index-degraded",
                message="请给我一个值班提示。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done_event = next(event for event in events if event.get("type") == "done")

    assert not any(event.get("type") == "error" for event in events)
    assert done_event.get("content") == "单轮收口回答"
    output_commit = dict(done_event.get("output_commit") or {})
    assert output_commit["state_index_degraded"] is True
    assert dict(done_event.get("runtime_state_index") or {})["phase"] == "finished_task_run_state_write"


def test_agent_runtime_reports_coordination_continuation_without_running_graph_stage() -> None:
    runtime = _build_stream_runtime()
    original_upsert = runtime.harness_service_host.task_run_finalizer.upsert_finished_task_run

    def _upsert_with_continuation(*args, **kwargs):
        finished = original_upsert(*args, **kwargs)
        return FinishedTaskRunResult(
            events=finished.events,
            continuation_payload={
                "next_task_ref": "task.dev.followup",
                "message": "继续执行后续节点。",
            },
        )

    runtime.harness_service_host.task_run_finalizer.upsert_finished_task_run = _upsert_with_continuation  # type: ignore[method-assign]

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-done-ends-stream",
                message="你好",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert events[-1].get("type") == "done"
    assert events[-1].get("content") == "单轮收口回答"
    continuation = dict(events[-1].get("coordination_continuation") or {})
    assert continuation["next_task_ref"] == "task.dev.followup"
    assert continuation["message"] == "继续执行后续节点。"
    assert dict(events[-1].get("output_commit") or {})["coordination_continuation_ready"] is True


def test_assistant_commit_enqueues_memory_maintenance_without_waiting(tmp_path: Path) -> None:
    runtime = QueryRuntime(
        base_dir=tmp_path,
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=SingleMessageModelRuntimeStub(),
    )

    result = runtime._apply_assistant_message_commit(
        "session-queued-commit",
        {
            "role": "assistant",
            "content": "已提交。",
            "turn_id": "turn:queued:1",
        },
    )

    assert result["memory_maintenance_status"] == "queued"
    assert result["memory_maintenance_attempted"] is False
    assert result["durable_memory_commit_attempted"] is False


