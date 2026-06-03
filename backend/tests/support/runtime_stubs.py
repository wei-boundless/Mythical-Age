from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class RuntimeBaseDirStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


class MemoryApiRuntimeStub(RuntimeBaseDirStub):
    def __init__(self, base_dir: Path) -> None:
        from memory_system import MemoryFacade

        super().__init__(base_dir)
        self.memory_facade = MemoryFacade(base_dir)
        self.refreshed_paths: list[str] = []

    def refresh_indexes_for_path(self, path: str) -> None:
        self.refreshed_paths.append(path)


class HarnessRuntimeFacadeMemoryFacadeStub:
    session_memory = SimpleNamespace(
        manager=lambda _session_id: SimpleNamespace(load_state=lambda: None),
        update_runtime_state_from_context_state=lambda *_args, **_kwargs: None,
    )

    def build_memory_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_runtime_view(self, *_args, **_kwargs):
        return {"view_id": "memview:test", "state_snapshot": {}}

    def enqueue_memory_maintenance_after_commit(self, *_args, **_kwargs):
        return SimpleNamespace(
            to_dict=lambda: {
                "attempted": False,
                "queued": True,
                "status": "queued",
                "session_memory_succeeded": False,
                "durable_memory_succeeded": False,
                "durable_write_count": 0,
            }
        )


class EmptySkillRegistryStub:
    skills = []


class PrimarySettingsStub:
    def get_rag_mode(self) -> bool:
        return False

    def get_orchestration_plan_mode(self) -> str:
        return "primary"


class DefaultPermissionStub:
    def current_mode(self) -> str:
        return "default"

    def supported_modes(self) -> list[str]:
        return ["default"]


class InMemorySessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.api_transcript: list[dict[str, object]] = []
        self.compressed_context = ""

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages), "compressed_context": self.compressed_context}

    def load_session_for_agent(self, _session_id):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def load_session_for_api(self, _session_id):
        return list(self.api_transcript or self.messages)

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)

    def append_api_messages(self, _session_id, messages):
        self.api_transcript.extend(messages)
        return list(self.api_transcript)


class EmptyToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_definition(self, _name):
        return None

    def get_instance(self, _name):
        return None


class SingleMessageModelRuntimeStub:
    def __init__(
        self,
        content: str = "单轮收口回答",
        *,
        agent_turn_action_request: dict[str, object] | None = None,
    ) -> None:
        self.content = content
        self.agent_turn_action_request = dict(agent_turn_action_request or {})

    async def invoke_messages(self, messages, **_kwargs):
        if self.agent_turn_action_request and _is_model_action_request(messages):
            request = self.agent_turn_action_request or _default_agent_turn_action_request(messages)
            return SimpleNamespace(content=json.dumps(request, ensure_ascii=False))
        return SimpleNamespace(content=self.content)


class NativeToolCallModelRuntimeStub(SingleMessageModelRuntimeStub):
    def __init__(
        self,
        *,
        content: str = "",
        tool_calls: list[dict[str, object]] | None = None,
        agent_turn_action_request: dict[str, object] | None = None,
    ) -> None:
        super().__init__(content=content, agent_turn_action_request=agent_turn_action_request)
        self.tool_calls = list(tool_calls or [])
        self.seen_tools: list[object] = []

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.seen_tools.append(list(tools or []))
        if self.tool_calls:
            return SimpleNamespace(content=self.content, tool_calls=list(self.tool_calls))
        if self.agent_turn_action_request and _is_model_action_request(messages):
            return SimpleNamespace(content=json.dumps(self.agent_turn_action_request, ensure_ascii=False), tool_calls=[])
        return SimpleNamespace(content=self.content, tool_calls=[])


class NativeToolCallSequenceModelRuntimeStub(SingleMessageModelRuntimeStub):
    def __init__(self, responses: list[dict[str, object]]) -> None:
        super().__init__(content="")
        self.responses = [dict(item) for item in list(responses or [])]
        self.calls = 0
        self.seen_tools: list[object] = []
        self.seen_messages: list[list[object]] = []
        self.seen_accounting_contexts: list[dict[str, object]] = []

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.calls += 1
        self.seen_tools.append(list(tools or []))
        self.seen_messages.append(list(messages or []))
        self.seen_accounting_contexts.append(dict(_kwargs.get("accounting_context") or {}))
        response = self.responses[min(self.calls - 1, max(0, len(self.responses) - 1))] if self.responses else {}
        return SimpleNamespace(
            content=str(response.get("content") or ""),
            tool_calls=[dict(item) for item in list(response.get("tool_calls") or []) if isinstance(item, dict)],
            additional_kwargs=dict(response.get("additional_kwargs") or {}),
        )


class StreamingMessageModelRuntimeStub(SingleMessageModelRuntimeStub):
    def __init__(self, *, chunks: list[str], content: str | None = None) -> None:
        super().__init__(content=content or "".join(chunks))
        self.chunks = list(chunks)

    async def astream_messages(self, _messages, **_kwargs):
        for chunk in self.chunks:
            yield SimpleNamespace(content=chunk)


