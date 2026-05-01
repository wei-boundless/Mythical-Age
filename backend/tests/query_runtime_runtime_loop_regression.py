from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from tasks import TaskCoordinator
from orchestration import RuntimeActionRequest, RuntimeLoopLimits
from orchestration.runtime_loop.tool_adoption import build_tool_request_runtime_adoption
from operations import ResourceDecision, ResourcePolicy, build_default_operation_registry


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return False

    def get_orchestration_plan_mode(self) -> str:
        return "primary"


class _MemoryFacadeStub:
    session_memory = SimpleNamespace(manager=lambda _session_id: SimpleNamespace(load_state=lambda: None))

    def compact_history_for_query(self, _session_id, history):
        return history, {"pressure_level": "normal"}

    def inspect_query_context(self, *_args, **_kwargs):
        return {}

    def build_context_package(self, *_args, **_kwargs):
        return None

    def build_persistent_memory_block(self, *_args, **_kwargs):
        return ""

    def prefetch_relevant_notes(self, *_args, **_kwargs):
        return []


class _ToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_instance(self, _name):
        return None


class _LoopToolRuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        from tools.definitions import build_tool_instances, get_tool_definition_map

        self.instances = build_tool_instances(base_dir)
        self.definition_map = get_tool_definition_map()
        self.registry = None
        self.definitions = []

    def get_instance(self, _name):
        for item in self.instances:
            if getattr(item, "name", "") == _name:
                return item
        return None

    def get_definition(self, name):
        return self.definition_map.get(name)


class _SkillRegistryStub:
    skills = []

    def format_active_skill_block(self, _active_skill):
        return None

    def get_by_name(self, _name):
        return None

    def match_for_query(self, **_kwargs):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=False, reason="not_authorized")


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def invoke_messages(self, messages):
        self.messages = list(messages)
        return SimpleNamespace(content="single-agent runtime directive answer")


class _ToolLoopModelRuntimeStub:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_enabled_calls = 0
        self.last_tools: list[object] = []

    async def invoke_messages(self, messages):
        self.calls += 1
        return SimpleNamespace(content="summary after tools")

    async def invoke_messages_with_tools(self, messages, tools):
        self.calls += 1
        self.tool_enabled_calls += 1
        self.last_tools = list(tools)
        if self.tool_enabled_calls > 1:
            return SimpleNamespace(content="summary after tools")
        return SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": f"tool-call-{self.calls}",
                    "name": "read_file",
                    "args": {"path": "backend/soul/agent_core/CORE.md"},
                    "type": "tool_call",
                }
            ],
        )


class _SessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages)}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def save_message(self, _session_id, role, content):
        self.messages.append({"role": role, "content": content})

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)

    def set_title(self, _session_id, _title):
        return None


def _build_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
        task_coordinator=TaskCoordinator(),
    )


def _build_stream_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
        task_coordinator=TaskCoordinator(),
    )


def _build_tool_loop_runtime(tmp_path: Path) -> QueryRuntime:
    runtime = QueryRuntime(
        base_dir=tmp_path,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(Path.cwd()),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ToolLoopModelRuntimeStub(),
        task_coordinator=TaskCoordinator(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=3)
    return runtime


def test_execution_events_use_runtime_stream() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "session-runtime-events",
            "修改任务系统文档，然后检查有没有前后矛盾",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]

    assert "runtime_directive" in event_types
    assert "operation_gate" in event_types
    assert "done" in event_types
    assert not any(str(event_type).endswith("_preview") for event_type in event_types)


