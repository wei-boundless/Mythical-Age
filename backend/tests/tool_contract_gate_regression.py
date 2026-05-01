from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools.contracts import SkillToolScope, ToolContractGate
from tools.runtime import ToolRuntime


def test_pdf_contract_shadow_mode_marks_missing_owner_without_blocking() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="shadow")
        decision = gate.evaluate(
            tool_name="pdf_analysis",
            contract=runtime.get_contract("pdf_analysis"),
            tool_input={"query": "第四页讲了什么"},
            binding_context={"active_pdf": ""},
        )

        assert decision.allowed is False
        assert decision.action == "clarify"
        assert decision.reason == "missing_required_binding"
        assert decision.should_block is False
        assert decision.missing_bindings == ["active_pdf"]


def test_pdf_contract_enforce_mode_blocks_missing_owner() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="enforce")
        decision = gate.evaluate(
            tool_name="pdf_analysis",
            contract=runtime.get_contract("pdf_analysis"),
            tool_input={"query": "第四页讲了什么"},
            binding_context={"active_pdf": ""},
        )

        assert decision.allowed is False
        assert decision.should_block is True
        assert decision.action == "clarify"


def test_pdf_contract_allows_explicit_path_without_active_binding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="enforce")
        decision = gate.evaluate(
            tool_name="pdf_analysis",
            contract=runtime.get_contract("pdf_analysis"),
            tool_input={"query": "第四页讲了什么", "path": "knowledge/report.pdf"},
            binding_context={"active_pdf": ""},
        )

        assert decision.allowed is True
        assert decision.should_block is False
        assert decision.reason == "contract_satisfied"


def test_skill_scope_is_checked_by_contract_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runtime = ToolRuntime(Path(tmp))
        gate = ToolContractGate(mode="enforce")
        decision = gate.evaluate(
            tool_name="pdf_analysis",
            contract=runtime.get_contract("pdf_analysis"),
            tool_input={"query": "第四页讲了什么", "path": "knowledge/report.pdf"},
            tool_scope=SkillToolScope(
                source="skill",
                allowed_tools=("get_weather",),
                skill_name="weather-advisor",
                reason="regression_scope",
            ),
            binding_context={"active_pdf": ""},
        )

        assert decision.allowed is False
        assert decision.should_block is True
        assert decision.reason == "tool_not_allowed_by_skill_contract"
