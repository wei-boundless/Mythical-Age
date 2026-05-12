from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from capability_system.local_mcp_registry import get_local_mcp_unit
from context_management import ContextResolver
from tasks.assembly_builder import build_task_execution_assembly_bundle
from tasks.flow_registry import TaskFlowRegistry
from understanding.capability_resolution_view import capability_resolution_view
from understanding.memory_intent import analyze_memory_intent
from understanding.query_understanding import analyze_query_understanding

from .agent_runtime_registry import AgentRuntimeRegistry
from .assembly_builder import build_orchestration_runtime_bundle


class AgentRuntimeChainAssembler:
    """Assembles the current single-agent runtime chain."""

    def __init__(self, *, base_dir: Path, memory_facade, skill_registry=None, tool_registry=None) -> None:
        self.base_dir = Path(base_dir)
        self.memory_facade = memory_facade
        self.skill_registry = skill_registry
        self.tool_registry = tool_registry

    def build_runtime(
        self,
        *,
        session_id: str,
        task_id: str,
        turn_id: str = "",
        message: str,
        source: str,
        task_selection: dict[str, Any] | None = None,
        agent_runtime_profile: Any | None = None,
    ) -> dict[str, Any]:
        task_selection_payload = dict(task_selection or {})
        effective_agent_runtime_profile = agent_runtime_profile
        if effective_agent_runtime_profile is None:
            selected_agent_id = str(task_selection_payload.get("agent_id") or "").strip()
            if selected_agent_id:
                effective_agent_runtime_profile = AgentRuntimeRegistry(self.base_dir).get_profile(selected_agent_id)
        memory_intent = analyze_memory_intent(message)
        memory_payload = self.build_memory_runtime_view_payload(
            task_id=task_id,
            agent_id=str(getattr(effective_agent_runtime_profile, "agent_id", "") or "agent:0"),
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
        query_understanding = _align_understanding_with_explicit_task_selection(
            self.base_dir,
            query_understanding,
            task_selection=task_selection_payload,
        )
        current_turn_context = ContextResolver().resolve(
            session_id=session_id,
            task_id=task_id,
            user_message=message,
            memory_runtime_view=memory_payload,
            query_understanding=asdict(query_understanding),
        )
        current_turn_context_payload = current_turn_context.to_dict()
        if turn_id:
            current_turn_context_payload["turn_id"] = turn_id
        if task_selection:
            current_turn_context_payload.update(
                {
                    key: value
                    for key, value in dict(task_selection or {}).items()
                    if value not in ("", None, [], {})
                }
            )
        skill_frame = _resolve_skill_frame(self.skill_registry, query_understanding)
        task_bundle = build_task_execution_assembly_bundle(
            base_dir=self.base_dir,
            session_id=session_id,
            task_id=task_id,
            user_goal=message,
            source=source,
            query_understanding=asdict(query_understanding),
            current_turn_context=current_turn_context_payload,
            active_skill=_skill_frame_payload(skill_frame),
            runtime_required_operations=_operation_ids_for_runtime(
                query_understanding=query_understanding,
                skill_frame=skill_frame,
                tool_registry=self.tool_registry,
            ),
            agent_runtime_profile=effective_agent_runtime_profile,
        )
        context_payload: dict[str, Any] = {}
        task_operation: dict[str, Any] = dict(task_bundle)
        memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
        memory_payload = self.build_memory_runtime_view_payload(
            task_id=task_id,
            agent_id=str(getattr(effective_agent_runtime_profile, "agent_id", "") or "agent:0"),
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
        orchestration_bundle = build_orchestration_runtime_bundle(
            base_dir=self.base_dir,
            session_id=session_id,
            task_id=task_id,
            user_goal=message,
            task_assembly_bundle=task_bundle,
            memory_runtime_view=memory_payload,
            context_policy_result=context_payload,
            current_turn_context=current_turn_context_payload,
            active_skill=_skill_frame_payload(skill_frame),
            agent_runtime_profile=effective_agent_runtime_profile,
        )
        task_operation.update(
            {
                "memory_runtime_view": memory_payload,
                "context_policy_result": context_payload,
                "task_body_orchestration": dict(orchestration_bundle.get("task_body_orchestration") or {}),
                "agent_runtime_spec": dict(orchestration_bundle.get("agent_runtime_spec") or {}),
                "agent_body_profile": dict(orchestration_bundle.get("agent_body_profile") or {}),
                "prompt_structure_profile": dict(orchestration_bundle.get("prompt_structure_profile") or {}),
                "memory_scope_profile": dict(orchestration_bundle.get("memory_scope_profile") or {}),
                "runtime_lane_profile": dict(orchestration_bundle.get("runtime_lane_profile") or {}),
                "output_boundary_profile": dict(orchestration_bundle.get("output_boundary_profile") or {}),
            }
        )
        return {
            "memory_runtime_view": memory_payload,
            "context_policy_result": context_payload,
            "current_turn_context": current_turn_context_payload,
            "task_operation": task_operation,
            "task_execution_assembly": dict(task_operation.get("task_execution_assembly") or {}),
            "task_body_orchestration": dict(task_operation.get("task_body_orchestration") or {}),
            "agent_runtime_spec": dict(task_operation.get("agent_runtime_spec") or {}),
            "status": "runtime",
            "runtime_executable": True,
        }

    def build_memory_runtime_view_payload(
        self,
        *,
        task_id: str = "task-runtime",
        agent_id: str = "agent:0",
        session_id: str,
        message: str,
        memory_intent: Any,
        memory_request_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bundle_builder = getattr(self.memory_facade, "build_memory_bundle", None)
        if callable(bundle_builder):
            bundle = bundle_builder(
                task_id=task_id,
                session_id=session_id,
                agent_id=agent_id,
                query=message,
                memory_intent=memory_intent,
                memory_request_profile=memory_request_profile,
            )
            payload = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle)
            return dict(payload.get("runtime_view") or {})
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


def _align_understanding_with_explicit_task_selection(
    base_dir: Path,
    query_understanding: Any,
    *,
    task_selection: dict[str, Any],
) -> Any:
    selected_task_id = str(
        task_selection.get("selected_task_id")
        or task_selection.get("task_id")
        or task_selection.get("specific_task_id")
        or ""
    ).strip()
    if not selected_task_id:
        return query_understanding
    try:
        record = TaskFlowRegistry(base_dir).get_specific_task_record(selected_task_id)
    except Exception:
        record = None
    if record is None:
        return query_understanding

    metadata = dict(record.metadata or {})
    template_id = str(metadata.get("template_id") or "").strip()
    query_understanding.intent = f"{record.task_mode}_task"
    query_understanding.source_kind = "task_system"
    query_understanding.task_kind = record.task_mode
    query_understanding.modality = record.task_family or "task"
    query_understanding.route = "agent"
    query_understanding.execution_posture = "task_runtime"
    query_understanding.direct_route_reason = "explicit_task_selection"
    query_understanding.preferred_skill = None
    query_understanding.skill_name = None
    query_understanding.tool_name = None
    query_understanding.capability_requests = []
    query_understanding.candidate_tools = []
    query_understanding.tool_input = {"selected_task_id": selected_task_id}
    query_understanding.should_skip_rag = True
    query_understanding.confidence = 1.0
    query_understanding.reasons = [
        "explicit_task_selection",
        *[reason for reason in list(query_understanding.reasons or []) if reason != "explicit_task_selection"],
    ]
    signals = dict(query_understanding.structural_signals or {})
    signals.update(
        {
            "selected_task_id": selected_task_id,
            "selected_task_family": record.task_family,
            "selected_task_mode": record.task_mode,
            "selected_template_id": template_id,
            "understanding_aligned_to_explicit_task": True,
        }
    )
    query_understanding.structural_signals = signals
    return query_understanding


def _resolve_skill_frame(skill_registry: Any | None, task_frame: Any) -> Any | None:
    if skill_registry is None:
        return None
    try:
        from capability_system.skill_policy import SkillPolicyResolver

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
    _ = skill_frame
    operations: list[str] = []
    seen: set[str] = set()
    resolution = capability_resolution_view(query_understanding)
    effective_route = resolution.route
    effective_skill = resolution.preferred_skill
    if effective_route == "memory" or str(getattr(query_understanding, "execution_posture", "") or "") == "direct_memory":
        return ("op.memory_read",)
    if effective_route == "rag" or effective_skill == "rag-skill":
        mcp_unit = get_local_mcp_unit("retrieval")
    elif effective_route == "pdf" or effective_skill == "pdf-analysis":
        mcp_unit = get_local_mcp_unit("pdf")
    elif effective_route == "structured_data" or effective_skill == "structured-data-analysis":
        mcp_unit = get_local_mcp_unit("structured_data")
    else:
        mcp_unit = None
    if mcp_unit is not None:
        operation_id = str(getattr(mcp_unit, "operation_id", "") or "").strip()
        if operation_id:
            return (operation_id,)

    tool_names: list[str] = []
    tool_name = str(getattr(query_understanding, "tool_name", "") or "").strip()
    if tool_name:
        tool_names.append(tool_name)
    tool_names.extend(
        str(item).strip()
        for item in list(getattr(query_understanding, "candidate_tools", []) or [])
        if str(item).strip()
    )
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
