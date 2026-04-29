from __future__ import annotations

import pytest

from orchestration import ControlKernel, ControlKernelPreviewContext, TaskContract
from tasks import build_task_runtime_contract_preview


def test_control_kernel_preview_context_records_refs_without_directives() -> None:
    task = TaskContract(
        task_id="task-kernel-preview",
        user_goal="读取 docs 并总结",
        session_id="session-kernel",
    )
    context = ControlKernelPreviewContext(
        task_prompt_contract_ref="task-prompt:task-kernel-preview:preview",
        resource_policy_ref="policy:task-kernel-preview:preview",
        prompt_manifest_ref="manifest-task-kernel-preview-preview",
        operation_requirement_ref="opreq:task-kernel-preview:task_binding_preview",
        denied_operations=("op.shell",),
        requires_approval_operations=("op.edit_file",),
    )

    result = ControlKernel().collect(task=task, preview_context=context)
    graph = result.execution_graph

    assert result.status == "blocked"
    assert result.reason == "preview_only"
    assert result.directives == ()
    assert graph is not None
    assert graph.nodes == ()
    assert graph.edges == ()
    assert graph.refs["state"] == "preview_only"
    assert graph.refs["blocked_reason"] == "preview_only"
    assert graph.refs["resource_policy_ref"] == "policy:task-kernel-preview:preview"
    assert graph.refs["resource_policy_adopted"] is False
    assert graph.refs["runtime_directive_enabled"] is False
    assert graph.refs["runtime_executable"] is False
    assert result.diagnostics["fail_closed"] is True
    assert result.diagnostics["preview_only"] is True
    assert result.diagnostics["resource_policy_state"] == "preview"
    assert result.diagnostics["resource_policy_adopted"] is False
    assert result.diagnostics["runtime_directive_enabled"] is False
    assert result.diagnostics["runtime_executable"] is False
    assert result.diagnostics["operation_gate_required_before_execution"] is True
    assert result.diagnostics["directive_count"] == 0
    assert result.diagnostics["execution_node_count"] == 0
    assert result.diagnostics["denied_operations"] == ["op.shell"]
    assert result.diagnostics["requires_approval_operations"] == ["op.edit_file"]


def test_control_kernel_preview_context_rejects_runtime_authority() -> None:
    with pytest.raises(ValueError, match="adopted policy"):
        ControlKernelPreviewContext(resource_policy_adopted=True)

    with pytest.raises(ValueError, match="runtime directives"):
        ControlKernelPreviewContext(runtime_directive_enabled=True)

    with pytest.raises(ValueError, match="runtime executable"):
        ControlKernelPreviewContext(runtime_executable=True)


def test_task_runtime_contract_preview_uses_control_kernel_preview_result() -> None:
    preview = build_task_runtime_contract_preview(
        session_id="session-kernel-bridge",
        task_id="task-kernel-bridge",
        user_goal="修改任务系统文档，然后检查有没有前后矛盾",
    )
    result = preview["control_kernel_result"]
    graph = result["execution_graph"]
    diagnostics = preview["control_kernel_diagnostics"]

    assert result["status"] == "blocked"
    assert result["reason"] == "preview_only"
    assert result["directives"] == []
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["refs"]["state"] == "preview_only"
    assert graph["refs"]["resource_policy_ref"] == preview["resource_policy"]["policy_id"]
    assert graph["refs"]["task_prompt_contract_ref"] == preview["task_prompt_contract"]["contract_id"]
    assert graph["refs"]["prompt_manifest_ref"] == preview["prompt_manifest_preview"]["manifest_id"]
    assert graph["refs"]["operation_requirement_ref"] == preview["operation_requirement"]["requirement_id"]
    assert diagnostics["resource_policy_ref"] == preview["resource_policy"]["policy_id"]
    assert diagnostics["resource_policy_state"] == "preview"
    assert diagnostics["resource_policy_adopted"] is False
    assert diagnostics["preview_only"] is True
    assert diagnostics["runtime_directive_enabled"] is False
    assert diagnostics["runtime_executable"] is False
    assert diagnostics["operation_gate_required_before_execution"] is True
    assert "op.edit_file" in diagnostics["requires_approval_operations"]
