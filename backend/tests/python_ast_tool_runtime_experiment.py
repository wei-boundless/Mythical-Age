from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile  # noqa: E402
from capability_system import build_default_operation_registry  # noqa: E402
from capability_system.tool_authorization import build_tool_authorization_index  # noqa: E402
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions  # noqa: E402
from permissions import OperationGate, OperationGatePipelineContext, build_model_response_runtime_admission  # noqa: E402
from capability_system.validators import validate_filesystem_path  # noqa: E402
from runtime.capabilities import build_current_turn_capability_plan, tool_instances_for_capability_plan  # noqa: E402


PYTHON_AST_OPERATIONS = (
    "op.python_code_outline",
    "op.python_parse_check",
    "op.python_symbol_search",
)
PYTHON_AST_TOOLS = (
    "python_code_outline",
    "python_parse_check",
    "python_symbol_search",
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "pkg"
        package.mkdir()
        (package / "sample.py").write_text(
            "\n".join(
                [
                    "import pathlib",
                    "ANSWER = 42",
                    "",
                    "class Runner:",
                    "    async def execute(self) -> int:",
                    "        return ANSWER",
                    "",
                    "def make_runner() -> Runner:",
                    "    return Runner()",
                ]
            ),
            encoding="utf-8",
        )
        (package / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

        registry = build_default_operation_registry()
        profile = AgentRuntimeProfile(
            agent_profile_id="experiment.python_ast",
            agent_id="agent:experiment",
            allowed_operations=("op.model_response", *PYTHON_AST_OPERATIONS),
            blocked_operations=(),
        )
        task_operation = {
            "task_contract": {"task_id": "task:experiment:python_ast"},
            "operation_requirement": {
                "required_operations": ["op.model_response"],
                "optional_operations": list(PYTHON_AST_OPERATIONS),
                "denied_operations": [],
                "metadata": {"approval_policy": "default"},
            },
        }

        _directive, resource_policy = build_model_response_runtime_admission(
            task_operation,
            operation_registry=registry,
            agent_runtime_profile=profile,
        )
        assert set(PYTHON_AST_OPERATIONS).issubset(set(resource_policy.allowed_operations))
        assert set(PYTHON_AST_TOOLS).issubset(set(resource_policy.allowed_tools))

        tool_instances = build_tool_instances(root)
        index = build_tool_authorization_index(get_tool_definitions())
        plan = build_current_turn_capability_plan(
            tool_instances=tool_instances,
            resource_policy=resource_policy,
            definitions_by_name=index.definitions_by_name,
            normalize_operation_id=registry.normalize_id,
            task_operation=task_operation,
        )
        final_tools = tool_instances_for_capability_plan(
            tool_instances=tool_instances,
            capability_plan=plan,
        )
        final_by_name = {str(getattr(tool, "name", "") or ""): tool for tool in final_tools}
        assert set(PYTHON_AST_TOOLS).issubset(set(plan.model_visible_tools))
        assert set(PYTHON_AST_TOOLS).issubset(set(final_by_name))

        outline = final_by_name["python_code_outline"]._run("pkg/sample.py")
        parse_ok = final_by_name["python_parse_check"]._run("pkg/sample.py")
        parse_bad = final_by_name["python_parse_check"]._run("pkg/broken.py")
        search = final_by_name["python_symbol_search"]._run("execute", roots=["pkg"])

        assert "Runner.execute" in str(outline)
        assert parse_ok["structured_payload"]["tool_result"]["valid"] is True
        assert parse_bad["structured_payload"]["tool_result"]["ok"] is False
        assert "Runner.execute" in str(search)

        gate = OperationGate(registry)
        allowed_gate = gate.check(
            "op.python_code_outline",
            resource_policy=resource_policy,
            directive_ref="directive:experiment:python-outline",
            context=OperationGatePipelineContext(
                operation_input={"path": "pkg/sample.py"},
                validators={"filesystem_path": validate_filesystem_path},
            ),
        )
        denied_gate = gate.check(
            "op.python_code_outline",
            resource_policy=resource_policy,
            directive_ref="directive:experiment:python-outline-denied",
            context=OperationGatePipelineContext(
                operation_input={"path": "../outside.py"},
                validators={"filesystem_path": validate_filesystem_path},
            ),
        )
        assert allowed_gate.allowed is True
        assert denied_gate.allowed is False
        assert denied_gate.pipeline_stage == "operation_specific_safety_validator"

    print("ALL PASSED (python ast tool runtime experiment)")


if __name__ == "__main__":
    main()
