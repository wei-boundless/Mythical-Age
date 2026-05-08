from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from health_system import HealthRegistry
from orchestration import AgentRuntimeRegistry
from orchestration import AgentRegistry
from tasks import TaskFlowRegistry

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from bootstrap.app_runtime import app_runtime
from fastapi.testclient import TestClient


class FakeTestSystemService:
    def start(self, profile: str, scenario_ids: list[str]) -> dict[str, object]:
        return {
            "run_id": "test-run:fake-health",
            "profile": profile,
            "status": "running",
            "output_dir": "storage/test-runs/test-run:fake-health",
            "log_path": "storage/test-runs/test-run:fake-health/run.log",
            "started_at": 1.0,
            "ended_at": 0.0,
            "scenario_ids": scenario_ids,
        }


async def _fake_health_executor_stream(*, user_message, model_messages, directive, tool_instances):
    del model_messages, directive, tool_instances
    yield {"type": "answer_candidate", "content": f"健康分析已收到：{user_message}"}
    yield {"type": "done", "content": f"健康分析已收到：{user_message}"}


def test_health_report_issue_command_creates_receipt_report_and_issue(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)

    response = asyncio.run(
        registry.submit_command(
            {
                "command_id": "health-command:test-report-issue",
                "command_type": "report_issue",
                "initiator_type": "user",
                "source": "regression",
                "payload": {
                    "title": "回归测试健康问题",
                    "owner_system": "health_system",
                    "severity": "medium",
                    "runtime_trace_refs": ["runtime-loop:test"],
                },
            }
        )
    )

    assert response["receipt"]["accepted"] is True
    assert response["receipt"]["health_issue_ref"]
    assert response["receipt"]["report_ref"]
    assert registry.get_command("health-command:test-report-issue") is not None
    assert registry.get_report(response["receipt"]["report_ref"]) is not None


def test_health_command_admission_rejects_blocked_operation(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)

    response = asyncio.run(
        registry.submit_command(
            {
                "command_id": "health-command:test-blocked-operation",
                "command_type": "analyze_trace",
                "initiator_type": "agent",
                "initiator_ref": "agent:3",
                "target_scope": "health_issue",
                "target_ref": "health:issue:sample-task-system-chain",
                "task_mode": "issue_triage",
                "payload": {"requested_operations": ["op.write_file"]},
            }
        )
    )

    assert response["receipt"]["accepted"] is False
    assert response["receipt"]["status"] == "rejected"
    assert "operation_blocked:op.write_file" in response["receipt"]["blocked_reasons"]
    admission = dict(response["receipt"]["diagnostics"]["admission"])
    assert admission["task_execution_assembly_ref"].startswith("taskasm:")
    assert admission["task_body_orchestration_ref"].startswith("orchestration:")
    assert admission["runtime_spec_ref"].startswith("rtspec:")


def test_task_system_exposes_generic_agent_task_connection_profile(tmp_path) -> None:
    overview = TaskFlowRegistry(tmp_path).build_agent_task_connection_overview(task_family="health")
    profiles = overview["profiles"]
    health_profile = next(item for item in profiles if item["agent_id"] == "agent:3")

    assert overview["authority"] == "task_system.agent_task_connections"
    assert health_profile["owner_system"] == "health_system"
    assert "flow.health.issue_triage" in health_profile["flow_refs"]
    assert "workflow.health.issue_triage" in health_profile["workflow_refs"]
    assert health_profile["validation_state"] == "valid"


def test_health_agent_run_preview_does_not_expose_projection_instance(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)
    issue = registry.create_issue(
        {
            "title": "健康系统预览边界测试",
            "owner_system": "health_system",
            "severity": "medium",
            "runtime_trace_refs": ["runtime-loop:test"],
        }
    )

    preview = registry.preview_agent_run(issue_id=issue.issue_id, task_mode="issue_triage")

    assert preview["status"] == "ready"
    assert "projection_instance" not in preview
    assert preview["task_execution_assembly"]["authority"] == "task_system.task_execution_assembly"
    assert preview["task_body_orchestration"]["authority"] == "orchestration.task_body_orchestration"
    assert preview["agent_runtime_spec"]["authority"] == "orchestration.agent_runtime_spec"


def test_launch_health_test_command_records_health_test_run(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)

    response = asyncio.run(
        registry.submit_command(
            {
                "command_id": "health-command:test-launch-health-test",
                "command_type": "launch_health_test",
                "initiator_type": "user",
                "payload": {
                    "profile": "functional",
                    "scenario_refs": ["health-scenario:static-contract"],
                },
            },
            test_system_service=FakeTestSystemService(),
        )
    )

    assert response["receipt"]["accepted"] is True
    assert response["receipt"]["test_run_ref"] == "test-run:fake-health"
    assert registry.list_health_test_runs()[0].scenario_refs == ("health-scenario:static-contract",)


