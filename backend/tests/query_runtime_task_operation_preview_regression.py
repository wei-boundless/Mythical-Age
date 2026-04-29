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
    pass


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
    preview_event = events[0]
    control_event = events[1]
    error_event = events[2]
    preview = preview_event["preview"]
    assert isinstance(preview, dict)

    assert preview_event["type"] == "task_operation_preview"
    assert preview["status"] == "preview_only"
    assert preview["resource_policy"]["preview_only"] is True
    assert preview["resource_policy"]["adopted"] is False
    assert preview["resource_policy"]["runtime_executable"] is False
    assert preview["control_kernel_result"]["status"] == "blocked"
    assert preview["control_kernel_result"]["reason"] == "preview_only"
    assert preview["control_kernel_result"]["directives"] == []
    assert preview["control_kernel_result"]["execution_graph"]["nodes"] == []

    assert control_event["type"] == "orchestration_control"
    assert control_event["control"] == preview["control_kernel_result"]
    assert control_event["task_operation_preview_ref"]["resource_policy_ref"] == preview["resource_policy"]["policy_id"]
    assert control_event["task_operation_preview_ref"]["runtime_directive_enabled"] is False
    assert control_event["task_operation_preview_ref"]["runtime_executable"] is False

    assert error_event["type"] == "error"
    assert error_event["error"] == "preview_only"
    assert error_event["answer_channel"] == "orchestration_fail_closed"
