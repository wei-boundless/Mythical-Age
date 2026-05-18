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
