from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.graph.models import GraphHarnessConfig
from health_system.command_supervisor import HealthCommandSupervisor
from health_system.graph_breakpoint_command_supervisor import GraphBreakpointCommandSupervisor
from health_system.graph_breakpoint_supervisor import GraphBreakpointSupervisor
from health_system.registry import HealthRegistry
from task_system.repositories import GraphHarnessConfigRepository


def _runtime(tmp_path: Path):
    task_run = SimpleNamespace(
        task_run_id="taskrun:graph:001",
        session_id="session-graph-001",
        status="blocked",
        terminal_reason="model_action_protocol_repair_required",
        diagnostics={
            "graph_run_id": "grun:graph:001",
            "graph_id": "graph.writing.modular_novel.master",
            "graph_harness_config_id": "ghcfg:graph:001",
            "recoverable_error": {
                "error_code": "model_action_protocol_repair_required",
                "retryable": True,
                "detail": "missing final brace",
            },
            "parse_error_message": "Expecting ',' delimiter",
            "parse_error_line": 1,
            "parse_error_column": 2048,
        },
    )

    class StateIndexStub:
        def list_recent_task_runs(self, limit=200):
            assert limit >= 20
            return [task_run]

    class GraphHarnessStub:
        def __init__(self) -> None:
            self.resume_calls: list[dict[str, object]] = []
            self.run_until_idle_calls: list[dict[str, object]] = []

        def get_graph_run_health_monitor(self, graph_run_id: str):
            assert graph_run_id == "grun:graph:001"
            return {
                "graph_run": {
                    "graph_run_id": graph_run_id,
                    "graph_id": "graph.writing.modular_novel.master",
                    "config_id": "ghcfg:graph:001",
                    "status": "blocked",
                    "terminal_reason": "model_action_protocol_repair_required",
                },
                "task_run_monitor": {"status": "blocked"},
                "graph_loop_state": {
                    "status": "blocked",
                    "terminal_reason": "model_action_protocol_repair_required",
                    "blocked_node_ids": ["chapter_draft"],
                    "failed_node_ids": [],
                    "running_node_ids": [],
                },
                "active_node_runtime_views": [
                    {
                        "node_id": "chapter_draft",
                        "work_order_id": "gwork:001",
                        "work_order_summary": {"work_order_id": "gwork:001"},
                        "node_executor_task_run": {
                            "task_run_id": "taskrun:graphnode:001",
                            "terminal_reason": "model_action_protocol_repair_required",
                        },
                        "node_executor_task_run_monitor": {
                            "step": {"terminal_reason": "model_action_protocol_repair_required"}
                        },
                    }
                ],
            }

        def resume_run(self, *, graph_config, graph_run_id: str, dispatch_ready: bool = True, max_requests: int | None = None):
            self.resume_calls.append(
                {
                    "graph_config": graph_config,
                    "graph_run_id": graph_run_id,
                    "dispatch_ready": dispatch_ready,
                    "max_requests": max_requests,
                }
            )
            return SimpleNamespace(
                to_dict=lambda: {
                    "authority": "harness.graph_resume_result",
                    "graph_run_id": graph_run_id,
                    "resumed": True,
                    "reason": "blocked_nodes_requeued",
                    "graph_loop_state": {"status": "running", "blocked_node_ids": []},
                    "checkpoint": {"checkpoint_id": "gchk:test"},
                    "active_work_orders": [],
                    "node_work_orders": [],
                    "events": [],
                }
            )

        async def run_until_idle(
            self,
            *,
            graph_config,
            graph_run_id: str,
            max_node_executions: int = 64,
            max_loop_iterations: int = 128,
            max_node_steps: int = 12,
            max_dispatches: int = 64,
            max_runtime_seconds: float = 0.0,
            max_dispatch_requests: int | None = None,
        ):
            self.run_until_idle_calls.append(
                {
                    "graph_config": graph_config,
                    "graph_run_id": graph_run_id,
                    "max_node_executions": max_node_executions,
                    "max_loop_iterations": max_loop_iterations,
                    "max_node_steps": max_node_steps,
                    "max_dispatches": max_dispatches,
                    "max_runtime_seconds": max_runtime_seconds,
                    "max_dispatch_requests": max_dispatch_requests,
                }
            )
            return SimpleNamespace(
                to_dict=lambda: {
                    "authority": "harness.graph_run_runner",
                    "graph_run_id": graph_run_id,
                    "status": "idle",
                    "terminal_reason": "",
                    "executed_work_order_count": 1,
                    "accepted_result_count": 1,
                    "dispatch_count": 0,
                    "blocked_reason": "",
                    "budget_exhausted": False,
                    "graph_loop_state": {"status": "running", "blocked_node_ids": []},
                    "graph_result": {},
                    "active_node_work_orders": [],
                    "active_node_work_order_count": 0,
                    "events": [],
                }
            )

    graph_harness = GraphHarnessStub()
    return SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(state_index=StateIndexStub()),
            graph_harness=graph_harness,
        )
    )


