from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import graph_task_instances as instance_api
from api import orchestration as orchestration_api
from harness import AgentRuntimeServices, GraphHarness
from harness.runtime import SingleAgentRuntimeHost
from core.project_layout import ProjectLayout
from sessions import SessionManager
from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import publish_graph_harness_config_for_graph
from task_system.graph_instances import GraphTaskInstanceFileService, GraphTaskInstanceRepository
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


def _graph(graph_id: str = "graph.test.instance_project") -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id=graph_id,
        title="Instance Project Graph",
        graph_kind="multi_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="produce",
        output_node_id="produce",
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="生产节点",
                task_id="task.test.instance.produce",
                agent_id="agent:0",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名生产节点执行员。",
                        "task_instruction": "请完成当前生产节点任务。",
                    }
                },
            ),
        ),
    )


def _handoff_graph(
    graph_id: str = "graph.test.instance_human_edge",
    *,
    draft_post_node_gate: bool = False,
) -> TaskGraphDefinition:
    draft_metadata = {
        "prompt_contract": {
            "role_prompt": "你是一名章节写手。",
            "task_instruction": "请根据项目输入完成当前章节正文。",
        }
    }
    if draft_post_node_gate:
        draft_metadata["post_node_gate_policy"] = {
            "mode": "wait_human_after_node",
            "review_result_policy": "wait_always",
            "allowed_human_actions": ["approve_continue", "request_revision"],
        }
    return TaskGraphDefinition(
        graph_id=graph_id,
        title="Instance Human Edge Graph",
        graph_kind="multi_agent",
        publish_state="published",
        enabled=True,
        entry_node_id="draft",
        output_node_id="review",
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="写手",
                task_id="task.test.instance.draft",
                agent_id="agent:writer",
                metadata=draft_metadata,
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                task_id="task.test.instance.review",
                agent_id="agent:reviewer",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名章节审核员。",
                        "task_instruction": "请审核上游章节是否可以进入正式库。",
                    }
                },
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="handoff",
            ),
        ),
    )


def _runtime_with_graph_harness(*, base_dir: Path) -> SimpleNamespace:
    host = SingleAgentRuntimeHost(
        ProjectLayout.from_backend_dir(base_dir).runtime_state_dir,
        backend_dir=base_dir,
    )
    services = AgentRuntimeServices.from_runtime_host(host)
    graph_harness = GraphHarness(services=services)
    return SimpleNamespace(
        base_dir=base_dir,
        session_manager=SessionManager(base_dir),
        harness_runtime=SimpleNamespace(graph_harness=graph_harness),
    )


def _upsert_graph(registry: TaskFlowRegistry, graph: TaskGraphDefinition) -> None:
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        domain_id=graph.domain_id,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(item.to_dict() for item in graph.nodes),
        edges=tuple(item.to_dict() for item in graph.edges),
        graph_contract_id=graph.graph_contract_id,
        contract_bindings=dict(graph.contract_bindings or {}),
        default_protocol_id=graph.default_protocol_id,
        working_memory_policy_profile_id=graph.working_memory_policy_profile_id,
        working_memory_policy=dict(graph.working_memory_policy or {}),
        runtime_policy=dict(graph.runtime_policy or {}),
        context_policy=dict(graph.context_policy or {}),
        loop_frames=tuple(dict(item) for item in graph.loop_frames),
        publish_state=graph.publish_state,
        enabled=graph.enabled,
        metadata=dict(graph.metadata or {}),
    )


