from __future__ import annotations

from orchestration import (
    ApprovalState,
    ApprovalToken,
    DenialTrackingState,
    OperationGate,
    OperationGatePipelineContext,
    ResourceDecision,
    ResourcePolicy,
    RuntimeApprovalContext,
    build_default_operation_registry,
    build_operation_requirement,
    build_resource_policy_candidate,
    build_resource_runtime_views,
)
from capability_system.validators import validate_filesystem_path, validate_shell_read_only


def test_operation_requirement_is_candidate_only_and_preserves_denied_operations() -> None:
    requirement = build_operation_requirement(
        task_id="task-1",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.edit_file"),
        denied_operations=("terminal",),
        skill_required_operations=("op.search_text",),
        approval_policy="default",
        review_policy="required",
    )

    assert requirement.authority == "candidate_only"
    assert requirement.required_operations == ("op.read_file", "op.edit_file")
    assert requirement.optional_operations == ("op.search_text",)
    assert requirement.denied_operations == ("terminal",)
    assert requirement.metadata["review_policy"] == "required"


def test_resource_policy_candidate_denies_unknown_and_denied_aliases() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-2",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.shell", "op.unknown"),
        denied_operations=("terminal",),
    )

    policy = build_resource_policy_candidate(requirement, registry)
    decisions = {decision.operation_id: decision for decision in policy.decisions}

    assert policy.authority == "resource_policy"
    assert policy.runtime_view_only is True
    assert policy.adopted is False
    assert policy.runtime_executable is False
    assert decisions["op.read_file"].decision == "allow"
    assert decisions["op.shell"].decision == "deny"
    assert decisions["op.shell"].reason == "explicitly denied by task binding"
    assert decisions["op.unknown"].decision == "deny"
    assert decisions["op.unknown"].reason == "unknown operation"
    assert "op.shell" in policy.denied_operations


def test_high_risk_operations_require_approval_but_do_not_become_executable() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-3",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.edit_file", "op.python_repl"),
    )

    policy = build_resource_policy_candidate(requirement, registry)
    decisions = {decision.operation_id: decision for decision in policy.decisions}
    views = {view.resource_id: view for view in build_resource_runtime_views(policy, registry)}

    assert decisions["op.edit_file"].decision == "requires_approval"
    assert decisions["op.python_repl"].decision == "requires_approval"
    assert views["op.read_file"].authorized is True
    assert views["op.read_file"].available_to_model is True
    assert views["op.read_file"].runtime_executable is False
    assert views["op.edit_file"].authorized is False
    assert views["op.edit_file"].requires_approval is True
    assert views["op.edit_file"].runtime_executable is False
    assert views["op.edit_file"].input_contract_ref == "op.edit_file.input"
    assert views["op.edit_file"].authorization_owner == "ResourcePolicy"


def test_headless_requires_approval_fails_closed_without_approval_channel() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-4",
        source="task_binding_preview",
        operation_scope=("op.edit_file",),
    )

    policy = build_resource_policy_candidate(
        requirement,
        registry,
        approval_context=RuntimeApprovalContext(
            interactive_ui_available=False,
            headless_mode=True,
            approval_hook_available=False,
            bubble_to_parent_allowed=False,
        ),
    )
    decision = policy.decisions[0]

    assert decision.operation_id == "op.edit_file"
    assert decision.decision == "deny"
    assert decision.reason == "approval unavailable in headless context"
    assert "op.edit_file" in policy.denied_operations


def test_headless_requires_approval_can_route_to_hook_without_allowing_execution() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-5",
        source="task_binding_preview",
        operation_scope=("op.edit_file",),
    )

    policy = build_resource_policy_candidate(
        requirement,
        registry,
        approval_context=RuntimeApprovalContext(
            interactive_ui_available=False,
            headless_mode=True,
            approval_hook_available=True,
        ),
    )
    decision = policy.decisions[0]

    assert decision.decision == "requires_approval"
    assert decision.approval_channel == "hook"
    assert policy.runtime_executable is False