def test_graph_breakpoint_supervisor_creates_health_issue(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    supervisor = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)

    result = supervisor.run_once()

    assert result["packet_count"] == 1
    assert result["command_count"] == 1
    registry = HealthRegistry(tmp_path)
    issues = [item for item in registry.list_issues() if item.source == "health_system.graph_breakpoint_poller"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.owner_system == "graph_runtime"
    assert issue.runtime_trace_refs[0] == "taskrun:graph:001"
    packet = dict(issue.metadata.get("graph_breakpoint_packet") or {})
    assert packet["graph_run_id"] == "grun:graph:001"
    assert packet["node_id"] == "chapter_draft"
    assert packet["terminal_reason"] == "model_action_protocol_repair_required"
    assert packet["parse_diagnostics"]["parse_error_message"] == "Expecting ',' delimiter"
    commands = registry.list_commands()
    assert len(commands) == 1
    command = commands[0]
    assert command.command_type == "analyze_trace"
    assert command.target_scope == "health_issue"
    assert command.target_ref == issue.issue_id
    assert command.health_action == "graph_breakpoint_diagnostics"
    assert command.status == "pending"
    assert command.payload["graph_breakpoint_fingerprint"] == packet["fingerprint"]
    assert command.payload["node_id"] == "chapter_draft"


def test_graph_breakpoint_supervisor_upserts_same_issue_id(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    supervisor = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)

    first = supervisor.run_once()
    second = supervisor.run_once()

    assert first["issue_ids"] == second["issue_ids"]
    assert first["command_ids"] == second["command_ids"]
    registry = HealthRegistry(tmp_path)
    issues = [item for item in registry.list_issues() if item.source == "health_system.graph_breakpoint_poller"]
    assert len(issues) == 1
    commands = registry.list_commands()
    assert len(commands) == 1


def test_graph_breakpoint_supervisor_keeps_one_command_when_work_order_changes(tmp_path: Path) -> None:
    task_run = SimpleNamespace(
        task_run_id="taskrun:graph:stable-command",
        session_id="session-graph-stable-command",
        status="running",
        terminal_reason="",
        diagnostics={
            "graph_run_id": "grun:graph:stable-command",
            "graph_id": "graph.writing.modular_novel.master",
            "graph_harness_config_id": "ghcfg:graph:stable-command",
        },
    )

    class StateIndexStub:
        def list_recent_task_runs(self, limit=200):
            return [task_run]

    class GraphHarnessStub:
        def __init__(self) -> None:
            self.work_order_id = "gwork:stable:001"

        def get_graph_run_health_monitor(self, graph_run_id: str):
            return _running_graph_monitor(
                graph_run_id=graph_run_id,
                config_id="ghcfg:graph:stable-command",
                work_order_id=self.work_order_id,
                executor_presence="missing",
            )

    graph_harness = GraphHarnessStub()
    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(state_index=StateIndexStub()),
            graph_harness=graph_harness,
        )
    )
    supervisor = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)

    first = supervisor.run_once()
    graph_harness.work_order_id = "gwork:stable:002"
    second = supervisor.run_once()

    registry = HealthRegistry(tmp_path)
    commands = registry.list_commands()
    assert len(commands) == 1
    assert first["command_ids"] == second["command_ids"]
    assert commands[0].payload["graph_breakpoint_recovery_key"] == (
        "grun:graph:stable-command|chapter_draft|active_work_order_executor_missing_after_restart|ghcfg:graph:stable-command"
    )


