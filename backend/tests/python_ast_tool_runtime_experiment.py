from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile  # noqa: E402
from permissions.operations import build_default_operation_registry  # noqa: E402
from capability_system.tools.authorization import build_tool_authorization_index  # noqa: E402
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions  # noqa: E402
from permissions import OperationGate, OperationGatePipelineContext, build_model_response_runtime_admission  # noqa: E402
from capability_system.tools.validators import validate_filesystem_path  # noqa: E402
from harness.runtime import build_runtime_tool_plan, tool_instances_for_runtime_tool_plan  # noqa: E402


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
        plan = build_runtime_tool_plan(
            runtime_assembly=_runtime_assembly_for_tools(
                "turn:python-ast",
                tool_names=PYTHON_AST_TOOLS,
                definitions_by_name=index.definitions_by_name,
            ),
            invocation_kind="task_execution",
            tool_definitions_by_name=index.definitions_by_name,
        )
        final_tools = tool_instances_for_runtime_tool_plan(
            tool_instances=tool_instances,
            tool_plan=plan,
        )
        final_by_name = {str(getattr(tool, "name", "") or ""): tool for tool in final_tools}
        assert set(PYTHON_AST_TOOLS).issubset({str(item.get("tool_name") or "") for item in plan.model_visible_tools})
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

class _runtime_assembly_for_tools:
    def __init__(self, turn_id: str, *, tool_names: tuple[str, ...], definitions_by_name: dict[str, object]) -> None:
        self.turn_id = turn_id
        self.tool_names = tool_names
        self.definitions_by_name = definitions_by_name

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": "session:python-ast",
            "turn_id": self.turn_id,
            "agent_invocation_id": f"aginvoke:{self.turn_id}",
            "available_tools": [
                {
                    "tool_name": name,
                    "operation_id": str(getattr(self.definitions_by_name[name], "operation_id", "") or name),
                }
                for name in self.tool_names
            ],
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {},
        }


if __name__ == "__main__":
    main()
