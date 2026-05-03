from __future__ import annotations

from dataclasses import asdict
from typing import Any

from context_management import ContextResolver
from tasks.contract_builder import build_task_runtime_contract
from understanding import analyze_memory_intent
from understanding.query_understanding import analyze_query_understanding


class AgentRuntimeChainAssembler:
    """Assembles the current single-agent runtime chain."""

    def __init__(self, *, memory_facade, skill_registry=None, tool_registry=None) -> None:
        self.memory_facade = memory_facade
        self.skill_registry = skill_registry
        self.tool_registry = tool_registry

    def build_runtime(
        self,
        *,
        session_id: str,
        task_id: str,
        message: str,
        source: str,
        task_selection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memory_intent = analyze_memory_intent(message)
        memory_payload = self.build_memory_runtime_view_payload(
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
        )
        active_bindings = _active_bindings_from_memory_payload(memory_payload)
        query_understanding = analyze_query_understanding(
            message,
            memory_intent,
            active_bindings=active_bindings,
            skill_registry=self.skill_registry,
            tool_registry=self.tool_registry,
        )
        current_turn_context = ContextResolver().resolve(
            session_id=session_id,
            task_id=task_id,
            user_message=message,
            memory_runtime_view=memory_payload,
            query_understanding=asdict(query_understanding),
        )
        current_turn_context_payload = current_turn_context.to_dict()
        if task_selection:
            current_turn_context_payload.update(
                {
                    key: value
                    for key, value in dict(task_selection or {}).items()
                    if value not in ("", None, [], {})
                }
            )
        skill_frame = _resolve_skill_frame(self.skill_registry, query_understanding)
        context_payload: dict[str, Any] = {}
        task_operation = build_task_runtime_contract(
            session_id=session_id,
            task_id=task_id,
            user_goal=message,
            source=source,
            memory_runtime_view=memory_payload,
            context_policy_result=context_payload,
            query_understanding=asdict(query_understanding),
            current_turn_context=current_turn_context_payload,
            active_skill=_skill_frame_payload(skill_frame),
            runtime_required_operations=_operation_ids_for_runtime(
                query_understanding=query_understanding,
                skill_frame=skill_frame,
                tool_registry=self.tool_registry,
            ),
        )
        memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
        memory_payload = self.build_memory_runtime_view_payload(
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )
        context_policy_result = self.build_context_policy_result(
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )
        context_payload = _to_dict(context_policy_result)
        task_operation["memory_runtime_view"] = memory_payload
        task_operation["context_policy_result"] = context_payload
        return {
            "memory_runtime_view": memory_payload,
            "context_policy_result": context_payload,
            "current_turn_context": current_turn_context_payload,
            "task_operation": task_operation,
            "status": "runtime",
            "runtime_executable": True,
        }

    def build_memory_runtime_view_payload(
        self,
        *,
        session_id: str,
        message: str,
        memory_intent: Any,
        memory_request_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        builder = getattr(self.memory_facade, "build_memory_runtime_view", None)
        if not callable(builder):
            return {}
        view = builder(
            session_id=session_id,
            query=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )
        return _to_dict(view)

    def build_context_policy_result(
        self,
        *,
        session_id: str,
        message: str | None,
        memory_intent: Any,
        memory_request_profile: dict[str, Any] | None = None,
        relevant_memory_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ):
        builder = getattr(self.memory_facade, "build_memory_context_package", None)
        if not callable(builder):
            return None
        return builder(
            session_id=session_id,
            pending_user_message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )

    def build_context_package(
        self,
        *,
        session_id: str,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ):
        result = self.build_context_policy_result(
            session_id=session_id,
            message=pending_user_message,
            memory_intent=memory_intent or analyze_memory_intent(pending_user_message or ""),
            relevant_memory_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
        )
        return getattr(result, "package", result)


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return dict(value)


def _active_bindings_from_memory_payload(memory_payload: dict[str, Any]) -> dict[str, Any]:
    state_snapshot = dict(memory_payload.get("state_snapshot") or {})
    context_slots = dict(state_snapshot.get("context_slots") or {})
    active_handles = dict(state_snapshot.get("active_handles") or {})
    result: dict[str, Any] = {}
    for key in (
        "active_pdf",
        "active_pdf_mode",
        "active_pdf_section",
        "active_pdf_pages",
        "active_dataset",
        "active_binding_kind",
        "active_binding_identity",
        "active_binding_owner_task_id",
        "committed_pdf",
        "committed_pdf_owner_task_id",
        "committed_dataset",
        "committed_dataset_owner_task_id",
    ):
        value = context_slots.get(key)
        if value not in ("", [], {}, None):
            result[key] = value
    bundle_refs = list(state_snapshot.get("bundle_result_refs") or [])
    if bundle_refs:
        result["bundle_result_refs"] = [
            dict(item)
            for item in bundle_refs
            if isinstance(item, dict)
        ]
    for key in ("active_object_handle_id", "active_result_handle_id", "active_subset_handle_id"):
        value = active_handles.get(key) or context_slots.get(key)
        if value not in ("", [], {}, None):
            result[key] = value
    return result


def _resolve_skill_frame(skill_registry: Any | None, task_frame: Any) -> Any | None:
    if skill_registry is None:
        return None
    try:
        from skill_system.policy import SkillPolicyResolver

        return SkillPolicyResolver(skill_registry).resolve(task_frame=task_frame)
    except Exception:
        return None


def _skill_frame_payload(skill_frame: Any | None) -> dict[str, Any]:
    if skill_frame is None:
        return {}
    payload = skill_frame.to_dict() if hasattr(skill_frame, "to_dict") else dict(skill_frame)
    prompt_view = getattr(skill_frame, "prompt_view", None)
    if prompt_view is not None:
        if hasattr(prompt_view, "to_dict"):
            payload["prompt_view"] = prompt_view.to_dict()
        if hasattr(prompt_view, "render_block"):
            payload["prompt_block"] = prompt_view.render_block()
    return payload


def _operation_ids_for_runtime(
    *,
    query_understanding: Any,
    skill_frame: Any | None,
    tool_registry: Any | None,
) -> tuple[str, ...]:
    tool_names: list[str] = []
    tool_name = str(getattr(query_understanding, "tool_name", "") or "").strip()
    if tool_name:
        tool_names.append(tool_name)
    tool_names.extend(
        str(item).strip()
        for item in list(getattr(query_understanding, "candidate_tools", []) or [])
        if str(item).strip()
    )
    if skill_frame is not None:
        tool_scope = getattr(skill_frame, "tool_scope", None)
        allowed_tools = getattr(tool_scope, "allowed_tools", ()) if tool_scope is not None else ()
        tool_names.extend(str(item).strip() for item in list(allowed_tools or []) if str(item).strip())

    operations: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        operation_id = _operation_id_for_tool(tool_registry, name)
        if not operation_id or operation_id in seen:
            continue
        seen.add(operation_id)
        operations.append(operation_id)
    return tuple(operations)


def _operation_id_for_tool(tool_registry: Any | None, tool_name: str) -> str:
    if tool_registry is None:
        return ""
    getter = getattr(tool_registry, "get_by_name", None)
    if not callable(getter):
        return ""
    definition = getter(tool_name)
    return str(getattr(definition, "operation_id", "") or "").strip()
