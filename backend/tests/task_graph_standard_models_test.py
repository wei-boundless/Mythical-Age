from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system import TaskFlowRegistry, build_task_graph_standard_view
from tests.support.runtime_stubs import RuntimeBaseDirStub


_RuntimeStub = RuntimeBaseDirStub


def _seed_graph(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.design.initialization",
        title="设计初始化图模块",
        domain_id="domain.health",
        graph_kind="coordination",
        entry_node_id="child_input",
        output_node_id="child_review",
        nodes=(
            {"node_id": "child_input", "node_type": "input", "title": "模块输入", "phase_id": "phase.child.start", "sequence_index": 1},
            {"node_id": "child_draft", "node_type": "agent", "title": "模块起草", "agent_id": "agent:writer", "phase_id": "phase.child.work", "sequence_index": 2},
            {"node_id": "child_review", "node_type": "review_gate", "title": "模块审核", "agent_id": "agent:reviewer", "phase_id": "phase.child.review", "sequence_index": 3},
            {
                "node_id": "child.memory",
                "node_type": "memory_repository",
                "title": "模块记忆",
                "metadata": {"repository_id": "child.memory", "collections": ["design"]},
            },
        ),
        edges=(
            {"edge_id": "edge.child.input.draft", "source_node_id": "child_input", "target_node_id": "child_draft", "edge_type": "handoff"},
            {"edge_id": "edge.child.draft.review", "source_node_id": "child_draft", "target_node_id": "child_review", "edge_type": "handoff"},
            {"edge_id": "edge.child.memory.read", "source_node_id": "child.memory", "target_node_id": "child_draft", "edge_type": "memory_read"},
        ),
        publish_state="published",
        enabled=True,
    )
    registry.upsert_task_graph(
        graph_id="graph.test.standard_view",
        title="标准视图图",
        domain_id="domain.health",
        graph_kind="coordination",
        entry_node_id="input",
        output_node_id="commit",
        nodes=(
            {"node_id": "input", "node_type": "input", "title": "输入", "phase_id": "phase.start", "sequence_index": 0},
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "agent_id": "agent:writer",
                "phase_id": "phase.start",
                "sequence_index": 1,
                "input_contract_id": "contract.user_request.basic",
                "output_contract_id": "contract.agent_output.markdown",
            },
            {
                "node_id": "baseline.memory",
                "node_type": "memory_repository",
                "title": "基线记忆库",
                "phase_id": "phase.memory",
                "sequence_index": 2,
                "resource_lifecycle_policy": {
                    "task_run_scope_policy": "isolated_per_task_run",
                    "versioning": "append_version",
                },
                "metadata": {
                    "memory_repository": {
                        "repository_id": "baseline",
                        "collections": [
                            {
                                "collection_id": "world",
                                "schema_id": "memory.collection.baseline_canon",
                                "record_kinds": ["world_bible"],
                                "content_requirement": {
                                    "canonical_text_required": True,
                                    "artifact_ref_only_allowed": False,
                                },
                                "snapshot_budget": {"default_max_records": 12, "default_max_chars": 32000},
                            },
                            {
                                "collection_id": "outline",
                                "schema_id": "memory.collection.baseline_canon",
                                "record_kinds": ["outline"],
                                "content_requirement": {
                                    "canonical_text_required": True,
                                    "artifact_ref_only_allowed": False,
                                },
                            },
                        ],
                    },
                },
            },
            {
                "node_id": "thread.ledger.1",
                "node_type": "thread_ledger",
                "title": "线程账本",
                "phase_id": "phase.memory",
                "sequence_index": 3,
                "resource_lifecycle_policy": {
                    "task_run_scope_policy": "isolated_per_task_run",
                    "versioning": "append_version",
                },
                "metadata": {
                    "memory_repository": {
                        "repository_id": "thread.ledger.1",
                        "collections": [
                            {
                                "collection_id": "threads",
                                "schema_id": "memory.collection.mutable_delta",
                                "content_requirement": {
                                    "canonical_text_required": True,
                                    "artifact_ref_only_allowed": False,
                                },
                            },
                            {
                                "collection_id": "decisions",
                                "schema_id": "memory.collection.baseline_canon",
                                "content_requirement": {
                                    "canonical_text_required": True,
                                    "artifact_ref_only_allowed": False,
                                },
                            },
                        ],
                    },
                },
            },
            {
                "node_id": "commit",
                "node_type": "manual_gate",
                "title": "人工提交",
                "phase_id": "phase.memory",
                "sequence_index": 4,
                "human_gate_policy": {"required": True, "gate_type": "manual_approval"},
            },
        ),
        edges=(
            {"edge_id": "edge.input.draft", "source_node_id": "input", "target_node_id": "draft", "edge_type": "handoff"},
            {
                "edge_id": "edge.memory.read",
                "source_node_id": "baseline.memory",
                "target_node_id": "draft",
                "edge_type": "memory_read",
                "metadata": {
                    "repository": "baseline",
                    "collection": "world",
                    "selector": {"collection": "world", "record_kind": "world_bible"},
                },
            },
            {
                "edge_id": "edge.memory.commit",
                "source_node_id": "commit",
                "target_node_id": "baseline.memory",
                "edge_type": "memory_commit",
                "metadata": {
                    "repository": "baseline",
                    "collection": "world",
                    "candidate_ref_key": "world_candidate_ref",
                    "verdict_key": "decision",
                    "required_verdict": "approved",
                },
            },
        ),
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.design",
                    "block_type": "design_graph",
                    "title": "设计阶段图",
                    "phase_id": "phase.start",
                    "linked_graph_id": "graph.design.initialization",
                    "entry_node_id": "input",
                    "exit_node_id": "draft",
                    "contract_bindings": {"handoff": {"handoff_contract_id": "contract.design.handoff"}},
                    "visibility_policy": "committed_only",
                    "version_ref": "v1",
                }
            ],
            "temporal_edges": [
                {
                    "edge_id": "temporal.phase.start->phase.memory",
                    "source_node_id": "draft",
                    "target_node_id": "commit",
                    "temporal_type": "phase_dependency",
                    "phase_id": "phase.memory",
                    "blocking": True,
                }
            ]
        },
    )


