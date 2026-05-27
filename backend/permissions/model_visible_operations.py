from __future__ import annotations


MODEL_VISIBLE_AGENT_OPERATIONS = frozenset({"op.delegate_to_agent"})
MODEL_VISIBLE_STATE_OPERATIONS = frozenset({"op.agent_todo"})


def is_model_visible_agent_operation(operation_id: str) -> bool:
    return str(operation_id or "").strip() in MODEL_VISIBLE_AGENT_OPERATIONS


def is_model_visible_state_operation(operation_id: str) -> bool:
    return str(operation_id or "").strip() in MODEL_VISIBLE_STATE_OPERATIONS