def test_graph_breakpoint_supervisor_detects_running_work_order_without_executor(tmp_path: Path) -> None:
    task_run = SimpleNamespace(
        task_run_id="taskrun:graph:running",
        session_id="session-graph-running",
        status="running",
        terminal_reason="",
        diagnostics={
            "graph_run_id": "grun:graph:running",
            "graph_id": "graph.writing.modular_novel.master",
            "graph_harness_config_id": "ghcfg:graph:running",
        },
    )

    class StateIndexStub:
        def list_recent_task_runs(self, limit=200):
            return [task_run]

    class GraphHarnessStub:
        def get_graph_run_health_monitor(self, graph_run_id: str):
            assert graph_run_id == "grun:graph:running"
            return {
                "graph_run": {
                    "graph_run_id": graph_run_id,
                    "graph_id": "graph.writing.modular_novel.master",
                    "config_id": "ghcfg:graph:running",
                    "status": "running",
                    "terminal_reason": "",
                },
                "task_run_monitor": {"status": "running"},
                "graph_loop_state": {
                    "status": "running",
                    "terminal_reason": "",
                    "blocked_node_ids": [],
                    "failed_node_ids": [],
                    "running_node_ids": ["chapter_draft"],
                    "node_states": {
                        "chapter_draft": {
                            "node_id": "chapter_draft",
                            "status": "running",
                            "work_order_id": "gwork:running",
                            "updated_at": 1.0,
                        }
                    },
                },
                "active_node_work_order_count": 1,
                "active_node_runtime_views": [
                    {
                        "node_id": "chapter_draft",
                        "status": "running",
                        "work_order_id": "gwork:running",
                        "work_order_summary": {"work_order_id": "gwork:running"},
                        "executor_presence": "missing",
                        "node_executor_task_run_id": "",
                        "node_executor_task_run": None,
                        "node_executor_task_run_monitor": None,
                    }
                ],
            }

    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(state_index=StateIndexStub()),
            graph_harness=GraphHarnessStub(),
        )
    )

    result = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    assert result["packet_count"] == 1
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    assert command.payload["terminal_reason"] == "active_work_order_executor_missing_after_restart"
    assert command.payload["recoverable_error"]["error_code"] == "active_work_order_executor_missing_after_restart"
    assert command.payload["work_order_id"] == "gwork:running"


def test_graph_breakpoint_supervisor_does_not_recover_present_executor(tmp_path: Path) -> None:
    task_run = SimpleNamespace(
        task_run_id="taskrun:graph:running-present",
        session_id="session-graph-running-present",
        status="running",
        terminal_reason="",
        diagnostics={
            "graph_run_id": "grun:graph:running-present",
            "graph_id": "graph.writing.modular_novel.master",
            "graph_harness_config_id": "ghcfg:graph:running-present",
        },
    )

    class StateIndexStub:
        def list_recent_task_runs(self, limit=200):
            return [task_run]

    class GraphHarnessStub:
        def get_graph_run_health_monitor(self, graph_run_id: str):
            return _running_graph_monitor(
                graph_run_id=graph_run_id,
                config_id="ghcfg:graph:running-present",
                work_order_id="gwork:running-present",
                executor_presence="present",
                node_executor_task_run_id="taskrun:graphnode:present",
                node_executor_task_run={"task_run_id": "taskrun:graphnode:present", "status": "running"},
                node_executor_task_run_monitor={"lifecycle": "running"},
            )

    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(state_index=StateIndexStub()),
            graph_harness=GraphHarnessStub(),
        )
    )

    result = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    assert result["packet_count"] == 0
    assert HealthRegistry(tmp_path).list_commands() == []