def test_build_task_graph_standard_view_projects_nodes_edges_resources_and_timeline(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    graph = TaskFlowRegistry(tmp_path).get_task_graph("graph.test.standard_view")
    assert graph is not None

    view = build_task_graph_standard_view(graph=graph, graph_lookup=TaskFlowRegistry(tmp_path))
    payload = view.to_dict()

    assert payload["authority"] == "task_system.task_graph_standard_view"
    assert any(item["node_id"] == "draft" for item in payload["nodes"])
    assert any(item["edge_id"] == "edge.memory.read" for item in payload["edges"])
    assert any(item["node_id"] == "baseline.memory" for item in payload["resources"])
    assert any(item["resource_type"] == "thread_ledger" for item in payload["resources"])
    assert payload["timeline"]["timeline_blocks"][0]["block_id"] == "block.design"
    assert payload["timeline"]["entry_node_id"] == "input"
    assert payload["runtime_isolation"]["memory_repositories"][0]["repository_id"] == "baseline"
    assert any(item["repository_id"] == "thread.ledger.1" for item in payload["runtime_isolation"]["memory_repositories"])
    baseline_resource = next(item for item in payload["resources"] if item["node_id"] == "baseline.memory")
    world_spec = next(item for item in baseline_resource["collection_specs"] if item["collection_id"] == "world")
    assert world_spec["content_requirement"]["canonical_text_required"] is True
    protocol = payload["memory_protocol"]
    assert protocol["summary"]["repository_count"] == 2
    assert any(item["repository_id"] == "baseline" for item in protocol["repositories"])
    assert any(item["repository_id"] == "baseline" and item["collection_id"] == "world" for item in protocol["collections"])
    assert any(item["edge_id"] == "edge.memory.read" and item["collection_id"] == "world" for item in protocol["read_edges"])
    assert any(item["edge_id"] == "edge.memory.commit" and item["collection_id"] == "world" for item in protocol["commit_edges"])
    protocol_world = next(item for item in protocol["collections"] if item["repository_id"] == "baseline" and item["collection_id"] == "world")
    assert protocol_world["content_requirement"]["artifact_ref_only_allowed"] is False
    assert any(item["unit_id"] == "unit.node.draft" for item in payload["units"])
    assert any(item["unit_id"] == "unit.graph.block.design" and item["ref"]["graph_id"] == "graph.design.initialization" for item in payload["units"])
    assert any(item["interface_id"] == "interface.node.draft" for item in payload["interfaces"])
    assert any(item["edge_id"] == "edge.input.draft" and item["source_unit_id"] == "unit.node.input" for item in payload["port_edges"])
    assert payload["graph_module_expansions"] == []
    assert payload["diagnostics"]["composable_graph"]["diagnostics"]["mode"] == "read_only_shadow_model"
    assert payload["diagnostics"]["graph_module_expansion_count"] == 0
    loop_plan = payload["diagnostics"]["loop_plan"]
    assert loop_plan["available"] is True
    assert loop_plan["authority"] == "task_system.loop_plan_preview"
    assert loop_plan["start_node_ids"] == ["input"]
    assert "baseline.memory" not in loop_plan["executable_node_ids"]
    assert any(item["edge_id"] == "edge.input.draft" for item in loop_plan["dependency_edges"])
    assert any(item["edge_id"] == "edge.memory.read" for item in loop_plan["context_edges"])
    assert all(item["edge_id"] != "edge.memory.read" for item in loop_plan["dependency_edges"])
    assert loop_plan["initial_ready_node_ids"] == ["input"]


def test_task_graph_standard_view_surfaces_memory_protocol_preflight_issues(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.test.memory_protocol_issues",
        title="记忆协议问题图",
        graph_kind="coordination",
        entry_node_id="draft",
        output_node_id="gate",
        nodes=(
            {"node_id": "draft", "node_type": "agent", "title": "执行者"},
            {"node_id": "gate", "node_type": "review_gate", "title": "审核门"},
            {
                "node_id": "memory.repo",
                "node_type": "memory_repository",
                "title": "正式记忆库",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory",
                        "collections": [
                            {
                                "collection_id": "canon",
                                "schema_id": "memory.collection.baseline_canon",
                                "content_requirement": {
                                    "canonical_text_required": True,
                                    "artifact_ref_only_allowed": False,
                                },
                            }
                        ],
                    },
                },
            },
        ),
        edges=(
            {
                "edge_id": "edge.memory.read.missing_collection",
                "source_node_id": "memory.repo",
                "target_node_id": "draft",
                "edge_type": "memory_read",
                "metadata": {"repository": "memory"},
            },
            {
                "edge_id": "edge.memory.write.refs_only",
                "source_node_id": "draft",
                "target_node_id": "memory.repo",
                "edge_type": "memory_write",
                "metadata": {
                    "repository": "memory",
                    "collection": "canon",
                    "materialization_policy": {"canonical_text_mode": "refs_only"},
                },
            },
            {
                "edge_id": "edge.memory.commit.no_candidate",
                "source_node_id": "gate",
                "target_node_id": "memory.repo",
                "edge_type": "memory_commit",
                "metadata": {
                    "repository": "memory",
                    "collection": "canon",
                    "materialization_policy": {"canonical_text_mode": "refs_only"},
                },
            },
        ),
    )
    graph = registry.get_task_graph("graph.test.memory_protocol_issues")
    assert graph is not None

    payload = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()
    protocol_codes = {item["code"] for item in payload["memory_protocol"]["issues"]}
    top_level_codes = {item["code"] for item in payload["issues"]}

    assert "memory_protocol_collection_missing" in protocol_codes
    assert "memory_protocol_canonical_write_uses_refs_only_materialization" in protocol_codes
    assert "memory_protocol_commit_candidate_source_missing" in protocol_codes
    assert protocol_codes <= top_level_codes


