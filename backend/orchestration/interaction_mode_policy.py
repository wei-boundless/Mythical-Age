from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ROLE_MODE = "role_mode"
STANDARD_MODE = "standard_mode"
PROFESSIONAL_MODE = "professional_mode"


@dataclass(frozen=True, slots=True)
class RuntimeInteractionModePolicy:
    interaction_mode: str
    mode_reason: str
    runtime_lane: str
    recipe_id: str
    projection_strength: str
    semantic_contract_required: bool
    professional_profile_required: bool
    tool_policy: dict[str, Any] = field(default_factory=dict)
    delegation_policy: dict[str, Any] = field(default_factory=dict)
    checkpoint_policy: dict[str, Any] = field(default_factory=dict)
    verification_policy: dict[str, Any] = field(default_factory=dict)
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    output_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_interaction_mode_policy"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.runtime_interaction_mode_policy":
            raise ValueError("RuntimeInteractionModePolicy authority must be orchestration.runtime_interaction_mode_policy")
        if self.interaction_mode not in {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE}:
            raise ValueError(f"unsupported interaction_mode: {self.interaction_mode}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_runtime_interaction_mode_policy(
    *,
    semantic_task_contract: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    intent_decision: dict[str, Any] | None = None,
    execution_obligation: dict[str, Any] | None = None,
) -> RuntimeInteractionModePolicy:
    contract = dict(semantic_task_contract or {})
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    intent = dict(intent_decision or current_turn.get("intent_decision") or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or current_turn.get("execution_obligation") or {})
    explicit_mode = _normalize_mode(
        current_turn.get("interaction_mode")
        or current_turn.get("runtime_interaction_mode")
        or dict(current_turn.get("mode_policy") or {}).get("interaction_mode")
        or dict(current_turn.get("runtime_mode_policy") or {}).get("interaction_mode")
        or intent.get("interaction_mode")
    )
    if _is_task_graph_node_runtime(current_turn, contract):
        return _policy_for_mode(
            explicit_mode or ROLE_MODE,
            mode_reason="task_graph_node_runtime",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    if _obligation_requires_professional_mode(obligation):
        return _policy_for_mode(
            PROFESSIONAL_MODE,
            mode_reason="execution_obligation:write_or_verify",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    if explicit_mode:
        return _policy_for_mode(
            explicit_mode,
            mode_reason="explicit_interaction_mode",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    strategy = str(
        intent.get("execution_strategy")
        or dict(current_turn.get("runtime_assembly_hint") or {}).get("execution_strategy")
        or ""
    ).strip()
    route = str(understanding.get("route") or understanding.get("route_hint") or "").strip()
    posture = str(understanding.get("execution_posture") or "").strip()
    if task_goal_type in {
        "test_report_triage",
        "runtime_trace_analysis",
        "code_fix_execution",
        "regression_test_design",
        "artifact_delivery",
    }:
        return _policy_for_mode(
            PROFESSIONAL_MODE,
            mode_reason=f"semantic_task:{task_goal_type}",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    if strategy == "professional_task_run":
        return _policy_for_mode(
            PROFESSIONAL_MODE,
            mode_reason=f"intent_strategy:{strategy}",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    if task_goal_type in {"bounded_tool_task", "material_synthesis"}:
        return _policy_for_mode(
            STANDARD_MODE,
            mode_reason=f"semantic_task:{task_goal_type}",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    if route in {"search", "realtime_network", "workspace_read", "workspace_path_search", "workspace_text_search", "tool"}:
        return _policy_for_mode(
            STANDARD_MODE,
            mode_reason=f"capability_route:{route}",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    if posture in {"builtin_tool_lane", "direct_rag"}:
        return _policy_for_mode(
            STANDARD_MODE,
            mode_reason=f"execution_posture:{posture}",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        )
    return _policy_for_mode(
        ROLE_MODE,
        mode_reason=f"semantic_task:{task_goal_type or 'role_conversation'}",
        contract=contract,
        understanding=understanding,
        execution_obligation=obligation,
    )


def mode_policy_from_payload(payload: dict[str, Any] | None) -> RuntimeInteractionModePolicy | None:
    item = dict(payload or {})
    if not item:
        return None
    try:
        return RuntimeInteractionModePolicy(
            interaction_mode=str(item.get("interaction_mode") or ""),
            mode_reason=str(item.get("mode_reason") or ""),
            runtime_lane=str(item.get("runtime_lane") or ""),
            recipe_id=str(item.get("recipe_id") or ""),
            projection_strength=str(item.get("projection_strength") or ""),
            semantic_contract_required=bool(item.get("semantic_contract_required")),
            professional_profile_required=bool(item.get("professional_profile_required")),
            tool_policy=dict(item.get("tool_policy") or {}),
            delegation_policy=dict(item.get("delegation_policy") or {}),
            checkpoint_policy=dict(item.get("checkpoint_policy") or {}),
            verification_policy=dict(item.get("verification_policy") or {}),
            sandbox_policy=dict(item.get("sandbox_policy") or {}),
            context_policy=dict(item.get("context_policy") or {}),
            output_policy=dict(item.get("output_policy") or {}),
            diagnostics=dict(item.get("diagnostics") or {}),
        )
    except ValueError:
        return None


def _normalize_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "role": ROLE_MODE,
        "role_mode": ROLE_MODE,
        "standard": STANDARD_MODE,
        "standard_mode": STANDARD_MODE,
        "professional": PROFESSIONAL_MODE,
        "professional_mode": PROFESSIONAL_MODE,
    }
    return mapping.get(raw, "")


def _is_task_graph_node_runtime(current_turn: dict[str, Any], contract: dict[str, Any]) -> bool:
    if str(contract.get("task_goal_type") or "").strip() == "task_graph_node_execution":
        return True
    if current_turn.get("task_graph_node_runtime") is True or current_turn.get("suppress_bundle_projection") is True:
        return True
    if str(current_turn.get("runtime_lane") or "").strip() == "coordination_task":
        return True
    if str(dict(contract.get("execution_obligation") or {}).get("task_graph_node_policy") or "").strip():
        return True
    return False


def _policy_for_mode(
    interaction_mode: str,
    *,
    mode_reason: str,
    contract: dict[str, Any],
    understanding: dict[str, Any],
    execution_obligation: dict[str, Any] | None = None,
) -> RuntimeInteractionModePolicy:
    obligation = dict(execution_obligation or {})
    if interaction_mode == ROLE_MODE:
        policy = RuntimeInteractionModePolicy(
            interaction_mode=ROLE_MODE,
            mode_reason=mode_reason,
            runtime_lane="role_interaction",
            recipe_id="runtime.recipe.role_interaction",
            projection_strength="primary",
            semantic_contract_required=False,
            professional_profile_required=False,
            tool_policy={
                "enabled": True,
                "allowed_tool_names": ["mcp_retrieval", "web_search", "fetch_url"],
                "allowed_operation_refs": ["op.mcp_retrieval", "op.web_search", "op.fetch_url", "op.memory_read"],
                "read_only": True,
                "max_tool_rounds_per_task_run": 1,
                "max_tool_calls_per_task_run": 1,
                "max_tool_calls_per_round": 1,
            },
            delegation_policy={"enabled": False},
            checkpoint_policy={"terminal": True},
            verification_policy={"required": False, "summary_check": True, "strict": False},
            sandbox_policy={"enabled": False},
            context_policy={
                "main_session_history": "full_or_summary",
                "memory": "conversation_and_state",
                "working_memory": False,
            },
            output_policy={"answer_boundary": "conversation", "deliverable_validator": False},
            diagnostics=_diagnostics(contract, understanding, obligation),
        )
        return _with_contract_bound_tool_policy(policy, contract)
    if interaction_mode == STANDARD_MODE:
        policy = RuntimeInteractionModePolicy(
            interaction_mode=STANDARD_MODE,
            mode_reason=mode_reason,
            runtime_lane="standard_task",
            recipe_id="runtime.recipe.standard_task",
            projection_strength="companion",
            semantic_contract_required=True,
            professional_profile_required=False,
            tool_policy={
                "enabled": True,
                "allowed_tool_names": [
                    "read_file",
                    "read_structured_file",
                    "search_text",
                    "search_files",
                    "web_search",
                    "fetch_url",
                    "write_file",
                    "edit_file",
                    "terminal",
                ],
                "allowed_operation_refs": [
                    "op.read_file",
                    "op.read_structured_file",
                    "op.search_text",
                    "op.search_files",
                    "op.web_search",
                    "op.fetch_url",
                    "op.write_file",
                    "op.edit_file",
                    "op.shell",
                ],
                "max_tool_rounds_per_task_run": 2,
                "max_tool_calls_per_task_run": 4,
                "max_tool_calls_per_round": 1,
            },
            delegation_policy={"enabled": False},
            checkpoint_policy={"before_commit": True, "terminal": True},
            verification_policy={"required": True, "strict": False, "deliverable_validator": True},
            sandbox_policy={
                "enabled": True,
                "mode": "workspace_overlay",
                "side_effect_tools": ["write_file", "edit_file", "terminal"],
            },
            context_policy={
                "main_session_history": "summary",
                "memory": "conversation_and_state",
                "working_memory": "light",
            },
            output_policy={"answer_boundary": "task", "deliverable_validator": "basic"},
            diagnostics=_diagnostics(contract, understanding, obligation),
        )
        return _with_contract_bound_tool_policy(policy, contract)
    policy = RuntimeInteractionModePolicy(
        interaction_mode=PROFESSIONAL_MODE,
        mode_reason=mode_reason,
        runtime_lane="professional_task",
        recipe_id="runtime.recipe.professional_task",
        projection_strength="style_only",
        semantic_contract_required=True,
        professional_profile_required=True,
        tool_policy={
            "enabled": True,
            "allowed_tool_names": [
                "read_file",
                "read_structured_file",
                "search_text",
                "search_files",
                "git_status",
                "git_diff",
                "delegate_to_agent",
                "write_file",
                "edit_file",
                "terminal",
                "web_search",
                "fetch_url",
            ],
            "allowed_operation_refs": [
                "op.read_file",
                "op.read_structured_file",
                "op.search_text",
                "op.search_files",
                "op.git_status",
                "op.git_diff",
                "op.delegate_to_agent",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.web_search",
                "op.fetch_url",
            ],
            "max_tool_rounds_per_task_run": 16,
            "max_tool_calls_per_task_run": 32,
            "max_tool_calls_per_round": 1,
            "requires_evidence_packet": True,
        },
        delegation_policy={
            "enabled": True,
            "max_delegate_calls_per_step": 1,
            "max_delegate_calls_per_task_run": 4,
            "delegate_retry_budget": 1,
            "nested_delegation": False,
            "child_result_is_evidence_packet": True,
            "allowed_tool_name": "delegate_to_agent",
            "allowed_operation_ref": "op.delegate_to_agent",
            "allowed_agent_ids": [
                "agent:rag_analyst",
                "agent:pdf_reader",
                "agent:table_analyst",
                "agent:web_researcher",
            ],
        },
        checkpoint_policy={
            "after_each_plan_item": True,
            "after_each_tool_action": True,
            "after_delegation": True,
            "before_commit": True,
            "terminal": True,
        },
        verification_policy={
            "required": True,
            "strict": True,
            "deliverable_validator": True,
            "require_summary_check": True,
            "require_artifact_refs_for_write": True,
            "require_test_or_limitation": True,
        },
        sandbox_policy={
            "enabled": True,
            "mode": "workspace_overlay",
            "side_effect_root": "output/sandbox_runs",
            "workspace_dir_name": "workspace",
            "real_workspace_access": "read_only",
            "approval_policy": "sandboxed_side_effects",
            "side_effect_tools": ["write_file", "edit_file", "terminal", "python_repl"],
            "side_effect_operations": ["op.write_file", "op.edit_file", "op.shell", "op.python_repl"],
            "overlay_copy_on_write": True,
        },
        context_policy={
            "main_session_history": "task_scoped_summary",
            "memory": "refs_only",
            "working_memory": "required",
        },
        output_policy={"answer_boundary": "professional_deliverable", "deliverable_validator": "strict"},
        diagnostics=_diagnostics(contract, understanding, obligation),
    )
    return _with_contract_bound_tool_policy(policy, contract)


def _with_contract_bound_tool_policy(
    policy: RuntimeInteractionModePolicy,
    contract: dict[str, Any],
) -> RuntimeInteractionModePolicy:
    node_policy = _contract_bound_tool_policy(contract)
    if not node_policy:
        return policy
    merged_tool_policy = {
        **dict(policy.tool_policy),
        **node_policy,
        "allowed_tool_names": _dedupe_policy_values(
            [
                *list(dict(policy.tool_policy).get("allowed_tool_names") or []),
                *list(node_policy.get("allowed_tool_names") or []),
            ]
        ),
        "allowed_operation_refs": _dedupe_policy_values(
            [
                *list(dict(policy.tool_policy).get("allowed_operation_refs") or []),
                *list(node_policy.get("allowed_operation_refs") or []),
            ]
        ),
        "denied_tool_names": _dedupe_policy_values(
            [
                *list(dict(policy.tool_policy).get("denied_tool_names") or []),
                *list(node_policy.get("denied_tool_names") or []),
            ]
        ),
    }
    return RuntimeInteractionModePolicy(
        interaction_mode=policy.interaction_mode,
        mode_reason=policy.mode_reason,
        runtime_lane=policy.runtime_lane,
        recipe_id=policy.recipe_id,
        projection_strength=policy.projection_strength,
        semantic_contract_required=policy.semantic_contract_required,
        professional_profile_required=policy.professional_profile_required,
        tool_policy=merged_tool_policy,
        delegation_policy=dict(policy.delegation_policy),
        checkpoint_policy=dict(policy.checkpoint_policy),
        verification_policy=dict(policy.verification_policy),
        sandbox_policy=dict(policy.sandbox_policy),
        context_policy=dict(policy.context_policy),
        output_policy=dict(policy.output_policy),
        diagnostics={
            **dict(policy.diagnostics),
            "contract_bound_tool_policy_adopted": True,
        },
    )


def _contract_bound_tool_policy(contract: dict[str, Any]) -> dict[str, Any]:
    bindings = dict(contract.get("contract_bindings") or contract.get("bindings") or {})
    runtime = dict(bindings.get("runtime") or contract.get("runtime") or {})
    policy = dict(runtime.get("tool_execution_policy") or contract.get("tool_execution_policy") or {})
    if not policy:
        current_turn = dict(bindings.get("current_turn") or {})
        stage_request = dict(current_turn.get("stage_execution_request") or {})
        runtime = dict(dict(stage_request.get("standard_input_package") or {}).get("contract", {}).get("contract_bindings", {}).get("runtime") or {})
        policy = dict(runtime.get("tool_execution_policy") or {})
    if not policy or policy.get("enabled") is False:
        return {}
    return policy


def _dedupe_policy_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _diagnostics(contract: dict[str, Any], understanding: dict[str, Any], execution_obligation: dict[str, Any] | None = None) -> dict[str, Any]:
    obligation = dict(execution_obligation or contract.get("execution_obligation") or {})
    return {
        "task_goal_type": str(contract.get("task_goal_type") or ""),
        "professional_profile_id": str(contract.get("professional_profile_id") or ""),
        "route": str(understanding.get("route") or understanding.get("route_hint") or ""),
        "execution_posture": str(understanding.get("execution_posture") or ""),
        "execution_obligation": _obligation_summary(obligation),
    }


def _obligation_requires_professional_mode(obligation: dict[str, Any]) -> bool:
    item = dict(obligation or {})
    if _obligation_forbids_write(item):
        return False
    return bool(
        list(item.get("required_writes") or [])
        or list(item.get("required_commands") or [])
        or list(item.get("required_verifications") or [])
    )


def _obligation_forbids_write(obligation: dict[str, Any]) -> bool:
    forbidden = {
        str(item).strip()
        for item in list(dict(obligation or {}).get("forbidden_actions") or [])
        if str(item).strip()
    }
    return bool(forbidden.intersection({"modify_code", "write_file", "edit_file"}))


def _obligation_summary(obligation: dict[str, Any]) -> dict[str, Any]:
    item = dict(obligation or {})
    return {
        "required_reads": len(list(item.get("required_reads") or [])),
        "required_writes": len(list(item.get("required_writes") or [])),
        "required_commands": len(list(item.get("required_commands") or [])),
        "required_verifications": len(list(item.get("required_verifications") or [])),
        "required_deliverables": list(item.get("required_deliverables") or []),
        "forbidden_actions": list(item.get("forbidden_actions") or []),
    }