def test_graph_breakpoint_supervisor_does_not_recover_unknown_executor_presence(tmp_path: Path) -> None:
    task_run = SimpleNamespace(
        task_run_id="taskrun:graph:running-unknown",
        session_id="session-graph-running-unknown",
        status="running",
        terminal_reason="",
        diagnostics={
            "graph_run_id": "grun:graph:running-unknown",
            "graph_id": "graph.writing.modular_novel.master",
            "graph_harness_config_id": "ghcfg:graph:running-unknown",
        },
    )

    class StateIndexStub:
        def list_recent_task_runs(self, limit=200):
            return [task_run]

    class GraphHarnessStub:
        def get_graph_run_health_monitor(self, graph_run_id: str):
            return _running_graph_monitor(
                graph_run_id=graph_run_id,
                config_id="ghcfg:graph:running-unknown",
                work_order_id="gwork:running-unknown",
                executor_presence="unknown",
            )

    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(state_index=StateIndexStub()),
            graph_harness=GraphHarnessStub(),
        )
    )

    result = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    assert result["packet_count"] == 0
    assert HealthRegistry(tmp_path).list_commands() == []


def _running_graph_monitor(
    *,
    graph_run_id: str,
    config_id: str,
    work_order_id: str,
    executor_presence: str,
    node_executor_task_run_id: str = "",
    node_executor_task_run: dict[str, object] | None = None,
    node_executor_task_run_monitor: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "graph_run": {
            "graph_run_id": graph_run_id,
            "graph_id": "graph.writing.modular_novel.master",
            "config_id": config_id,
            "status": "running",
            "terminal_reason": "",
        },
        "task_run_monitor": {"status": "running"},
        "graph_loop_state": {
            "status": "running",
            "terminal_reason": "",
            "blocked_node_ids": [],
            "failed_node_ids": [],
            "running_node_ids": ["chapter_draft"],
            "node_states": {
                "chapter_draft": {
                    "node_id": "chapter_draft",
                    "status": "running",
                    "work_order_id": work_order_id,
                    "updated_at": 1.0,
                }
            },
        },
        "active_node_work_order_count": 1,
        "active_node_runtime_views": [
            {
                "node_id": "chapter_draft",
                "status": "running",
                "work_order_id": work_order_id,
                "work_order_summary": {"work_order_id": work_order_id},
                "executor_presence": executor_presence,
                "node_executor_task_run_id": node_executor_task_run_id,
                "node_executor_task_run": node_executor_task_run,
                "node_executor_task_run_monitor": node_executor_task_run_monitor,
            }
        ],
    }