def test_task_graph_standard_view_merges_composable_metadata_overlay(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None

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
        default_protocol_id=graph.default_protocol_id,
        working_memory_policy_profile_id=graph.working_memory_policy_profile_id,
        working_memory_policy=graph.working_memory_policy,
        runtime_policy=graph.runtime_policy,
        context_policy=graph.context_policy,
        publish_state=graph.publish_state,
        enabled=graph.enabled,
        metadata={
            **dict(graph.metadata or {}),
            "composable_graph": {
                "version": "v1",
                "interfaces": [
                    {
                        "interface_id": "interface.node.draft",
                        "unit_id": "unit.node.draft",
                        "display_name_zh": "起草节点显式接口",
                        "input_ports": [{"port_id": "input.reviewed", "title": "审核后输入", "direction": "input", "payload_contract_id": "contract.reviewed.input"}],
                        "output_ports": [{"port_id": "output.explicit", "title": "显式输出", "direction": "output", "payload_contract_id": "contract.explicit.output"}],
                    }
                ],
                "port_edges": [
                    {
                        "edge_id": "port_edge.explicit.design_to_draft",
                        "source_unit_id": "unit.graph.block.design",
                        "source_port_id": "output.default",
                        "target_unit_id": "unit.node.draft",
                        "target_port_id": "input.reviewed",
                        "payload_contract_id": "contract.design.handoff",
                        "temporal_semantics": {"trigger_timing": "after_source_commit"},
                    }
                ],
            },
        },
    )
    updated_graph = registry.get_task_graph("graph.test.standard_view")
    assert updated_graph is not None

    payload = build_task_graph_standard_view(graph=updated_graph, graph_lookup=registry).to_dict()

    draft_interface = next(item for item in payload["interfaces"] if item["interface_id"] == "interface.node.draft")
    assert draft_interface["display_name_zh"] == "起草节点显式接口"
    assert draft_interface["input_ports"][0]["port_id"] == "input.reviewed"
    assert any(item["edge_id"] == "port_edge.explicit.design_to_draft" for item in payload["port_edges"])
    assert payload["diagnostics"]["composable_graph"]["diagnostics"]["mode"] == "metadata_overlay_shadow_model"
    assert payload["diagnostics"]["composable_graph"]["diagnostics"]["overlay_port_edge_count"] == 1


