from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.context_materializer import GraphContextMaterializer
from harness.graph.models import GraphLoopState, NodeResultEnvelope, graph_harness_config_from_dict
from harness.graph.scheduler_view import build_scheduler_view
from harness.runtime.compiler import _graph_authorized_inputs
from task_system import TaskFlowRegistry, apply_task_graph_standard_view_update, build_task_graph_standard_view
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph
from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    TaskGraphEdgeDefinition,
    TaskGraphNodeDefinition,
)
from tests.support.writing_fixtures import load_writing_modular_config_module


def _writing_like_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.writing_language_preservation",
        title="Writing Language Preservation",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="memory.commit",
        publish_state="published",
        enabled=True,
        runtime_policy={"coordinator_agent_id": "agent:0"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="memory.world",
                node_type="memory_repository",
                title="世界观记忆库",
                metadata={
                    "memory_repository": {
                        "repository_id": "repo.world",
                        "collections": [{"collection_id": "world_setting"}],
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="issue.ledger",
                node_type="issue_ledger",
                title="问题账本",
            ),
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent_role",
                title="起草",
                agent_id="agent:0",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名长篇小说设定起草员。",
                        "task_instruction": "请根据输入材料起草可审核的世界观设定。",
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="review_gate",
                title="审核",
                agent_id="agent:0",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "下游专属审核角色文本不得进入起草节点。",
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="memory.commit",
                node_type="memory_commit",
                title="记忆提交",
                agent_id="agent:0",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.memory.read",
                source_node_id="memory.world",
                target_node_id="draft",
                edge_type="memory_read",
                metadata={"repository": "repo.world", "collection": "world_setting", "on_missing": "warn"},
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="structured_handoff",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.review.revise",
                source_node_id="review",
                target_node_id="draft",
                edge_type="revision_request",
                metadata={"trigger": {"verdict": "revise"}, "carry": ["review_notes"]},
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.memory_commit",
                source_node_id="draft",
                target_node_id="memory.commit",
                edge_type="memory_commit",
                metadata={
                    "repository": "repo.world",
                    "collection": "world_setting",
                    "source_output_key": "world_setting",
                },
            ),
        ),
    )


def _graph_harness_config():
    graph = _writing_like_graph()
    return build_graph_harness_config_from_graph(
        graph=graph,
        contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
    )


def _seed_writing_modular_graphs(tmp_path: Path):
    module = load_writing_modular_config_module()
    registry = TaskFlowRegistry(tmp_path)
    module._upsert_imported_module_graph(
        registry,
        graph_id=module.DESIGN_GRAPH_ID,
        nodes=module.DESIGN_NODES,
        business_edges=module.DESIGN_BUSINESS_EDGES,
    )
    module._upsert_imported_module_graph(
        registry,
        graph_id=module.CHAPTER_GRAPH_ID,
        nodes=module.CHAPTER_NODES,
        business_edges=module.CHAPTER_BUSINESS_EDGES,
    )
    module._upsert_imported_module_graph(
        registry,
        graph_id=module.FINALIZE_GRAPH_ID,
        nodes=module.FINALIZE_NODES,
        business_edges=module.FINALIZE_BUSINESS_EDGES,
    )
    module._upsert_master_graph(registry)
    return module, registry


def test_graph_harness_config_preserves_full_graph_language() -> None:
    graph_config = _graph_harness_config()

    node_types = {str(node.get("node_id")): str(node.get("node_type")) for node in graph_config.nodes}
    edge_types = {str(edge.get("edge_id")): str(edge.get("edge_type")) for edge in graph_config.edges}

    assert len(graph_config.nodes) == 5
    assert len(graph_config.edges) == 4
    assert node_types["memory.world"] == "memory_repository"
    assert node_types["issue.ledger"] == "issue_ledger"
    assert node_types["memory.commit"] == "memory_commit"
    assert edge_types["edge.memory.read"] == "memory_read"
    assert edge_types["edge.draft.memory_commit"] == "memory_commit"
    assert edge_types["edge.review.revise"] == "revision_request"