def test_graph_breakpoint_supervisor_detects_budget_exhausted_live_work_order(tmp_path: Path) -> None:
    task_run = SimpleNamespace(
        task_run_id="taskrun:graph:budget",
        session_id="session-graph-budget",
        status="waiting_executor",
        terminal_reason="max_node_executions_exhausted",
        diagnostics={
            "graph_run_id": "grun:graph:budget",
            "graph_id": "graph.writing.modular_novel.master",
            "graph_harness_config_id": "ghcfg:graph:budget",
        },
    )

    class StateIndexStub:
        def list_recent_task_runs(self, limit=200):
            return [task_run]

    class GraphHarnessStub:
        def get_graph_run_health_monitor(self, graph_run_id: str):
            assert graph_run_id == "grun:graph:budget"
            return {
                "graph_run": {
                    "graph_run_id": graph_run_id,
                    "graph_id": "graph.writing.modular_novel.master",
                    "config_id": "ghcfg:graph:budget",
                    "status": "budget_exhausted",
                    "terminal_reason": "max_node_executions_exhausted",
                },
                "task_run_monitor": {"status": "waiting_executor"},
                "graph_loop_state": {
                    "status": "running",
                    "terminal_reason": "",
                    "blocked_node_ids": [],
                    "failed_node_ids": [],
                    "running_node_ids": ["chapter_draft"],
                    "node_states": {
                        "chapter_draft": {
                            "node_id": "chapter_draft",
                            "status": "running",
                            "work_order_id": "gwork:budget",
                            "updated_at": 1.0,
                        }
                    },
                },
                "active_node_work_order_count": 1,
                "active_node_runtime_views": [
                    {
                        "node_id": "chapter_draft",
                        "status": "running",
                        "work_order_id": "gwork:budget",
                        "work_order_summary": {"work_order_id": "gwork:budget"},
                        "executor_presence": "missing",
                        "node_executor_task_run_id": "",
                        "node_executor_task_run": None,
                        "node_executor_task_run_monitor": None,
                    }
                ],
            }

    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=SimpleNamespace(state_index=StateIndexStub()),
            graph_harness=GraphHarnessStub(),
        )
    )

    result = GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    assert result["packet_count"] == 1
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    assert command.payload["graph_status"] == "budget_exhausted"
    assert command.payload["terminal_reason"] == "active_work_order_executor_missing_after_restart"
    assert command.payload["work_order_id"] == "gwork:budget"


def test_graph_breakpoint_command_supervisor_auto_resumes_recoverable_command(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    supervisor = GraphBreakpointCommandSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)
    supervisor._resolve_graph_config = lambda payload: SimpleNamespace(config_id=payload["graph_harness_config_id"])  # type: ignore[method-assign]

    result = asyncio.run(supervisor.run_once())

    assert result["processed_count"] == 1
    assert result["resumed_count"] == 1
    assert result["pumped_count"] == 0
    resume_calls = runtime.harness_runtime.graph_harness.resume_calls
    assert len(resume_calls) == 1
    assert resume_calls[0]["graph_run_id"] == "grun:graph:001"
    assert runtime.harness_runtime.graph_harness.run_until_idle_calls == []
    registry = HealthRegistry(tmp_path)
    commands = registry.list_commands()
    assert len(commands) == 1
    assert commands[0].status == "completed"
    receipts = registry.list_receipts()
    assert receipts
    assert receipts[-1].accepted is True
    assert receipts[-1].diagnostics["verdict"]["recommended_action"] == "resume_graph_run"
    assert receipts[-1].diagnostics["resume_result"]["reason"] == "blocked_nodes_requeued"
    assert "pump_result" not in receipts[-1].diagnostics
    reports = registry.list_reports()
    assert reports
    assert "短恢复" in reports[-1].summary


def test_graph_breakpoint_command_supervisor_observes_active_work_after_resume(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    def resume_with_active_work(**kwargs):
        runtime.harness_runtime.graph_harness.resume_calls.append(dict(kwargs))
        return SimpleNamespace(
            to_dict=lambda: {
                "authority": "harness.graph_resume_result",
                "graph_run_id": kwargs["graph_run_id"],
                "resumed": True,
                "reason": "active_work_orders_reconnected",
                "graph_loop_state": {
                    "status": "running",
                    "ready_node_ids": [],
                    "running_node_ids": ["chapter_draft"],
                    "blocked_node_ids": [],
                },
                "active_work_orders": [{"node_id": "chapter_draft", "work_order_id": "gwork:next"}],
                "active_node_work_order_count": 1,
            }
        )

    runtime.harness_runtime.graph_harness.resume_run = resume_with_active_work
    supervisor = GraphBreakpointCommandSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)
    supervisor._resolve_graph_config = lambda payload: SimpleNamespace(config_id=payload["graph_harness_config_id"])  # type: ignore[method-assign]

    result = asyncio.run(supervisor.run_once())

    assert result["processed_count"] == 1
    assert result["continued_count"] == 0
    assert result["observing_count"] == 1
    assert runtime.harness_runtime.graph_harness.run_until_idle_calls == []
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    assert command.status == "observing"
    assert "recovery_observing_report_ref" in command.payload
    receipts = registry.list_receipts()
    assert receipts[-1].status == "observing"
    assert receipts[-1].run_status == "observing"
    assert receipts[-1].diagnostics["continued"] is False
    assert receipts[-1].diagnostics["observing"] is True
    assert receipts[-1].diagnostics["resume_result"]["reason"] == "active_work_orders_reconnected"
    assert "pump_result" not in receipts[-1].diagnostics
    reports = registry.list_reports()
    assert reports[-1].verdict == "observing"
    assert "转为观察" in reports[-1].summary