def test_mcp_and_memory_write_candidate_stay_hidden_or_denied() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-6",
        source="task_binding_preview",
        operation_scope=("op.mcp_pdf", "op.memory_write_candidate"),
    )

    policy = build_resource_policy_candidate(requirement, registry)
    decisions = {decision.operation_id: decision for decision in policy.decisions}
    views = {view.resource_id: view for view in build_resource_runtime_views(policy, registry)}

    assert decisions["op.mcp_pdf"].decision == "not_executable"
    assert decisions["op.memory_write_candidate"].decision == "deny"
    assert views["op.mcp_pdf"].available_to_model is False
    assert views["op.mcp_pdf"].authorized is False
    assert views["op.mcp_pdf"].runtime_executable is False


def test_operation_gate_rejects_preview_policy_even_for_allowed_preview_operation() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-7",
        source="task_binding_preview",
        operation_scope=("op.read_file",),
    )
    policy = build_resource_policy_candidate(requirement, registry)
    gate = OperationGate(registry)

    missing_directive = gate.check("op.read_file", resource_policy=policy)
    preview_policy = gate.check("op.read_file", resource_policy=policy, directive_ref="directive-1")

    assert missing_directive.allowed is False
    assert missing_directive.reason == "missing directive_ref"
    assert missing_directive.pipeline_stage == "runtime_directive_exists"
    assert preview_policy.allowed is False
    assert preview_policy.reason == "resource policy is not adopted for execution"


def test_operation_descriptor_exports_thick_contract_fields() -> None:
    registry = build_default_operation_registry()
    descriptor = registry.get_operation("op.read_file")

    assert descriptor is not None
    assert descriptor.input_contract_ref == "op.read_file.input"
    assert descriptor.output_contract_ref == "op.read_file.output"
    assert descriptor.read_only is True
    assert descriptor.concurrency_safe is True
    assert descriptor.max_result_size_chars > 0
    assert descriptor.safety_validator_ref == "filesystem_path"


def test_operation_gate_pipeline_strips_dangerous_auto_allow() -> None:
    registry = build_default_operation_registry()
    policy = _runtime_policy(
        allowed=("op.shell",),
        task_id="task-auto",
    )
    gate = OperationGate(registry)

    result = gate.check(
        "op.shell",
        resource_policy=policy,
        directive_ref="directive-auto",
        context=OperationGatePipelineContext(permission_mode="auto"),
    )

    assert result.allowed is False
    assert result.reason == "dangerous allow rule stripped in auto/bypass permission mode"
    assert result.pipeline_stage == "dangerous_allow_rule_stripper"


def test_operation_gate_headless_approval_requires_matching_token() -> None:
    registry = build_default_operation_registry()
    policy = _runtime_policy(
        requires_approval=("op.edit_file",),
        task_id="task-approval",
    )
    gate = OperationGate(registry)

    blocked = gate.check(
        "op.edit_file",
        resource_policy=policy,
        directive_ref="directive-edit",
        context=OperationGatePipelineContext(permission_mode="headless", headless_mode=True),
    )
    allowed_after_token = gate.check(
        "op.edit_file",
        resource_policy=policy,
        directive_ref="directive-edit",
        context=OperationGatePipelineContext(
            permission_mode="headless",
            headless_mode=True,
            approval_token=ApprovalToken(
                token_id="approval-1",
                operation_id="op.edit_file",
                directive_ref="directive-edit",
                granted=True,
                source="test",
            ),
        ),
    )

    assert blocked.allowed is False
    assert blocked.decision == "deny"
    assert blocked.pipeline_stage == "headless_policy"
    assert allowed_after_token.allowed is True
    assert allowed_after_token.decision == "allow"
    assert allowed_after_token.pipeline_stage == "allow_rule"


