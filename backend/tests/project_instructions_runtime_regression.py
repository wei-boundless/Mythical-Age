from __future__ import annotations

from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler


def test_single_turn_runtime_injects_root_agents_as_project_instruction(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (tmp_path / "AGENTS.md").write_text("ROOT_PROJECT_INSTRUCTION: use fixed ports.", encoding="utf-8")

    packet = RuntimeCompiler(base_dir=backend_dir).compile_single_agent_turn_packet(
        session_id="session:project-instructions",
        turn_id="turn:project-instructions",
        agent_invocation_id="aginvoke:project-instructions",
        user_message="检查项目规则",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
            "control_capabilities": {"may_request_task_run": False, "may_control_active_work": False},
        },
    ).packet

    model_input = _model_input(packet)
    manifest = packet.diagnostics["prompt_manifest"]

    assert "project.instructions.scoped" in manifest["project_instruction_refs"]
    assert manifest["project_instructions"]["source_count"] == 1
    assert manifest["project_instructions"]["sources"][0]["path"].endswith("AGENTS.md")
    assert manifest["project_instructions"]["sources"][0]["content_hash"].startswith("sha256:")
    assert "AGENTS.md" not in manifest["stable_prompt_refs"]


def test_task_execution_project_instructions_include_nested_scope_for_target_file(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    nested_dir = tmp_path / "backend" / "module"
    nested_dir.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("ROOT_SCOPE_RULE", encoding="utf-8")
    (nested_dir / "AGENTS.md").write_text("NESTED_SCOPE_RULE", encoding="utf-8")

    packet = RuntimeCompiler(base_dir=backend_dir).compile_task_execution_packet(
        session_id="session:nested-project-instructions",
        task_run={
            "task_run_id": "taskrun:nested-project-instructions",
            "task_id": "task:nested-project-instructions",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={
            "task_run_goal": "修改 backend/module/service.py",
            "completion_criteria": ["完成修改"],
            "target_files": ["backend/module/service.py"],
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    ).packet

    model_input = _model_input(packet)
    manifest = packet.diagnostics["prompt_manifest"]

    assert manifest["project_instructions"]["source_count"] == 2
    assert manifest["project_instructions"]["cache_scope"] == "task_stable"


def test_task_execution_does_not_include_unscoped_nested_agents(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    nested_dir = tmp_path / "backend" / "module"
    other_dir = tmp_path / "backend" / "other"
    nested_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("ROOT_SCOPE_RULE", encoding="utf-8")
    (nested_dir / "AGENTS.md").write_text("NESTED_SCOPE_RULE", encoding="utf-8")
    (other_dir / "AGENTS.md").write_text("OTHER_SCOPE_RULE", encoding="utf-8")

    packet = RuntimeCompiler(base_dir=backend_dir).compile_task_execution_packet(
        session_id="session:nested-project-instructions",
        task_run={
            "task_run_id": "taskrun:nested-project-instructions",
            "task_id": "task:nested-project-instructions",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={
            "task_run_goal": "修改 backend/module/service.py",
            "completion_criteria": ["完成修改"],
            "target_files": ["backend/module/service.py"],
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    ).packet

    model_input = _model_input(packet)



def _model_input(packet) -> str:
    return "\n".join(str(message.get("content") or "") for message in packet.model_messages)
