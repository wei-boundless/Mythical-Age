from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCALAR_FIELDS = {
    "interaction_intent",
    "action_intent",
    "execution_mode_hint",
    "task_domain_hint",
    "task_goal_type_hint",
}

SEQUENCE_FIELDS = {
    "target_objects",
    "desired_outcomes",
    "explicit_constraints",
    "forbidden_actions",
    "user_provided_flow",
    "evidence_requirements",
    "ambiguity_points",
    "assumption_set",
}

DICT_FIELDS = {"context_binding"}

MODEL_UNDERSTANDING_FIELDS = SCALAR_FIELDS | SEQUENCE_FIELDS | DICT_FIELDS


@dataclass(frozen=True, slots=True)
class ModelUnderstandingDraft:
    draft_id: str
    user_message: str
    interaction_intent: str = ""
    action_intent: str = ""
    target_objects: tuple[str, ...] = ()
    desired_outcomes: tuple[str, ...] = ()
    explicit_constraints: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    user_provided_flow: tuple[str, ...] = ()
    context_binding: dict[str, Any] = field(default_factory=dict)
    execution_mode_hint: str = ""
    task_domain_hint: str = ""
    task_goal_type_hint: str = ""
    evidence_requirements: tuple[str, ...] = ()
    ambiguity_points: tuple[str, ...] = ()
    assumption_set: tuple[str, ...] = ()
    confidence: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.model_understanding_draft"

    def __post_init__(self) -> None:
        if self.authority != "intent.model_understanding_draft":
            raise ValueError("ModelUnderstandingDraft authority must be intent.model_understanding_draft")
        if not self.draft_id:
            raise ValueError("ModelUnderstandingDraft requires draft_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in SEQUENCE_FIELDS:
            payload[key] = list(payload.get(key) or [])
        payload["context_binding"] = dict(self.context_binding or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class UnderstandingArbitration:
    arbitration_id: str
    deterministic_source_ref: str
    model_draft_ref: str = ""
    model_draft_status: str = "absent"
    resolved_values: dict[str, Any] = field(default_factory=dict)
    priority_stack: tuple[dict[str, Any], ...] = ()
    conflict_set: tuple[dict[str, Any], ...] = ()
    assumption_set: tuple[str, ...] = ()
    decision_trace: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.understanding_arbitration"

    def __post_init__(self) -> None:
        if self.authority != "intent.understanding_arbitration":
            raise ValueError("UnderstandingArbitration authority must be intent.understanding_arbitration")
        if not self.arbitration_id:
            raise ValueError("UnderstandingArbitration requires arbitration_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resolved_values"] = _public_values(dict(self.resolved_values or {}))
        payload["priority_stack"] = [dict(item) for item in self.priority_stack]
        payload["conflict_set"] = [dict(item) for item in self.conflict_set]
        payload["assumption_set"] = list(self.assumption_set)
        payload["decision_trace"] = [dict(item) for item in self.decision_trace]
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def model_understanding_draft_from_payload(
    payload: dict[str, Any] | None,
    *,
    user_message: str,
) -> tuple[ModelUnderstandingDraft | None, dict[str, Any]]:
    raw = dict(payload or {})
    if not raw:
        return None, {
            "model_draft_status": "absent",
            "model_draft_absent": True,
            "model_authority_used": False,
        }
    errors: list[str] = []
    authority = str(raw.get("authority") or "intent.model_understanding_draft").strip()
    if authority != "intent.model_understanding_draft":
        errors.append("invalid_authority")
    unknown_fields = sorted(
        key
        for key in raw
        if key
        not in {
            "draft_id",
            "user_message",
            "confidence",
            "diagnostics",
            "authority",
            *MODEL_UNDERSTANDING_FIELDS,
        }
    )
    sequence_values: dict[str, tuple[str, ...]] = {}
    for key in SEQUENCE_FIELDS:
        value = raw.get(key)
        if value in (None, ""):
            sequence_values[key] = ()
            continue
        if not isinstance(value, (list, tuple)):
            errors.append(f"{key}_must_be_list")
            sequence_values[key] = ()
            continue
        sequence_values[key] = tuple(_dedupe([str(item).strip() for item in value if str(item).strip()]))
    context_binding = raw.get("context_binding") or {}
    if not isinstance(context_binding, dict):
        errors.append("context_binding_must_be_object")
        context_binding = {}
    confidence = _confidence(raw.get("confidence"), errors)
    recognized = [
        key
        for key in MODEL_UNDERSTANDING_FIELDS
        if raw.get(key) not in (None, "", [], {})
    ]
    if not recognized:
        errors.append("no_recognized_understanding_fields")
    draft_id = str(raw.get("draft_id") or f"modeldraft:{_slug(user_message)[:48] or 'runtime'}").strip()
    diagnostics = {
        **dict(raw.get("diagnostics") or {}),
        "schema": "intent.model_understanding_draft.v1",
        "recognized_fields": recognized,
        "unknown_fields": unknown_fields,
    }
    if errors:
        return None, {
            "model_draft_status": "rejected_invalid",
            "model_draft_absent": False,
            "model_authority_used": False,
            "draft_id": draft_id,
            "validation_errors": errors,
            "unknown_fields": unknown_fields,
        }
    return (
        ModelUnderstandingDraft(
            draft_id=draft_id,
            user_message=str(raw.get("user_message") or user_message or "").strip(),
            interaction_intent=str(raw.get("interaction_intent") or "").strip(),
            action_intent=str(raw.get("action_intent") or "").strip(),
            target_objects=sequence_values["target_objects"],
            desired_outcomes=sequence_values["desired_outcomes"],
            explicit_constraints=sequence_values["explicit_constraints"],
            forbidden_actions=sequence_values["forbidden_actions"],
            user_provided_flow=sequence_values["user_provided_flow"],
            context_binding=dict(context_binding),
            execution_mode_hint=str(raw.get("execution_mode_hint") or "").strip(),
            task_domain_hint=str(raw.get("task_domain_hint") or "").strip(),
            task_goal_type_hint=str(raw.get("task_goal_type_hint") or "").strip(),
            evidence_requirements=sequence_values["evidence_requirements"],
            ambiguity_points=sequence_values["ambiguity_points"],
            assumption_set=sequence_values["assumption_set"],
            confidence=confidence,
            diagnostics=diagnostics,
        ),
        {
            "model_draft_status": "accepted",
            "model_draft_absent": False,
            "model_authority_used": True,
            "draft_id": draft_id,
            "validation_errors": [],
            "unknown_fields": unknown_fields,
        },
    )


def arbitrate_task_understanding(
    *,
    user_message: str,
    deterministic_values: dict[str, Any],
    model_understanding_draft: dict[str, Any] | None = None,
) -> UnderstandingArbitration:
    deterministic = dict(deterministic_values or {})
    source_strength = dict(deterministic.get("_source_strength") or {})
    frame_id = str(deterministic.get("frame_id") or f"understanding:{_slug(user_message)[:48] or 'runtime'}")
    draft, draft_diagnostics = model_understanding_draft_from_payload(
        model_understanding_draft,
        user_message=user_message,
    )
    resolved = _normalize_deterministic_values(deterministic)
    conflicts: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    assumptions: list[str] = []
    priority_stack = _priority_stack(source_strength=source_strength, has_model_draft=draft is not None)

    if draft is None:
        for field_name in _resolved_field_order():
            trace.append(_trace(field_name, "deterministic_fallback", "model_draft_absent_or_invalid"))
        diagnostics = {
            **draft_diagnostics,
            "arbitration_policy": "deterministic_signals_without_model_authority",
            "deterministic_signals_are_fallback": True,
        }
        return UnderstandingArbitration(
            arbitration_id=f"understanding-arbitration:{_slug(user_message)[:48] or 'runtime'}",
            deterministic_source_ref=frame_id,
            model_draft_ref=str(draft_diagnostics.get("draft_id") or ""),
            model_draft_status=str(draft_diagnostics.get("model_draft_status") or "absent"),
            resolved_values=resolved,
            priority_stack=tuple(priority_stack),
            conflict_set=(),
            assumption_set=(),
            decision_trace=tuple(trace),
            diagnostics=diagnostics,
        )

    model = draft.to_dict()
    hard_user_fields = {"explicit_constraints", "forbidden_actions", "user_provided_flow"}
    merge_fields = {"target_objects", "desired_outcomes", "evidence_requirements", "ambiguity_points"}

    for field_name in hard_user_fields:
        det_value = _sequence(resolved.get(field_name))
        model_value = _sequence(model.get(field_name))
        if det_value:
            resolved[field_name] = det_value
            if model_value and model_value != det_value:
                conflicts.append(
                    _conflict(
                        field_name,
                        deterministic_value=det_value,
                        model_value=model_value,
                        selected_source="latest_user_instruction",
                        reason="user_explicit_boundary_has_priority",
                    )
                )
            trace.append(_trace(field_name, "latest_user_instruction", "explicit_user_boundary"))
        elif model_value:
            resolved[field_name] = model_value
            trace.append(_trace(field_name, "model_understanding_draft", "model_extracted_user_boundary"))
        else:
            trace.append(_trace(field_name, "deterministic_fallback", "empty_boundary"))

    for field_name in merge_fields:
        det_value = _sequence(resolved.get(field_name))
        model_value = _sequence(model.get(field_name))
        merged = _dedupe([*det_value, *model_value])
        resolved[field_name] = merged
        if model_value and det_value and model_value != det_value:
            trace.append(_trace(field_name, "merged_deterministic_and_model", "model_enriched_signal"))
        else:
            trace.append(_trace(field_name, "model_understanding_draft" if model_value else "deterministic_fallback", "sequence_signal"))

    for field_name in ("interaction_intent", "action_intent", "execution_mode_hint", "task_domain_hint", "task_goal_type_hint"):
        det_value = str(resolved.get(field_name) or "").strip()
        model_value = str(model.get(field_name) or "").strip()
        selected_source = "deterministic_fallback"
        reason = "model_value_absent"
        if field_name in {"task_domain_hint", "task_goal_type_hint"} and source_strength.get(field_name) == "caller_hint" and det_value:
            selected_source = "caller_goal_hint"
            reason = "upstream_goal_or_domain_hint_has_priority"
            if model_value and model_value != det_value:
                conflicts.append(
                    _conflict(
                        field_name,
                        deterministic_value=det_value,
                        model_value=model_value,
                        selected_source=selected_source,
                        reason="model_conflicts_with_authoritative_hint",
                    )
                )
        elif model_value:
            selected_source = "model_understanding_draft"
            reason = "model_authority_for_interpretive_field"
            det_value = model_value
        resolved[field_name] = det_value
        trace.append(_trace(field_name, selected_source, reason))

    resolved_context = _resolved_context_binding(
        deterministic=dict(resolved.get("context_binding") or {}),
        model=dict(model.get("context_binding") or {}),
        trace=trace,
    )
    resolved["context_binding"] = resolved_context
    assumptions.extend(_sequence(model.get("assumption_set")))
    conflicts.extend(_hard_policy_conflicts(resolved=resolved, model=model))
    diagnostics = {
        **draft_diagnostics,
        "arbitration_policy": "latest_user_instruction_then_contract_hint_then_model_then_deterministic",
        "deterministic_signals_are_fallback": False,
        "model_draft_confidence": draft.confidence,
    }
    return UnderstandingArbitration(
        arbitration_id=f"understanding-arbitration:{_slug(user_message)[:48] or 'runtime'}",
        deterministic_source_ref=frame_id,
        model_draft_ref=draft.draft_id,
        model_draft_status="accepted",
        resolved_values=resolved,
        priority_stack=tuple(priority_stack),
        conflict_set=tuple(conflicts),
        assumption_set=tuple(_dedupe(assumptions)),
        decision_trace=tuple(trace),
        diagnostics=diagnostics,
    )


def _normalize_deterministic_values(values: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(values or {})
    for key in SEQUENCE_FIELDS - {"assumption_set"}:
        resolved[key] = _sequence(resolved.get(key))
    resolved["context_binding"] = dict(resolved.get("context_binding") or {})
    for key in SCALAR_FIELDS:
        resolved[key] = str(resolved.get(key) or "").strip()
    return resolved


def _resolved_context_binding(
    *,
    deterministic: dict[str, Any],
    model: dict[str, Any],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    deterministic_kind = str(deterministic.get("kind") or "").strip()
    model_kind = str(model.get("kind") or "").strip()
    if deterministic_kind and deterministic_kind != "current_turn":
        if model_kind and model_kind != deterministic_kind:
            trace.append(_trace("context_binding", "deterministic_context", "continuation_or_runtime_context_has_priority"))
        else:
            trace.append(_trace("context_binding", "deterministic_context", "context_already_bound"))
        return deterministic
    if model:
        trace.append(_trace("context_binding", "model_understanding_draft", "model_bound_context"))
        return model
    trace.append(_trace("context_binding", "deterministic_fallback", "current_turn_context"))
    return deterministic


def _hard_policy_conflicts(*, resolved: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    forbidden = set(_sequence(resolved.get("forbidden_actions")))
    model_action = str(model.get("action_intent") or "").strip()
    model_mode = str(model.get("execution_mode_hint") or "").strip()
    if "modify_workspace" in forbidden and (
        model_action in {"modify", "create", "execute"} or model_mode in {"implementation", "agent_execution"}
    ):
        conflicts.append(
            _conflict(
                "forbidden_actions",
                deterministic_value=sorted(forbidden),
                model_value={"action_intent": model_action, "execution_mode_hint": model_mode},
                selected_source="latest_user_instruction",
                reason="model_action_conflicts_with_user_forbidden_workspace_change",
            )
        )
        resolved["action_intent"] = "answer" if model_action in {"modify", "create", "execute"} else str(resolved.get("action_intent") or "")
        resolved["execution_mode_hint"] = "analysis_only"
    if "network_lookup" in forbidden and model_action == "research":
        conflicts.append(
            _conflict(
                "forbidden_actions",
                deterministic_value=sorted(forbidden),
                model_value={"action_intent": model_action},
                selected_source="latest_user_instruction",
                reason="model_action_conflicts_with_user_forbidden_network_lookup",
            )
        )
        resolved["action_intent"] = "answer"
    return conflicts


def _priority_stack(*, source_strength: dict[str, Any], has_model_draft: bool) -> list[dict[str, Any]]:
    return [
        {
            "priority": 1000,
            "source": "latest_user_instruction",
            "applies_to": ["explicit_constraints", "forbidden_actions", "user_provided_flow"],
        },
        {
            "priority": 850,
            "source": "upstream_goal_or_domain_hint",
            "applies_to": [
                key
                for key in ("task_goal_type_hint", "task_domain_hint")
                if source_strength.get(key) == "caller_hint"
            ],
        },
        {
            "priority": 700,
            "source": "model_understanding_draft",
            "applies_to": sorted(SCALAR_FIELDS | {"context_binding"}) if has_model_draft else [],
        },
        {
            "priority": 500,
            "source": "deterministic_signal",
            "applies_to": sorted(MODEL_UNDERSTANDING_FIELDS - {"assumption_set"}),
        },
        {
            "priority": 100,
            "source": "default_fallback",
            "applies_to": ["execution_mode_hint", "task_domain_hint", "desired_outcomes"],
        },
    ]


def _resolved_field_order() -> list[str]:
    return [
        "interaction_intent",
        "action_intent",
        "target_objects",
        "desired_outcomes",
        "explicit_constraints",
        "forbidden_actions",
        "user_provided_flow",
        "context_binding",
        "execution_mode_hint",
        "task_domain_hint",
        "task_goal_type_hint",
        "evidence_requirements",
        "ambiguity_points",
    ]


def _trace(field_name: str, selected_source: str, reason: str) -> dict[str, Any]:
    return {
        "field": field_name,
        "selected_source": selected_source,
        "reason": reason,
    }


def _conflict(
    field_name: str,
    *,
    deterministic_value: Any,
    model_value: Any,
    selected_source: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "field": field_name,
        "deterministic_value": deterministic_value,
        "model_value": model_value,
        "selected_source": selected_source,
        "reason": reason,
    }


def _public_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if not key.startswith("_")}


def _confidence(value: Any, errors: list[str]) -> float:
    if value in (None, ""):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors.append("confidence_must_be_number")
        return 0.0
    if parsed < 0.0 or parsed > 1.0:
        errors.append("confidence_must_be_between_0_and_1")
        return min(max(parsed, 0.0), 1.0)
    return parsed


def _sequence(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return _dedupe([str(item).strip() for item in value if str(item).strip()])
    return _dedupe([str(value).strip()])


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
