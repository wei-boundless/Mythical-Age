from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.runtime.compiler import RuntimeCompiler, _dynamic_context_segment_metadata
from harness.runtime.context_budget_policy import build_model_aware_context_budget_policy
from harness.runtime.artifact_scope import canonicalize_task_contract_artifacts
from harness.runtime.dynamic_context import DynamicContextProjection, VolatileSectionReport
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert content.startswith(marker)
    return json.loads(content[len(marker):])


def test_runtime_compiler_emits_dynamic_context_report_and_projected_task_state() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:dynamic-context",
        task_run={"task_run_id": "taskrun:dynamic-context", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证动态上下文投影", "completion_criteria": ["投影进入 packet"]},
        observations=[
            {
                "observation_id": "obs:tool",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:obs",
                        "tool_name": "read_file",
                        "status": "ok",
                        "text": "file content",
                        "artifact_refs": [{"path": "artifacts/file.txt"}],
                    }
                },
            }
        ],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "current_facts": [{"tool_name": "write_file", "summary": "已创建入口文件"}],
                "artifact_evidence": [{"path": "artifacts/file.txt", "kind": "file"}],
                "pending_user_steers": [{"steer_id": "steer:1", "summary": "改成五层"}],
            },
            "large_internal_blob": "x" * 5000,
        },
        work_rollout={
            "latest_progress": "完成第一步",
            "model_visible_history": [{"title": "第一步", "status": "completed", "summary": "完成初始化"}],
            "artifact_refs": [{"path": "artifacts/file.txt"}],
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    packet = result.packet
    manifest = packet.diagnostics["prompt_manifest"]
    volatile_payload = _payload_after_title(packet.model_messages[-1]["content"], "Task execution current state")

    assert "dynamic_context_report" in manifest
    assert all(item["volatility_reason"] for item in manifest["dynamic_context_report"]["section_reports"])
    task_state = volatile_payload["task_state"]
    assert task_state["current_facts"][0]["summary"] == "已创建入口文件"
    assert task_state["artifact_evidence"][0]["path"] == "artifacts/file.txt"
    assert task_state["pending_user_steers"][0]["steer_id"] == "steer:1"
    assert "large_internal_blob" not in json.dumps(volatile_payload, ensure_ascii=False)
    assert task_state["latest_tool_results"][0]["tool_name"] == "read_file"
    assert packet.artifact_refs == ("artifacts/file.txt",)


def test_read_file_content_windows_survive_task_state_projection() -> None:
    def _read_observation(ref: str, text: str, start_line: int, end_line: int, next_start_line: int | None) -> dict[str, object]:
        return {
            "observation_id": ref,
            "payload": {
                "result_envelope": {
                    "envelope_id": f"tool-result:{ref}",
                    "tool_name": "read_file",
                    "status": "ok",
                    "text": text,
                    "observed_paths": ["docs/long.md"],
                    "structured_payload": {
                        "observed_paths": ["docs/long.md"],
                        "tool_result": {
                            "kind": "text_file",
                            "path": "docs/long.md",
                            "total_lines": 30,
                            "start_line": start_line,
                            "line_count": 10,
                            "returned_lines": end_line - start_line + 1,
                            "end_line": end_line,
                            "next_start_line": next_start_line,
                            "has_more": next_start_line is not None,
                            "truncated": next_start_line is not None,
                            "content_sha256": "sha256:test",
                        },
                    },
                }
            },
        }

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:read-windows",
        task_run={"task_run_id": "taskrun:read-windows", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "连续读取长文件", "completion_criteria": ["读取窗口可见"]},
        observations=[
            _read_observation("obs:window:1", "1 | first", 1, 10, 11),
            _read_observation("obs:window:11", "11 | next", 11, 20, 21),
        ],
        execution_state={
            "system_projection": {
                "file_state": [
                    {
                        "path": "docs/long.md",
                        "read_ranges": [
                            {"start_line": 1, "end_line": 10, "observation_ref": "obs:window:1"},
                            {"start_line": 11, "end_line": 20, "observation_ref": "obs:window:11"},
                        ],
                        "coverage": {"covered_lines": 20, "total_lines": 30, "complete": False},
                        "total_lines": 30,
                        "content_sha256": "sha256:test",
                        "last_observation_ref": "obs:window:11",
                        "has_more": True,
                        "status": "partial",
                    }
                ]
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.development.sandbox"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    windows = [
        item
        for item in volatile_payload["task_state"]["latest_tool_results"]
        if item.get("tool_name") == "read_file"
    ]

    assert [item["content_range"]["start_line"] for item in windows] == [1, 11]
    assert windows[0]["content_range"]["next_start_line"] == 11
    assert "不要重复读取相同行窗口" in windows[0]["tool_guidance"]
    assert volatile_payload["task_state"]["file_state"][0]["read_ranges"] == [
        {"start_line": 1, "end_line": 10, "observation_ref": "obs:window:1"},
        {"start_line": 11, "end_line": 20, "observation_ref": "obs:window:11"},
    ]


def test_task_execution_prompt_uses_canonical_artifact_scope_only() -> None:
    artifact_root = "storage/task_environments/development/sandbox/artifacts"
    requested_path = "artifacts/prompt_cache_live_e2e/run/index.html"
    canonical_path = f"{artifact_root}/prompt_cache_live_e2e/run/index.html"
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:canonical-artifact",
        task_run={"task_run_id": "taskrun:canonical-artifact", "diagnostics": {"executor_status": "running"}},
        contract={
            "contract_id": "contract:canonical-artifact",
            "task_run_goal": "生成可打开的 HTML 页面",
            "completion_criteria": ["页面存在"],
            "required_artifacts": [
                {"artifact_kind": "html_document", "path": requested_path, "user_visible_name": "index.html"}
            ],
        },
        observations=[],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {
                "environment_id": "env.development.sandbox",
                "storage_space": {"artifact_root": artifact_root},
                "artifact_policy": {"artifact_root": "runtime_output"},
                "sandbox_policy": {},
            },
            "operation_authorization": {"allowed_operations": ["op.write_file"]},
        },
    )

    model_input = "\n".join(str(message["content"]) for message in result.packet.model_messages)
    diagnostics = result.packet.diagnostics["artifact_scope"]
    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")

    assert result.envelope.artifact_policy["artifact_root"] == artifact_root
    assert canonical_path in model_input
    assert f'"path":"{requested_path}"' not in model_input
    assert "runtime_output" not in model_input
    artifact_scope_segments = [
        segment
        for segment in result.packet.segment_plan["segments"]
        if segment.get("kind") == "artifact_scope_stable"
    ]
    assert artifact_scope_segments
    assert artifact_scope_segments[0]["cache_scope"] == "task"
    assert artifact_scope_segments[0]["cache_role"] == "session_stable"
    assert volatile_payload["task_state"]["runtime_boundary"]["artifact_root"] == artifact_root
    assert diagnostics["normalizations"][0]["requested_path"] == requested_path
    assert diagnostics["normalizations"][0]["path"] == canonical_path
    assert diagnostics["canonical_output_paths"] == [canonical_path]