def test_standard_view_exposes_and_round_trips_node_prompt_contract() -> None:
    graph = _writing_like_graph()
    payload = build_task_graph_standard_view(graph=graph).to_dict()
    draft = next(item for item in payload["nodes"] if item["node_id"] == "draft")

    assert draft["prompt"]["role_prompt"] == "你是一名长篇小说设定起草员。"
    assert draft["prompt"]["task_instruction"] == "请根据输入材料起草可审核的世界观设定。"
    assert draft["prompt"]["authority"] == "task_system.task_graph_standard_node_prompt"

    draft["prompt"] = {
        **draft["prompt"],
        "role_prompt": "你是一名迁移后的长篇小说设定起草员。",
        "task_instruction": "只根据已授权输入起草世界观候选。",
    }
    updated = apply_task_graph_standard_view_update(graph=graph, payload=payload)
    updated_draft = next(item for item in updated.nodes if item.node_id == "draft")
    prompt_contract = dict(updated_draft.metadata.get("prompt_contract") or {})

    assert prompt_contract["role_prompt"] == "你是一名迁移后的长篇小说设定起草员。"
    assert prompt_contract["task_instruction"] == "只根据已授权输入起草世界观候选。"
    assert updated_draft.metadata["role_prompt"] == "你是一名迁移后的长篇小说设定起草员。"


def test_writing_modular_node_prompts_are_migrated_to_standard_graph_prompt_contracts(tmp_path: Path) -> None:
    module, registry = _seed_writing_modular_graphs(tmp_path)
    graph = registry.get_task_graph(module.DESIGN_GRAPH_ID)
    assert graph is not None

    source_payload = module._node_payload(next(node for node in module.DESIGN_NODES if node.node_id == "project_brief"))
    source_prompt = dict(source_payload["metadata"]["prompt_contract"])
    view = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()
    project_brief = next(item for item in view["nodes"] if item["node_id"] == "project_brief")

    assert source_prompt["authority"] == "task_system.writing_graph.node_prompt_contract"
    assert source_prompt["source"] == "writing_modular_novel.NodeSpec.prompt"
    assert "你是一名中文商业网文项目启动整理员" in source_prompt["role_prompt"]
    assert project_brief["prompt"]["role_prompt"] == source_prompt["role_prompt"]
    assert project_brief["prompt"]["authority"] == "task_system.writing_graph.node_prompt_contract"
    assert "系统会根据任务图边、记忆协议和产物合同" not in project_brief["prompt"]["role_prompt"]
    assert "artifact_payloads" not in project_brief["prompt"]["role_prompt"]


def test_writing_chapter_standard_view_preserves_old_loop_and_edge_topology(tmp_path: Path) -> None:
    module, registry = _seed_writing_modular_graphs(tmp_path)
    graph = registry.get_task_graph(module.CHAPTER_GRAPH_ID)
    assert graph is not None

    payload = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()
    loop_frames = {item["frame_id"]: item for item in payload["timeline"]["loop_frames"]}
    edges = {item["edge_id"]: item for item in payload["edges"]}

    assert set(loop_frames) == {"loop.chapter_unit", "loop.chapter_batch", "loop.volume"}
    assert loop_frames["loop.chapter_unit"]["entry_node_id"] == "chapter_draft"
    assert loop_frames["loop.chapter_unit"]["router_node_id"] == "chapter_unit_router"
    assert loop_frames["loop.chapter_unit"]["continue_node_id"] == "chapter_draft"
    assert loop_frames["loop.chapter_unit"]["exit_node_id"] == "chapter_batch_assemble"
    assert loop_frames["loop.chapter_batch"]["continue_node_id"] == "chapter_outline"
    assert loop_frames["loop.volume"]["exit_node_id"] == "__graph_module_complete__"
    assert loop_frames["loop.chapter_unit"]["initial_inputs"]["target_unit_count"] == module.CHAPTER_REQUESTED_COUNT
    assert any(item.get("key") == "batch_end_index" for item in loop_frames["loop.chapter_unit"]["derived_fields"])

    assert edges["edge.outline.draft"]["edge_type"] == "structured_handoff"
    assert edges["edge.outline.draft"]["semantic"] == {}
    assert edges["edge.revision.chapter_review.chapter_draft"]["revision"]["trigger"]["verdict"] == "revise"
    assert edges["edge.revision.volume_review.chapter_outline"]["revision"]["target_node_id"] == "chapter_outline"
    memory_read = edges["edge.memory_read.memory.writing.baseline.world_bible.chapter_draft"]
    assert memory_read["memory"]["repository"] == "memory.writing.baseline"
    assert memory_read["memory"]["collection"] == "world_bible"
    assert memory_read["memory"]["on_missing"] == "block"