def test_graph_breakpoint_command_supervisor_classifies_graph_config_mismatch(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    def resume_with_config_mismatch(**kwargs):
        runtime.harness_runtime.graph_harness.resume_calls.append(dict(kwargs))
        raise ValueError("GraphRun structure_hash does not match GraphHarnessConfig")

    runtime.harness_runtime.graph_harness.resume_run = resume_with_config_mismatch
    supervisor = GraphBreakpointCommandSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)
    supervisor._resolve_graph_config = lambda payload: SimpleNamespace(config_id=payload["graph_harness_config_id"])  # type: ignore[method-assign]

    result = asyncio.run(supervisor.run_once())

    assert result["resumed_count"] == 1
    assert result["continued_count"] == 0
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    assert command.status == "completed"
    receipts = registry.list_receipts()
    assert receipts[-1].accepted is True
    assert receipts[-1].run_status == "blocked"
    assert receipts[-1].diagnostics["recovery_failure_kind"] == "graph_config_snapshot_mismatch"
    reports = registry.list_reports()
    assert reports[-1].verdict == "completed"
    assert "配置快照" in reports[-1].summary
    assert "inspect_graph_config_snapshot" in reports[-1].recommended_actions


def test_graph_breakpoint_command_supervisor_does_not_fallback_to_published_for_existing_run(tmp_path: Path) -> None:
    GraphHarnessConfigRepository(tmp_path).upsert(
        GraphHarnessConfig(
            config_id="ghcfg:published",
            graph_id="graph.test.snapshot",
            graph_title="Snapshot Test",
            publish_version="published",
            nodes=({"node_id": "node", "node_type": "agent", "title": "node"},),
        ).with_content_identity(config_id="ghcfg:published"),
        publish=True,
    )
    supervisor = GraphBreakpointCommandSupervisor(base_dir=tmp_path, runtime=_runtime(tmp_path), poll_interval_seconds=2.0)

    with pytest.raises(ValueError, match="graph_config_snapshot_missing"):
        supervisor._resolve_graph_config(
            {
                "graph_run_id": "grun:old",
                "graph_id": "graph.test.snapshot",
                "graph_harness_config_id": "",
            }
        )