def test_operation_gate_approval_state_can_satisfy_headless_approval() -> None:
    registry = build_default_operation_registry()
    policy = _runtime_policy(
        requires_approval=("op.edit_file",),
        task_id="task-approval-state",
    )
    gate = OperationGate(registry)

    result = gate.check(
        "op.edit_file",
        resource_policy=policy,
        directive_ref="directive-edit-state",
        context=OperationGatePipelineContext(
            permission_mode="headless",
            headless_mode=True,
            approval_state=ApprovalState(
                tokens=(
                    ApprovalToken(
                        token_id="approval-state-1",
                        operation_id="op.edit_file",
                        directive_ref="directive-edit-state",
                        granted=True,
                        source="checkpoint",
                    ),
                )
            ),
        ),
    )

    assert result.allowed is True
    assert result.decision == "allow"
    assert result.pipeline_stage == "allow_rule"


def test_operation_gate_denial_tracking_circuit_breaker() -> None:
    registry = build_default_operation_registry()
    policy = _runtime_policy(allowed=("op.read_file",), task_id="task-denial")
    tracker = DenialTrackingState(max_consecutive_denials=1, max_total_denials=20)
    gate = OperationGate(registry)

    first = gate.check(
        "op.write_file",
        resource_policy=policy,
        directive_ref="directive-denied",
        context=OperationGatePipelineContext(denial_tracking=tracker),
    )
    second = gate.check(
        "op.read_file",
        resource_policy=policy,
        directive_ref="directive-read",
        context=OperationGatePipelineContext(denial_tracking=tracker),
    )

    assert first.allowed is False
    assert tracker.tripped is True
    assert second.allowed is False
    assert second.reason == "denial tracking circuit is open"
    assert second.pipeline_stage == "denial_tracking"


def test_operation_gate_invokes_operation_specific_safety_validator() -> None:
    registry = build_default_operation_registry()
    policy = _runtime_policy(allowed=("op.shell",), task_id="task-shell-validator")
    gate = OperationGate(registry)

    result = gate.check(
        "op.shell",
        resource_policy=policy,
        directive_ref="directive-shell",
        context=OperationGatePipelineContext(
            operation_input={"command": "rg TODO | cat"},
            validators={"shell_read_only": validate_shell_read_only},
        ),
    )

    assert result.allowed is False
    assert result.reason == "shell command uses control operators"
    assert result.pipeline_stage == "operation_specific_safety_validator"


def test_shell_read_only_validator_blocks_control_operators_and_git_config() -> None:
    assert validate_shell_read_only({"command": "git status"})[0] is True
    assert validate_shell_read_only({"command": "git -c core.pager=cat status"}) == (
        False,
        "git command uses dangerous configuration flag",
    )
    assert validate_shell_read_only({"command": "rg TODO | cat"}) == (
        False,
        "shell command uses control operators",
    )


def test_filesystem_path_validator_blocks_workspace_escape_and_expansion() -> None:
    assert validate_filesystem_path({"path": "backend/orchestration/resource_gate.py"})[0] is True
    assert validate_filesystem_path({"path": "../outside.txt"}) == (
        False,
        "filesystem path escapes through parent traversal",
    )
    assert validate_filesystem_path({"path": "$HOME/secret.txt"}) == (
        False,
        "filesystem path uses expansion syntax",
    )


def _runtime_policy(
    *,
    task_id: str,
    allowed: tuple[str, ...] = (),
    denied: tuple[str, ...] = (),
    requires_approval: tuple[str, ...] = (),
) -> ResourcePolicy:
    decisions = tuple(
        ResourceDecision(operation_id=operation_id, decision="allow", reason="test")
        for operation_id in allowed
    )
    return ResourcePolicy(
        policy_id=f"respol:{task_id}:runtime",
        task_id=task_id,
        allowed_operations=allowed,
        denied_operations=denied,
        requires_approval_operations=requires_approval,
        runtime_view_only=False,
        adopted=True,
        runtime_executable=True,
        decisions=decisions,
    )
