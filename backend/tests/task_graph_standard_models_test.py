from __future__ import annotations

import asyncio
from pathlib import Path

from api import tasks as tasks_api
from tasks import TaskFlowRegistry, build_task_graph_standard_view


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)


def _seed_graph(tmp_path: Path) -> None:
    TaskFlowRegistry(tmp_path).upsert_task_graph(
        graph_id="graph.test.standard_view",
        title="标准视图图",
        domain_id="domain.health",
        task_family="health",
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
                    "repository_id": "baseline",
                    "collections": ["world", "outline"],
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
                    "repository_id": "thread.ledger.1",
                    "collections": ["threads", "decisions"],
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
                    "handoff_contract_id": "contract.design.handoff",
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

    view = build_task_graph_standard_view(graph=graph)
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
    assert any(item["unit_id"] == "unit.node.draft" for item in payload["units"])
    assert any(item["unit_id"] == "unit.graph.block.design" and item["ref"]["graph_id"] == "graph.design.initialization" for item in payload["units"])
    assert any(item["interface_id"] == "interface.node.draft" for item in payload["interfaces"])
    assert any(item["edge_id"] == "edge.input.draft" and item["source_unit_id"] == "unit.node.input" for item in payload["port_edges"])
    assert payload["nested_runtime"][0]["linked_graph_id"] == "graph.design.initialization"
    assert payload["diagnostics"]["composable_graph"]["diagnostics"]["mode"] == "read_only_shadow_model"


def test_task_graph_standard_view_merges_composable_metadata_overlay(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None

    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        domain_id=graph.domain_id,
        task_family=graph.task_family,
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

    payload = build_task_graph_standard_view(graph=updated_graph).to_dict()

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


def test_runtime_spec_promotes_linked_timeline_block_to_graph_unit(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    graph = TaskFlowRegistry(tmp_path).get_task_graph("graph.test.standard_view")
    assert graph is not None

    spec = build_task_graph_standard_view(graph=graph).diagnostics["runtime_spec"]
    graph_units = spec["nested_runtime_plans"]
    graph_unit_nodes = [node for node in spec["nodes"] if node["node_type"] == "graph_unit"]

    assert graph_units[0]["linked_graph_id"] == "graph.design.initialization"
    assert graph_units[0]["runtime_node_id"] == "graph_unit.block.design"
    assert graph_unit_nodes[0]["metadata"]["nested_runtime_plan_id"] == "nested.block.design"
    assert graph_unit_nodes[0]["metadata"]["execution_mode"] == "nested_graph_run"


def test_graph_unit_handoff_contract_binding_overrides_legacy_timeline_field(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None
    metadata = dict(graph.metadata or {})
    timeline_blocks = [dict(item) for item in list(metadata.get("timeline_blocks") or [])]
    timeline_blocks[0]["handoff_contract_id"] = "contract.legacy.graph_unit.handoff"
    timeline_blocks[0]["contract_bindings"] = {
        "handoff": {"handoff_contract_id": "contract.binding.graph_unit.handoff"}
    }
    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        domain_id=graph.domain_id,
        task_family=graph.task_family,
        graph_kind=graph.graph_kind,
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        nodes=tuple(item.to_dict() for item in graph.nodes),
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
        metadata={**metadata, "timeline_blocks": timeline_blocks},
    )

    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None
    view = build_task_graph_standard_view(graph=graph).to_dict()
    graph_interface = next(item for item in view["interfaces"] if item["unit_id"] == "unit.graph.block.design")
    runtime_spec = view["diagnostics"]["runtime_spec"]

    assert view["timeline"]["timeline_blocks"][0]["handoff_contract_id"] == "contract.binding.graph_unit.handoff"
    assert graph_interface["input_ports"][0]["payload_contract_id"] == "contract.binding.graph_unit.handoff"
    assert runtime_spec["nested_runtime_plans"][0]["handoff_contract_id"] == "contract.binding.graph_unit.handoff"
    assert runtime_spec["nodes"][-1]["metadata"]["handoff_contract_id"] == "contract.binding.graph_unit.handoff"


def test_standard_view_round_trips_contract_bindings(tmp_path: Path) -> None:
    _seed_graph(tmp_path)
    registry = TaskFlowRegistry(tmp_path)
    graph = registry.get_task_graph("graph.test.standard_view")
    assert graph is not None

    registry.upsert_task_graph(
        graph_id=graph.graph_id,
        title=graph.title,
        domain_id=graph.domain_id,
        task_family=graph.task_family,
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
    payload = build_task_graph_standard_view(graph=updated).to_dict()

    assert payload["graph"]["contract_bindings"]["unit_batch"]["unit_label"] == "项"