def test_artifact_contract_normalization_replaces_path_aliases_with_canonical_path() -> None:
    artifact_root = "storage/task_environments/development/sandbox/artifacts"
    normalized = canonicalize_task_contract_artifacts(
        {
            "required_artifacts": [
                {"artifact_kind": "html_document", "artifact_path": "artifacts/demo/index.html"}
            ],
            "required_verifications": [
                {"verification_kind": "readback", "target_path": "artifacts/demo/index.html"}
            ],
        },
        artifact_root=artifact_root,
    )

    expected = f"{artifact_root}/demo/index.html"
    assert normalized.contract["required_artifacts"][0] == {"artifact_kind": "html_document", "path": expected}
    assert normalized.contract["required_verifications"][0] == {"verification_kind": "readback", "path": expected}
    assert [item["requested_path"] for item in normalized.normalizations] == [
        "artifacts/demo/index.html",
        "artifacts/demo/index.html",
    ]


def test_task_work_rollout_only_enters_model_through_dynamic_context_projection() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:work-rollout-projection",
        task_run={"task_run_id": "taskrun:work-rollout-projection", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证工作历史投影", "completion_criteria": ["工作历史只走动态上下文投影"]},
        observations=[],
        work_rollout={
            "latest_progress": "完成初始化",
            "latest_step_title": "初始化",
            "agent_brief_output": "ROOT_AGENT_BRIEF_SHOULD_NOT_BYPASS_PROJECTOR",
            "latest_checkpoint_ref": "rtchk:old-control-point",
            "lineage": {"parent_task_run_id": "taskrun:old"},
            "model_visible_history": [
                {
                    "title": "初始化",
                    "status": "completed",
                    "summary": "已创建基础文件",
                    "event_offset": 12,
                    "refs": {"checkpoint_ref": "rtchk:old-step"},
                    "checkpoint": {"ref": "rtchk:old-step"},
                }
            ],
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    model_input = "\n".join(str(message["content"]) for message in result.packet.model_messages)
    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")

    assert "ROOT_AGENT_BRIEF_SHOULD_NOT_BYPASS_PROJECTOR" not in model_input
    work_progress = volatile_payload["task_state"]["work_progress"]
    assert work_progress["recent_steps"][0]["summary"] == "已创建基础文件"
    assert work_progress["historical_work_summary"]["non_control_context"] is True
    assert "checkpoint" not in json.dumps(work_progress, ensure_ascii=False)
    assert "lineage" not in json.dumps(work_progress, ensure_ascii=False)
    assert "event_offset" not in json.dumps(work_progress, ensure_ascii=False)
    assert "refs" not in work_progress["recent_steps"][0]


def test_task_execution_state_deduplicates_observation_failures_and_preserves_retry_fields() -> None:
    observation = {
        "observation_id": "obs:image",
        "payload": {
            "tool_name": "image_generate",
            "result": json.dumps(
                {
                    "ok": False,
                    "error": "gateway timeout",
                    "structured_error": {
                        "code": "image_provider_transient_error",
                        "message": "Image API failed with status 504",
                        "retryable": True,
                        "origin": "image_provider",
                        "provider_retryable": True,
                        "agent_auto_retry_allowed": True,
                        "agent_retry_policy": "bounded_retry_with_backoff",
                        "max_agent_retry_attempts": 2,
                        "suggested_retry_delay_seconds": 15,
                        "attempts": [
                            {
                                "model": "gpt-image-2",
                                "attempt_index": 1,
                                "http_status": 504,
                                "code": "image_provider_transient_error",
                                "retryable": True,
                            }
                        ],
                    },
                }
            ),
        },
        "runtime_freshness": {"visibility": "active"},
    }
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-state-dedupe",
        task_run={"task_run_id": "taskrun:task-state-dedupe", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "执行 image_generate，遇到供应商瞬时错误时允许有限退避重试", "completion_criteria": ["生成图片或说明重试耗尽"]},
        observations=[observation],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "active_failures": [
                    {
                        "observation_ref": "obs:image",
                        "tool_name": "image_generate",
                        "status": "error",
                        "summary": "gateway timeout",
                        "error": {
                            "code": "image_provider_transient_error",
                            "message": "Image API failed with status 504",
                            "retryable": True,
                            "origin": "image_provider",
                            "provider_retryable": True,
                            "agent_auto_retry_allowed": True,
                            "agent_retry_policy": "bounded_retry_with_backoff",
                            "max_agent_retry_attempts": 2,
                            "suggested_retry_delay_seconds": 15,
                        },
                    }
                ],
                "last_action_receipts": [
                    {
                        "observation_ref": "obs:image",
                        "tool_name": "image_generate",
                        "status": "error",
                        "summary": "gateway timeout",
                    }
                ],
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.development.sandbox"},
            "operation_authorization": {"allowed_operations": ["op.image_generate"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    task_state = volatile_payload["task_state"]
    assert "observations" not in volatile_payload
    assert "execution_state" not in volatile_payload
    assert len(task_state["active_failures"]) == 1
    error = task_state["active_failures"][0]["error"]
    assert error["provider_retryable"] is True
    assert error["agent_auto_retry_allowed"] is True
    assert error["agent_retry_policy"] == "bounded_retry_with_backoff"
    assert error["max_agent_retry_attempts"] == 2
    assert error["attempts"][0]["http_status"] == 504


def test_task_execution_state_semantically_deduplicates_repeated_tool_facts() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:semantic-dedupe",
        task_run={
            "task_run_id": "taskrun:semantic-dedupe",
            "status": "running",
            "diagnostics": {"executor_status": "running"},
        },
        contract={"task_run_goal": "检查目录并继续", "completion_criteria": ["目录检查只保留一条事实"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "current_facts": [
                    {"observation_ref": "obs:path:1", "tool_name": "path_exists", "path": "artifacts/demo", "status": "ok", "summary": "路径不存在"},
                    {"observation_ref": "obs:path:2", "tool_name": "path_exists", "path": "artifacts/demo", "status": "ok", "summary": "路径不存在"},
                ],
                "last_action_receipts": [
                    {"observation_ref": "obs:path:2", "tool_name": "path_exists", "path": "artifacts/demo", "status": "ok", "summary": "路径不存在"},
                ],
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.path_exists"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    task_state = volatile_payload["task_state"]
    assert [item["observation_ref"] for item in task_state["current_facts"]] == ["obs:path:1"]
    assert "latest_tool_results" not in task_state
    assert "task_run_id" not in json.dumps(volatile_payload, ensure_ascii=False)


def test_task_execution_state_hides_sandbox_artifact_paths_and_supersedes_missing_probe() -> None:
    artifact_path = "storage/task_environments/general/workspace/artifacts/five_floor_dungeon.html"
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:artifact-path-clean",
        task_run={
            "task_run_id": "taskrun:artifact-path-clean",
            "status": "running",
            "diagnostics": {"executor_status": "running"},
        },
        contract={"task_run_goal": "写入并验证 HTML", "completion_criteria": ["文件存在"]},
        observations=[],
        execution_state={
            "system_projection": {
                "runtime_status": "running",
                "current_facts": [
                    {
                        "observation_ref": "obs:missing",
                        "tool_name": "path_exists",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "false",
                    },
                    {
                        "observation_ref": "obs:write",
                        "tool_name": "write_file",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "Write succeeded",
                    },
                ],
                "last_action_receipts": [
                    {
                        "observation_ref": "obs:missing",
                        "tool_name": "path_exists",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "false",
                    },
                    {
                        "observation_ref": "obs:write",
                        "tool_name": "write_file",
                        "path": artifact_path,
                        "status": "ok",
                        "summary": "Write succeeded",
                    },
                ],
                "artifact_evidence": [
                    {
                        "path": artifact_path,
                        "absolute_path": "D:/AI应用/langchain-agent/storage/runtime_state/sandboxes/taskrun_x/storage/task_environments/general/workspace/artifacts/five_floor_dungeon.html",
                        "sandbox_path": artifact_path,
                        "kind": "file",
                        "source": "write_file",
                    }
                ],
            }
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.path_exists", "op.write_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Task execution current state")
    task_state = volatile_payload["task_state"]
    serialized = json.dumps(task_state, ensure_ascii=False)

    assert "absolute_path" not in serialized
    assert "sandbox_path" not in serialized
    assert "storage/runtime_state/sandboxes" not in serialized
    assert task_state["artifact_evidence"] == [{"path": artifact_path, "kind": "file", "source": "write_file"}]
    assert all(item.get("observation_ref") != "obs:missing" for item in task_state.get("current_facts", []))
    assert all(item.get("observation_ref") != "obs:missing" for item in task_state.get("latest_tool_results", []))
    assert any(item.get("observation_ref") == "obs:write" for item in task_state["current_facts"])


def test_task_execution_uses_invocation_scoped_agent_prompt_refs() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:prompt-scope",
        task_run={"task_run_id": "taskrun:prompt-scope", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "执行 image_generate 调用，供应商瞬时失败时允许有限退避重试",
            "completion_criteria": ["生成图片，或说明有限重试后仍失败"],
        },
        observations=[],
        available_tools=[
            {"tool_name": "image_generate", "operation_id": "op.image_generate"},
            {"tool_name": "python_symbol_search", "operation_id": "op.python_symbol_search"},
        ],
        runtime_assembly={
            "profile": {
                "mode": "professional",
                "metadata": {},
            },
            "agent_prompt_refs": ["agent.main_interactive_agent.single_agent_turn.work_role.v1"],
            "agent_prompt_refs_by_invocation": {
                "single_agent_turn": ["agent.main_interactive_agent.single_agent_turn.work_role.v1"],
                "task_execution": ["agent.main_interactive_agent.task_execution.work_role.v1"],
            },
            "environment_prompt_refs": ["environment.development.sandbox.orientation.v1"],
            "task_environment": {
                "environment_id": "env.development.sandbox",
                "title": "Development Sandbox",
                "description": "Project workspace boundary",
            },
            "operation_authorization": {"allowed_operations": ["op.image_generate", "op.python_symbol_search"]},
        },
    )

    model_input = "\n".join(str(message["content"]) for message in result.packet.model_messages)
    manifest = result.packet.diagnostics["prompt_manifest"]
    assert "agent.main_interactive_agent.task_execution.work_role.v1" in manifest["stable_prompt_refs"]
    assert "agent.main_interactive_agent.single_agent_turn.work_role.v1" not in manifest["stable_prompt_refs"]
    assert "持续任务执行 agent" in model_input
    assert "不负责重新判断是否建立任务生命周期" in model_input
    assert "请求持续任务生命周期" not in model_input
    assert "处理 Python 开发任务" in model_input
    assert "AST 工具只用于只读代码智能" in model_input


def test_environment_strategy_prompt_ref_is_rejected_after_strategy_moves_to_agent_profile() -> None:
    obsolete_environment_strategy_ref = "strategy." + "development.execution.v1"
    with pytest.raises(ValueError, match="runtime prompt ref assembly rejected refs"):
        RuntimeCompiler().compile_task_execution_packet(
            session_id="session:structured-strategy",
            task_run={"task_run_id": "taskrun:structured-strategy", "diagnostics": {"executor_status": "running"}},
            contract={
                "task_run_goal": "执行 image_generate 调用，供应商瞬时失败时允许有限退避重试",
                "completion_criteria": ["生成图片，或说明有限重试后仍失败"],
            },
            observations=[],
            available_tools=[
                {"tool_name": "image_generate", "operation_id": "op.image_generate"},
                {"tool_name": "python_symbol_search", "operation_id": "op.python_symbol_search"},
            ],
            runtime_assembly={
                "profile": {"mode": "professional"},
                "environment_prompt_refs": [
                    "environment.development.sandbox.orientation.v1",
                    obsolete_environment_strategy_ref,
                ],
                "task_environment": {
                    "environment_id": "env.development.sandbox",
                    "title": "Development Sandbox",
                    "description": "Project workspace boundary",
                },
                "operation_authorization": {"allowed_operations": ["op.image_generate", "op.python_symbol_search"]},
            },
        )


def test_runtime_compiler_rejects_wrong_invocation_prompt_ref() -> None:
    with pytest.raises(ValueError, match="resource_invocation_kind_mismatch"):
        RuntimeCompiler().compile_task_execution_packet(
            session_id="session:wrong-ref",
            task_run={"task_run_id": "taskrun:wrong-ref", "diagnostics": {"executor_status": "running"}},
            contract={"task_run_goal": "验证错误 prompt ref 不会静默装配", "completion_criteria": ["抛出错误"]},
            observations=[],
            runtime_assembly={
                "profile": {"mode": "professional"},
                "agent_prompt_refs_by_invocation": {
                    "task_execution": ["agent.main_interactive_agent.single_agent_turn.work_role.v1"],
                },
                "task_environment": {"environment_id": "env.general.workspace"},
            },
        )


def test_single_agent_turn_keeps_compressed_context_outside_recent_history_window() -> None:
    history = [
        {"role": "assistant", "content": "[Compressed session context]\n此前已经确认项目采用 DeepSeek。"},
        *({"role": "user", "content": f"user-{index}"} for index in range(8)),
    ]
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:compressed-context",
        turn_id="turn:compressed-context",
        agent_invocation_id="aginvoke:compressed-context",
        user_message="继续检查 prompt 装载。",
        history=history,
        session_context={"compressed_context": "此前已经确认项目采用 DeepSeek。"},
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    history_payload = volatile_payload["history"]

    assert history_payload["session_context"]["compressed_summary"] == "此前已经确认项目采用 DeepSeek。"
    assert [item["content"] for item in history_payload["recent_turns"]] == [f"user-{index}" for index in range(8)]
    assert all("[Compressed session context]" not in item["content"] for item in history_payload["recent_turns"])


def test_observation_followup_projects_session_context_with_observations() -> None:
    result = RuntimeCompiler().compile_observation_followup_packet(
        session_id="session:followup-context",
        turn_id="turn:followup-context",
        agent_invocation_id="aginvoke:followup-context",
        user_message="根据工具结果继续。",
        history=[{"role": "user", "content": "先读文件。"}],
        session_context={"compressed_context": "此前决定优先修结构问题。"},
        observations=[{"observation_id": "obs:1", "content": "read_file ok"}],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Observation followup current request")

    assert volatile_payload["history"]["session_context"]["compressed_summary"] == "此前决定优先修结构问题。"
    assert volatile_payload["history"]["recent_turns"][0]["content"] == "先读文件。"
    assert volatile_payload["observations"]["latest_observations"][0]["summary"] == "read_file ok"


def test_single_agent_turn_projects_compressed_context_as_session_context() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:single-turn-context",
        turn_id="turn:single-turn-context",
        agent_invocation_id="aginvoke:single-turn-context",
        user_message="继续。",
        history=[
            {"role": "user", "content": "上一轮用户消息"},
            {"role": "assistant", "content": "上一轮助手回复"},
        ],
        session_context={"compressed_context": "此前已经完成项目结构审查。"},
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    message_texts = [str(message["content"]) for message in result.packet.model_messages]

    assert volatile_payload["history"]["session_context"]["compressed_summary"] == "此前已经完成项目结构审查。"
    assert "[Compressed session context]" not in "\n".join(message_texts)
    assert [item["content"] for item in volatile_payload["history"]["recent_turns"]] == ["上一轮用户消息", "上一轮助手回复"]
    assert volatile_payload["history"]["current_user_message_ref"] == "volatile_current_request"
    assert result.packet.invocation_kind == "single_agent_turn"
    context_window = result.packet.diagnostics["prompt_manifest"]["context_window"]
    assert context_window["compressed_summary_present"] is True
    assert str(context_window["compressed_summary_hash"]).startswith("sha256:")


def test_single_agent_turn_projects_recent_work_outcome_as_read_only_context() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:recent-work-outcome",
        turn_id="turn:recent-work-outcome",
        agent_invocation_id="aginvoke:recent-work-outcome",
        user_message="刚才为什么卡住了？",
        history=[
            {"role": "user", "content": "开始复杂版五层地下塔。"},
            {"role": "assistant", "content": "我会按这个目标推进。"},
        ],
        session_context={
            "recent_work_outcome": {
                "task_run_id": "taskrun:turn:session-recent:1:root",
                "status": "failed",
                "terminal_reason": "task_executor_schedule_failed",
                "user_visible_goal": "制作复杂版五层地下塔像素风游戏。",
                "latest_progress": "生图工具未配置，无法完成合同要求的真实美术资产。",
                "agent_brief_output": "image_generate returned Image generation is not configured.",
                "decision_boundary": "This is a read-only result from the most recent terminal task.",
                "continuation_state": "terminal_or_interrupted_task_record",
            }
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    volatile_payload = _payload_after_title(result.packet.model_messages[-1]["content"], "Single agent turn current request")
    outcome = volatile_payload["history"]["session_context"]["recent_work_outcome"]
    model_input = "\n".join(str(message.get("content") or "") for message in result.packet.model_messages)

    assert outcome["status"] == "failed"
    assert outcome["terminal_reason"] == "task_executor_schedule_failed"
    assert outcome["latest_progress"] == "生图工具未配置，无法完成合同要求的真实美术资产。"
    assert outcome["continuation_state"] == "terminal_or_interrupted_task_record"
    assert "active_work_context" not in json.dumps(volatile_payload, ensure_ascii=False)
    assert "最近一次终止、阻塞或中断任务的只读事实" in model_input
    context_window = result.packet.diagnostics["prompt_manifest"]["context_window"]
    assert context_window["recent_work_outcome_present"] is True
    assert str(context_window["recent_work_outcome_hash"]).startswith("sha256:")


def test_single_agent_turn_replays_api_transcript_as_real_chat_messages() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:deepseek-protocol",
        turn_id="turn:deepseek-protocol:2",
        agent_invocation_id="aginvoke:deepseek-protocol",
        user_message="继续查广州。",
        history=[
            {"role": "user", "content": "查杭州天气。"},
            {"role": "assistant", "content": "杭州天气结果。"},
        ],
        session_context={
            "api_transcript": [
                {"role": "user", "content": "查杭州天气。"},
                {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "I need the date first.",
                    "tool_calls": [{"id": "call_1", "name": "get_date", "args": {}, "type": "tool_call"}],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "2026-04-20"},
                {"role": "assistant", "content": "杭州天气结果。", "reasoning_content": "Now I can answer."},
            ]
        },
        runtime_assembly={
            "profile": {"mode": "conversation"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    messages = result.packet.model_messages
    assistant_tool_message = next(item for item in messages if item.get("tool_calls"))
    tool_message = next(item for item in messages if item.get("role") == "tool")
    current_request_text = str(messages[-1].get("content") or "")

    assert assistant_tool_message["role"] == "assistant"
    assert assistant_tool_message["content"] == ""
    assert assistant_tool_message["reasoning_content"] == "I need the date first."
    assert assistant_tool_message["tool_calls"][0]["id"] == "call_1"
    assert tool_message["tool_call_id"] == "call_1"
    assert sum(1 for item in messages if item.get("reasoning_content") == "I need the date first.") == 1
    assert "I need the date first." not in current_request_text
    assert "Now I can answer." not in current_request_text
    assert any(
        segment["kind"] == "provider_protocol_history" and segment["cache_role"] == "never_cache"
        for segment in result.packet.segment_plan["segments"]
    )


def test_model_aware_context_budget_uses_deepseek_1m_for_v4_models() -> None:
    policy = build_model_aware_context_budget_policy(
        invocation_kind="single_agent_turn",
        model_selection={
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "context_budget_preset": "deepseek_1m",
            "max_output_tokens": 65536,
            "thinking_mode": "enabled",
            "reasoning_effort": "max",
        },
    )

    assert policy.effective_preset_id == "deepseek_1m"
    assert policy.context_window_tokens == 1_000_000
    assert policy.available_context_tokens >= 800_000
    assert policy.projection_limits["recent_history_message_limit"] > 100
    assert policy.volatile_char_budget > 1_000_000
    assert policy.thinking_mode == "enabled"
    assert policy.reasoning_effort == "max"


def test_model_aware_context_budget_does_not_enable_deepseek_1m_for_other_models() -> None:
    policy = build_model_aware_context_budget_policy(
        invocation_kind="single_agent_turn",
        model_selection={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "context_budget_preset": "deepseek_1m",
        },
    )

    assert policy.requested_preset_id == "deepseek_1m"
    assert policy.effective_preset_id == "long_128k"
    assert policy.preset_status == "incompatible_model_downgraded"
    assert policy.context_window_tokens == 128_000
    assert policy.diagnostics["preset_rejection_reason"] == "deepseek_1m_requires_deepseek_v4_pro_or_flash"


def test_runtime_compiler_exposes_model_budget_policy_in_context_window_report() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:budget-policy",
        turn_id="turn:budget-policy",
        agent_invocation_id="aginvoke:budget-policy",
        user_message="继续审查上下文预算。",
        history=[],
        model_selection={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "context_budget_preset": "deepseek_1m",
            "thinking_mode": "enabled",
            "reasoning_effort": "high",
        },
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    budget_report = result.packet.diagnostics["prompt_manifest"]["context_window"]["budget_report"]
    policy = budget_report["context_budget_policy"]

    assert policy["authority"] == "harness.runtime.context_budget_policy"
    assert policy["effective_preset_id"] == "deepseek_1m"
    assert policy["context_window_tokens"] == 1_000_000
    assert budget_report["volatile_char_budget"] == policy["volatile_char_budget"]


def test_dynamic_context_manager_rebinds_to_runtime_assembly_backend_dir(tmp_path: Path) -> None:
    old_backend = tmp_path / "old_backend"
    new_backend = tmp_path / "new_backend"
    result = RuntimeCompiler(base_dir=old_backend).compile_task_execution_packet(
        session_id="session:backend-dir",
        task_run={"task_run_id": "taskrun:backend-dir", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证动态上下文存储根目录", "completion_criteria": ["写入新 backend_dir"]},
        observations=[
            {
                "observation_id": "obs:backend-dir",
                "payload": {
                    "result_envelope": {
                        "envelope_id": "tool-result:backend-dir",
                        "tool_name": "read_file",
                        "status": "ok",
                        "text": "file content",
                    }
                },
            }
        ],
        runtime_assembly={
            "backend_dir": str(new_backend),
            "profile": {"mode": "professional"},
            "task_environment": {
                "environment_id": "env.test",
                "storage_space": {"runtime_state_root": "runtime_state"},
            },
            "operation_authorization": {"allowed_operations": ["op.read_file"]},
        },
    )

    assert result.packet.context_refs
    assert (new_backend / "runtime_state" / "dynamic_context" / "replacements").exists()
    assert not (old_backend / "runtime_state" / "dynamic_context" / "replacements").exists()


def test_prompt_segment_plan_can_enforce_dynamic_context_metadata() -> None:
    with pytest.raises(ValueError):
        build_prompt_segment_plan(
            packet_id="packet:missing-report",
            invocation_kind="task_execution",
            enforce_dynamic_context_reports=True,
            message_specs=[
                {
                    "role": "user",
                    "content": "Task execution current state\n{}",
                    "kind": "volatile_task_state",
                    "cache_role": "volatile",
                }
            ],
        )

    plan = build_prompt_segment_plan(
        packet_id="packet:with-report",
        invocation_kind="task_execution",
        enforce_dynamic_context_reports=True,
        message_specs=[
            {
                "role": "user",
                "content": "Task execution current state\n{}",
                "kind": "volatile_task_state",
                "cache_role": "volatile",
                "metadata": {
                    "dynamic_context_report_ref": "dynamic_context:task_execution:task_state",
                    "volatility_reason": "task state changes each step",
                },
            }
        ],
    )
    assert plan.segments[0].metadata["dynamic_context_report_ref"] == "dynamic_context:task_execution:task_state"


def test_dynamic_context_metadata_lookup_does_not_fallback_to_wrong_section() -> None:
    projection = DynamicContextProjection(
        section_reports=(
            VolatileSectionReport(
                section_id="dynamic_context:task_execution:runtime_delta",
                source="runtime_delta",
                volatility_reason="runtime delta changes by invocation",
            ),
        )
    )

    with pytest.raises(ValueError, match="execution_state"):
        _dynamic_context_segment_metadata(projection, source="execution_state")
