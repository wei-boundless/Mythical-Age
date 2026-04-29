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
        return SimpleNamespace(allowed=False, reason="preview_only")


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def invoke_messages(self, messages):
        self.messages = list(messages)
        return SimpleNamespace(content="model-only runtime directive answer")


class _SessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages)}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def save_message(self, _session_id, role, content):
        self.messages.append({"role": role, "content": content})

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)

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


def test_execution_events_emit_task_operation_preview_before_fail_closed() -> None:
    runtime = _build_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "session-preview-live",
            "修改任务系统文档，然后检查有没有前后矛盾",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    chain_event = events[0]
    preview_event = events[1]
    candidate_event = events[2]
    plan_event = events[3]
    validation_event = events[4]
    graph_preview_event = events[5]
    adoption_event = events[6]
    directive_candidate_event = events[7]
    commit_gate_event = events[8]
    control_event = events[9]
    error_event = events[10]
    chain = chain_event["preview"]
    preview = preview_event["preview"]
    assert isinstance(chain, dict)
    assert isinstance(preview, dict)

    assert chain_event["type"] == "agent_runtime_chain_preview"
    assert chain["query_runtime_role"] == "adapter_only"
    assert chain["runtime_executable"] is False
    assert chain["diagnostics"]["legacy_query_execution_available"] is False
    assert preview_event["type"] == "task_operation_preview"
    assert preview["status"] == "preview_only"
    assert preview["resource_policy"]["preview_only"] is True
    assert preview["resource_policy"]["adopted"] is False
    assert preview["resource_policy"]["runtime_executable"] is False
    assert preview["control_kernel_result"]["status"] == "blocked"
    assert preview["control_kernel_result"]["reason"] == "preview_only"
    assert preview["control_kernel_result"]["directives"] == []
    assert preview["control_kernel_result"]["execution_graph"]["nodes"] == []
    assert preview["execution_topology_preview"]["mode"] == "single_agent"
    assert preview["execution_topology_preview"]["runtime_executable"] is False
    assert preview["coordination_policy_preview"]["max_agents"] == 1
    assert preview["coordination_policy_preview"]["max_parallelism"] == 1
    assert preview["agent_seat_plan_previews"] == []
    assert preview["agent_assignment_candidates"] == []
    assert len(preview["candidate_set_preview"]) >= 6
    assert len(preview["understanding_candidate_preview"]) == 5
    assert all(item["authority"] == "candidate_only" for item in preview["understanding_candidate_preview"])
    assert preview["orchestration_plan_preview"]["topology_mode"] == "single_agent"
    assert preview["orchestration_plan_preview"]["runtime_executable"] is False
    assert preview["plan_validation"]["status"] == "blocked"
    assert preview["plan_validation"]["runtime_executable"] is False
    assert preview["execution_graph_preview"]["runtime_executable"] is False
    assert preview["execution_graph_preview"]["node_previews"][0]["authority"] == "preview_only"
    assert preview["adoption_candidate_preview"]["status"] == "blocked"
    assert preview["adoption_candidate_preview"]["can_adopt_plan"] is False
    assert preview["adoption_block"]["blocked"] is True
    assert preview["runtime_directive_candidates"][0]["authority"] == "candidate_only"
    assert preview["runtime_directive_candidates"][0]["runtime_executable"] is False
    assert preview["runtime_directive_block"]["blocked"] is True
    assert preview["operation_gate_preflight"]["operation_gate_passed"] is False
    assert preview["operation_gate_preflight"]["checks"]
    assert preview["directive_only_executor_preview"]["accepted_input_type"] == "RuntimeDirective"
    assert preview["directive_only_executor_preview"]["will_dispatch"] is False
    assert preview["commit_gate_preview"]["status"] == "blocked"
    assert preview["commit_gate_preview"]["commit_allowed"] is False
    assert preview["commit_gate_preview"]["runtime_executable"] is False
    assert all(candidate["allowed"] is False for candidate in preview["commit_gate_preview"]["commit_candidates"])

    assert candidate_event["type"] == "candidate_set_preview"
    assert candidate_event["candidates"] == preview["candidate_set_preview"]
    assert plan_event["type"] == "orchestration_plan_preview"
    assert plan_event["plan"] == preview["orchestration_plan_preview"]
    assert validation_event["type"] == "plan_validation"
    assert validation_event["validation"] == preview["plan_validation"]
    assert graph_preview_event["type"] == "execution_graph_preview"
    assert graph_preview_event["graph_preview"] == preview["execution_graph_preview"]
    assert adoption_event["type"] == "adoption_candidate_preview"
    assert adoption_event["adoption"] == preview["adoption_candidate_preview"]
    assert directive_candidate_event["type"] == "runtime_directive_candidate_preview"
    assert directive_candidate_event["candidates"] == preview["runtime_directive_candidates"]
    assert commit_gate_event["type"] == "commit_gate_preview"
    assert commit_gate_event["commit_gate"] == preview["commit_gate_preview"]

    assert control_event["type"] == "orchestration_control"
    assert control_event["control"] == preview["control_kernel_result"]
    assert control_event["task_operation_preview_ref"]["resource_policy_ref"] == preview["resource_policy"]["policy_id"]
    assert control_event["task_operation_preview_ref"]["execution_topology_mode"] == "single_agent"
    assert control_event["task_operation_preview_ref"]["orchestration_plan_ref"] == preview["orchestration_plan_preview"]["plan_id"]
    assert control_event["task_operation_preview_ref"]["plan_validation_status"] == "blocked"
    assert control_event["task_operation_preview_ref"]["execution_graph_preview_node_count"] == 1
    assert control_event["task_operation_preview_ref"]["adoption_candidate_status"] == "blocked"
    assert control_event["task_operation_preview_ref"]["adopted_resource_policy_available"] is False
    assert control_event["task_operation_preview_ref"]["runtime_directive_candidate_count"] == 1
    assert control_event["task_operation_preview_ref"]["runtime_directive_available"] is False
    assert control_event["task_operation_preview_ref"]["operation_gate_passed"] is False
    assert control_event["task_operation_preview_ref"]["operation_gate_check_count"] == len(
        preview["operation_gate_preflight"]["checks"]
    )
    assert control_event["task_operation_preview_ref"]["executor_dispatch_enabled"] is False
    assert control_event["task_operation_preview_ref"]["executor_accepts_only"] == "RuntimeDirective"
    assert control_event["task_operation_preview_ref"]["commit_gate_status"] == "blocked"
    assert control_event["task_operation_preview_ref"]["commit_allowed"] is False
    assert control_event["task_operation_preview_ref"]["commit_candidate_count"] == len(
        preview["commit_gate_preview"]["commit_candidates"]
    )
    assert control_event["task_operation_preview_ref"]["understanding_candidate_count"] == len(
        preview["understanding_candidate_preview"]
    )
    assert control_event["task_operation_preview_ref"]["candidate_count"] == len(preview["candidate_set_preview"])
    assert control_event["task_operation_preview_ref"]["multi_agent_enabled"] is False
    assert control_event["task_operation_preview_ref"]["agent_seat_count"] == 0
    assert control_event["task_operation_preview_ref"]["runtime_directive_enabled"] is False
    assert control_event["task_operation_preview_ref"]["runtime_executable"] is False

    assert error_event["type"] == "error"
    assert error_event["error"] == "preview_only"
    assert error_event["answer_channel"] == "orchestration_fail_closed"


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

    assert "agent_runtime_chain_preview" in event_types
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
    assert directive_event["directive"]["operation_refs"] == ["op.model_response"]
    assert directive_event["resource_policy"]["adopted"] is True
    assert directive_event["resource_policy"]["runtime_executable"] is True
    assert directive_event["resource_policy"]["allowed_operations"] == ("op.model_response",)
    assert gate_event["gate"]["allowed"] is True
    assert gate_event["gate"]["operation_id"] == "op.model_response"
    output_event = next(event for event in events if event["type"] == "output_boundary")
    runtime_commit_gate_event = next(event for event in events if event["type"] == "runtime_commit_gate")
    assert output_event["output"]["canonical_answer"] == "model-only runtime directive answer"
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
    assert done_event["content"] == "model-only runtime directive answer"