def test_astream_executes_only_model_response_runtime_directive() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-runtime-directive",
                message="给我一个简短结论",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]
    directive_event = next(event for event in events if event["type"] == "runtime_directive")
    gate_event = next(event for event in events if event["type"] == "operation_gate")
    input_commit_event = next(event for event in events if event["type"] == "input_commit_gate")
    done_event = next(event for event in events if event["type"] == "done")

    assert not any(str(event_type).endswith("_preview") for event_type in event_types)
    assert "input_commit_gate" in event_types
    assert "runtime_directive" in event_types
    assert "operation_gate" in event_types
    assert "answer_candidate" in event_types
    assert "output_boundary" in event_types
    assert "runtime_commit_gate" in event_types
    assert "done" in event_types
    assert not any(
        event.get("type") == "error" and event.get("answer_source") == "control_kernel"
        for event in events
    )
    assert input_commit_event["commit_gate"]["commit_allowed"] is True
    assert input_commit_event["commit_gate"]["commit_candidate"]["payload"]["role"] == "user"
    assert input_commit_event["commit_gate"]["diagnostics"]["assistant_write_allowed"] is False
    assert directive_event["directive"]["executor_type"] == "model"
    assert "op.model_response" in directive_event["directive"]["operation_refs"]
    assert directive_event["resource_policy"]["adopted"] is True
    assert directive_event["resource_policy"]["runtime_executable"] is True
    assert "op.model_response" in directive_event["resource_policy"]["allowed_operations"]
    assert gate_event["gate"]["allowed"] is True
    assert gate_event["gate"]["operation_id"] == "op.model_response"
    output_event = next(event for event in events if event["type"] == "output_boundary")
    runtime_commit_gate_event = next(event for event in events if event["type"] == "runtime_commit_gate")
    assert output_event["output"]["canonical_answer"] == "single-agent runtime directive answer"
    assert runtime_commit_gate_event["commit_gate"]["status"] == "blocked"
    assert runtime_commit_gate_event["commit_gate"]["commit_allowed"] is False
    assert runtime_commit_gate_event["commit_gate"]["reason"] == "commit_gate_blocked"
    assert all(
        candidate["allowed"] is False
        for candidate in runtime_commit_gate_event["commit_gate"]["commit_candidates"]
    )
    assert done_event["answer_source"] == "runtime_directive:model_response"
    assert done_event["persist_policy"] == "commit_gate_blocked"
    assert done_event["commit_gate"]["commit_allowed"] is False
    assert done_event["content"] == "single-agent runtime directive answer"
    projection_event = next(
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "stage_projection_built"
    )
    projection = dict(dict(projection_event["event"]).get("payload", {}).get("stage_projection") or {})
    sections = list(dict(projection.get("soul_runtime_view") or {}).get("sections") or [])
    section_ids = {str(dict(section).get("section_id") or "") for section in sections}
    assert "resource_section" not in section_ids
    assert "guardrail_section" not in section_ids
    context_event = next(
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "context_snapshot_built"
    )
    snapshot = dict(dict(context_event["event"]).get("payload", {}).get("context_snapshot") or {})
    system_prompt = str(list(snapshot.get("model_messages") or [{}])[0].get("content") or "")
    assert "resource_section" not in system_prompt
    assert "guardrail_section" not in system_prompt


def test_astream_exposes_only_adopted_main_runtime_tools_to_model_lane(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
                QueryRequest(
                    session_id="session-budget-exhausted",
                    message="读取 backend/soul/agent_core/CORE.md 并总结",
                    history=[],
                )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assistant_commit_event = next(event for event in events if event["type"] == "runtime_assistant_session_commit")
    directive_event = next(event for event in events if event["type"] == "runtime_directive")
    tool_names = {getattr(tool, "name", "") for tool in runtime.model_runtime.last_tools}

    assert runtime.model_runtime.tool_enabled_calls >= 1
    assert {"search_files", "search_text", "read_file"}.issubset(tool_names)
    assert "terminal" not in tool_names
    assert "python_repl" not in tool_names
    assert "op.read_file" in directive_event["resource_policy"]["allowed_operations"]
    assert "tool_call_requested" in [event.get("type") for event in events]
    assert "tool_result_received" in [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    assert assistant_commit_event["commit_applied"] is True


def test_astream_keeps_hidden_and_unrequested_tools_out_of_model_lane(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-hidden-tools",
                message="读取 backend/soul/agent_core/CORE.md 并检查内容",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    tool_names = {getattr(tool, "name", "") for tool in runtime.model_runtime.last_tools}
    directive_event = next(event for event in events if event["type"] == "runtime_directive")

    assert "read_file" in tool_names
    assert "terminal" not in tool_names
    assert "python_repl" not in tool_names
    assert "pdf_analysis" not in tool_names
    assert "op.shell" not in directive_event["resource_policy"]["allowed_operations"]
    assert "op.python_repl" not in directive_event["resource_policy"]["allowed_operations"]


def test_tool_request_adoption_cannot_self_authorize_against_adopted_policy() -> None:
    registry = build_default_operation_registry()
    action_request = RuntimeActionRequest(
        request_id="rtact-test",
        task_run_id="taskrun-test",
        request_type="tool_call",
        operation_id="read_file",
        payload={"tool_name": "read_file", "tool_call": {"name": "read_file", "args": {}}},
    )
    adopted_policy = ResourcePolicy(
        policy_id="respol-test-adopted-runtime",
        task_id="task-test",
        allowed_operations=("op.model_response",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
        decisions=(
            ResourceDecision(
                operation_id="op.model_response",
                decision="allow",
                reason="test policy only allows model response",
            ),
        ),
    )

    _directive, tool_policy = build_tool_request_runtime_adoption(
        action_request=action_request,
        task_id="task-test",
        task_operation={},
        operation_id="op.read_file",
        operation_descriptor=registry.get_operation("op.read_file"),
        adopted_resource_policy=adopted_policy,
    )

    assert tool_policy.allowed_operations == ()
    assert tool_policy.denied_operations == ("op.read_file",)
    assert tool_policy.decisions[0].decision == "deny"
    assert tool_policy.decisions[0].reason == "tool request is not allowed by adopted resource policy"
