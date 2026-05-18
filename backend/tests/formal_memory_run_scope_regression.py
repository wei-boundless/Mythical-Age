from __future__ import annotations

from memory_system.formal_memory_service import FormalMemoryService


def _edge() -> dict:
    return {
        "edge_id": "edge.memory_write.world",
        "repository": "memory.project.world",
        "collection": "world",
        "selector": {"collection": "world", "record_key": "world.current"},
        "record_key": "world.current",
    }


def test_formal_memory_defaults_to_task_run_isolation(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    service.sync_graph_spec(
        graph_id="graph.test",
        task_run_id="taskrun:one",
        graph_spec={
            "nodes": [
                {
                    "node_id": "memory.project.world",
                    "node_type": "memory_repository",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.project.world",
                            "collections": ["world"],
                        }
                    },
                }
            ]
        },
    )
    candidate, _write_txn = service.write_candidate_from_edge(
        edge=_edge(),
        candidate={"canonical_text": "旧运行世界观", "record_key": "world.current"},
        task_run_id="taskrun:one",
        node_run_id="taskrun:one:writer",
        source_node_id="writer",
        source_clock_seq=1,
    )
    service.commit_from_edge(
        edge=_edge(),
        candidate_version_id=candidate.version_id,
        node_run_id="taskrun:one:commit",
        source_clock_seq=2,
    )

    selected_one = service.select_for_node(
        read_edges=[_edge()],
        task_run_id="taskrun:one",
        node_run_id="taskrun:one:reader",
        clock_seq=3,
    )
    assert selected_one["required_records"][0]["canonical_text"] == "旧运行世界观"

    selected_two = service.select_for_node(
        read_edges=[_edge()],
        task_run_id="taskrun:two",
        node_run_id="taskrun:two:reader",
        clock_seq=3,
    )
    assert selected_two["required_records"] == []


def test_formal_memory_durable_scope_can_be_shared_across_runs(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    durable_edge = {**_edge(), "lifecycle_policy": {"scope_kind": "durable"}}
    candidate, _write_txn = service.write_candidate_from_edge(
        edge=durable_edge,
        candidate={"canonical_text": "共享世界观", "record_key": "world.current"},
        task_run_id="taskrun:one",
        node_run_id="taskrun:one:writer",
        source_node_id="writer",
        source_clock_seq=1,
    )
    service.commit_from_edge(
        edge=durable_edge,
        candidate_version_id=candidate.version_id,
        node_run_id="taskrun:one:commit",
        source_clock_seq=2,
    )

    selected = service.select_for_node(
        read_edges=[durable_edge],
        task_run_id="taskrun:two",
        node_run_id="taskrun:two:reader",
        clock_seq=3,
    )
    assert selected["required_records"][0]["canonical_text"] == "共享世界观"
