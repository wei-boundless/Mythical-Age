from __future__ import annotations

import sys
import asyncio
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definition_map
from harness.agent_control.controller import SubagentControl
from harness.runtime.assembly import assemble_runtime
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.runtime_object_store import RuntimeObjectStore
from runtime.shared.models import AgentRun, TaskRun


class _FakeEvent:
    def __init__(self, task_run_id: str, event_type: str, payload: dict[str, object] | None = None, refs: dict[str, str] | None = None) -> None:
        self.created_at = time.time()
        self.offset = 0
        self.task_run_id = task_run_id
        self.event_type = event_type
        self.payload = payload or {}
        self.refs = refs or {}


class _FakeEventLog:
    def __init__(self) -> None:
        self.events: list[_FakeEvent] = []

    def append(self, task_run_id: str, event_type: str, payload: dict[str, object] | None = None, refs: dict[str, str] | None = None) -> _FakeEvent:
        event = _FakeEvent(task_run_id, event_type, payload, refs)
        event.offset = len(self.events)
        self.events.append(event)
        return event


def test_main_profile_exposes_subagent_policy_and_tools() -> None:
    backend_dir = BACKEND_DIR
    profile = AgentRuntimeRegistry(backend_dir).get_profile("agent:0")
    assert profile is not None
    assert profile.subagent_policy.enabled is True
    assert "agent:knowledge_searcher" in profile.subagent_policy.allowed_subagent_ids

    definitions = get_tool_definition_map()
    instances = build_tool_instances(backend_dir)
    build_tool_authorization_index(tuple(definitions.values()))
    assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-1",
        turn_id="turn-1",
        agent_invocation_id="inv-1",
        request_task_selection={"runtime_mode": "standard", "runtime_profile": {"mode": "standard"}},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=instances,
        definitions_by_name=definitions,
    )
    assert "spawn_subagent" in assembly.tool_names
    assert "send_subagent_message" in assembly.tool_names


def test_subagent_control_lifecycle_roundtrip() -> None:
    asyncio.run(_subagent_control_lifecycle_roundtrip())


async def _subagent_control_lifecycle_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = RuntimeStateIndex(root)
        task = TaskRun(task_run_id="tr1", session_id="s1", task_id="task1")
        state.upsert_task_run(task)
        parent = AgentRun(agent_run_id="ag1", task_run_id="tr1", agent_id="agent:0", agent_profile_id="main_interactive_agent", status="running")
        state.upsert_agent_run(parent)
        host = type("Host", (), {"backend_dir": root, "state_index": state, "event_log": _FakeEventLog()})()
        controller = SubagentControl(host)
        assembly = {
            "profile": {
                "subagent_policy": {
                    "enabled": True,
                    "allowed_subagent_ids": ["agent:knowledge_searcher"],
                    "max_subagent_runs_per_task": 2,
                    "max_active_subagents": 1,
                    "context_policy": "summary_and_refs_only",
                    "result_policy": "observation_refs_only",
                }
            }
        }
        spawned = await controller.spawn_subagent(
            task_run=task,
            parent_agent_run=parent,
            runtime_assembly=assembly,
            target_agent_id="agent:knowledge_searcher",
            goal="查找资料",
            instructions="只返回引用",
            context_refs=["ref1"],
            expected_outputs=["summary"],
        )
        assert spawned["ok"] is True
        child_task = state.get_task_run(spawned["subtask_run_ref"])
        assert child_task is not None
        assert child_task.status == "waiting_executor"
        assert child_task.execution_runtime_kind == "subagent_task"
        child_ref = spawned["subagent_run_ref"]
        listed = await controller.list_subagents(task_run=task, parent_agent_run=parent)
        assert listed["count"] == 1
        waited = await controller.wait(task_run=task, parent_agent_run=parent, subagent_run_ref=child_ref)
        assert waited["ok"] is True
        assert waited["no_update"] is False or waited["status"] in {"pending", "running", "completed"}
        await asyncio.sleep(0.05)
        closed = await controller.close(task_run=task, parent_agent_run=parent, subagent_run_ref=child_ref, reason="done")
        assert closed["ok"] is True
        assert closed["status"] in {"completed", "killed"}


