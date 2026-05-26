from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "ApprovalState": (".operation_gate", "ApprovalState"),
    "ApprovalToken": (".operation_gate", "ApprovalToken"),
    "DenialTrackingState": (".operation_gate", "DenialTrackingState"),
    "OperationGate": (".operation_gate", "OperationGate"),
    "OperationGatePipelineContext": (".operation_gate", "OperationGatePipelineContext"),
    "OperationGateResult": (".operation_gate", "OperationGateResult"),
    "PERMISSION_MODES": (".policy", "PERMISSION_MODES"),
    "PermissionDecision": (".models", "PermissionDecision"),
    "PermissionContext": (".context_models", "PermissionContext"),
    "PermissionReceipt": (".receipt_models", "PermissionReceipt"),
    "UnifiedPermissionDecision": (".decision_models", "PermissionDecision"),
    "PermissionService": (".service", "PermissionService"),
    "ResourceDecision": (".resource_policy", "ResourceDecision"),
    "ResourcePolicy": (".resource_policy", "ResourcePolicy"),
    "RuntimeApprovalContext": (".resource_policy_builder", "RuntimeApprovalContext"),
    "build_model_response_runtime_admission": (
        ".runtime_policy_builder",
        "build_model_response_runtime_admission",
    ),
    "build_resource_policy_candidate": (".resource_policy_builder", "build_resource_policy_candidate"),
    "build_runtime_capability_state": (".runtime_policy_builder", "build_runtime_capability_state"),
    "build_tool_request_runtime_admission": (".tool_admission", "build_tool_request_runtime_admission"),
    "decide_tool_permission": (".decision_pipeline", "decide_tool_permission"),
    "list_allowed_tool_names": (".decision_pipeline", "list_allowed_tool_names"),
    "mode_allows_tool": (".policy", "mode_allows_tool"),
    "normalize_permission_mode": (".policy", "normalize_permission_mode"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
