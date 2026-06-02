from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.models import AgentRun, TaskRun
from runtime.shared.runtime_object_store import RuntimeObjectStore
from harness.agent_control.controller import SubagentControl
from harness.loop.specialist_runtime_router import SpecialistRuntimeExecution, SpecialistRuntimeRouter
from harness.loop.task_executor import _finish_specialist_runtime_execution
from harness.runtime.services import TaskExecutorServices


class _FakeEvent:
    def __init__(self, task_run_id: str, event_type: str, payload: dict | None = None, refs: dict | None = None) -> None:
        self.created_at = time.time()
        self.offset = 0
        self.task_run_id = task_run_id
        self.event_type = event_type
        self.payload = payload or {}
        self.refs = refs or {}

    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "offset": self.offset,
            "task_run_id": self.task_run_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "refs": self.refs,
        }


class _FakeEventLog:
    def __init__(self) -> None:
        self.events: list[_FakeEvent] = []

    def append(self, task_run_id: str, event_type: str, payload: dict | None = None, refs: dict | None = None) -> _FakeEvent:
        event = _FakeEvent(task_run_id, event_type, payload, refs)
        event.offset = len(self.events)
        self.events.append(event)
        return event

    def list_events(self, task_run_id: str) -> list[_FakeEvent]:
        return [event for event in self.events if event.task_run_id == task_run_id]


class _FakeCapability:
    def __init__(self, *, status: str = "completed") -> None:
        self.status = status
        self.calls: list[dict] = []

    async def run(self, *, request, agent, profile, config) -> dict:
        self.calls.append(
            {
                "request": request,
                "agent": agent,
                "profile": profile,
                "config": config,
            }
        )
        return {
            "status": self.status,
            "summary": f"{request.target_agent_id} handled {request.input_payload['query']}",
            "answer_candidate": f"{request.target_agent_id} handled {request.input_payload['query']}",
            "evidence_refs": ["evidence:1"],
            "artifact_refs": [{"path": "artifact:report"}],
            "limitations": [],
            "diagnostics": {"capability_id": "capability.fake"},
        }


def _profile(agent_id: str):
    profiles = {profile.agent_id: profile for profile in default_agent_runtime_profiles()}
    return profiles[agent_id]


def _task_run(agent_id: str, profile_id: str) -> TaskRun:
    return TaskRun(
        task_run_id=f"taskrun:{profile_id}",
        session_id="session:test",
        task_id="task:test",
        agent_id=agent_id,
        agent_profile_id=profile_id,
        execution_runtime_kind="subagent_task",
        diagnostics={
            "subagent_control": {
                "parent_task_run_id": "taskrun:parent",
                "parent_agent_run_ref": "agrun:parent",
                "goal": "find current source evidence",
                "instructions": "return concise evidence",
                "context_refs": ["ctx:1"],
                "expected_outputs": ["summary"],
            },
            "origin": {"parent_agent_run_ref": "agrun:parent"},
        },
    )


def _agent_run(task_run: TaskRun) -> AgentRun:
    return AgentRun(
        agent_run_id=f"agrun:{task_run.task_run_id}:main",
        task_run_id=task_run.task_run_id,
        agent_id=task_run.agent_id,
        agent_profile_id=task_run.agent_profile_id,
        spawn_mode="subagent",
        parent_agent_run_ref="agrun:parent",
        execution_runtime_kind="subagent_task",
        status="running",
        diagnostics={
            "subagent_control": {
                "parent_task_run_id": "taskrun:parent",
                "parent_agent_run_ref": "agrun:parent",
            }
        },
    )


def test_router_dispatches_search_agent_to_deepsearch_without_taskrun_binding() -> None:
    capability = _FakeCapability()
    profile = _profile("agent:web_researcher")
    task_run = _task_run(profile.agent_id, profile.agent_profile_id)
    agent_run = _agent_run(task_run)

    execution = asyncio.run(
        SpecialistRuntimeRouter(BACKEND_DIR, deepsearch_capability=capability).try_run(
            task_run=task_run,
            agent_run=agent_run,
            profile=profile,
            contract={"task_run_goal": "find current source evidence"},
        )
    )

    assert execution.handled is True
    assert execution.runtime_kind == "search_agent"
    assert execution.route == "deepsearch"
    assert capability.calls
    request = capability.calls[0]["request"]
    assert request.input_payload["query"] == "find current source evidence"
    assert "capability" not in dict(task_run.diagnostics or {})


