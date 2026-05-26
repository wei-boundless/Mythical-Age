from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.registry.agent_registry import AgentRegistry
from health_system import HealthRegistry
from task_system import TaskFlowRegistry

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app
from bootstrap.app_runtime import app_runtime
from fastapi.testclient import TestClient


async def _fake_health_executor_stream(
    *,
    user_message,
    model_messages,
    directive,
    tool_instances,
    model_stream_policy=None,
    model_spec=None,
):
    del model_messages, directive, tool_instances, model_stream_policy, model_spec
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
    assert response["receipt"]["status"] == "blocked"
    assert "health_agent_config_not_rebuilt" in response["receipt"]["blocked_reasons"]
    admission = dict(response["receipt"]["diagnostics"]["admission"])
    assert admission["agent_id"] == "agent:3"
    assert admission["task_execution_assembly_ref"] == ""
    assert admission["task_body_orchestration_ref"] == ""
    assert admission["runtime_spec_ref"] == ""


def test_task_system_no_longer_exposes_old_health_connection_profile(tmp_path) -> None:
    overview = TaskFlowRegistry(tmp_path).build_agent_task_connection_overview()

    assert overview["authority"] == "task_system.agent_task_connections"
    profiles = list(overview["profiles"])
    assert profiles
    assert not any(str(item.get("owner_system") or "") == "health" for item in profiles)
    assert not any(str(item.get("profile_id") or "").startswith("health.") for item in profiles)


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

    preview = registry.preview_agent_run(issue_id=issue.issue_id, health_action="issue_triage")

    assert preview["status"] == "blocked"
    assert "projection_instance" not in preview
    assert preview["reason"] == "health_agent_config_not_rebuilt"
    assert preview["task_execution_assembly"] == {}
    assert preview["task_body_orchestration"] == {}
    assert preview["agent_runtime_spec"] == {}


def test_health_system_rejects_old_test_launch_command(tmp_path) -> None:
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
        )
    )

    assert response["receipt"]["accepted"] is False
    assert response["receipt"]["status"] == "rejected"
    assert response["receipt"]["blocked_reasons"] == ["unsupported_command_type"]


def test_agent3_identity_remains_but_old_health_runtime_config_is_absent(tmp_path) -> None:
    agent_registry = AgentRegistry(tmp_path)
    profile = AgentRuntimeRegistry(tmp_path).get_profile("agent:3")
    agent = agent_registry.get_agent("agent:3")
    registry = TaskFlowRegistry(tmp_path)

    assert agent is not None
    assert agent.agent_id == "agent:3"
    assert profile is None
    assert registry.get_flow("flow.health.issue_triage") is None
    assert registry.get_specific_task_record("task.health.issue_triage") is None
    assert all(not item.workflow_id.startswith("workflow.health.") for item in registry.workflow_registry.list_workflows())


def test_health_conversation_session_uses_orchestration_config_not_payload_overrides(tmp_path) -> None:
    registry = HealthRegistry(tmp_path)
    issue = registry.create_issue(
        {
            "title": "健康会话配置边界",
            "owner_system": "health_system",
            "severity": "medium",
            "runtime_trace_refs": ["runtime-loop:test-session-config"],
        }
    )

    session = registry.create_conversation_session(
        {
            "active_issue_ref": issue.issue_id,
            "health_action": "issue_triage",
            "agent_id": "agent:0",
            "agent_profile_id": "main_interactive_agent",
            "workflow_id": "workflow.fake.override",
            "runtime_lane": "standard_task",
        }
    )

    assert session.agent_id == "agent:3"
    assert session.agent_profile_id == ""
    assert session.workflow_id == ""
    assert session.runtime_lane == ""


def test_health_conversation_message_fails_closed_until_agent_config_is_rebuilt() -> None:
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
            assert "运行时门禁拦截" in payload["assistant_message"]["content"]
            runs = [
                item
                for item in HealthRegistry(runtime.base_dir).list_agent_runs()
                if item.issue_id == issue_id and item.metadata.get("runtime_execution_owner")
            ]
            assert runs == []
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

    routed = registry._route_conversation_health_action(  # type: ignore[attr-defined]
        user_message="请分析一下这次运行链路和问题节点",
        session=session,
    )

    assert routed == "trace_analysis"


def test_health_store_reports_health_and_tolerates_bad_jsonl(tmp_path) -> None:
    from health_system.store import HealthStore

    store = HealthStore(tmp_path)
    store.issues_path.parent.mkdir(parents=True, exist_ok=True)
    store.issues_path.write_text('{"issue_id":"ok"}\n{bad json}\n', encoding="utf-8")

    issues = store.load_issues()
    health = store.store_health()

    assert len(issues) == 1
    assert health["authority"] == "health_system.store_health"
    assert health["bad_jsonl_line_count"] >= 1
    assert health["files"]["issues.jsonl"]["exists"] is True