def test_default_health_management_agent_configuration_is_bound_and_guarded(tmp_path) -> None:
    agent_registry = AgentRegistry(tmp_path)
    profile = AgentRuntimeRegistry(tmp_path).get_profile("agent:3")
    connection = next(
        item
        for item in TaskFlowRegistry(tmp_path).list_agent_task_connection_profiles()
        if item.agent_id == "agent:3"
    )

    assert profile is not None
    assert "op.write_file" in profile.blocked_operations
    assert "issue_triage" in connection.available_task_modes
    assert connection.default_runtime_lane_hint == "health_issue_read"


def test_health_conversation_message_returns_real_assistant_reply() -> None:
    with TestClient(app) as client:
        runtime = app_runtime.require_ready()
        original_stream = runtime.query_runtime.model_response_executor.stream
        runtime.query_runtime.model_response_executor.stream = _fake_health_executor_stream  # type: ignore[method-assign]
        try:
            issue = client.post(
                "/api/health-system/issues",
                json={
                    "title": "健康对话真实执行回归",
                    "owner_system": "health_system",
                    "severity": "medium",
                    "runtime_trace_refs": ["runtime-loop:test-health-conversation"],
                },
            )
            assert issue.status_code == 200
            issue_id = issue.json()["issue_id"]

            session = client.post(
                "/api/health-system/conversation-sessions",
                json={"active_issue_ref": issue_id},
            )
            assert session.status_code == 200
            session_id = session.json()["session"]["session_id"]

            response = client.post(
                f"/api/health-system/conversation-sessions/{session_id}/messages",
                json={"role": "user", "content": "请分析这个问题"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["message"]["role"] == "user"
            assert payload["assistant_message"]["role"] == "assistant"
            assert "请分析这个问题" in payload["assistant_message"]["content"]
        finally:
            runtime.query_runtime.model_response_executor.stream = original_stream  # type: ignore[method-assign]


def test_health_conversation_without_bound_issue_returns_block_message() -> None:
    with TestClient(app) as client:
        session = client.post("/api/health-system/conversation-sessions", json={})
        assert session.status_code == 200
        session_id = session.json()["session"]["session_id"]

        response = client.post(
            f"/api/health-system/conversation-sessions/{session_id}/messages",
            json={"role": "user", "content": "帮我看看"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["assistant_message"]["role"] == "assistant"
        assert "还没有绑定健康问题" in payload["assistant_message"]["content"]


def test_health_conversation_routes_trace_analysis_mode() -> None:
    registry = HealthRegistry(BACKEND_DIR)
    issue = registry.create_issue(
        {
            "title": "健康会话链路分析路由",
            "owner_system": "health_system",
            "severity": "medium",
            "runtime_trace_refs": ["runtime-loop:test-trace-route"],
        }
    )
    session = registry.create_conversation_session({"active_issue_ref": issue.issue_id})

    routed = registry._route_conversation_task_mode(  # type: ignore[attr-defined]
        user_message="请分析一下这次运行链路和问题节点",
        session=session,
    )

    assert routed == "trace_analysis"


def test_health_conversation_routes_case_draft_mode() -> None:
    registry = HealthRegistry(BACKEND_DIR)
    issue = registry.create_issue(
        {
            "title": "健康会话用例草案路由",
            "owner_system": "health_system",
            "severity": "medium",
            "runtime_trace_refs": ["runtime-loop:test-case-route"],
        }
    )
    session = registry.create_conversation_session({"active_issue_ref": issue.issue_id})

    routed = registry._route_conversation_task_mode(  # type: ignore[attr-defined]
        user_message="帮我整理一个复现用例草案，顺便列断言",
        session=session,
    )

    assert routed == "case_draft"


def test_health_conversation_routes_fix_verification_mode() -> None:
    registry = HealthRegistry(BACKEND_DIR)
    issue = registry.create_issue(
        {
            "title": "健康会话修复验证路由",
            "owner_system": "health_system",
            "severity": "medium",
            "runtime_trace_refs": ["runtime-loop:test-fix-route"],
        }
    )
    session = registry.create_conversation_session({"active_issue_ref": issue.issue_id})

    routed = registry._route_conversation_task_mode(  # type: ignore[attr-defined]
        user_message="请帮我做修复验证，确认问题是不是已经消失",
        session=session,
    )

    assert routed == "fix_verification"
