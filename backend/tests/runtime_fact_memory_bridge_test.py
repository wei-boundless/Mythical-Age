from __future__ import annotations

from memory_system.runtime_fact_bridge import RuntimeFactBridge
from runtime.facts import RuntimeFactLedger


def test_runtime_fact_bridge_only_exposes_memory_governed_candidates(tmp_path) -> None:
    ledger = RuntimeFactLedger(tmp_path)
    diagnostic = ledger.record_fact(
        fact_type="trace_span",
        scope={"session_id": "session:memory-bridge", "task_run_id": "taskrun:memory-bridge"},
        refs={"trace_id": "trace:memory-bridge", "span_id": "span:memory-bridge"},
        attributes={"tool_output": "must not become memory"},
        summary="diagnostic trace span",
        idempotency_key="trace-span:memory-bridge",
    )
    eligible = ledger.record_fact(
        fact_type="memory_candidate",
        scope={"session_id": "session:memory-bridge", "task_run_id": "taskrun:memory-bridge"},
        refs={"trace_id": "trace:memory-bridge", "artifact_ref": "artifact:world"},
        attributes={"canonical_text": "must not be copied into candidate"},
        summary="world memory candidate",
        retention_class="memory_governed",
        model_visibility="governed_memory_only",
        idempotency_key="memory-candidate:memory-bridge",
    )
    bridge = RuntimeFactBridge(ledger)

    result = bridge.list_candidates(task_run_id="taskrun:memory-bridge", limit=20)

    assert result["authority"] == "memory_system.runtime_fact_bridge"
    assert result["candidate_count"] == 1
    assert result["rejected_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["source_fact_id"] == eligible.fact_id
    assert candidate["fact_type"] == "memory_candidate"
    assert candidate["refs"]["artifact_ref"] == "artifact:world"
    assert "canonical_text" not in candidate
    assert diagnostic.fact_id not in {item["source_fact_id"] for item in result["candidates"]}


def test_runtime_fact_bridge_records_memory_commit_provenance_edge(tmp_path) -> None:
    ledger = RuntimeFactLedger(tmp_path)
    source = ledger.record_fact(
        fact_type="memory_candidate",
        scope={"session_id": "session:memory-commit", "task_run_id": "taskrun:memory-commit"},
        refs={"trace_id": "trace:memory-commit"},
        summary="candidate ready for commit",
        retention_class="memory_governed",
        model_visibility="governed_memory_only",
        idempotency_key="memory-candidate:memory-commit",
    )
    bridge = RuntimeFactBridge(ledger)

    receipt = bridge.record_memory_commit(
        source_fact_id=source.fact_id,
        memory_record_id="memrec:world",
        memory_version_id="memver:world:1",
        attributes={"content_hash": "sha256:test"},
    )

    commit = ledger.get_record(receipt["commit_fact_id"])
    edges = ledger.list_edges(source_fact_id=source.fact_id, relation="promoted_to_memory")
    assert commit is not None
    assert commit.fact_type == "memory_commit"
    assert commit.refs["memory_record_id"] == "memrec:world"
    assert commit.refs["memory_version_id"] == "memver:world:1"
    assert commit.refs["source_fact_id"] == source.fact_id
    assert commit.retention_class == "memory_governed"
    assert commit.model_visibility == "governed_memory_only"
    assert len(edges) == 1
    assert edges[0].target_fact_id == commit.fact_id
