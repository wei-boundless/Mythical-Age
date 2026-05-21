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
    assert health_profile["validation_state"] in {"valid", "invalid"}


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

    assert preview["status"] in {"ready", "blocked"}
    assert "projection_instance" not in preview
    assert preview["task_execution_assembly"]["authority"] == "task_system.task_execution_assembly"
    assert preview["task_body_orchestration"]["authority"] == "orchestration.task_body_orchestration"
    assert preview["agent_runtime_spec"]["authority"] == "orchestration.agent_runtime_spec"
    if preview["status"] == "blocked":
        assert preview["reason"]


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
    assert "health" in connection.task_family_refs
    assert connection.default_flow_ref == "flow.health.issue_triage"
    assert connection.default_runtime_lane_hint == "health_issue_read"


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
            "runtime_lane": "full_interactive",
        }
    )

    assert session.agent_id == "agent:3"
    assert session.agent_profile_id == "health_maintainer_agent"
    assert session.workflow_id == "workflow.health.issue_triage"
    assert session.runtime_lane == "health_issue_read"


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
            runs = [
                item
                for item in HealthRegistry(runtime.base_dir).list_agent_runs()
                if item.issue_id == issue_id and item.metadata.get("runtime_execution_owner")
            ]
            assert runs
            run = runs[-1]
            assert run.agent_id == "agent:3"
            assert run.agent_profile_id == "health_maintainer_agent"
            assert run.metadata["runtime_execution_owner"] == "TaskRunLoop.run_single_agent_stream"
            trace = runtime.query_runtime.task_run_loop.get_trace(run.task_run_id, include_payloads=True)
            assert trace is not None
            events = trace["events"]
            assert any(item["event_type"] == "task_contract_built" for item in events)
            assert any(item["event_type"] == "stage_projection_built" for item in events)
            assert not any(
                str(dict(item.get("payload") or {}).get("source") or "").startswith("health_system.agent_run")
                for item in events
            )
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

    routed = registry._route_conversation_health_action(  # type: ignore[attr-defined]
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

    routed = registry._route_conversation_health_action(  # type: ignore[attr-defined]
        user_message="请帮我做修复验证，确认问题是不是已经消失",
        session=session,
    )

    assert routed == "fix_verification"


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


def test_health_verification_sync_is_explicit_and_read_only(tmp_path) -> None:
    from health_system.models import VerificationRun
    from health_system.verification_service import HealthVerificationService

    class _TestSystemService:
        def __init__(self) -> None:
            self.calls = 0

        def list_runs(self, *, limit: int = 20):
            self.calls += 1
            return [
                {
                    "run_id": "verification-run:sample",
                    "profile": "functional",
                    "status": "passed",
                    "output_dir": str(tmp_path / "output"),
                    "started_at": 1.0,
                    "ended_at": 2.0,
                    "summary": {"total": 1, "passed": 1, "failed": 0, "first_failure": ""},
                }
            ]

    service = HealthVerificationService(tmp_path, service=_TestSystemService())

    before = service.list_verification_runs(limit=10)
    synced = service.sync_verification_runs_from_test_system(limit=10)
    after = service.list_verification_runs(limit=10)

    assert before == []
    assert after == synced
    assert isinstance(synced[0], VerificationRun)


def test_runtime_loop_evidence_packet_prefers_delegation_metadata() -> None:
    from health_system.maintenance.test_system.runtime_loop_probe import runtime_loop_evidence_packet_from_turn_payload

    payload = {
        "runtime_loop_events": [
            {
                "event_type": "tool_call_requested",
                "task_run_id": "taskrun:evidence",
                "offset": 1,
                "payload": {
                    "action_request": {
                        "payload": {
                            "tool_name": "delegate_to_agent",
                        }
                    }
                },
            },
            {
                "event_type": "agent_delegation_requested",
                "task_run_id": "taskrun:evidence",
                "offset": 2,
                "payload": {
                    "agent_delegation_request": {
                        "target_agent_id": "agent:rag_analyst",
                        "delegation_kind": "evidence_lookup",
                    }
                },
            },
            {
                "event_type": "loop_terminal",
                "task_run_id": "taskrun:evidence",
                "offset": 3,
                "payload": {"status": "completed", "terminal_reason": "completed"},
            },
        ],
        "latest_checkpoint": {"checkpoint_id": "checkpoint-1", "loop_state": {"status": "running"}},
    }

    packet = runtime_loop_evidence_packet_from_turn_payload(payload, question="是否真的发生了子 Agent 委派？")
    selected_ids = [item["candidate_id"] for item in packet["selected_evidence"]]
    selected_metadata = [item.get("metadata") or {} for item in packet["selected_evidence"]]

    assert packet["authority"] == "health_system.evidence_packet"
    assert packet["summary"]
    assert any(item.get("tool_name") == "delegate_to_agent" for item in selected_metadata)
    assert any(
        item.get("target_agent_id") == "agent:rag_analyst" or item.get("delegation_kind") == "evidence_lookup"
        for item in selected_metadata
    )
