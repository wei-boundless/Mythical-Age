from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


INTERACTION_INTENTS = {"answer", "explain", "inspect", "review", "plan", "modify", "create", "run", "verify", "continue", "stop", "restore"}
ACTION_INTENTS = {"answer_only", "read_context", "search_external", "edit_workspace", "run_command", "start_service", "use_browser", "delegate", "ask_clarification", "block"}
WORK_MODES = {"conversation", "read_only_analysis", "implementation", "verification", "planning", "delegated", "background"}


@dataclass(frozen=True, slots=True)
class ModelTurnDecision:
    decision_id: str
    user_message: str
    interaction_intent: str
    action_intent: str
    work_mode: str
    task_goal_type: str = ""
    task_domain: str = ""
    target_objects: tuple[str, ...] = ()
    desired_outcome: str = ""
    deliverables: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    selected_skill_ids: tuple[str, ...] = ()
    resource_contract: dict[str, Any] = field(default_factory=dict)
    context_binding_decision: dict[str, Any] = field(default_factory=dict)
    planning_required: bool = False
    todo_required: bool = False
    completion_criteria: tuple[str, ...] = ()
    needs_clarification: bool = False
    clarification_question: str = ""
    confidence: float = 0.0
    ambiguity: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.model_turn_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "target_objects",
            "deliverables",
            "constraints",
            "forbidden_actions",
            "selected_skill_ids",
            "completion_criteria",
            "ambiguity",
        ):
            payload[key] = list(payload.get(key) or [])
        payload["context_binding_decision"] = dict(self.context_binding_decision or {})
        payload["resource_contract"] = dict(self.resource_contract or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def model_turn_decision_from_payload(
    payload: dict[str, Any] | None,
    *,
    user_message: str,
) -> tuple[ModelTurnDecision | None, dict[str, Any]]:
    raw = dict(payload or {})
    if not raw:
        return None, {"decision_status": "absent", "model_authority_used": False}
    errors: list[str] = []
    authority = str(raw.get("authority") or "agent_runtime.model_turn_decision").strip()
    if authority != "agent_runtime.model_turn_decision":
        errors.append("invalid_authority")
    interaction = _normalized(raw.get("interaction_intent"), INTERACTION_INTENTS, errors, "interaction_intent")
    action = _normalized(raw.get("action_intent"), ACTION_INTENTS, errors, "action_intent")
    work_mode = _normalized(raw.get("work_mode"), WORK_MODES, errors, "work_mode")
    task_goal_type = str(raw.get("task_goal_type") or "").strip()
    task_domain = str(raw.get("task_domain") or "").strip()
    if not task_goal_type:
        errors.append("task_goal_type_required")
    if not task_domain:
        errors.append("task_domain_required")
    warnings: list[str] = []
    confidence = _confidence(raw.get("confidence"), warnings)
    binding = raw.get("context_binding_decision") or {}
    if not isinstance(binding, dict):
        errors.append("context_binding_decision_must_be_object")
        binding = {}
    resource_contract = raw.get("resource_contract") or {}
    if not isinstance(resource_contract, dict):
        errors.append("resource_contract_must_be_object")
        resource_contract = {}
    if errors:
        return None, {"decision_status": "rejected_invalid", "validation_errors": errors, "model_authority_used": False}
    decision = ModelTurnDecision(
        decision_id=str(raw.get("decision_id") or f"model-turn-decision:{_slug(user_message)[:48] or 'runtime'}"),
        user_message=str(raw.get("user_message") or user_message or "").strip(),
        interaction_intent=interaction,
        action_intent=action,
        work_mode=work_mode,
        task_goal_type=task_goal_type,
        task_domain=task_domain,
        target_objects=tuple(_sequence(raw.get("target_objects"))),
        desired_outcome=str(raw.get("desired_outcome") or "").strip(),
        deliverables=tuple(_sequence(raw.get("deliverables"))),
        constraints=tuple(_sequence(raw.get("constraints"))),
        forbidden_actions=tuple(_sequence(raw.get("forbidden_actions"))),
        selected_skill_ids=tuple(_skill_ids(raw.get("selected_skill_ids"))),
        resource_contract=_normalize_resource_contract(resource_contract),
        context_binding_decision=dict(binding),
        planning_required=bool(raw.get("planning_required") is True),
        todo_required=bool(raw.get("todo_required") is True),
        completion_criteria=tuple(_sequence(raw.get("completion_criteria"))),
        needs_clarification=bool(raw.get("needs_clarification") is True),
        clarification_question=str(raw.get("clarification_question") or "").strip(),
        confidence=confidence,
        ambiguity=tuple(_sequence(raw.get("ambiguity"))),
        diagnostics={
            **dict(raw.get("diagnostics") or {}),
            "model_authority_used": True,
            "validation_warnings": warnings,
        },
    )
    return decision, {
        "decision_status": "accepted",
        "model_authority_used": True,
        "validation_errors": [],
        "validation_warnings": warnings,
    }


def _normalized(value: Any, allowed: set[str], errors: list[str], field_name: str) -> str:
    item = str(value or "").strip()
    if not item:
        errors.append(f"{field_name}_required")
        return ""
    if item not in allowed:
        errors.append(f"{field_name}_unsupported:{item}")
        return ""
    return item


def _confidence(value: Any, warnings: list[str]) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        warnings.append("confidence_defaulted_from_non_numeric")
        return 0.0
    if parsed < 0.0 or parsed > 1.0:
        warnings.append("confidence_clamped_to_range")
        return min(max(parsed, 0.0), 1.0)
    return parsed


def _sequence(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [str(value).strip()]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _skill_ids(value: Any) -> list[str]:
    ids = []
    for item in _sequence(value):
        normalized = item if item.startswith("skill.") else f"skill.{item}"
        ids.append(normalized)
    return _sequence(ids)


def _normalize_resource_contract(value: dict[str, Any]) -> dict[str, Any]:
    item = dict(value or {})

    def project_entries(key: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for raw_entry in list(item.get(key) or []):
            if isinstance(raw_entry, str):
                entry = {"path": raw_entry}
            elif isinstance(raw_entry, dict):
                entry = dict(raw_entry)
            else:
                continue
            path = _clean_path(str(entry.get("path") or ""))
            if not path:
                continue
            entries.append(
                {
                    **entry,
                    "path": path,
                    "role": str(entry.get("role") or "").strip(),
                    "required": entry.get("required") is not False,
                }
            )
        return entries

    return {
        "source_projects": project_entries("source_projects"),
        "target_projects": project_entries("target_projects"),
        "required_read_files": _relative_paths(item.get("required_read_files")),
        "required_read_dirs": _relative_paths(item.get("required_read_dirs")),
        "required_write_files": _relative_paths(item.get("required_write_files")),
        "required_write_dirs": _relative_paths(item.get("required_write_dirs")),
        "asset_policy": dict(item.get("asset_policy") or {}) if isinstance(item.get("asset_policy"), dict) else {},
    }


def _relative_paths(value: Any) -> list[str]:
    return [
        item.strip("/")
        for item in (_clean_path(raw) for raw in _sequence(value))
        if item and not item.startswith(("/", "../")) and ":/" not in item
    ]


def _clean_path(value: str) -> str:
    return str(value or "").strip().strip("`'\"“”‘’ ，,。；;").replace("\\", "/").strip()


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
