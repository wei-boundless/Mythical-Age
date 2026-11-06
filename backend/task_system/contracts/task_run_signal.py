from __future__ import annotations

from typing import Any


def task_run_contract_signal_from_context(
    *,
    current_turn_context: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_turn = dict(current_turn_context or {})
    understanding = dict(query_understanding or {})
    for source_name, candidate in _task_run_contract_candidates(current_turn, understanding):
        signal = _task_run_contract_signal(candidate, source_name=source_name)
        if signal:
            return signal
    return {}


def _task_run_contract_candidates(
    current_turn: dict[str, Any],
    understanding: dict[str, Any],
) -> tuple[tuple[str, Any], ...]:
    runtime_contract = dict(current_turn.get("runtime_contract") or {})
    model_decision = dict(current_turn.get("model_turn_decision") or {})
    action_request = dict(current_turn.get("agent_turn_action_request") or {})
    understanding_action = dict(understanding.get("agent_turn_action_request") or {})
    understanding_decision = dict(understanding.get("model_turn_decision") or {})
    return (
        ("current_turn.task_run_contract", current_turn.get("task_run_contract")),
        ("runtime_contract.task_run_contract", runtime_contract.get("task_run_contract")),
        ("current_turn.task_run_contract_seed", current_turn.get("task_run_contract_seed")),
        ("agent_turn_action_request.task_run_contract_seed", action_request.get("task_run_contract_seed")),
        ("model_turn_decision.task_run_contract_seed", model_decision.get("task_run_contract_seed")),
        ("query_understanding.task_run_contract", understanding.get("task_run_contract")),
        ("query_understanding.task_run_contract_seed", understanding.get("task_run_contract_seed")),
        ("query_understanding.agent_turn_action_request.task_run_contract_seed", understanding_action.get("task_run_contract_seed")),
        ("query_understanding.model_turn_decision.task_run_contract_seed", understanding_decision.get("task_run_contract_seed")),
        ("runtime_contract.working_scope", runtime_contract),
    )


def _task_run_contract_signal(value: Any, *, source_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    payload = dict(value)
    if _is_compact_task_start_intent(payload):
        return _compact_task_start_signal(payload, source_name=source_name)
    task_run_contract = _task_run_contract_payload(payload)
    if task_run_contract:
        return _full_task_run_contract_signal(task_run_contract, source_name=source_name)
    if isinstance(payload.get("working_scope"), dict):
        return _drop_empty(
            {
                "working_scope": dict(payload.get("working_scope") or {}),
                "required_artifacts": _dict_list(payload.get("required_artifacts")),
                "completion_criteria": _string_list(payload.get("completion_criteria")),
                "source_ref": source_name,
                "authority": "task_system.task_run_contract_signal",
            }
        )
    return {}


def _is_compact_task_start_intent(value: dict[str, Any]) -> bool:
    if str(value.get("contract_shape") or "").strip() == "compact_task_start_intent":
        return True
    compact_keys = {
        "primary_mode",
        "task_shape",
        "minimum_viable_next_step",
        "working_scope",
        "acceptance",
        "mode_payload",
    }
    return bool(compact_keys.intersection(value)) and not (
        isinstance(value.get("container_contract"), dict) or isinstance(value.get("work_modes"), list)
    )


def _compact_task_start_signal(value: dict[str, Any], *, source_name: str) -> dict[str, Any]:
    acceptance = dict(value.get("acceptance") or {}) if isinstance(value.get("acceptance"), dict) else {}
    mode_payload = dict(value.get("mode_payload") or {}) if isinstance(value.get("mode_payload"), dict) else {}
    return _drop_empty(
        {
            "contract_shape": "compact_task_start_intent",
            "primary_mode": str(value.get("primary_mode") or "").strip(),
            "task_shape": str(value.get("task_shape") or "").strip(),
            "minimum_viable_next_step": str(value.get("minimum_viable_next_step") or "").strip(),
            "working_scope": dict(value.get("working_scope") or {}) if isinstance(value.get("working_scope"), dict) else {},
            "completion_criteria": _string_list(acceptance.get("criteria")),
            "final_answer_requirements": _string_list(acceptance.get("final_answer_requirements")),
            "acceptance_mode": str(acceptance.get("mode") or "").strip(),
            "mode_summary": str(mode_payload.get("summary") or "").strip(),
            "mode_steps": _string_list(mode_payload.get("steps")),
            "success_definition": str(mode_payload.get("success_definition") or "").strip(),
            "notes": _string_list(mode_payload.get("notes")),
            "source_ref": source_name,
            "authority": "task_system.task_run_contract_signal",
        }
    )


def _task_run_contract_payload(value: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value.get("task_run_contract"), dict):
        return dict(value.get("task_run_contract") or {})
    if isinstance(value.get("container_contract"), dict) or isinstance(value.get("work_modes"), list):
        return dict(value)
    return {}


def _full_task_run_contract_signal(value: dict[str, Any], *, source_name: str) -> dict[str, Any]:
    container_contract = dict(value.get("container_contract") or {}) if isinstance(value.get("container_contract"), dict) else {}
    work_modes = _dict_list(value.get("work_modes"))
    primary_mode = _primary_work_mode(work_modes, container_contract=container_contract)
    primary_contract = dict(primary_mode.get("contract") or {}) if isinstance(primary_mode.get("contract"), dict) else {}
    goal_mode = _first_work_mode(work_modes, "goal")
    plan_mode = _first_work_mode(work_modes, "plan")
    goal_contract = dict(goal_mode.get("contract") or {}) if isinstance(goal_mode.get("contract"), dict) else {}
    plan_contract = dict(plan_mode.get("contract") or {}) if isinstance(plan_mode.get("contract"), dict) else {}
    acceptance_contract = dict(value.get("acceptance_contract") or {}) if isinstance(value.get("acceptance_contract"), dict) else {}
    runtime_requirements = dict(value.get("runtime_requirements") or {}) if isinstance(value.get("runtime_requirements"), dict) else {}
    working_scope = _first_dict(
        primary_contract.get("working_scope"),
        goal_contract.get("working_scope"),
        plan_contract.get("working_scope"),
        container_contract.get("working_scope"),
        value.get("working_scope"),
    )
    return _drop_empty(
        {
            "contract_id": str(value.get("contract_id") or "").strip(),
            "primary_mode": str(primary_mode.get("mode_kind") or "").strip(),
            "task_shape": str(container_contract.get("task_shape") or primary_mode.get("task_shape") or "").strip(),
            "minimum_viable_next_step": str(container_contract.get("minimum_viable_next_step") or "").strip(),
            "working_scope": working_scope,
            "required_artifacts": _dict_list(acceptance_contract.get("required_artifacts")),
            "completion_criteria": _string_list(acceptance_contract.get("completion_criteria")),
            "required_verifications": _dict_or_string_list(acceptance_contract.get("required_verifications")),
            "final_answer_requirements": _string_list(acceptance_contract.get("final_answer_requirements")),
            "acceptance_mode": str(acceptance_contract.get("acceptance_mode") or "").strip(),
            "safety_boundaries": _string_list(runtime_requirements.get("safety_boundaries")),
            "source_ref": source_name,
            "authority": "task_system.task_run_contract_signal",
        }
    )


def _primary_work_mode(work_modes: list[dict[str, Any]], *, container_contract: dict[str, Any]) -> dict[str, Any]:
    primary_ref = str(container_contract.get("primary_work_mode_ref") or "").strip()
    for item in work_modes:
        if primary_ref and str(item.get("mode_instance_id") or "").strip() == primary_ref:
            return dict(item)
    for item in work_modes:
        if str(item.get("mode_role") or "").strip() == "primary":
            return dict(item)
    return {}


def _first_work_mode(work_modes: list[dict[str, Any]], mode_kind: str) -> dict[str, Any]:
    for item in work_modes:
        if str(item.get("mode_kind") or "").strip() == mode_kind:
            return dict(item)
    return {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    return [dict(item) for item in raw_values if isinstance(item, dict)]


def _dict_or_string_list(value: Any) -> list[Any]:
    result: list[Any] = []
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    for item in raw_values:
        if isinstance(item, dict):
            result.append(dict(item))
        elif str(item).strip():
            result.append(str(item).strip())
    return result


def _string_list(value: Any) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}
