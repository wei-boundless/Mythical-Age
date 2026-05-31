from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.runtime.compiler import RuntimeCompiler, _dynamic_context_segment_metadata
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
    assert volatile_payload["execution_state"]["pending_user_steers"][0]["steer_id"] == "steer:1"
    assert "large_internal_blob" not in json.dumps(volatile_payload, ensure_ascii=False)
    assert volatile_payload["observations"]["latest_observations"][0]["tool_result"]["tool_name"] == "read_file"
    assert packet.artifact_refs == ("artifacts/file.txt",)


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
            "model_visible_history": [
                {
                    "title": "初始化",
                    "status": "completed",
                    "summary": "已创建基础文件",
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
    assert volatile_payload["work_history"]["recent_steps"][0]["summary"] == "已创建基础文件"


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
