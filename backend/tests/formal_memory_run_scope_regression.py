from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from capability_system.tools.native_tool_runtime import ToolRuntime
from memory_system.formal_memory_service import FormalMemoryService
from orchestration.runtime_directive import RuntimeDirective
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import OperationExecutionRecord
from runtime.tool_runtime.tool_executor import ToolRuntimeExecutor

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _edge() -> dict:
    return {
        "edge_id": "edge.memory_write.world",
        "repository": "memory.project.world",
        "collection": "world",
        "selector": {"collection": "world", "record_key": "world.current"},
        "record_key": "world.current",
    }


def test_formal_memory_run_scope_requires_explicit_task_run_or_scope_id(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)

    try:
        service.resolve_repository_scope(logical_repository_id="memory.project.world")
    except ValueError as exc:
        assert "run_scoped formal memory requires task_run_id" in str(exc)
    else:
        raise AssertionError("run-scoped formal memory silently created an unbound_run scope")


def test_formal_memory_project_scope_requires_explicit_project_id(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)

    try:
        service.resolve_repository_scope(
            logical_repository_id="memory.project.world",
            lifecycle_policy={"scope_kind": "project_scoped"},
        )
    except ValueError as exc:
        assert "project_scoped formal memory requires project_id" in str(exc)
    else:
        raise AssertionError("project-scoped formal memory silently created a default_project scope")


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


def test_writing_graph_memory_repository_nodes_and_edges_share_graph_task_namespace(tmp_path) -> None:
    from scripts.configure_writing_modular_novel_graph import REPOSITORY_NODES, _memory_edge, _repository_node_payload

    artifact_index_spec = next(item for item in REPOSITORY_NODES if item["node_id"] == "memory.writing.artifact_index")
    repository_node = _repository_node_payload(artifact_index_spec)
    repository_policy = repository_node["metadata"]["memory_repository"]["lifecycle_policy"]
    edge = _memory_edge(
        "edge.artifact_index.project_brief",
        "project_brief",
        "memory.writing.artifact_index",
        "commit",
        "commit_refs",
        ("artifact_ref",),
        "产物索引",
    )
    edge_policy = edge["metadata"]["lifecycle_policy"]

    assert repository_policy == edge_policy
    assert repository_policy["scope_kind"] == "run_scoped"
    assert repository_policy["namespace_policy"] == "graph_task_instance"
    assert repository_policy["scope_id_source"] == "graph_task_memory_namespace"

    service = FormalMemoryService(tmp_path)
    runtime_scope = {"graph_task_memory_namespace": {"namespace_id": "graphmem:writing:test"}}
    service.sync_graph_spec_for_scope(
        graph_id="graph.writing.modular_novel.design_init",
        task_run_id="taskrun:writing:test",
        runtime_scope=runtime_scope,
        graph_spec={"resource_nodes": [repository_node]},
    )
    candidate, _write_txn = service.write_candidate_from_edge(
        edge={
            "repository": "memory.writing.artifact_index",
            "collection": "commit_refs",
            "record_key": "project_brief.artifact",
            "record_kind": "artifact_ref",
            "lifecycle_policy": edge_policy,
        },
        candidate={
            "canonical_text": "",
            "summary": "project_brief artifact",
            "record_key": "project_brief.artifact",
            "record_kind": "artifact_ref",
            "artifact_refs": ["storage/task_environments/office/file-search/artifacts/project_brief.md"],
        },
        task_run_id="taskrun:writing:test",
        node_run_id="taskrun:writing:test:project_brief",
        source_node_id="project_brief",
        runtime_scope=runtime_scope,
    )

    assert candidate.effective_repository_id == "run:graphmem_writing_test:memory.writing.artifact_index"


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