def test_subagent_control_background_execution_roundtrip() -> None:
    asyncio.run(_subagent_control_background_execution_roundtrip())


async def _subagent_control_background_execution_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = RuntimeStateIndex(root)
        runtime_objects = RuntimeObjectStore(root)
        task = TaskRun(task_run_id="tr2", session_id="s1", task_id="task2")
        state.upsert_task_run(task)
        parent = AgentRun(agent_run_id="ag2", task_run_id="tr2", agent_id="agent:0", agent_profile_id="main_interactive_agent", status="running")
        state.upsert_agent_run(parent)

        async def _execute_task_run(task_run_id: str, *, max_steps: int = 12):
            current = state.get_task_run(task_run_id)
            assert current is not None
            runs = state.list_task_agent_runs(task_run_id)
            assert runs
            child = runs[0]
            state.upsert_agent_run(
                replace(
                    child,
                    status="running",
                    updated_at=time.time(),
                )
            )
            state.upsert_agent_run(
                replace(
                    child,
                    status="completed",
                    result_ref=runtime_objects.put_object(
                        "agent_run_result",
                        f"{child.agent_run_id}:result",
                        {
                            "final_answer": "子 agent 搜索完成： https://github.com/example/project",
                            "artifact_refs": [{"path": "storage/task_environments/research/web/artifacts/report.md"}],
                            "observation_refs": ["rtobs:child:1"],
                        },
                    ),
                    updated_at=time.time(),
                )
            )
            state.upsert_task_run(
                replace(
                    current,
                    status="completed",
                    terminal_reason="completed",
                    updated_at=time.time(),
                )
            )
            return {"ok": True, "task_run_id": task_run_id, "max_steps": max_steps}

        host = type("Host", (), {"backend_dir": root, "state_index": state, "event_log": _FakeEventLog(), "runtime_objects": runtime_objects})()
        services = type("Services", (), {"execute_task_run_callback": _execute_task_run})()
        controller = SubagentControl(host, services=services)
        assembly = {
            "profile": {
                "subagent_policy": {
                    "enabled": True,
                    "allowed_subagent_ids": ["agent:knowledge_searcher"],
                    "max_subagent_runs_per_task": 2,
                    "max_active_subagents": 1,
                    "context_policy": "summary_and_refs_only",
                    "result_policy": "observation_refs_only",
                }
            }
        }
        spawned = await controller.spawn_subagent(
            task_run=task,
            parent_agent_run=parent,
            runtime_assembly=assembly,
            target_agent_id="agent:knowledge_searcher",
            goal="查找资料",
            instructions="只返回引用",
            context_refs=["ref1"],
            expected_outputs=["summary"],
        )
        child_ref = spawned["subagent_run_ref"]
        listed = await _wait_for_subagent_state(controller, task=task, parent=parent, desired_status="completed")
        assert listed["count"] == 1
        assert listed["subagents"][0]["status"] == "completed"
        waited = await controller.wait(task_run=task, parent_agent_run=parent, subagent_run_ref=child_ref)
        assert waited["ok"] is True
        assert waited["status"] == "completed"
        assert waited["no_update"] is False
        assert waited["messages"]
        assert waited["result_available"] is True
        assert waited["result"]["final_answer"] == "子 agent 搜索完成： https://github.com/example/project"
        assert waited["result"]["artifact_refs"] == [{"path": "storage/task_environments/research/web/artifacts/report.md"}]


async def _wait_for_subagent_state(
    controller: SubagentControl,
    *,
    task: TaskRun,
    parent: AgentRun,
    desired_status: str,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    latest: dict[str, object] = {"count": 0, "subagents": []}
    while time.time() < deadline:
        latest = await controller.list_subagents(task_run=task, parent_agent_run=parent)
        subagents = list(latest.get("subagents") or [])
        if subagents and str(subagents[0].get("status") or "") == desired_status:
            return latest
        await asyncio.sleep(0.05)
    return latest