def test_writing_master_standard_view_exposes_module_topology_and_imported_prompts(tmp_path: Path) -> None:
    module, registry = _seed_writing_modular_graphs(tmp_path)
    graph = registry.get_task_graph(module.MASTER_GRAPH_ID)
    assert graph is not None

    payload = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()
    module_nodes = {item["node_id"]: item for item in payload["nodes"] if item["node_type"] == "graph_module"}
    expansion_by_graph_id = {
        item["linked_graph_id"]: item
        for item in payload["graph_module_expansions"]
    }

    assert set(module_nodes) == {
        "graph_module.design_init",
        "graph_module.chapter_cycle",
        "graph_module.finalize",
    }
    assert module_nodes["graph_module.chapter_cycle"]["contracts"]["contract_bindings"]["runtime"]["graph_module_expansion"]["linked_graph_id"] == module.CHAPTER_GRAPH_ID
    assert set(expansion_by_graph_id) == {
        module.DESIGN_GRAPH_ID,
        module.CHAPTER_GRAPH_ID,
        module.FINALIZE_GRAPH_ID,
    }
    chapter_expansion = expansion_by_graph_id[module.CHAPTER_GRAPH_ID]
    imported_draft = next(item for item in chapter_expansion["nodes"] if item["node_id"] == "chapter_draft")
    assert chapter_expansion["metadata"]["expansion_status"] == "expanded"
    assert imported_draft["scoped_node_id"] == "graph_module.chapter_cycle::chapter_draft"
    assert imported_draft["loop"]["scope_id"] == "loop.chapter_unit"
    assert "你是一名名家级中文商业网文单章写手" in imported_draft["prompt"]["role_prompt"]


def test_graph_module_expansion_scopes_imported_loop_contracts() -> None:
    child = TaskGraphDefinition(
        graph_id="graph.test.child_loop",
        title="Child Loop",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        loop_frames=(
            {
                "frame_id": "loop.units",
                "scope_id": "loop.units",
                "kind": "bounded_metric_iteration",
                "entry_node_id": "draft",
                "router_node_id": "router",
                "continue_node_id": "draft",
                "exit_node_id": "review",
                "scope_node_ids": ["draft", "router"],
                "initial_inputs": {"target_unit_count": 2, "unit_index": 1},
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="起草",
                agent_id="agent:0",
                loop={"scope_id": "loop.units", "kind": "bounded_metric_iteration"},
            ),
            TaskGraphNodeDefinition(
                node_id="router",
                node_type="agent",
                title="路由",
                agent_id="agent:0",
                loop={
                    "scope_id": "loop.units",
                    "kind": "bounded_metric_iteration",
                    "route_policy": {
                        "scope_id": "loop.units",
                        "continue_node_id": "draft",
                        "exit_node_id": "review",
                        "current_key": "unit_index",
                        "target_key": "target_unit_count",
                    },
                },
            ),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="审核", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.draft.router", source_node_id="draft", target_node_id="router", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.router.review", source_node_id="router", target_node_id="review", edge_type="handoff"),
        ),
    )
    parent = TaskGraphDefinition(
        graph_id="graph.test.parent_loop_composition",
        title="Parent Loop Composition",
        graph_kind="multi_agent",
        entry_node_id="graph_module.child",
        output_node_id="graph_module.child",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="graph_module.child",
                node_type="graph_module",
                title="导入子图",
                metadata={"linked_graph_id": child.graph_id},
            ),
        ),
    )

    graph_config = build_graph_harness_config_from_graph(
        graph=parent,
        graph_lookup={child.graph_id: child},
        contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
    )

    frame = graph_config.loop_frames[0]
    router = next(node for node in graph_config.nodes if node["node_id"] == "graph_module.child::router")
    route_policy = dict(dict(router["loop"]).get("route_policy") or {})

    assert frame["frame_id"] == "graph_module.child::loop.units"
    assert frame["scope_id"] == "graph_module.child::loop.units"
    assert frame["entry_node_id"] == "graph_module.child::draft"
    assert frame["router_node_id"] == "graph_module.child::router"
    assert frame["continue_node_id"] == "graph_module.child::draft"
    assert frame["exit_node_id"] == "graph_module.child::review"
    assert frame["scope_node_ids"] == ["graph_module.child::draft", "graph_module.child::router"]
    assert router["loop"]["scope_id"] == "graph_module.child::loop.units"
    assert route_policy["scope_id"] == "graph_module.child::loop.units"
    assert route_policy["continue_node_id"] == "graph_module.child::draft"
    assert route_policy["exit_node_id"] == "graph_module.child::review"


