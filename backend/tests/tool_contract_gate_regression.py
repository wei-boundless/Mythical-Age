from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tool_contracts import SkillToolScope, ToolContractGate
from capability_system.tool_runtime import ToolRuntime


def test_read_file_contract_shadow_mode_marks_missing_owner_without_blocking() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="shadow")
        decision = gate.evaluate(
            tool_name="read_file",
            contract=runtime.get_contract("read_file"),
            tool_input={},
            binding_context={},
        )

        assert decision.allowed is False
        assert decision.action == "clarify"
        assert decision.reason == "missing_required_input"
        assert decision.should_block is False
        assert decision.missing_inputs == ["path"]


def test_read_file_contract_enforce_mode_blocks_missing_owner() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="enforce")
        decision = gate.evaluate(
            tool_name="read_file",
            contract=runtime.get_contract("read_file"),
            tool_input={},
            binding_context={},
        )

        assert decision.allowed is False
        assert decision.should_block is True
        assert decision.action == "clarify"


def test_read_file_contract_allows_explicit_path_without_active_binding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="enforce")
        decision = gate.evaluate(
            tool_name="read_file",
            contract=runtime.get_contract("read_file"),
            tool_input={"path": "knowledge/report.md"},
            binding_context={},
        )

        assert decision.allowed is True
        assert decision.should_block is False
        assert decision.reason == "contract_satisfied"


def test_skill_scope_is_checked_by_contract_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="enforce")
        decision = gate.evaluate(
            tool_name="read_file",
            contract=runtime.get_contract("read_file"),
            tool_input={"path": "knowledge/report.md"},
            tool_scope=SkillToolScope(
                source="skill",
                allowed_tools=("web_search",),
                skill_name="legacy-test-skill",
                reason="regression_scope",
            ),
            binding_context={},
        )

        assert decision.allowed is False
        assert decision.should_block is True
        assert decision.reason == "tool_not_allowed_by_skill_contract"
