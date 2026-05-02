from __future__ import annotations

from tasks import TaskFlowRegistry, TaskTemplateRegistry


def test_task_template_registry_lists_core_templates() -> None:
    templates = TaskTemplateRegistry().list_templates()
    template_ids = {item.template_id for item in templates}

    assert "template.chat.general_response" in template_ids
    assert "template.rag.knowledge_answer" in template_ids
    assert "template.pdf.document_analysis" in template_ids
    assert "template.data.structured_analysis" in template_ids
    assert "template.dev.workspace_patch" in template_ids
    assert "template.dev.light_web_game" in template_ids


def test_task_template_registry_selects_game_template_for_light_web_game_request() -> None:
    template = TaskTemplateRegistry().select_template(
        user_goal="开发一个贪吃蛇小游戏，并接到当前前端页面里。",
        query_understanding={"source_kind": "workspace", "candidate_tools": ["read_file", "edit_file"]},
        current_turn_context={"authority": "context.current_turn", "execution_mode": "single"},
        definitions=[],
    )

    assert template.template_id == "template.dev.light_web_game"
    assert any(step.step_kind == "verify" for step in template.step_blueprints)


def test_task_system_overview_exposes_templates_and_validation_matrix(tmp_path) -> None:
    payload = TaskFlowRegistry(tmp_path).build_overview()

    assert payload["summary"]["task_template_count"] >= 6
    assert payload["templates"]
    assert payload["template_validation_matrix"]["authority"] == "task_system.template_validation_matrix"
    assert all("template_id" in row for row in payload["template_validation_matrix"]["rows"])