def test_loop_exit_node_receives_preserved_iteration_artifact_payloads(tmp_path: Path) -> None:
    chapter_paths = []
    for index in range(1, 11):
        path = tmp_path / f"chapter_{index:03d}.md"
        path.write_text(f"第{index}章正文\n" + ("本章内容。" * 20), encoding="utf-8")
        chapter_paths.append(path)
    graph_config = graph_harness_config_from_dict(
        {
            "config_id": "ghcfg:test_loop_iteration_payloads",
            "graph_id": "graph.test.loop_iteration_payloads",
            "graph_title": "Loop Iteration Payloads",
            "publish_version": "test",
            "content_hash": "hash",
            "nodes": [
                {"node_id": "draft", "node_type": "agent_role", "title": "起草"},
                {"node_id": "router", "node_type": "agent_role", "title": "路由"},
                {"node_id": "assemble", "node_type": "agent_role", "title": "汇总"},
            ],
            "loop_frames": [
                {
                    "frame_id": "loop.chapter_unit",
                    "scope_id": "loop.chapter_unit",
                    "entry_node_id": "draft",
                    "router_node_id": "router",
                    "continue_node_id": "draft",
                    "exit_node_id": "assemble",
                    "scope_node_ids": ["draft", "router"],
                }
            ],
        }
    )
    state = GraphLoopState(
        state_id="gstate:test_loop_iteration_payloads",
        graph_run_id="grun:test_loop_iteration_payloads",
        task_run_id="taskrun:test_loop_iteration_payloads",
        session_id="session:test",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        graph_id=graph_config.graph_id,
        loop_state={
            "frames": {
                "loop.chapter_unit": {
                    "frame_id": "loop.chapter_unit",
                    "scope_id": "loop.chapter_unit",
                    "exit_node_id": "assemble",
                    "status": "exited",
                }
            },
            "iteration_results": {
                "loop.chapter_unit": {
                    f"chapter_{index:03d}": {
                        "draft": {
                            "node_id": "draft",
                            "status": "completed",
                            "artifact_refs": [str(path)],
                            "handoff_summary": f"第{index}章已完成",
                        }
                    }
                    for index, path in enumerate(chapter_paths, start=1)
                }
            },
        },
    )

    contexts = GraphContextMaterializer().inbound_context_for_node(
        graph_config=graph_config,
        state=state,
        node_id="assemble",
    )
    loop_context = next(item for item in contexts if item["packet_type"] == "loop_iteration_results")
    payload = dict(loop_context["payload"])

    assert len(payload["loop_iteration_results"]) == 10
    assert len(payload["artifact_payloads"]) == 10
    assert "第10章正文" in payload["artifact_payloads"][-1]["content"]

    authorized = _graph_authorized_inputs(contexts)
    loop_authorized = next(item for item in authorized if item["packet_type"] == "loop_iteration_results")
    assert len(loop_authorized["payload"]["artifact_payloads"]) == 10
    assert "第10章正文" in str(loop_authorized)


def test_scheduler_view_uses_only_dependency_edges() -> None:
    graph_config = _graph_harness_config()
    scheduler = build_scheduler_view(graph_config)

    dependency_edge_ids = {str(edge.get("edge_id")) for edge in scheduler.dependency_edges}

    assert scheduler.executable_node_ids == ("draft", "review", "memory.commit")
    assert dependency_edge_ids == {"edge.draft.review", "edge.draft.memory_commit"}
    assert scheduler.start_node_ids == ("draft",)
    assert set(scheduler.terminal_node_ids) == {"review", "memory.commit"}


