from __future__ import annotations

from harness.loop.graph_coordination.checkpoint_adapter import GraphCoordinationCheckpointStore


def test_langgraph_checkpoint_adapter_persists_by_thread_id(tmp_path) -> None:
    adapter = GraphCoordinationCheckpointStore(tmp_path)

    checkpoint = adapter.put_state(
        thread_id="coordrun:test",
        state={"active_stage_id": "volume_planning"},
        metadata={"event": "unit"},
    )

    assert checkpoint.thread_id == "coordrun:test"
    assert adapter.get_state(thread_id="coordrun:test")["active_stage_id"] == "volume_planning"
    assert adapter.get_checkpoint(thread_id="coordrun:test").metadata["event"] == "unit"
