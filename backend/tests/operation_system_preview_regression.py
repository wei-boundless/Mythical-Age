from __future__ import annotations

from operations import (
    OperationGate,
    RuntimeApprovalContext,
    build_default_operation_registry,
    build_operation_requirement,
    build_resource_policy_preview,
    build_resource_runtime_views,
)


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


def test_resource_policy_preview_denies_unknown_and_denied_aliases() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-2",
        source="task_binding_preview",
        operation_scope=("op.read_file", "op.shell", "op.unknown"),
        denied_operations=("terminal",),
    )

    policy = build_resource_policy_preview(requirement, registry)
    decisions = {decision.operation_id: decision for decision in policy.decisions}

    assert policy.authority == "resource_policy"
    assert policy.preview_only is True
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

    policy = build_resource_policy_preview(requirement, registry)
    decisions = {decision.operation_id: decision for decision in policy.decisions}
    views = {view.resource_id: view for view in build_resource_runtime_views(policy, registry)}

    assert decisions["op.edit_file"].decision == "requires_approval"
    assert decisions["op.python_repl"].decision == "requires_approval"
    assert views["op.read_file"].authorized is True
    assert views["op.read_file"].preview_available is True
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

    policy = build_resource_policy_preview(
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

    policy = build_resource_policy_preview(
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


def test_worker_and_memory_write_candidate_stay_preview_or_denied() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-6",
        source="task_binding_preview",
        operation_scope=("op.worker_pdf", "op.memory_write_candidate"),
    )

    policy = build_resource_policy_preview(requirement, registry)
    decisions = {decision.operation_id: decision for decision in policy.decisions}
    views = {view.resource_id: view for view in build_resource_runtime_views(policy, registry)}

    assert decisions["op.worker_pdf"].decision == "preview_only"
    assert decisions["op.memory_write_candidate"].decision == "deny"
    assert views["op.worker_pdf"].preview_available is True
    assert views["op.worker_pdf"].authorized is False
    assert views["op.worker_pdf"].runtime_executable is False


def test_operation_gate_rejects_preview_policy_even_for_allowed_preview_operation() -> None:
    registry = build_default_operation_registry()
    requirement = build_operation_requirement(
        task_id="task-7",
        source="task_binding_preview",
        operation_scope=("op.read_file",),
    )
    policy = build_resource_policy_preview(requirement, registry)
    gate = OperationGate(registry)

    missing_directive = gate.check("op.read_file", resource_policy=policy)
    preview_policy = gate.check("op.read_file", resource_policy=policy, directive_ref="directive-1")

    assert missing_directive.allowed is False
    assert missing_directive.reason == "missing directive_ref"
    assert preview_policy.allowed is False
    assert preview_policy.reason == "resource policy is preview-only and not executable"

