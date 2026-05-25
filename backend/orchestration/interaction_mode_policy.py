from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.goal_profiles import get_task_goal_profile

ROLE_MODE = "role_mode"
STANDARD_MODE = "standard_mode"
PROFESSIONAL_MODE = "professional_mode"

INTERACTION_MODES = {ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE}


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
        if self.interaction_mode not in INTERACTION_MODES:
            raise ValueError(f"unsupported interaction_mode: {self.interaction_mode}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_runtime_interaction_mode_policy(
    *,
    task_requirement_contract: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    execution_obligation: dict[str, Any] | None = None,
) -> RuntimeInteractionModePolicy:
    contract = dict(task_requirement_contract or {})
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    obligation = dict(execution_obligation or contract.get("execution_obligation") or current_turn.get("execution_obligation") or {})
    explicit_mode = _normalize_mode(
        current_turn.get("interaction_mode")
        or current_turn.get("runtime_interaction_mode")
        or dict(current_turn.get("mode_policy") or {}).get("interaction_mode")
        or dict(current_turn.get("runtime_mode_policy") or {}).get("interaction_mode")
    )
    explicit_policy = _explicit_turn_mode_policy(current_turn)
    if _is_task_graph_node_runtime(current_turn, contract):
        return _with_explicit_turn_policy(
            _policy_for_mode(
                explicit_mode or ROLE_MODE,
                mode_reason="task_graph_node_runtime",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    if _obligation_requires_professional_mode(obligation):
        obligation_mode = _interaction_mode_for_profile(get_task_goal_profile(str(contract.get("task_goal_type") or ""))) or PROFESSIONAL_MODE
        return _with_explicit_turn_policy(
            _policy_for_mode(
                obligation_mode,
                mode_reason="execution_obligation:write_or_verify",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    if explicit_mode:
        return _with_explicit_turn_policy(
            _policy_for_mode(
                explicit_mode,
                mode_reason="explicit_interaction_mode",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    decision = _model_turn_decision(understanding, current_turn)
    if not decision:
        raise RuntimeError("ModelTurnDecision is required to select runtime interaction mode")
    task_goal_type = str(contract.get("task_goal_type") or "").strip()
    action_intent = str(decision.get("action_intent") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    interaction_intent = str(decision.get("interaction_intent") or "").strip()
    profile_mode = _interaction_mode_for_profile(get_task_goal_profile(task_goal_type))
    if profile_mode:
        return _with_explicit_turn_policy(
            _policy_for_mode(
                profile_mode,
                mode_reason=f"semantic_task:{task_goal_type}",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    if action_intent in {"read_context", "search_external", "use_browser", "ask_clarification"}:
        return _with_explicit_turn_policy(
            _policy_for_mode(
                STANDARD_MODE,
                mode_reason=f"model_action:{action_intent}",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    if action_intent in {"edit_workspace", "run_command", "start_service", "delegate"} or work_mode in {"implementation", "verification", "delegated"}:
        return _with_explicit_turn_policy(
            _policy_for_mode(
                PROFESSIONAL_MODE,
                mode_reason=f"model_work_mode:{work_mode or action_intent}",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    if interaction_intent in {"plan", "review", "inspect"} or work_mode == "planning":
        return _with_explicit_turn_policy(
            _policy_for_mode(
                STANDARD_MODE,
                mode_reason=f"model_interaction:{interaction_intent}",
                contract=contract,
                understanding=understanding,
                execution_obligation=obligation,
            ),
            explicit_policy,
        )
    if action_intent != "answer_only":
        raise RuntimeError(f"Unsupported ModelTurnDecision action_intent for interaction mode: {action_intent}")
    return _with_explicit_turn_policy(
        _policy_for_mode(
            ROLE_MODE,
            mode_reason=f"semantic_task:{task_goal_type or 'role_conversation'}",
            contract=contract,
            understanding=understanding,
            execution_obligation=obligation,
        ),
        explicit_policy,
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
        "coding": PROFESSIONAL_MODE,
        "code": PROFESSIONAL_MODE,
        "coder": PROFESSIONAL_MODE,
    }
    return mapping.get(raw, "")


def _interaction_mode_for_profile(profile: Any) -> str:
    if profile is None:
        return ""
    task_goal_type = str(getattr(profile, "task_goal_type", "") or "").strip()
    if task_goal_type in {"role_conversation", "light_qa", "blocked"}:
        return ROLE_MODE
    capabilities = {
        str(item).strip()
        for item in list(getattr(profile, "required_capabilities", ()) or ())
        if str(item).strip()
    }
    actions = {
        str(item).strip()
        for item in list(getattr(profile, "required_actions", ()) or ())
        if str(item).strip()
    }
    deliverables = {
        str(item).strip()
        for item in list(getattr(profile, "default_core_deliverables", ()) or ())
        if str(item).strip()
    }
    professional_capabilities = {
        "workspace_write",
        "terminal",
        "browser",
        "image_generation_or_asset_integration",
    }
    professional_actions = {
        "apply_real_change",
        "run_verification",
        "run_browser_verification",
        "integrate_asset",
        "execute_node_contract",
    }
    professional_deliverables = {
        "verification_evidence",
        "runnable_artifact_refs",
        "gameplay_acceptance",
        "workflow_acceptance",
        "visual_asset_refs",
    }
    if (
        str(getattr(profile, "professional_profile_id", "") or "").strip()
        or capabilities & professional_capabilities
        or actions & professional_actions
        or deliverables & professional_deliverables
    ):
        return PROFESSIONAL_MODE
    return STANDARD_MODE


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
                    "browser_control",
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
                    "op.browser_control",
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
                "side_effect_tools": ["write_file", "edit_file", "terminal", "browser_control"],
                "side_effect_operations": ["op.write_file", "op.edit_file", "op.shell", "op.browser_control"],
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
                "agent_todo",
                "read_file",
                "read_structured_file",
                "list_dir",
                "stat_path",
                "path_exists",
                "glob_paths",
                "search_text",
                "search_files",
                "git_status",
                "git_diff",
                "git_log",
                "git_show",
                "delegate_to_agent",
                "write_file",
                "edit_file",
                "terminal",
                "browser_control",
                "web_search",
                "fetch_url",
            ],
            "allowed_operation_refs": [
                "op.agent_todo",
                "op.read_file",
                "op.read_structured_file",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.search_text",
                "op.search_files",
                "op.git_status",
                "op.git_diff",
                "op.git_log",
                "op.git_show",
                "op.delegate_to_agent",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.browser_control",
                "op.web_search",
                "op.fetch_url",
            ],
            "max_tool_rounds_per_task_run": 96,
            "max_tool_calls_per_task_run": 144,
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
                "agent:knowledge_searcher",
                "agent:codebase_searcher",
                "agent:memory_searcher",
                "agent:pdf_reader",
                "agent:table_analyst",
                "agent:web_researcher",
                "agent:verifier",
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
            "side_effect_tools": ["write_file", "edit_file", "terminal", "python_repl", "browser_control"],
            "side_effect_operations": ["op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.browser_control"],
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


def _explicit_turn_mode_policy(current_turn: dict[str, Any]) -> dict[str, Any]:
    mode_policy = dict(current_turn.get("mode_policy") or {})
    runtime_mode_policy = dict(current_turn.get("runtime_mode_policy") or {})
    merged = {**runtime_mode_policy, **mode_policy}
    explicit_tool_policy = dict(runtime_mode_policy.get("tool_policy") or {})
    explicit_tool_policy.update(dict(mode_policy.get("tool_policy") or {}))
    if explicit_tool_policy:
        merged["tool_policy"] = explicit_tool_policy
    explicit_delegation_policy = dict(runtime_mode_policy.get("delegation_policy") or {})
    explicit_delegation_policy.update(dict(mode_policy.get("delegation_policy") or {}))
    if explicit_delegation_policy:
        merged["delegation_policy"] = explicit_delegation_policy
    explicit_verification_policy = dict(runtime_mode_policy.get("verification_policy") or {})
    explicit_verification_policy.update(dict(mode_policy.get("verification_policy") or {}))
    if explicit_verification_policy:
        merged["verification_policy"] = explicit_verification_policy
    explicit_sandbox_policy = dict(runtime_mode_policy.get("sandbox_policy") or {})
    explicit_sandbox_policy.update(dict(mode_policy.get("sandbox_policy") or {}))
    if explicit_sandbox_policy:
        merged["sandbox_policy"] = explicit_sandbox_policy
    return merged


def _with_explicit_turn_policy(
    policy: RuntimeInteractionModePolicy,
    explicit_policy: dict[str, Any],
) -> RuntimeInteractionModePolicy:
    explicit = dict(explicit_policy or {})
    explicit_tool_policy = dict(explicit.get("tool_policy") or {})
    explicit_delegation_policy = dict(explicit.get("delegation_policy") or {})
    explicit_verification_policy = dict(explicit.get("verification_policy") or {})
    explicit_sandbox_policy = dict(explicit.get("sandbox_policy") or {})
    if not any((explicit_tool_policy, explicit_delegation_policy, explicit_verification_policy, explicit_sandbox_policy)):
        return policy
    return RuntimeInteractionModePolicy(
        interaction_mode=policy.interaction_mode,
        mode_reason=policy.mode_reason,
        runtime_lane=policy.runtime_lane,
        recipe_id=policy.recipe_id,
        projection_strength=policy.projection_strength,
        semantic_contract_required=policy.semantic_contract_required,
        professional_profile_required=policy.professional_profile_required,
        tool_policy=_merge_explicit_tool_policy(policy.tool_policy, explicit_tool_policy),
        delegation_policy={**dict(policy.delegation_policy), **explicit_delegation_policy},
        checkpoint_policy=dict(policy.checkpoint_policy),
        verification_policy={**dict(policy.verification_policy), **explicit_verification_policy},
        sandbox_policy={**dict(policy.sandbox_policy), **explicit_sandbox_policy},
        context_policy=dict(policy.context_policy),
        output_policy=dict(policy.output_policy),
        diagnostics={
            **dict(policy.diagnostics),
            "explicit_turn_policy_adopted": True,
        },
    )


def _merge_explicit_tool_policy(base_policy: dict[str, Any], explicit_policy: dict[str, Any]) -> dict[str, Any]:
    if not explicit_policy:
        return dict(base_policy)
    merged = {**dict(base_policy), **dict(explicit_policy)}
    for key in ("allowed_tool_names", "allowed_operation_refs", "denied_tool_names"):
        explicit_values = list(explicit_policy.get(key) or [])
        if explicit_values:
            merged[key] = _dedupe_policy_values([*list(base_policy.get(key) or []), *explicit_values])
    return merged


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
        "model_turn_decision": _model_turn_decision(understanding, {}),
        "action_permit": dict(understanding.get("action_permit") or {}),
        "execution_obligation": _obligation_summary(obligation),
    }


def _model_turn_decision(understanding: dict[str, Any], current_turn: dict[str, Any]) -> dict[str, Any]:
    return dict(
        dict(understanding or {}).get("model_turn_decision")
        or dict(current_turn or {}).get("model_turn_decision")
        or {}
    )


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