def test_formal_memory_project_scope_shares_within_project_only(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    project_edge = {**_edge(), "lifecycle_policy": {"scope_kind": "project_scoped"}}
    candidate, _write_txn = service.write_candidate_from_edge(
        edge=project_edge,
        candidate={"canonical_text": "同项目共享世界观", "record_key": "world.current"},
        task_run_id="taskrun:design",
        node_run_id="taskrun:design:writer",
        source_node_id="writer",
        source_clock_seq=1,
        runtime_scope={"project_id": "project:one"},
    )
    service.commit_from_edge(
        edge=project_edge,
        candidate_version_id=candidate.version_id,
        node_run_id="taskrun:design:commit",
        source_clock_seq=2,
    )

    same_project = service.select_for_node(
        read_edges=[project_edge],
        task_run_id="taskrun:chapter",
        node_run_id="taskrun:chapter:reader",
        clock_seq=3,
        runtime_scope={"project_id": "project:one"},
    )
    other_project = service.select_for_node(
        read_edges=[project_edge],
        task_run_id="taskrun:other",
        node_run_id="taskrun:other:reader",
        clock_seq=3,
        runtime_scope={"project_id": "project:two"},
    )

    assert same_project["required_records"][0]["canonical_text"] == "同项目共享世界观"
    assert other_project["required_records"] == []


def test_graph_task_memory_search_is_bound_to_runtime_project_scope(tmp_path) -> None:
    service = FormalMemoryService(tmp_path / "storage" / "formal_memory")
    project_edge = {**_edge(), "lifecycle_policy": {"scope_kind": "project_scoped"}}
    candidate, _write_txn = service.write_candidate_from_edge(
        edge=project_edge,
        candidate={"canonical_text": "旧项目世界观", "record_key": "world.current"},
        task_run_id="taskrun:old",
        node_run_id="taskrun:old:writer",
        source_node_id="writer",
        source_clock_seq=1,
        runtime_scope={"project_id": "project:old"},
    )
    service.commit_from_edge(
        edge=project_edge,
        candidate_version_id=candidate.version_id,
        node_run_id="taskrun:old:commit",
        source_clock_seq=2,
    )

    executor = ToolRuntimeExecutor(tool_runtime=ToolRuntime(tmp_path))
    task_run_id = "gtask:graph:new:node"
    action = RuntimeActionRequest(
        request_id="model-action:memory-search",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id="step:memory-search",
        directive_ref="directive:memory-search",
        operation_id="op.memory_read",
        payload={
            "tool_name": "memory_search",
            "tool_call": {
                "id": "model-action:memory-search",
                "name": "memory_search",
                "args": {"query": "旧项目世界观", "task_run_id": "", "project_id": "", "limit": 8},
            },
        },
        created_at=time.time(),
    )
    directive = RuntimeDirective(
        directive_id="directive:memory-search",
        task_id=task_run_id,
        plan_ref="plan:memory-search",
        stage_ref="stage:memory-search",
        executor_type="tool",
        adopted_resource_policy_ref="resource-policy:memory-search",
        operation_refs=("op.memory_read",),
    )
    record = OperationExecutionRecord(
        execution_id="rtexec:memory-search",
        task_run_id=task_run_id,
        step_id="step:memory-search",
        request_ref=action.request_id,
        directive_ref=directive.directive_id,
        operation_id="op.memory_read",
        executor_type="tool",
        request_fingerprint="fingerprint",
        idempotency_token="token",
        replay_policy="replay_read",
    )

    result = asyncio.run(
        executor.run(
            task_run_id=task_run_id,
            action_request=action,
            directive=directive,
            execution_record=record,
            sandbox_policy={
                "runtime_scope": {
                    "project_id": "project:new",
                    "graph_run_id": "grun:new",
                    "graph_node_id": "graph_module.design_init::project_brief",
                }
            },
        )
    )
    observation = result["observation"].to_dict()
    payload = json.loads(observation["payload"]["result"])

    assert payload["project_id"] == "project:new"
    assert payload["task_run_id"] == task_run_id
    assert payload["result_count"] == 0
    assert payload["diagnostics"]["candidate_version_count"] == 0