def test_graph_breakpoint_command_supervisor_waits_when_prompt_catalog_unavailable(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    def resume_with_prompt_catalog_error(**kwargs):
        runtime.harness_runtime.graph_harness.resume_calls.append(dict(kwargs))
        raise RuntimeError(
            "Worker prompt template resources missing from prompt_library/resources: worker.prompt.review"
        )

    runtime.harness_runtime.graph_harness.resume_run = resume_with_prompt_catalog_error
    supervisor = GraphBreakpointCommandSupervisor(
        base_dir=tmp_path,
        runtime=runtime,
        poll_interval_seconds=2.0,
        retryable_failure_cooldown_seconds=5.0,
    )
    supervisor._resolve_graph_config = lambda payload: SimpleNamespace(config_id=payload["graph_harness_config_id"])  # type: ignore[method-assign]

    result = asyncio.run(supervisor.run_once())

    assert result["processed_count"] == 1
    assert result["continued_count"] == 0
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    assert command.status == "pending"
    assert command.payload["recovery_last_run_status"] == "waiting_runtime_resource"
    assert command.payload["recovery_next_allowed_at"] > 0
    receipts = registry.list_receipts()
    assert receipts[-1].accepted is True
    assert receipts[-1].status == "pending"
    assert receipts[-1].run_status == "waiting_runtime_resource"
    assert receipts[-1].diagnostics["recovery_failure_kind"] == "runtime_prompt_catalog_unavailable"
    assert receipts[-1].diagnostics["retry_later"] is True
    reports = registry.list_reports()
    assert reports[-1].verdict == "continuing"
    assert "inspect_prompt_catalog" in reports[-1].recommended_actions


def test_graph_breakpoint_command_supervisor_waits_when_graph_runner_is_active(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    def resume_with_runner_busy(**kwargs):
        runtime.harness_runtime.graph_harness.resume_calls.append(dict(kwargs))
        raise ValueError("Graph operation resume_run rejected: graph_run_runner_already_active")

    runtime.harness_runtime.graph_harness.resume_run = resume_with_runner_busy
    supervisor = GraphBreakpointCommandSupervisor(
        base_dir=tmp_path,
        runtime=runtime,
        poll_interval_seconds=2.0,
        retryable_failure_cooldown_seconds=5.0,
    )
    supervisor._resolve_graph_config = lambda payload: SimpleNamespace(config_id=payload["graph_harness_config_id"])  # type: ignore[method-assign]

    result = asyncio.run(supervisor.run_once())

    assert result["processed_count"] == 1
    assert result["continued_count"] == 0
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    assert command.status == "pending"
    assert command.payload["recovery_last_run_status"] == "waiting_runtime_resource"
    receipts = registry.list_receipts()
    assert receipts[-1].accepted is True
    assert receipts[-1].status == "pending"
    assert receipts[-1].diagnostics["recovery_failure_kind"] == "graph_runner_active"
    assert receipts[-1].diagnostics["retry_later"] is True
    reports = registry.list_reports()
    assert reports[-1].verdict == "continuing"
    assert "wait_active_graph_runner" in reports[-1].recommended_actions
    assert "inspect_prompt_catalog" not in reports[-1].recommended_actions


def test_graph_breakpoint_command_supervisor_resumes_protocol_repair_signature_with_extra_errors(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()
    registry = HealthRegistry(tmp_path)
    command = registry.list_commands()[0]
    command.payload["recoverable_error"] = {
        "error_code": "model_action_invalid",
        "retryable": True,
        "validation_errors": [
            "action_type_unsupported:",
            "public_progress_note_required",
            "public_action_state_required",
        ],
    }
    command.payload["task_status"] = "waiting_executor"
    registry.store.upsert_command(command)

    supervisor = GraphBreakpointCommandSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0)
    supervisor._resolve_graph_config = lambda payload: SimpleNamespace(config_id=payload["graph_harness_config_id"])  # type: ignore[method-assign]

    result = asyncio.run(supervisor.run_once())

    assert result["resumed_count"] == 1
    assert result["pumped_count"] == 0
    resume_calls = runtime.harness_runtime.graph_harness.resume_calls
    assert len(resume_calls) == 1
    assert runtime.harness_runtime.graph_harness.run_until_idle_calls == []
    receipts = registry.list_receipts()
    assert receipts[-1].diagnostics["verdict"]["recommended_action"] == "resume_graph_run"
    assert receipts[-1].diagnostics["verdict"]["problem_type"] == "runtime_recoverable"


def test_health_command_supervisor_ignores_graph_breakpoint_command(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    GraphBreakpointSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()

    result = asyncio.run(
        HealthCommandSupervisor(base_dir=tmp_path, runtime=runtime, poll_interval_seconds=2.0).run_once()
    )

    assert result["processed_count"] == 0
    registry = HealthRegistry(tmp_path)
    commands = registry.list_commands()
    assert len(commands) == 1
    assert commands[0].status == "pending"
    assert registry.list_receipts() == []
    assert registry.list_reports() == []