def test_task_graph_standard_view_api_round_trips_title_and_node_runtime(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: _RuntimeStub(tmp_path)  # type: ignore[assignment]
    try:
        current = asyncio.run(tasks_api.get_task_system_task_graph_standard_view("graph.test.standard_view"))
        current["graph"]["title"] = "标准视图图-更新"
        current["nodes"][1]["runtime"] = {
            **dict(current["nodes"][1].get("runtime") or {}),
            "execution_mode": "parallel",
            "dispatch_group": "drafting",
        }
        updated = asyncio.run(
            tasks_api.upsert_task_system_task_graph_standard_view(
                "graph.test.standard_view",
                tasks_api.TaskGraphStandardViewUpsertRequest(**{
                    "graph": current["graph"],
                    "nodes": current["nodes"],
                    "edges": current["edges"],
                    "resources": current["resources"],
                    "timeline": current["timeline"],
                    "runtime_isolation": current["runtime_isolation"],
                }),
            )
        )
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    assert updated["graph"]["title"] == "标准视图图-更新"
    draft = next(item for item in updated["nodes"] if item["node_id"] == "draft")
    assert draft["runtime"]["execution_mode"] == "parallel"
    assert draft["runtime"]["dispatch_group"] == "drafting"


def test_standard_view_does_not_promote_linked_timeline_block_to_graph_module_expansion(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    graph = TaskFlowRegistry(tmp_path).get_task_graph("graph.test.standard_view")
    assert graph is not None

    view = build_task_graph_standard_view(graph=graph, graph_lookup=TaskFlowRegistry(tmp_path)).to_dict()

    assert view["graph_module_expansions"] == []
    assert view["diagnostics"]["graph_harness_config"]["composition_source_count"] == 0


def test_standard_view_surfaces_invalid_explicit_graph_module_node_without_old_runtime_plan(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.test.explicit_graph_module",
        title="显式图模块导入图",
        graph_kind="coordination",
        entry_node_id="graph_module.import",
        output_node_id="graph_module.import",
        nodes=(
            {
                "node_id": "graph_module.import",
                "node_type": "graph_module",
                "title": "显式图模块节点",
                "task_id": "task.test.graph_module_import",
                "agent_id": "agent:0",
                "agent_group_id": "group.should_not_survive",
                "work_posture": "graph_module_expansion_marker",
                "phase_id": "phase.import",
                "sequence_index": 10,
                "metadata": {"editor_node": True},
                "contract_bindings": {
                    "handoff": {"handoff_contract_id": "contract.agent_output.markdown"},
                    "runtime": {
                        "graph_module_expansion": {"linked_graph_id": "graph.test.imported", "version_ref": "published"},
                        "model_requirement": {"profile_ref": "should_not_survive", "preferred_output_tokens": 65536},
                    }
                },
            },
        ),
        publish_state="published",
        enabled=True,
    )
    graph = registry.get_task_graph("graph.test.explicit_graph_module")
    assert graph is not None

    view = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()
    graph_module_nodes = [node for node in view["nodes"] if node["node_id"] == "graph_module.import"]

    assert len(graph_module_nodes) == 1
    assert view["graph_module_expansion"][0]["linked_graph_id"] == "graph.test.imported"
    assert graph_module_nodes[0]["node_type"] == "graph_module"
    assert graph_module_nodes[0]["executor"]["agent_id"] == "agent:0"
    assert graph_module_nodes[0]["task_id"] == "task.test.graph_module_import"
    assert graph_module_nodes[0]["metadata"]["editor_node"] is True
    assert view["graph_module_expansions"][0]["linked_graph_id"] == "graph.test.imported"
    assert view["graph_module_expansions"][0]["metadata"]["expansion_status"] == "unavailable"
    assert any(issue["code"] == "graph_module_linked_graph_not_found" for issue in view["issues"])
    assert view["diagnostics"]["graph_harness_config"]["available"] is False


def test_graph_module_handoff_contract_binding_comes_from_explicit_node(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        domain_id=graph.domain_id,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=(
            *tuple(item.to_dict() for item in graph.nodes),
            {
                "node_id": "graph_module.design",
                "node_type": "graph_module",
                "title": "设计阶段图",
                "contract_bindings": {
                    "handoff": {"handoff_contract_id": "contract.binding.graph_module.handoff"},
                    "runtime": {
                        "graph_module_expansion": {
                            "linked_graph_id": "graph.design.initialization",
                            "version_ref": "v1",
                        }
                    },
                },
                "metadata": {
                    "graph_module": True,
                    "linked_graph_id": "graph.design.initialization",
                    "version_ref": "v1",
                    "graph_module_expansion_plan_id": "graph_module_expansion.design",
                },
            },
        ),
        edges=tuple(item.to_dict() for item in graph.edges),
        graph_contract_id=graph.graph_contract_id,
        contract_bindings=graph.contract_bindings,
        default_protocol_id=graph.default_protocol_id,
        working_memory_policy_profile_id=graph.working_memory_policy_profile_id,
        working_memory_policy=graph.working_memory_policy,
        runtime_policy=graph.runtime_policy,
        context_policy=graph.context_policy,
        publish_state=graph.publish_state,
        enabled=graph.enabled,
        metadata=dict(graph.metadata or {}),
    )

    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None
    view = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()
    graph_interface = next(item for item in view["interfaces"] if item["unit_id"] == "unit.node.graph_module.design")

    assert graph_interface["input_ports"][0]["payload_contract_id"] == "contract.binding.graph_module.handoff"
    assert view["graph_module_expansion"][0]["handoff_contract_id"] == "contract.binding.graph_module.handoff"
    assert view["graph_module_expansions"][0]["linked_graph_id"] == "graph.design.initialization"
    assert view["graph_module_expansions"][0]["metadata"]["expansion_status"] == "expanded"
    assert view["graph_module_expansions"][0]["nodes"]
    assert view["diagnostics"]["graph_harness_config"]["config_id"]


def test_standard_view_round_trips_contract_bindings(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None

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
        contract_bindings={"schema": {"graph_contract_id": "contract.graph"}, "unit_batch": {"unit_label": "项"}},
        default_protocol_id=graph.default_protocol_id,
        working_memory_policy_profile_id=graph.working_memory_policy_profile_id,
        working_memory_policy=graph.working_memory_policy,
        runtime_policy=graph.runtime_policy,
        context_policy=graph.context_policy,
        publish_state=graph.publish_state,
        enabled=graph.enabled,
        metadata=graph.metadata,
    )
    updated = registry.get_task_graph("graph.test.standard_view")
    assert updated is not None
    payload = build_task_graph_standard_view(graph=updated, graph_lookup=registry).to_dict()

    assert payload["graph"]["contract_bindings"]["unit_batch"]["unit_label"] == "项"


def test_graph_module_expansion_blocks_self_reference_and_surfaces_issue(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.test.self_import",
        title="自引用图模块",
        graph_kind="coordination",
        entry_node_id="input",
        output_node_id="input",
        nodes=(
            {"node_id": "input", "node_type": "input", "title": "输入"},
            {
                "node_id": "graph_module.block.self",
                "node_type": "graph_module",
                "title": "自引用模块",
                "contract_bindings": {
                    "handoff": {"handoff_contract_id": "contract.self.handoff"},
                    "runtime": {
                        "graph_module_expansion": {
                            "linked_graph_id": "graph.test.self_import",
                            "version_ref": "v1",
                        }
                    },
                },
                "metadata": {
                    "graph_module": True,
                    "linked_graph_id": "graph.test.self_import",
                    "version_ref": "v1",
                    "graph_module_expansion_plan_id": "graph_module_expansion.block.self",
                },
            },
        ),
        publish_state="published",
        enabled=True,
    )
    graph = registry.get_task_graph("graph.test.self_import")
    assert graph is not None

    payload = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()

    assert payload["graph_module_expansion"][0]["linked_graph_id"] == "graph.test.self_import"
    assert payload["graph_module_expansions"][0]["metadata"]["expansion_status"] == "unavailable"
    assert any(issue["code"] == "graph_module_self_reference" for issue in payload["issues"])


