from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json


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


class QueryRuntimeMemoryFacadeStub:
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
        self.compressed_context = ""

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages), "compressed_context": self.compressed_context}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)


class EmptyToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_definition(self, _name):
        return None

    def get_instance(self, _name):
        return None


class SingleMessageModelRuntimeStub:
    supports_structured_sidecars = True

    def __init__(self, content: str = "单轮收口回答") -> None:
        self.content = content

    async def invoke_messages(self, messages, **_kwargs):
        sidecar_payload = _sidecar_payload_from_messages(messages)
        if sidecar_payload is not None:
            return SimpleNamespace(content=json.dumps(sidecar_payload, ensure_ascii=False))
        return SimpleNamespace(content=self.content)


class StreamingMessageModelRuntimeStub(SingleMessageModelRuntimeStub):
    def __init__(self, *, chunks: list[str], content: str | None = None) -> None:
        super().__init__(content=content or "".join(chunks))
        self.chunks = list(chunks)

    async def astream_messages(self, _messages, **_kwargs):
        for chunk in self.chunks:
            yield SimpleNamespace(content=chunk)


def model_turn_context(
    *,
    action_intent: str = "answer_only",
    work_mode: str = "conversation",
    interaction_intent: str = "answer",
    target_objects: list[str] | None = None,
    desired_outcome: str = "test outcome",
    deliverables: list[str] | None = None,
    constraints: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    planning_required: bool = False,
    todo_required: bool = False,
    completion_criteria: list[str] | None = None,
    task_goal_type: str = "",
    task_domain: str = "",
) -> dict[str, object]:
    decision = {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test",
        "user_message": "test",
        "interaction_intent": interaction_intent,
        "action_intent": action_intent,
        "work_mode": work_mode,
        "target_objects": list(target_objects or []),
        "desired_outcome": desired_outcome,
        "deliverables": list(deliverables or []),
        "constraints": list(constraints or []),
        "forbidden_actions": list(forbidden_actions or []),
        "context_binding_decision": {},
        "planning_required": planning_required,
        "todo_required": todo_required,
        "completion_criteria": list(completion_criteria or []),
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.9,
        "ambiguity": [],
    }
    return {
        "model_turn_decision": decision,
        "request_facts": {
            "authority": "agent_runtime.request_facts",
            "facts_id": "request-facts:test",
            "user_message": "test",
            "explicit_paths": list(target_objects or []),
            "material_suffixes": [],
        },
        "boundary_policy": {
            "authority": "agent_runtime.boundary_policy",
            "policy_id": "boundary:test",
            "forbidden_actions": list(forbidden_actions or []),
        },
        "action_permit": {
            "authority": "agent_runtime.action_permit",
            "permit_id": "action-permit:test",
            "allowed": True,
            "action_intent": action_intent,
            "required_operations": ["op.model_response"],
            "optional_operations": [],
        },
        **(
            {
                "task_goal_spec": {
                    "authority": "agent_runtime.model_turn_goal_projection",
                    "task_goal_type": task_goal_type,
                    "task_domain": task_domain or "general",
                    "forbidden_actions": list(forbidden_actions or []),
                    "required_verifications": [],
                    "required_capabilities": [],
                }
            }
            if task_goal_type
            else {}
        ),
    }


def _sidecar_payload_from_messages(messages: Any) -> dict[str, object] | None:
    items = [dict(item) for item in list(messages or []) if isinstance(item, dict)]
    if len(items) != 2:
        return None
    system_content = str(items[0].get("content") or "")
    user_content = str(items[1].get("content") or "")
    if "你只能返回一个 JSON object" not in system_content:
        return None
    try:
        payload = json.loads(user_content)
    except Exception:
        return None
    request = dict(payload.get("request") or {})
    if request.get("authority") != "agent_runtime.model_turn_decision_request":
        return None
    user_message = str(request.get("user_message") or "")
    request_facts = dict(request.get("request_facts") or {})
    explicit_selection = dict(request_facts.get("explicit_selection") or {})
    mode_policy = dict(explicit_selection.get("mode_policy") or {})
    if (
        str(explicit_selection.get("interaction_mode") or "") == "professional_mode"
        or str(mode_policy.get("execution_strategy") or "") == "professional_task_run"
    ):
        return {
            "authority": "agent_runtime.model_turn_decision",
            "decision_id": "model-turn-decision:test-sidecar-professional",
            "user_message": user_message,
            "interaction_intent": "plan",
            "action_intent": "answer_only",
            "work_mode": "planning",
            "target_objects": [],
            "desired_outcome": "按专业任务模式完成追踪并交付结论",
            "deliverables": ["final_answer"],
            "constraints": [],
            "forbidden_actions": [],
            "context_binding_decision": {"explicit_selection": explicit_selection},
            "planning_required": True,
            "todo_required": True,
            "completion_criteria": ["final_answer"],
            "needs_clarification": False,
            "clarification_question": "",
            "confidence": 0.9,
            "ambiguity": [],
        }
    lowered = user_message.lower()
    action_intent = "read_context" if any(marker in lowered for marker in (".pdf", ".csv", ".xlsx", "knowledge/")) else "answer_only"
    work_mode = "read_only_analysis" if action_intent == "read_context" else "conversation"
    return {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test-sidecar",
        "user_message": user_message,
        "interaction_intent": "answer",
        "action_intent": action_intent,
        "work_mode": work_mode,
        "target_objects": [],
        "desired_outcome": "直接回答用户",
        "deliverables": ["final_answer"],
        "constraints": [],
        "forbidden_actions": [],
        "context_binding_decision": {},
        "planning_required": False,
        "todo_required": False,
        "completion_criteria": ["answer_user"],
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.9,
        "ambiguity": [],
    }


def isolated_backend_root(prefix: str = "backend-test-") -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix)) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_query_runtime(
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
    from query import QueryRuntime

    return QueryRuntime(
        base_dir=base_dir or isolated_backend_root(),
        settings_service=settings_service or PrimarySettingsStub(),
        session_manager=session_manager or InMemorySessionManagerStub(),
        memory_facade=memory_facade or QueryRuntimeMemoryFacadeStub(),
        retrieval_service=retrieval_service or SimpleNamespace(),
        tool_runtime=tool_runtime or EmptyToolRuntimeStub(),
        skill_registry=skill_registry or EmptySkillRegistryStub(),
        permission_service=permission_service or DefaultPermissionStub(),
        model_runtime=model_runtime or SingleMessageModelRuntimeStub(),
    )
