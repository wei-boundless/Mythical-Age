from __future__ import annotations

import json
from pathlib import Path

from capability_system.tools.native_tool_catalog import get_tool_definition_map
from capability_system.tools.tool_units.memory_search_tool import MemorySearchTool
from memory_system.formal_memory_models import FormalMemoryCollection, FormalMemoryRepository
from memory_system.runtime_services import MemoryRuntimeServices
from runtime.memory.state_index import RuntimeStateIndex
from runtime.shared.models import TaskRun


def test_memory_search_tool_reads_formal_task_memory_only(tmp_path: Path) -> None:
    services = MemoryRuntimeServices.from_runtime_root(tmp_path / "storage")
    store = services.formal_memory.store
    store.upsert_repository(
        FormalMemoryRepository(
            repository_id="run:task-1:memory.writing.manuscript",
            logical_repository_id="memory.writing.manuscript",
            effective_repository_id="run:task-1:memory.writing.manuscript",
            task_run_id="task-1",
            title="正文记忆库",
        )
    )
    store.upsert_collection(
        FormalMemoryCollection(
            repository_id="run:task-1:memory.writing.manuscript",
            collection_id="manuscript_fact_index",
            logical_repository_id="memory.writing.manuscript",
            effective_repository_id="run:task-1:memory.writing.manuscript",
            task_run_id="task-1",
        )
    )
    candidate, _transaction = services.formal_memory.write_candidate_from_edge(
        edge={
            "edge_id": "edge.test.memory_commit",
            "repository": "memory.writing.manuscript",
            "collection": "manuscript_fact_index",
        },
        candidate={
            "record_key": "chapter_001_daze_boy",
            "record_kind": "manuscript_fact",
            "summary": "大泽少年在第一章离开部族旧地。",
            "canonical_text": "大泽少年离开旧地，带走祭骨与关于神庭破灭的传闻。",
        },
        task_run_id="task-1",
        node_run_id="node-run:test",
        source_node_id="memory_commit_chapter",
        source_clock="clock:1",
        source_clock_seq=1,
    )
    committed, _commit = services.formal_memory.commit_from_edge(
        edge={"edge_id": "edge.test.memory_commit"},
        candidate_version_id=candidate.version_id,
        node_run_id="node-run:test",
        source_clock="clock:2",
        source_clock_seq=2,
    )

    result = json.loads(
        MemorySearchTool(tmp_path / "storage").invoke(
            {
                "query": "大泽少年 祭骨",
                "task_run_id": "task-1",
                "repositories": ["memory.writing.manuscript"],
                "collections": ["manuscript_fact_index"],
            }
        )
    )

    assert result["authority"] == "formal_memory.memory_search_tool"
    assert result["result_count"] == 1
    assert result["results"][0]["memory_ref"] == committed.version_id
    assert result["results"][0]["repository"] == "memory.writing.manuscript"


def test_memory_search_tool_registered_as_memory_read() -> None:
    definition = get_tool_definition_map()["memory_search"]
    assert definition.operation_id == "op.memory_read"
    assert definition.is_read_only is True
    assert "formal_memory" in definition.capability_tags


def test_memory_search_tool_resolves_project_scoped_memory_from_task_run(tmp_path: Path) -> None:
    services = MemoryRuntimeServices.from_runtime_root(tmp_path / "storage")
    runtime_index = RuntimeStateIndex(tmp_path / "storage" / "runtime_state")
    runtime_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:chapter",
            session_id="session:test",
            task_id="task:test",
            diagnostics={"project_id": "project:honghuang"},
        )
    )
    candidate, _transaction = services.formal_memory.write_candidate_from_edge(
        edge={
            "edge_id": "edge.test.project_memory",
            "repository": "memory.writing.baseline",
            "collection": "world_bible",
            "lifecycle_policy": {"scope_kind": "project_scoped"},
        },
        candidate={
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
            "summary": "神庭破灭五千年后，万族开始崛起。",
            "canonical_text": "神庭破灭五千年后，神灵统治衰弱，万族开始崛起。",
        },
        task_run_id="taskrun:design",
        node_run_id="node-run:design",
        source_node_id="baseline_memory_seed",
        source_clock="clock:1",
        source_clock_seq=1,
        runtime_scope={"project_id": "project:honghuang"},
    )
    committed, _commit = services.formal_memory.commit_from_edge(
        edge={"edge_id": "edge.test.project_memory"},
        candidate_version_id=candidate.version_id,
        node_run_id="node-run:design",
        source_clock="clock:2",
        source_clock_seq=2,
    )

    result = json.loads(
        MemorySearchTool(tmp_path / "storage").invoke(
            {
                "query": "神庭破灭 万族崛起",
                "task_run_id": "taskrun:chapter",
                "repositories": ["memory.writing.baseline"],
                "collections": ["world_bible"],
            }
        )
    )

    assert result["project_id"] == "project:honghuang"
    assert result["result_count"] == 1
    assert result["results"][0]["memory_ref"] == committed.version_id


