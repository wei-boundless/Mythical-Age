from __future__ import annotations

from harness.runtime.dynamic_context.replacement_store import ReplacementStore


def test_replacement_store_reuses_projection_for_same_source_policy_and_version(tmp_path) -> None:
    store = ReplacementStore(tmp_path)
    first, first_record = store.get_or_put(
        source_kind="tool_result",
        source_id="tool-result:1",
        content={"text": "same output"},
        projection_policy={"preview": 100},
        projector_version="test.v1",
        projection={"preview": "same output", "status": "ok"},
    )
    second, second_record = store.get_or_put(
        source_kind="tool_result",
        source_id="tool-result:1",
        content={"text": "same output"},
        projection_policy={"preview": 100},
        projector_version="test.v1",
        projection={"preview": "mutated output", "status": "ok"},
    )

    assert first == {"preview": "same output", "status": "ok"}
    assert second == first
    assert second_record.replacement_key == first_record.replacement_key


def test_replacement_store_key_changes_when_policy_changes(tmp_path) -> None:
    store = ReplacementStore(tmp_path)
    _, first_record = store.get_or_put(
        source_kind="observation",
        source_id="obs:1",
        content={"summary": "same observation"},
        projection_policy={"summary_chars": 100},
        projector_version="test.v1",
        projection={"summary": "same observation"},
    )
    _, second_record = store.get_or_put(
        source_kind="observation",
        source_id="obs:1",
        content={"summary": "same observation"},
        projection_policy={"summary_chars": 50},
        projector_version="test.v1",
        projection={"summary": "same observation"},
    )

    assert second_record.replacement_key != first_record.replacement_key


def test_replacement_store_reuses_rehydration_plan_for_same_source_policy_and_version(tmp_path) -> None:
    store = ReplacementStore(tmp_path)
    first, first_record = store.get_or_put(
        source_kind="tool_result",
        source_id="tool-result:rehydrate",
        content={"text": "large output"},
        projection_policy={"preview": 100},
        projector_version="test.v2",
        projection={
            "preview": "large output",
            "rehydration_plan": {
                "authority": "harness.runtime.dynamic_context.rehydration_plan",
                "source_kind": "tool_result",
                "prompt_status": "preview_only",
                "capabilities": [{"capability": "read_persisted_tool_result", "result_ref": "result:first"}],
            },
        },
    )
    second, second_record = store.get_or_put(
        source_kind="tool_result",
        source_id="tool-result:rehydrate",
        content={"text": "large output"},
        projection_policy={"preview": 100},
        projector_version="test.v2",
        projection={
            "preview": "changed output",
            "rehydration_plan": {
                "authority": "harness.runtime.dynamic_context.rehydration_plan",
                "source_kind": "tool_result",
                "prompt_status": "preview_only",
                "capabilities": [{"capability": "read_persisted_tool_result", "result_ref": "result:second"}],
            },
        },
    )

    assert second == first
    assert second_record.replacement_key == first_record.replacement_key
    assert first["rehydration_plan"]["replacement_ref"] == first_record.replacement_key
    assert first_record.rehydration_plan == first["rehydration_plan"]
    assert second_record.rehydration_plan == first["rehydration_plan"]
    assert second["rehydration_plan"]["capabilities"][0]["result_ref"] == "result:first"