def agent_turn_context(
    *,
    action_type: str = "respond",
    target_objects: list[str] | None = None,
    desired_outcome: str = "test outcome",
    deliverables: list[str] | None = None,
    constraints: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    selected_skill_ids: list[str] | None = None,
    planning_required: bool = False,
    todo_required: bool = False,
    completion_criteria: list[str] | None = None,
    task_goal_type: str = "light_qa",
    task_domain: str = "",
    model_agent_plan_draft: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_task_goal_type = str(task_goal_type or "").strip()
    if not resolved_task_goal_type:
        raise ValueError("agent_turn_context requires task_goal_type")
    task_contract_seed = {
        "goal": desired_outcome,
        "task_goal_type": resolved_task_goal_type,
        "deliverables": list(deliverables or []),
        "constraints": list(constraints or []),
        "forbidden_actions": list(forbidden_actions or []),
        "completion_criteria": list(completion_criteria or []),
    }
    if target_objects:
        task_contract_seed["resource_contract"] = {"required_read_files": list(target_objects)}
    if selected_skill_ids:
        task_contract_seed["selected_skill_ids"] = list(selected_skill_ids)
    action_request = {
        "authority": "agent_runtime.agent_turn_action_request",
        "request_id": "agent-turn-action:test",
        "turn_id": "turn:test",
        "action_type": action_type,
        "final_answer": desired_outcome if action_type == "respond" else "",
        "task_contract_seed": task_contract_seed if action_type == "request_task_run" else {},
        "completion_contract": {"completion_criteria": list(completion_criteria or [])},
        "permission_request": {},
        "diagnostics": {"test_stub_action": True},
    }
    result: dict[str, object] = {
        "agent_turn_action_request": action_request,
        "task_contract_seed": task_contract_seed,
        "runtime_admission": {"authority": "agent_runtime.runtime_admission", "allowed": True},
        "turn_signals": {
            "authority": "turn_signals.structural",
            "explicit_paths": list(target_objects or []),
            "material_suffixes": [],
        },
        **(
            {
                "task_goal_spec": {
                    "authority": "agent_runtime.task_goal_projection",
                    "task_goal_type": resolved_task_goal_type,
                    **({"task_domain": str(task_domain).strip()} if str(task_domain or "").strip() else {}),
                    "forbidden_actions": list(forbidden_actions or []),
                    "required_verifications": [],
                    "required_capabilities": [],
                }
            }
        ),
    }
    if model_agent_plan_draft:
        result["model_agent_plan_draft"] = dict(model_agent_plan_draft)
    return result


def _is_model_action_request(messages: Any) -> bool:
    try:
        first = list(messages or [])[0]
    except Exception:
        return False
    content = str(dict(first).get("content") if isinstance(first, dict) else getattr(first, "content", "") or "")
    return "harness.loop.model_action_request" in str(messages)


def _default_agent_turn_action_request(messages: Any) -> dict[str, object]:
    user_message = ""
    try:
        request_payload = json.loads(str(list(messages or [])[-1].get("content") or "{}"))
        user_message = str(request_payload.get("user_message") or "")
    except Exception:
        user_message = "test"
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": "model-action:stub:respond",
        "turn_id": "",
        "action_type": "respond",
        "public_progress_note": "已理解当前请求，正在整理可交付回答。",
        "public_action_state": {
            "current_judgment": "当前请求可直接回答。",
            "next_action": "整理最终回复并收口。"
        },
        "final_answer": user_message or "test outcome",
        "task_contract_seed": {},
        "completion_contract": {},
        "permission_request": {},
        "diagnostics": {
            "test_stub_action_request": True,
        },
    }


def isolated_backend_root(prefix: str = "backend-test-") -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix)) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_harness_runtime(
    *,
    base_dir: Path | None = None,
    settings_service: Any | None = None,
    session_manager: Any | None = None,
    memory_facade: Any | None = None,
    retrieval_service: Any | None = None,
    tool_runtime: Any | None = None,
    skill_registry: Any | None = None,
    permission_service: Any | None = None,
    model_runtime: Any | None = None,
):
    from harness.entrypoint import HarnessRuntimeFacade

    return HarnessRuntimeFacade(
        base_dir=base_dir or isolated_backend_root(),
        settings_service=settings_service or PrimarySettingsStub(),
        session_manager=session_manager or InMemorySessionManagerStub(),
        memory_facade=memory_facade or HarnessRuntimeFacadeMemoryFacadeStub(),
        retrieval_service=retrieval_service or SimpleNamespace(),
        tool_runtime=tool_runtime or EmptyToolRuntimeStub(),
        skill_registry=skill_registry or EmptySkillRegistryStub(),
        permission_service=permission_service or DefaultPermissionStub(),
        model_runtime=model_runtime or SingleMessageModelRuntimeStub(),
    )


