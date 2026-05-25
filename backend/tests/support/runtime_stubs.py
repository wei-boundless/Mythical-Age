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
    def __init__(self, content: str = "单轮收口回答") -> None:
        self.content = content

    async def invoke_messages(self, messages, **_kwargs):
        if _is_model_turn_decision_request(messages):
            return SimpleNamespace(content=json.dumps(_default_model_turn_decision_payload(messages), ensure_ascii=False))
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
        raise ValueError("model_turn_context requires task_goal_type")
    decision = {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test",
        "user_message": "test",
        "interaction_intent": interaction_intent,
        "action_intent": action_intent,
        "work_mode": work_mode,
        "task_goal_type": resolved_task_goal_type,
        "domain_mismatch_signal": {},
        "target_objects": list(target_objects or []),
        "desired_outcome": desired_outcome,
        "deliverables": list(deliverables or []),
        "constraints": list(constraints or []),
        "forbidden_actions": list(forbidden_actions or []),
        "selected_skill_ids": list(selected_skill_ids or []),
        "context_binding_decision": {},
        "planning_required": planning_required,
        "todo_required": todo_required,
        "completion_criteria": list(completion_criteria or []),
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.9,
        "ambiguity": [],
    }
    result: dict[str, object] = {
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


def _is_model_turn_decision_request(messages: Any) -> bool:
    try:
        first = list(messages or [])[0]
    except Exception:
        return False
    content = str(dict(first).get("content") if isinstance(first, dict) else getattr(first, "content", "") or "")
    return "理解决策器" in content and "只输出合法 JSON" in content


def _default_model_turn_decision_payload(messages: Any) -> dict[str, object]:
    user_message = ""
    task_selection: dict[str, object] = {}
    try:
        request_payload = json.loads(str(list(messages or [])[-1].get("content") or "{}"))
        user_message = str(request_payload.get("user_message") or "")
        task_selection = dict(request_payload.get("task_selection") or {})
    except Exception:
        user_message = "test"
        task_selection = {}
    text = user_message.lower()
    selected_task_id = str(task_selection.get("selected_task_id") or "").strip()
    explicit_mode = str(
        task_selection.get("interaction_mode")
        or task_selection.get("runtime_interaction_mode")
        or dict(task_selection.get("mode_policy") or {}).get("interaction_mode")
        or ""
    ).strip()
    action_intent = "answer_only"
    work_mode = "conversation"
    interaction_intent = "answer"
    task_goal_type = "light_qa"
    planning_required = False
    todo_required = False
    deliverables: list[str] = ["conversational_response"]
    if selected_task_id or any(marker in text for marker in ("生成", "开发", "实现", "修改", "重构", "修复", "运行", "验证", "game", "游戏", "前端", "代码")):
        action_intent = "edit_workspace"
        work_mode = "implementation"
        interaction_intent = "create" if any(marker in text for marker in ("生成", "create", "新增")) else "modify"
        task_goal_type = "game_vertical_slice_delivery" if "游戏" in text or "game" in text or selected_task_id == "task.dev.light_web_game" else "implementation"
        planning_required = explicit_mode == "professional_mode"
        todo_required = False
        deliverables = ["changed_files", "verification_result_or_limitation"]
    elif any(marker in text for marker in ("分析", "pdf", ".pdf", "报告")):
        action_intent = "read_context"
        work_mode = "read_only_analysis"
        interaction_intent = "inspect"
        task_goal_type = "document_analysis"
        deliverables = ["analysis_summary"]
    return {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:stub",
        "user_message": user_message,
        "interaction_intent": interaction_intent,
        "action_intent": action_intent,
        "work_mode": work_mode,
        "task_goal_type": task_goal_type,
        "domain_mismatch_signal": {},
        "target_objects": [selected_task_id] if selected_task_id else [],
        "desired_outcome": user_message or "test outcome",
        "deliverables": deliverables,
        "constraints": [],
        "forbidden_actions": [],
        "selected_skill_ids": [],
        "resource_contract": {},
        "context_binding_decision": {"mode": "test_stub"},
        "planning_required": planning_required,
        "todo_required": todo_required,
        "completion_criteria": [],
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.9,
        "ambiguity": [],
        "diagnostics": {"test_stub_decision": True},
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
