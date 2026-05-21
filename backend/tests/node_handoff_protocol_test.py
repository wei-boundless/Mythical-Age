from __future__ import annotations

from pathlib import Path

from runtime.execution.node_handoff_protocol import (
    build_node_executor_binding,
    build_standard_node_input_package,
    build_standard_node_result_package,
    render_human_work_packet,
)


def test_standard_node_input_package_merges_edge_backed_materials() -> None:
    contract = {
        "stage_id": "writer",
        "node_id": "writer",
        "title": "章节写作",
        "role": "章节写作者",
        "required_inputs": ["chapter_outline", "worldview"],
        "output_contract_id": "contract.chapter_draft",
        "output_mappings": [{"output_key": "chapter_body", "required": True}],
        "input_bindings": [{"source_stage_id": "outline", "output_key": "outline", "input_key": "chapter_outline"}],
    }
    package = build_standard_node_input_package(
        coordination_run_id="coordrun:1",
        stage_id="writer",
        node_id="writer",
        contract=contract,
        explicit_inputs={"chapter_range": "11-20"},
        dispatch_context={
            "dispatch_event_id": "event:1",
            "activation_id": "activation:writer:1",
            "execution_permit_id": "permit:writer:1",
        },
        memory_snapshot={
            "snapshot_id": "memsnap:1",
            "read_edge_ids": ["edge:world_to_writer"],
            "resolved_records": [
                {
                    "record_id": "memory:world",
                    "collection_id": "worldview",
                    "content": "世界观定稿",
                    "usage_instruction": "作为世界观约束。",
                }
            ],
        },
        artifact_context_packet={
            "packet_id": "artctx:1",
            "edge_ids": ["edge:outline_to_writer"],
            "source_node_ids": ["outline"],
            "artifact_refs": ["artifact:outline.md"],
            "expanded_text_by_input_key": {"chapter_outline": "第十一至二十章细纲"},
        },
        revision_packet={},
        handoff_packets=[],
    )

    by_key = {item.input_key: item for item in package.input_items}
    assert package.activation_id == "activation:writer:1"
    assert package.execution_permit_id == "permit:writer:1"
    assert by_key["chapter_outline"].source_edge_id == "edge:outline_to_writer"
    assert by_key["worldview"].source_edge_id == "edge:world_to_writer"
    assert package.output_contract["required_output_keys"] == ["chapter_body"]


def test_standard_node_input_package_expands_artifact_refs_for_text_artifact_runtime_agents(tmp_path: Path) -> None:
    artifact = tmp_path / "outline_review.md"
    artifact.write_text("# 细纲审核\n\n裁决：通过。可以提交基准库。", encoding="utf-8")

    package = build_standard_node_input_package(
        coordination_run_id="coordrun:1",
        stage_id="baseline_memory_seed",
        node_id="baseline_memory_seed",
        contract={
            "title": "基准库初始化",
            "required_inputs": ["上游交接包"],
            "output_mappings": [{"output_key": "baseline_commit", "required": True}],
        },
        explicit_inputs={},
        dispatch_context={"activation_id": "activation:baseline:1", "execution_permit_id": "permit:baseline:1"},
        memory_snapshot={},
        artifact_context_packet={
            "packet_id": "artctx:baseline",
            "edge_ids": ["edge.outline_review.baseline"],
            "source_node_ids": ["outline_review"],
            "artifact_refs": [f"artifact:{artifact}"],
        },
        revision_packet={},
        handoff_packets=[],
    )

    artifact_item = next(item for item in package.input_items if item.content_ref == f"artifact:{artifact}")
    assert artifact_item.content_type == "artifact_text"
    assert "裁决：通过" in artifact_item.content_preview
    assert artifact_item.metadata["text"].startswith("# 细纲审核")
    assert artifact_item.metadata["expanded_by_runtime"] is True


def test_standard_node_input_package_filters_internal_protocol_inputs() -> None:
    package = build_standard_node_input_package(
        coordination_run_id="coordrun:1",
        stage_id="child_node",
        node_id="child_node",
        contract={
            "title": "子图节点",
            "required_inputs": ["user_goal"],
            "output_mappings": [{"output_key": "result", "required": True}],
        },
        explicit_inputs={
            "user_goal": "启动子图",
            "importing_graph_module_runtime_handle": {"linked_graph_id": "graph.child"},
            "importing_stage_execution_request": {"stage_id": "graph_module.block.child"},
            "importing_standard_input_package": {"input_items": [{"input_key": "polluted"}]},
            "runtime_protocol.debug": {"artifact_refs": ["artifact:debug/should_not_leak.md"]},
        },
        dispatch_context={"activation_id": "activation:child:1", "execution_permit_id": "permit:child:1"},
        memory_snapshot={},
        artifact_context_packet={},
        revision_packet={},
        handoff_packets=[],
    )

    input_keys = {item.input_key for item in package.input_items}
    assert input_keys == {"user_goal"}
    assert package.diagnostics["missing_required_input_keys"] == []


def test_human_executor_uses_same_package_as_work_packet() -> None:
    contract = {
        "node_id": "reviewer",
        "title": "章节审核",
        "role": "章节审核员",
        "executor_policy": {
            "default_executor": "human",
            "allowed_executors": ["agent", "human"],
            "human_profile_id": "人工审核员",
        },
        "output_mappings": [{"output_key": "review_opinion", "required": True}],
    }
    binding = build_node_executor_binding(node_id="reviewer", contract=contract)
    package = build_standard_node_input_package(
        coordination_run_id="coordrun:1",
        stage_id="reviewer",
        node_id="reviewer",
        contract=contract,
        explicit_inputs={},
        dispatch_context={"activation_id": "activation:reviewer:1", "execution_permit_id": "permit:reviewer:1"},
        memory_snapshot={},
        artifact_context_packet={"packet_id": "artctx:1", "artifact_refs": ["artifact:draft.md"]},
        revision_packet={},
        handoff_packets=[],
    )
    work_packet = render_human_work_packet(input_package=package, executor_binding=binding, contract=contract)

    assert binding.selected_executor == "human"
    assert work_packet.package_id == package.package_id
    assert work_packet.output_form_schema["fields"][0]["field_id"] == "review_opinion"
    assert work_packet.submit_policy["submit_as"] == "standard_node_result_package"


def test_standard_result_package_preserves_activation_and_permit() -> None:
    result = build_standard_node_result_package(
        request_payload={
            "coordination_run_id": "coordrun:1",
            "stage_id": "writer",
            "node_id": "writer",
            "request_id": "request:1",
            "executor_type": "human",
            "standard_input_package": {
                "activation_id": "activation:writer:1",
                "execution_permit_id": "permit:writer:1",
            },
        },
        event={
            "task_run_id": "taskrun:writer",
            "task_result_ref": "taskresult:writer",
            "accepted": True,
            "diagnostics": {"handoff_summary": "正文已完成。"},
        },
        outputs={"chapter_body": "正文"},
        artifact_refs=["artifact:draft.md"],
    )

    assert result.executor_type == "human"
    assert result.activation_id == "activation:writer:1"
    assert result.execution_permit_id == "permit:writer:1"
    assert result.outputs["chapter_body"] == "正文"
    assert result.handoff_summary == "正文已完成。"