def test_graph_task_definition_can_create_multiple_project_instances(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _graph()
    _upsert_graph(registry, graph)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)

    original = instance_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        first = asyncio.run(
            instance_api.create_graph_task_instance(
                graph.graph_id,
                instance_api.GraphTaskInstanceCreateRequest(title="项目 A"),
            )
        )
        second = asyncio.run(
            instance_api.create_graph_task_instance(
                graph.graph_id,
                instance_api.GraphTaskInstanceCreateRequest(title="项目 B"),
            )
        )
    finally:
        instance_api.require_runtime = original  # type: ignore[assignment]

    first_id = first["instance"]["graph_task_instance_id"]
    second_id = second["instance"]["graph_task_instance_id"]
    assert first_id != second_id
    assert first["instance"]["graph_id"] == graph.graph_id
    assert second["instance"]["graph_id"] == graph.graph_id
    assert first["root_session"]["scope"] == {
        "workspace_view": "graph_task",
        "task_environment_id": "",
        "project_id": first_id,
    }
    tree = GraphTaskInstanceFileService(backend_dir).tree(first_id)
    child_names = {item["name"] for item in tree["tree"]["children"]}
    assert {"input", "working", "artifacts", "memory", "logs", "runs"}.issubset(child_names)


def test_writing_graph_instance_desk_projects_chapters_assets_and_reader(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _graph("graph.test.writing_desk_projection")
    _upsert_graph(registry, graph)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    instance = GraphTaskInstanceRepository(backend_dir).create(graph_id=graph.graph_id, title="写作投影项目")
    files = GraphTaskInstanceFileService(backend_dir)
    files.write_file(instance.graph_task_instance_id, "chapters/chapter-001.md", "第一章正文")
    files.write_file(instance.graph_task_instance_id, "outline/outline.md", "大纲")
    files.write_file(instance.graph_task_instance_id, "characters/characters.md", "角色表")
    files.write_file(instance.graph_task_instance_id, "chapters/chapter-002.md", "第二章正文")

    original = instance_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        desk = asyncio.run(instance_api.get_writing_graph_instance_desk(instance.graph_task_instance_id))
    finally:
        instance_api.require_runtime = original  # type: ignore[assignment]

    assert desk["authority"] == "api.graph_task_instances.writing_desk"
    assert [item["path"] for item in desk["chapter_index"]] == [
        "chapters/chapter-001.md",
        "chapters/chapter-002.md",
    ]
    assert desk["current_chapter"]["path"] == "chapters/chapter-002.md"
    assert desk["reader"]["content"] == "第二章正文"
    categories = {item["category_id"]: item for item in desk["writing_assets"]["categories"]}
    assert [item["path"] for item in categories["chapters"]["items"]] == [
        "chapters/chapter-001.md",
        "chapters/chapter-002.md",
    ]
    assert categories["outline"]["items"][0]["path"] == "outline/outline.md"
    assert categories["characters"]["items"][0]["path"] == "characters/characters.md"
    assert desk["summary"]["chapter_count"] == 2


def test_graph_task_instance_run_owns_graph_scope_without_environment(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _graph("graph.test.instance_run")
    _upsert_graph(registry, graph)
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    repo = GraphTaskInstanceRepository(backend_dir)
    instance = repo.create(
        graph_id=graph.graph_id,
        title="实例运行项目",
    )
    root_session = runtime.session_manager.create_session(
        title="实例根会话",
        scope={"workspace_view": "graph_task", "task_environment_id": "", "project_id": instance.graph_task_instance_id},
        session_id=f"gti-root-{instance.graph_task_instance_id}",
    )
    instance = repo.patch(instance.graph_task_instance_id, {"root_session_id": str(root_session["id"])})

    original_instance_runtime = instance_api.require_runtime
    original_orchestration_runtime = orchestration_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        result = asyncio.run(
            instance_api.start_graph_task_instance_run(
                instance.graph_task_instance_id,
                instance_api.GraphTaskInstanceRunStartRequest(
                    run_mode="dispatch_only",
                    dispatch_ready=True,
                ),
            )
        )
    finally:
        instance_api.require_runtime = original_instance_runtime  # type: ignore[assignment]
        orchestration_api.require_runtime = original_orchestration_runtime  # type: ignore[assignment]

    updated = result["instance"]
    start = result["start"]
    graph_run = start["graph_run"]
    runtime_scope = graph_run["diagnostics"]["runtime_scope"]
    assert updated["active_graph_run_id"] == start["graph_run_id"]
    assert start["graph_run_id"] in updated["graph_run_ids"]
    assert graph_run["workspace_view"] == "graph_task"
    assert graph_run["task_environment_id"] == ""
    assert graph_run["project_id"] == instance.graph_task_instance_id
    assert graph_run["diagnostics"]["graph_task_instance_id"] == instance.graph_task_instance_id
    assert runtime_scope["graph_task_instance_id"] == instance.graph_task_instance_id
    assert "task_environment_id" not in runtime_scope
    assert "environment_id" not in runtime_scope
    assert runtime_scope["artifact_root"].startswith("storage/graph_task_instances/")
    assert "/runs/" in runtime_scope["artifact_root"]
    assert runtime_scope["artifact_root"].endswith("/artifacts")
    instance_file_root = GraphTaskInstanceFileService(backend_dir).root(instance.graph_task_instance_id)
    assert f"storage/graph_task_instances/{instance_file_root.name}/runs/" in runtime_scope["artifact_root"]


def test_writing_graph_instance_run_uses_saved_project_brief_config(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _graph("graph.writing.modular_novel.instance_config")
    _upsert_graph(registry, graph)
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    project_brief = "题材：东方玄幻。世界核心：群星坠落后，凡人可借星骸修行。主角：边城少年，目标是重建家族。风格：热血升级。"

    original_instance_runtime = instance_api.require_runtime
    original_orchestration_runtime = orchestration_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        created = asyncio.run(
            instance_api.create_graph_task_instance(
                graph.graph_id,
                instance_api.GraphTaskInstanceCreateRequest(
                    title="星骸纪元",
                    description=project_brief,
                    initial_inputs={"project_brief": project_brief, "project_title": "星骸纪元"},
                ),
            )
        )
        result = asyncio.run(
            instance_api.start_graph_task_instance_run(
                created["instance"]["graph_task_instance_id"],
                instance_api.GraphTaskInstanceRunStartRequest(
                    run_mode="dispatch_only",
                    dispatch_ready=True,
                ),
            )
        )
    finally:
        instance_api.require_runtime = original_instance_runtime  # type: ignore[assignment]
        orchestration_api.require_runtime = original_orchestration_runtime  # type: ignore[assignment]

    graph_run_id = result["start"]["graph_run_id"]
    state = runtime.harness_runtime.graph_harness.graph_loop.get_state(graph_run_id)
    assert state is not None
    assert state.initial_inputs["project_brief"] == project_brief
    assert state.initial_inputs["project_title"] == "星骸纪元"
    assert state.initial_inputs["graph_task_instance_id"] == created["instance"]["graph_task_instance_id"]


def test_writing_graph_instance_desk_maps_human_edges_to_chapter_actions(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _handoff_graph("graph.test.writing_desk_human_actions")
    _upsert_graph(registry, graph)
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    instance = GraphTaskInstanceRepository(backend_dir).create(graph_id=graph.graph_id, title="人工审核投影项目")

    original_instance_runtime = instance_api.require_runtime
    original_orchestration_runtime = orchestration_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        asyncio.run(
            instance_api.start_graph_task_instance_run(
                instance.graph_task_instance_id,
                instance_api.GraphTaskInstanceRunStartRequest(
                    run_mode="dispatch_only",
                    dispatch_ready=False,
                ),
            )
        )
        desk = asyncio.run(instance_api.get_writing_graph_instance_desk(instance.graph_task_instance_id))
    finally:
        instance_api.require_runtime = original_instance_runtime  # type: ignore[assignment]
        orchestration_api.require_runtime = original_orchestration_runtime  # type: ignore[assignment]

    actions = desk["chapter_actions"]
    assert [(item["action"], item["decision"], item["label"]) for item in actions] == [
        ("replace_with_user_text", "replace", "采用我的改写稿"),
    ]
    assert {item["edge_id"] for item in actions} == {"edge.draft.review"}
    assert desk["summary"]["action_count"] == 1


def test_graph_task_instance_human_replace_decision_writes_file_and_advances_edge(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _handoff_graph()
    _upsert_graph(registry, graph)
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    instance = GraphTaskInstanceRepository(backend_dir).create(graph_id=graph.graph_id, title="人工替写项目")

    original_instance_runtime = instance_api.require_runtime
    original_orchestration_runtime = orchestration_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        start_result = asyncio.run(
            instance_api.start_graph_task_instance_run(
                instance.graph_task_instance_id,
                instance_api.GraphTaskInstanceRunStartRequest(
                    run_mode="dispatch_only",
                    dispatch_ready=False,
                ),
            )
        )
        monitor_before = asyncio.run(instance_api.get_graph_task_instance_monitor(instance.graph_task_instance_id, event_limit=40))
        controls = monitor_before["human_controls"]["available"]
        assert [item["edge_id"] for item in controls] == ["edge.draft.review"]
        assert controls[0]["allowed_decisions"] == ["replace"]

        decision_result = asyncio.run(
            instance_api.submit_graph_task_instance_human_edge_decision(
                instance.graph_task_instance_id,
                instance_api.HumanEdgeDecisionSubmitRequest(
                    graph_run_id=start_result["start"]["graph_run_id"],
                    edge_id="edge.draft.review",
                    decision="replace",
                    instruction="用户已完成正文，直接进入审核。",
                    content_submission={
                        "path": "chapters/chapter-001.md",
                        "content": "第一章正文",
                        "content_kind": "chapter",
                    },
                ),
            )
        )
    finally:
        instance_api.require_runtime = original_instance_runtime  # type: ignore[assignment]
        orchestration_api.require_runtime = original_orchestration_runtime  # type: ignore[assignment]

    assert decision_result["decision"]["status"] == "applied"
    assert decision_result["decision"]["content_submission"]["path"] == "chapters/chapter-001.md"
    assert "content" not in decision_result["decision"]["content_submission"]
    assert decision_result["apply_result"]["accepted_result"]["executor_type"] == "human"
    assert decision_result["apply_result"]["accepted_result"]["node_id"] == "draft"
    assert decision_result["apply_result"]["node_work_orders"][0]["node_id"] == "review"

    file_payload = GraphTaskInstanceFileService(backend_dir).read_file(
        instance.graph_task_instance_id,
        "chapters/chapter-001.md",
    )
    assert file_payload["content"] == "第一章正文"
    state = decision_result["apply_result"]["graph_loop_state"]
    assert state["node_states"]["draft"]["status"] == "completed"
    assert state["node_states"]["draft"]["human_edge_decision"]["decision"] == "replace"
    assert state["edge_states"]["edge.draft.review"]["status"] == "ready"


def test_writing_chapter_action_approve_normalizes_to_human_edge_decision(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _handoff_graph("graph.test.writing_chapter_action_approve", draft_post_node_gate=True)
    _upsert_graph(registry, graph)
    graph_config = publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    instance = GraphTaskInstanceRepository(backend_dir).create(graph_id=graph.graph_id, title="写作通过项目")

    original_instance_runtime = instance_api.require_runtime
    original_orchestration_runtime = orchestration_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        start_result = asyncio.run(
            instance_api.start_graph_task_instance_run(
                instance.graph_task_instance_id,
                instance_api.GraphTaskInstanceRunStartRequest(
                    run_mode="dispatch_only",
                    dispatch_ready=True,
                ),
            )
        )
        first_order = dict(start_result["start"]["node_work_orders"][0])
        runtime.harness_runtime.graph_harness.accept_node_result(
            graph_config=graph_config,
            graph_run_id=str(start_result["start"]["graph_run_id"]),
            result={
                "result_id": "nresult:writing-action-approve:draft",
                "graph_run_id": str(start_result["start"]["graph_run_id"]),
                "task_run_id": str(start_result["start"]["task_run_id"]),
                "node_id": "draft",
                "work_order_id": str(first_order["work_order_id"]),
                "outputs": {"chapter": "第一章正文"},
            },
        )
        desk = asyncio.run(instance_api.get_writing_graph_instance_desk(instance.graph_task_instance_id, event_limit=40))
        approve_action = next(item for item in desk["chapter_actions"] if item["action"] == "approve")

        result = asyncio.run(
            instance_api.submit_writing_graph_chapter_action(
                instance.graph_task_instance_id,
                instance_api.WritingChapterActionRequest(
                    action="approve",
                    control_id=approve_action["control_id"],
                    instruction="本章通过，进入审核。",
                ),
            )
        )
    finally:
        instance_api.require_runtime = original_instance_runtime  # type: ignore[assignment]
        orchestration_api.require_runtime = original_orchestration_runtime  # type: ignore[assignment]

    assert result["authority"] == "api.graph_task_instances.writing_chapter_action"
    assert result["chapter_action"]["action"] == "approve"
    assert result["summary"]["decision"] == "pass"
    decision_result = result["decision_result"]
    assert decision_result["decision"]["decision"] == "pass"
    assert decision_result["decision"]["status"] == "applied"
    assert decision_result["decision"]["metadata"]["submitted_from"] == "writing_chapter_action_api"
    assert decision_result["apply_result"]["node_work_orders"][0]["node_id"] == "review"
    state = decision_result["apply_result"]["graph_loop_state"]
    assert state["node_states"]["draft"]["human_edge_decision"]["decision"] == "pass"
    assert state["edge_states"]["edge.draft.review"]["status"] == "ready"


def test_writing_chapter_action_replace_writes_project_file_and_advances_edge(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    registry = TaskFlowRegistry(backend_dir)
    graph = _handoff_graph("graph.test.writing_chapter_action_replace")
    _upsert_graph(registry, graph)
    publish_graph_harness_config_for_graph(base_dir=backend_dir, graph_id=graph.graph_id)
    runtime = _runtime_with_graph_harness(base_dir=backend_dir)
    instance = GraphTaskInstanceRepository(backend_dir).create(graph_id=graph.graph_id, title="写作替写项目")

    original_instance_runtime = instance_api.require_runtime
    original_orchestration_runtime = orchestration_api.require_runtime
    instance_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    orchestration_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        asyncio.run(
            instance_api.start_graph_task_instance_run(
                instance.graph_task_instance_id,
                instance_api.GraphTaskInstanceRunStartRequest(
                    run_mode="dispatch_only",
                    dispatch_ready=False,
                ),
            )
        )
        desk = asyncio.run(instance_api.get_writing_graph_instance_desk(instance.graph_task_instance_id, event_limit=40))
        replace_action = next(item for item in desk["chapter_actions"] if item["action"] == "replace_with_user_text")

        result = asyncio.run(
            instance_api.submit_writing_graph_chapter_action(
                instance.graph_task_instance_id,
                instance_api.WritingChapterActionRequest(
                    action="replace_with_user_text",
                    control_id=replace_action["control_id"],
                    instruction="采用用户改写稿进入审核。",
                    target_path="chapters/chapter-001.md",
                    content="用户改写后的第一章正文",
                ),
            )
        )
    finally:
        instance_api.require_runtime = original_instance_runtime  # type: ignore[assignment]
        orchestration_api.require_runtime = original_orchestration_runtime  # type: ignore[assignment]

    decision_result = result["decision_result"]
    assert result["summary"]["decision"] == "replace"
    assert decision_result["decision"]["decision"] == "replace"
    assert decision_result["decision"]["status"] == "applied"
    assert decision_result["decision"]["content_submission"]["path"] == "chapters/chapter-001.md"
    assert "content" not in decision_result["decision"]["content_submission"]
    assert decision_result["apply_result"]["accepted_result"]["executor_type"] == "human"
    assert decision_result["apply_result"]["accepted_result"]["node_id"] == "draft"
    assert decision_result["apply_result"]["node_work_orders"][0]["node_id"] == "review"

    file_payload = GraphTaskInstanceFileService(backend_dir).read_file(
        instance.graph_task_instance_id,
        "chapters/chapter-001.md",
    )
    assert file_payload["content"] == "用户改写后的第一章正文"

