from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from continuation import collect_continuation_candidates, decide_continuation
from context_system import ContextResolver
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from task_system.registry.flow_registry import TaskFlowRegistry
from request_intent.memory_intent import analyze_memory_intent
from request_intent.request_signals import RequestSignals, build_request_signals

from runtime.agent_assembly.boundary import (
    build_model_context_payload,
    build_task_selection_payload,
    build_turn_context_payload,
)
from runtime.context_management.system_retrieval import task_operation_requests_context_retrieval
from ..identity import normalize_agent_id
from ..profiles.runtime_profile_registry import AgentRuntimeRegistry
from .runtime_bundle_builder import build_orchestration_runtime_bundle


class AgentRuntimeChainAssembler:
    """Builds task understanding and turn context for the current agent lane."""

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
        current_turn_context_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        turn_memory_cache: dict[str, Any] = {}
        task_selection_payload = build_task_selection_payload(
            task_selection=task_selection,
        )
        effective_agent_runtime_profile = agent_runtime_profile
        selected_agent_id = normalize_agent_id(
            str(task_selection_payload.get("agent_id") or "").strip()
        )
        task_default_agent_id = _resolve_task_selection_default_agent_id(
            self.base_dir,
            task_selection=task_selection_payload,
        )
        if not selected_agent_id and task_default_agent_id:
            selected_agent_id = task_default_agent_id
        if selected_agent_id:
            task_selection_payload["agent_id"] = selected_agent_id
        if effective_agent_runtime_profile is None:
            if selected_agent_id:
                effective_agent_runtime_profile = AgentRuntimeRegistry(self.base_dir).get_profile(selected_agent_id)
                if effective_agent_runtime_profile is None:
                    raise ValueError(f"TaskGraph node agent has no runtime profile: {selected_agent_id}")
        elif selected_agent_id and normalize_agent_id(str(getattr(effective_agent_runtime_profile, "agent_id", "") or "").strip()) != selected_agent_id:
            raise ValueError(
                "TaskGraph node agent profile mismatch: "
                f"requested {selected_agent_id}, got {getattr(effective_agent_runtime_profile, 'agent_id', '')}"
        )
        memory_intent = analyze_memory_intent(message)
        initial_memory_request_profile = _memory_request_profile_for_context_assembly(
            {},
            task_selection=task_selection_payload,
        )
        memory_view = self.build_memory_runtime_view(
            turn_memory_cache=turn_memory_cache,
            task_id=task_id,
            agent_id=str(getattr(effective_agent_runtime_profile, "agent_id", "") or "agent:0"),
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
            memory_request_profile=initial_memory_request_profile,
        )
        memory_payload = _to_dict(memory_view)
        query_understanding = build_request_signals(
            message,
            memory_intent,
            current_turn_context=task_selection_payload,
        )
        query_understanding = _align_understanding_with_explicit_task_selection(
            self.base_dir,
            query_understanding,
            task_selection=task_selection_payload,
        )
        if _should_request_state_recall(message=message, query_understanding=query_understanding):
            memory_view = self.build_memory_runtime_view(
                turn_memory_cache=turn_memory_cache,
                task_id=task_id,
                agent_id=str(getattr(effective_agent_runtime_profile, "agent_id", "") or "agent:0"),
                session_id=session_id,
                message=message,
                memory_intent=memory_intent,
                memory_request_profile={
                    "requested_memory_layers": ["state"],
                    "state_read_mode": "recall_candidates",
                    "memory_scope_hint": "intent_gated_state_recall",
                    "allow_long_term_memory": False,
                },
            )
            memory_payload = _to_dict(memory_view)
            query_understanding = build_request_signals(
                message,
                memory_intent,
                current_turn_context=task_selection_payload,
            )
            query_understanding = _align_understanding_with_explicit_task_selection(
                self.base_dir,
                query_understanding,
                task_selection=task_selection_payload,
            )
        continuation_candidates = collect_continuation_candidates(
            message=message,
            memory_runtime_view=memory_payload,
            request_intent=query_understanding,
        )
        continuation_decision = decide_continuation(
            candidates=continuation_candidates,
            request_intent=query_understanding,
        )
        override_payload = build_turn_context_payload(
            current_turn_context=current_turn_context_override
        )
        selection_override_payload = build_turn_context_payload(
            current_turn_context=task_selection_payload
        )
        early_context_payload = {
            **override_payload,
            **selection_override_payload,
        }
        agent_turn_action_request = dict(early_context_payload.get("agent_turn_action_request") or {})
        task_contract_seed = dict(
            early_context_payload.get("task_contract_seed")
            or agent_turn_action_request.get("task_contract_seed")
            or {}
        )
        query_understanding_payload = {
            **query_understanding.to_dict(),
            "agent_turn_action_request": agent_turn_action_request,
            "task_contract_seed": task_contract_seed,
            "runtime_admission": dict(early_context_payload.get("runtime_admission") or {}),
        }
        task_goal_spec = _task_goal_spec_from_admitted_contract(
            message=message,
            agent_turn_action_request=agent_turn_action_request,
            task_contract_seed=task_contract_seed,
            query_understanding=query_understanding_payload,
            explicit_task_goal_spec=dict(early_context_payload.get("task_goal_spec") or {}),
            explicit_semantic_task_type=str(early_context_payload.get("semantic_task_type") or ""),
        )
        current_turn_context = ContextResolver().resolve(
            session_id=session_id,
            task_id=task_id,
            user_message=message,
            memory_runtime_view=memory_payload,
            query_understanding=query_understanding_payload,
            task_goal_spec=task_goal_spec,
            continuation_candidates=[item.to_dict() for item in continuation_candidates],
            continuation_decision=continuation_decision.to_dict(),
        )
        current_turn_context_payload = current_turn_context.to_dict()
        if override_payload:
            current_turn_context_payload.update(override_payload)
        if turn_id:
            current_turn_context_payload["turn_id"] = turn_id
        if selection_override_payload:
            current_turn_context_payload.update(selection_override_payload)
        task_bundle = build_task_execution_assembly_bundle(
            base_dir=self.base_dir,
            session_id=session_id,
            task_id=task_id,
            user_goal=message,
            source=source,
            query_understanding=query_understanding_payload,
            current_turn_context=current_turn_context_payload,
            agent_runtime_profile=effective_agent_runtime_profile,
        )
        context_payload: dict[str, Any] = {}
        task_operation: dict[str, Any] = dict(task_bundle)
        memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
        memory_request_profile = _memory_request_profile_for_context_assembly(
            memory_request_profile,
            task_selection=task_selection_payload,
            current_turn_context=current_turn_context_payload,
        )
        task_operation["task_memory_request_profile"] = memory_request_profile
        memory_view = self.build_memory_runtime_view(
            turn_memory_cache=turn_memory_cache,
            task_id=task_id,
            agent_id=str(getattr(effective_agent_runtime_profile, "agent_id", "") or "agent:0"),
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )
        memory_payload = _to_dict(memory_view)
        context_policy_result = self.build_context_policy_result(
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            memory_runtime_view=memory_view,
            retrieval_allowed=task_operation_requests_context_retrieval(task_operation),
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

    def build_memory_runtime_view(
        self,
        *,
        turn_memory_cache: dict[str, Any] | None = None,
        task_id: str = "task-runtime",
        agent_id: str = "agent:0",
        session_id: str,
        message: str,
        memory_intent: Any,
        memory_request_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cache_key = _turn_memory_cache_key(
            task_id=task_id,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )
        if turn_memory_cache is not None and cache_key in turn_memory_cache:
            return turn_memory_cache[cache_key]
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
            runtime_view = getattr(bundle, "runtime_view", None)
            if runtime_view is None:
                payload = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle)
                runtime_view = dict(payload.get("runtime_view") or {})
            if turn_memory_cache is not None:
                turn_memory_cache[cache_key] = runtime_view
            return runtime_view
        builder = getattr(self.memory_facade, "build_memory_runtime_view", None)
        if not callable(builder):
            return {}
        view = builder(
            session_id=session_id,
            query=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
        )
        if turn_memory_cache is not None:
            turn_memory_cache[cache_key] = view
        return view

    def build_memory_runtime_view_payload(self, **kwargs) -> dict[str, Any]:
        return _to_dict(self.build_memory_runtime_view(**kwargs))

    def build_context_policy_result(
        self,
        *,
        session_id: str,
        message: str | None,
        memory_intent: Any,
        memory_request_profile: dict[str, Any] | None = None,
        memory_runtime_view: Any | None = None,
        relevant_memory_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        retrieval_allowed: bool = True,
    ):
        builder = getattr(self.memory_facade, "build_memory_context_package", None)
        if not callable(builder):
            return None
        if not retrieval_allowed:
            retrieval_results = None
        return builder(
            session_id=session_id,
            pending_user_message=message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            memory_view=memory_runtime_view,
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
        retrieval_allowed: bool = True,
    ):
        result = self.build_context_policy_result(
            session_id=session_id,
            message=pending_user_message,
            memory_intent=memory_intent or analyze_memory_intent(pending_user_message or ""),
            relevant_memory_notes=relevant_memory_notes,
            retrieval_results=retrieval_results,
            retrieval_allowed=retrieval_allowed,
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


def _turn_memory_cache_key(
    *,
    task_id: str,
    agent_id: str,
    session_id: str,
    message: str,
    memory_intent: Any,
    memory_request_profile: dict[str, Any] | None,
) -> str:
    payload = {
        "task_id": str(task_id or ""),
        "agent_id": str(agent_id or ""),
        "session_id": str(session_id or ""),
        "message": str(message or ""),
        "memory_intent": _to_dict(memory_intent) if hasattr(memory_intent, "to_dict") or isinstance(memory_intent, dict) else str(memory_intent or ""),
        "memory_request_profile": dict(memory_request_profile or {}),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _memory_request_profile_for_context_assembly(
    memory_request_profile: dict[str, Any],
    *,
    task_selection: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    runtime_assembly: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = _context_assembly_policy_from_payloads(
        {"runtime_assembly": dict(runtime_assembly or {})},
        task_selection,
        current_turn_context,
    )
    if not bool(policy.get("suppress_conversation_memory")):
        return dict(memory_request_profile or {})
    profile = dict(memory_request_profile or {})
    requested_layers = [
        str(item).strip()
        for item in list(profile.get("requested_memory_layers") or [])
        if str(item).strip() and str(item).strip() != "conversation"
    ]
    profile["requested_memory_layers"] = requested_layers
    profile["allow_long_term_memory"] = False
    profile["conversation_memory_suppressed"] = True
    metadata = dict(profile.get("metadata") or {})
    metadata["context_assembly_policy"] = "suppress_conversation_memory"
    profile["metadata"] = metadata
    return profile


def _should_request_state_recall(*, message: str, query_understanding: RequestSignals) -> bool:
    payload = query_understanding.to_dict()
    signals = dict(payload.get("turn_signals") or {})
    capability = dict(payload.get("capability_intent") or {})
    if signals.get("explicit_paths"):
        return False
    needs = {str(item).strip() for item in list(capability.get("capability_needs") or []) if str(item).strip()}
    if needs & {"weather", "gold_price", "latest_information"}:
        return False
    if bool(signals.get("external_context_required")):
        return False
    if bool(signals.get("memory_recall_required")):
        return False
    text = str(message or "").lower()
    has_followup_language = any(
        marker in text
        for marker in (
            "继续",
            "再",
            "刚才",
            "这些",
            "这个",
            "这份",
            "回到",
            "展开一下",
            "只基于",
            "上面",
            "前五",
            "不要回到",
        )
    )
    if not has_followup_language:
        return False
    material_kinds = {str(item).strip() for item in list(signals.get("material_kinds") or []) if str(item).strip()}
    if material_kinds & {"dataset", "pdf"}:
        return True
    return any(token in text for token in ("pdf", "报告", "表", "数据", "员工", "仓库", "库存", "第", "页"))


def _context_assembly_policy_from_payloads(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    for payload in payloads:
        policy = _context_assembly_policy_from_payload(payload)
        if policy:
            return policy
    return {}


def _context_assembly_policy_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    item = dict(payload or {})
    runtime_assembly = dict(item.get("runtime_assembly") or {})
    diagnostics = dict(runtime_assembly.get("diagnostics") or {})
    return dict(runtime_assembly.get("context_assembly_policy") or diagnostics.get("context_assembly_policy") or {})


def _align_understanding_with_explicit_task_selection(
    base_dir: Path,
    query_understanding: RequestSignals,
    *,
    task_selection: dict[str, Any],
) -> RequestSignals:
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

    record_policy = dict(getattr(record, "task_policy", {}) or {})
    record_structure = dict(record_policy.get("task_structure") or {})
    record_metadata = dict(getattr(record, "metadata", {}) or {})
    record_task_mode = str(
        record_metadata.get("task_mode")
        or record_structure.get("task_mode")
        or "task_runtime"
    ).strip()
    signals = dict(query_understanding.turn_signals or {})
    signals.update(
        {
            "selected_task_id": selected_task_id,
            "selected_task_mode": record_task_mode,
            "explicit_task_selection": True,
        }
    )
    context_binding = {
        "kind": "explicit_task_selection",
        "selected_task_id": selected_task_id,
        "selected_task_mode": record_task_mode,
    }
    return RequestSignals(
        frame_id=query_understanding.frame_id,
        user_message=query_understanding.user_message,
        structural_signals=signals,
        capability_needs=(),
        target_domain_hints=("task_system",),
        context_binding=context_binding,
        decision_trace=(
            *tuple(query_understanding.decision_trace or ()),
            {
                "stage": "context_binding",
                "decision": "explicit_task_selection",
                "reason": "selected task record binds context only; model turn decision still owns intent and execution mode",
            },
        ),
        confidence=1.0,
    )


def _resolve_task_selection_default_agent_id(
    base_dir: Path,
    *,
    task_selection: dict[str, Any],
) -> str:
    selected_task_id = str(
        task_selection.get("selected_task_id")
        or task_selection.get("task_id")
        or task_selection.get("specific_task_id")
        or task_selection.get("task_assignment_id")
        or ""
    ).strip()
    if not selected_task_id:
        return ""
    registry = TaskFlowRegistry(base_dir)
    execution_policy = registry.get_task_execution_policy(selected_task_id)
    if execution_policy is not None:
        agent_id = normalize_agent_id(str(execution_policy.default_agent_id or "").strip())
        if agent_id:
            return agent_id
    record = registry.get_specific_task_record(selected_task_id)
    if record is not None:
        flow_id = str(record.default_flow_contract_id or f"flow.{selected_task_id.removeprefix('task.')}").strip()
        flow = registry.get_flow(flow_id)
        agent_id = normalize_agent_id(str(getattr(flow, "default_agent_id", "") or "").strip())
        if agent_id:
            return agent_id
    general_profile = registry.get_general_task_profile(selected_task_id)
    if general_profile is not None:
        return normalize_agent_id(str(general_profile.default_agent_id or "").strip())
    return ""
def _task_goal_spec_from_admitted_contract(
    *,
    message: str,
    agent_turn_action_request: dict[str, Any],
    task_contract_seed: dict[str, Any],
    query_understanding: dict[str, Any],
    explicit_task_goal_spec: dict[str, Any] | None = None,
    explicit_semantic_task_type: str = "",
) -> dict[str, Any]:
    explicit_goal = _authoritative_explicit_task_goal_spec(
        explicit_task_goal_spec,
        task_contract_seed=task_contract_seed,
    )
    seed_task_goal_type = str(task_contract_seed.get("task_goal_type") or "").strip()
    selected_task_goal_type = str(explicit_semantic_task_type or "").strip()
    if explicit_goal:
        task_goal_type = str(explicit_goal.get("task_goal_type") or "").strip()
        task_domain = str(explicit_goal.get("task_domain") or "").strip() or "general"
    elif selected_task_goal_type:
        task_goal_type = selected_task_goal_type
        task_domain = _domain_for_concrete_task_goal(selected_task_goal_type)
    elif seed_task_goal_type:
        task_goal_type = seed_task_goal_type
        task_domain = _domain_for_concrete_task_goal(seed_task_goal_type)
    else:
        task_goal_type = "general"
        task_domain = "general"
    deliverables = [
        {"deliverable_id": _slug(value), "title": value, "kind": "deliverable", "role": "core", "required": True, "metadata": {}}
        for value in list(task_contract_seed.get("deliverables") or [])
        if str(value).strip()
    ]
    criteria = [
        {"criterion_id": _slug(value), "title": value, "verification_kind": "evidence", "required": True, "metadata": {}}
        for value in list(task_contract_seed.get("completion_criteria") or [])
        if str(value).strip()
    ]
    projected = {
        "authority": "agent_runtime.admitted_task_goal_projection",
        "user_goal": str(message or "").strip(),
        "goal_summary": str(task_contract_seed.get("goal") or message or "").strip()[:240],
        "task_goal_type": task_goal_type,
        "task_domain": task_domain,
        "complexity": "long_running",
        "core_deliverables": deliverables,
        "supporting_deliverables": [],
        "success_criteria": criteria,
        "required_capabilities": [],
        "required_verifications": criteria,
        "explicit_constraints": list(task_contract_seed.get("constraints") or []),
        "forbidden_actions": list(task_contract_seed.get("forbidden_actions") or []),
        "unacceptable_outcomes": ["invent_evidence", "execute_without_admitted_task_contract"],
        "ambiguity_points": [],
        "clarification_policy": {
            "clarification_needed": False,
            "question": "",
        },
        "evidence": {
            "agent_turn_action_request": agent_turn_action_request,
            "task_contract_seed": task_contract_seed,
            "request_signals_diagnostics_only": query_understanding,
            "explicit_semantic_task_type": selected_task_goal_type,
        },
        "confidence": 1.0 if task_contract_seed else 0.0,
    }
    if not explicit_goal:
        return projected
    merged = {
        **projected,
        **explicit_goal,
        "authority": str(explicit_goal.get("authority") or projected["authority"]),
        "user_goal": str(explicit_goal.get("user_goal") or projected["user_goal"]),
        "goal_summary": str(explicit_goal.get("goal_summary") or projected["goal_summary"]),
        "task_goal_type": task_goal_type,
        "task_domain": task_domain,
        "core_deliverables": list(explicit_goal.get("core_deliverables") or projected["core_deliverables"]),
        "supporting_deliverables": list(explicit_goal.get("supporting_deliverables") or projected["supporting_deliverables"]),
        "success_criteria": list(explicit_goal.get("success_criteria") or projected["success_criteria"]),
        "required_capabilities": list(explicit_goal.get("required_capabilities") or projected["required_capabilities"]),
        "required_verifications": list(explicit_goal.get("required_verifications") or projected["required_verifications"]),
        "explicit_constraints": list(explicit_goal.get("explicit_constraints") or projected["explicit_constraints"]),
        "forbidden_actions": list(explicit_goal.get("forbidden_actions") or projected["forbidden_actions"]),
        "unacceptable_outcomes": list(explicit_goal.get("unacceptable_outcomes") or projected["unacceptable_outcomes"]),
        "ambiguity_points": list(explicit_goal.get("ambiguity_points") or projected["ambiguity_points"]),
        "clarification_policy": dict(explicit_goal.get("clarification_policy") or projected["clarification_policy"]),
        "evidence": {
            **dict(projected.get("evidence") or {}),
            **dict(explicit_goal.get("evidence") or {}),
            "explicit_task_goal_spec": explicit_goal,
        },
        "confidence": float(explicit_goal.get("confidence") or projected["confidence"]),
    }
    return merged


def _authoritative_explicit_task_goal_spec(
    explicit_task_goal_spec: dict[str, Any] | None,
    *,
    task_contract_seed: dict[str, Any],
) -> dict[str, Any]:
    goal = dict(explicit_task_goal_spec or {})
    task_goal_type = str(goal.get("task_goal_type") or "").strip()
    if not task_goal_type:
        return {}
    authority = str(goal.get("authority") or "").strip()
    if authority and authority != "agent_runtime.admitted_task_goal_projection":
        return {}
    _ = task_contract_seed
    return goal


def _domain_for_concrete_task_goal(task_goal_type: str) -> str:
    if str(task_goal_type or "").strip() in {
        "test_report_triage",
        "runtime_trace_analysis",
        "code_fix_execution",
        "regression_test_design",
        "artifact_delivery",
        "frontend_app_delivery",
        "game_vertical_slice_delivery",
        "implementation",
        "verification",
        "inspection",
    }:
        return "workspace"
    return "general"


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "item"


