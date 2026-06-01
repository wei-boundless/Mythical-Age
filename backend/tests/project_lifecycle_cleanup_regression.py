from __future__ import annotations

from pathlib import Path

from task_system.projects.project_lifecycle_service import ProjectLifecycleService
from task_system.registry.flow_registry import TaskFlowRegistry


def _seed_tasks(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_assignment(
        task_id="task.writing.modular_novel.node.world_design",
        task_title="World Design Node",
        task_kind="specific_task",
        flow_id="flow.writing.modular_novel.node.world_design",
        domain_id="writing",
        task_environment_id="env.creation.writing",
        default_agent_id="agent:0",
    )
    registry.upsert_task_assignment(
        task_id="task.keep.nonwriting",
        task_title="Keep",
        task_kind="specific_task",
        flow_id="flow.keep.nonwriting",
        domain_id="general",
        task_environment_id="env.general.workspace",
        default_agent_id="agent:0",
    )
    registry.upsert_task_graph(
        graph_id="graph.writing.modular_novel.design_init",
        title="Design Init",
        domain_id="writing",
        graph_kind="task_graph",
        nodes=(),
        edges=(),
        enabled=True,
        metadata={"task_environment_id": "env.creation.writing"},
    )


def test_project_lifecycle_cleanup_preview_identifies_legacy_writing_node_tasks(tmp_path: Path) -> None:
    _seed_tasks(tmp_path)
    service = ProjectLifecycleService(tmp_path)

    payload = service.preview(project_id="project.creation.writing.honghuang", action="cleanup_legacy_writing_tasks")
    preview = payload["preview"]

    assert preview["task_ids"] == ["task.writing.modular_novel.node.world_design"]
    assert preview["preserved"]["task_graphs"] is True
    assert preview["preserved"]["artifacts"] is True


def test_project_lifecycle_cleanup_execute_removes_legacy_tasks_without_deleting_graphs(tmp_path: Path) -> None:
    _seed_tasks(tmp_path)
    service = ProjectLifecycleService(tmp_path)

    run_payload = service.start(project_id="project.creation.writing.honghuang", action="cleanup_legacy_writing_tasks", execute=True)
    run = run_payload["run"]
    registry = TaskFlowRegistry(tmp_path)

    assert run["status"] == "completed"
    assert "task.writing.modular_novel.node.world_design" in run["result"]["deleted_task_ids"]
    assert registry.get_task_assignment("task.writing.modular_novel.node.world_design") is None
    assert registry.get_task_assignment("task.keep.nonwriting") is not None
    assert registry.get_task_graph("graph.writing.modular_novel.design_init") is not None


def test_deleted_legacy_task_does_not_resurface_from_explicit_storage(tmp_path: Path) -> None:
    _seed_tasks(tmp_path)
    service = ProjectLifecycleService(tmp_path)
    service.start(project_id="project.creation.writing.honghuang", action="cleanup_legacy_writing_tasks", execute=True)

    registry = TaskFlowRegistry(tmp_path)
    assert registry.get_specific_task_record("task.writing.modular_novel.node.world_design") is None
    assert registry.get_task_assignment("task.writing.modular_novel.node.world_design") is None
    assert registry.get_task_execution_policy("task.writing.modular_novel.node.world_design") is None
    assert registry.get_flow_contract_binding("task.writing.modular_novel.node.world_design") is None

    preview = service.preview(project_id="project.creation.writing.honghuang", action="cleanup_legacy_writing_tasks")["preview"]
    assert preview["task_ids"] == []
