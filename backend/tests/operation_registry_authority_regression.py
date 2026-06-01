from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from permissions.operation_gate import OperationGate
from permissions.operations import build_default_operation_registry
from capability_system.tools.native_tool_catalog import ToolDefinition, get_tool_definitions


def test_tool_definition_risk_flags_derive_from_operation_registry() -> None:
    registry = build_default_operation_registry()

    for definition in get_tool_definitions():
        operation = registry.get_operation(definition.operation_id)
        assert operation is not None, f"{definition.name} references unknown operation {definition.operation_id}"
        assert definition.is_read_only is operation.read_only
        assert definition.is_destructive is operation.destructive
        assert definition.is_concurrency_safe is operation.concurrency_safe

    by_name = {definition.name: definition for definition in get_tool_definitions()}
    python_repl_operation = registry.get_operation("op.python_repl")
    assert python_repl_operation is not None
    assert by_name["python_repl"].is_destructive is True
    assert by_name["python_repl"].is_destructive is python_repl_operation.destructive


def test_tool_definition_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="unknown operation"):
        ToolDefinition(
            name="unknown_runtime_tool",
            display_name="Unknown runtime tool",
            operation_id="op.unknown_runtime_tool",
            module="tools.unknown_runtime_tool",
            factory=lambda _base_dir: None,  # type: ignore[return-value]
        )


def test_operation_gate_unknown_operation_fails_closed() -> None:
    gate = OperationGate(build_default_operation_registry())

    result = gate.check("op.unknown_runtime_tool", resource_policy=None, directive_ref="directive:test")

    assert result.allowed is False
    assert result.decision == "deny"
    assert result.reason == "unknown operation"
    assert result.pipeline_stage == "descriptor_exists"
    assert result.diagnostics["fail_closed"] is True