def test_router_dispatches_codebase_search_agent_to_codebase_capability() -> None:
    capability = _FakeCapability()
    profile = _profile("agent:codebase_searcher")
    task_run = _task_run(profile.agent_id, profile.agent_profile_id)
    agent_run = _agent_run(task_run)

    execution = asyncio.run(
        SpecialistRuntimeRouter(BACKEND_DIR, codebase_search_capability=capability).try_run(
            task_run=task_run,
            agent_run=agent_run,
            profile=profile,
            contract={"task_run_goal": "find CodebaseSearchCapability definition"},
        )
    )

    assert execution.handled is True
    assert execution.runtime_kind == "codebase_search_agent"
    assert execution.route == "codebase_search"
    assert capability.calls
    assert capability.calls[0]["request"].target_agent_id == "agent:codebase_searcher"


def test_router_ignores_unknown_runtime_kind() -> None:
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:custom",
            "agent_profile_id": "custom_agent",
            "metadata": {"runtime_config": {"runtime_kind": "agent_loop"}},
        },
    )()
    task_run = _task_run("agent:custom", "custom_agent")
    agent_run = _agent_run(task_run)

    execution = asyncio.run(
        SpecialistRuntimeRouter(BACKEND_DIR).try_run(
            task_run=task_run,
            agent_run=agent_run,
            profile=profile,
            contract={"task_run_goal": "normal model work"},
        )
    )

    assert execution.handled is False
    assert execution.runtime_kind == "agent_loop"


def test_specialist_result_is_waitable_without_taskrun_capability_binding() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = RuntimeStateIndex(root)
        runtime_objects = RuntimeObjectStore(root)
        parent_task = TaskRun(task_run_id="taskrun:parent", session_id="session:test", task_id="task:parent")
        parent_run = AgentRun(agent_run_id="agrun:parent", task_run_id=parent_task.task_run_id, agent_id="agent:0", agent_profile_id="main_interactive_agent", status="running")
        child_task = _task_run("agent:web_researcher", "web_research_agent")
        child_run = _agent_run(child_task)
        state.upsert_task_run(parent_task)
        state.upsert_agent_run(parent_run)
        state.upsert_task_run(child_task)
        state.upsert_agent_run(child_run)
        host = type("Host", (), {"state_index": state, "runtime_objects": runtime_objects, "event_log": _FakeEventLog()})()
        services = TaskExecutorServices(
            runtime_host=host,
            backend_dir=BACKEND_DIR,
            model_runtime=None,
            tool_control_plane=None,
            tool_runtime_executor=None,
            tool_instances=(),
            agent_runtime_profile=None,
            backend_config={},
        )
        execution = SpecialistRuntimeExecution(
            handled=True,
            runtime_kind="search_agent",
            route="deepsearch",
            result={
                "status": "completed",
                "summary": "DeepSearch 完成。",
                "answer_candidate": "DeepSearch 完成。",
                "evidence_refs": ["web:evidence:1"],
                "artifact_refs": [{"path": "artifact:deepsearch:1"}],
                "limitations": [],
                "diagnostics": {"capability_id": "capability.deepsearch"},
            },
        )

        closeout = _finish_specialist_runtime_execution(
            services,
            host,
            task_run=child_task,
            agent_run=child_run,
            execution=execution,
        )
        waited = asyncio.run(SubagentControl(host).wait(task_run=parent_task, parent_agent_run=parent_run, subagent_run_ref=child_run.agent_run_id))

        assert closeout["ok"] is True
        assert waited["ok"] is True
        assert waited["result_available"] is True
        assert waited["result"]["final_answer"] == "DeepSearch 完成。"
        finished_child = state.get_task_run(child_task.task_run_id)
        assert finished_child is not None
        assert "capability" not in dict(finished_child.diagnostics or {})
        assert dict(finished_child.diagnostics or {})["specialist_runtime"]["runtime_kind"] == "search_agent"