def test_current_node_input_package_does_not_expose_downstream_prompt_or_unrelated_resources() -> None:
    graph_config = _graph_harness_config()
    state = GraphLoopState(
        state_id="gstate:test:scope",
        graph_run_id="grun:test:scope",
        task_run_id="taskrun:test:scope",
        session_id="session:test",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        graph_id=graph_config.graph_id,
        status="running",
        node_states={"draft": {"node_id": "draft", "status": "ready"}},
    )
    draft = next(node for node in graph_config.nodes if node["node_id"] == "draft")

    materializer = GraphContextMaterializer(services=None)
    inbound_context = materializer.inbound_context_for_node(graph_config=graph_config, state=state, node_id="draft")
    input_package = materializer.build_input_package(
        graph_config=graph_config,
        state=state,
        node=draft,
        inbound_context=inbound_context,
    )
    package_text = str(input_package)
    resource_nodes = input_package["file_view"]["graph_resource_policy"]["resource_nodes"]

    assert "下游专属审核角色文本不得进入起草节点" not in package_text
    assert "memory.commit" not in package_text
    assert all(
        item["target_node_id"] == "draft"
        for item in input_package["memory_view"]["graph_memory_policy"]["read_rules"]
    )
    assert "readable_by" not in package_text
    assert "write_owner_node_ids" not in package_text
    assert all(item["node_id"] != "memory.commit" for item in resource_nodes)
    assert all(item["current_node_can_read"] for item in resource_nodes)

    try:
        materializer.build_work_order(graph_config=graph_config, state=state, node=draft)
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "formal_memory_service" in str(raised)


def test_graph_harness_config_rejects_unknown_scheduler_role() -> None:
    graph_config = _graph_harness_config()
    payload = graph_config.to_dict()
    payload["edges"][0]["scheduler_role"] = "unsupported_scheduler_role"

    try:
        graph_harness_config_from_dict(payload)
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "scheduler_role" in str(raised)


def test_graph_harness_config_rejects_unknown_edge_type_without_explicit_extension_role() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.unknown_edge_type",
        title="Unknown Edge Type",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(node_id="draft", node_type="agent", title="起草", agent_id="agent:0"),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="审核", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="custom_payload",
            ),
        ),
    )

    try:
        build_graph_harness_config_from_graph(
            graph=graph,
            contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
        )
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "unknown graph edge_type" in str(raised)


def test_explicit_extension_edge_is_preserved_but_not_scheduled() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.extension_edge",
        title="Extension Edge",
        graph_kind="multi_agent",
        entry_node_id="",
        output_node_id="",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(node_id="draft", node_type="agent", title="起草", agent_id="agent:0"),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="审核", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review.note",
                source_node_id="draft",
                target_node_id="review",
                edge_type="custom_payload",
                metadata={"harness_semantic_role": "extension", "scheduler_role": "none"},
            ),
        ),
    )

    graph_config = build_graph_harness_config_from_graph(
        graph=graph,
        contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
    )
    edge = graph_config.edges[0]
    scheduler = build_scheduler_view(graph_config)

    assert edge["semantic_role"] == "extension"
    assert edge["scheduler_role"] == "none"
    assert scheduler.dependency_edges == ()
    assert scheduler.start_node_ids == ("draft", "review")


def test_graph_loop_completion_counts_executable_nodes_not_resource_nodes(tmp_path: Path) -> None:
    from harness import AgentRuntimeServices, GraphHarness
    from harness.runtime import SingleAgentRuntimeHost

    graph_config = _graph_harness_config()
    host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=BACKEND_DIR)
    services = AgentRuntimeServices.from_runtime_host(host)
    graph_harness = GraphHarness(services=services)
    start = graph_harness.start_run(
        session_id="session:test",
        task_id="",
        graph_config=graph_config,
        dispatch_ready=True,
    )

    state = start.loop_state
    pending_orders = list(start.node_work_orders)
    for node_id in ("draft", "review", "memory.commit"):
        order = next(item for item in pending_orders if item.node_id == node_id)
        advance = graph_harness.accept_node_result(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            result=NodeResultEnvelope(
                result_id=f"nresult:test:{node_id}",
                graph_run_id=start.graph_run.graph_run_id,
                task_run_id=start.task_run.task_run_id,
                node_id=node_id,
                work_order_id=order.work_order_id,
                outputs={"ok": node_id},
            ),
        )
        state = advance.loop_state
        pending_orders = list(advance.node_work_orders)

    assert state.status == "completed"
    assert set(state.completed_node_ids) == {"draft", "review", "memory.commit"}
    assert "memory.world" not in state.completed_node_ids
    assert "issue.ledger" not in state.completed_node_ids
