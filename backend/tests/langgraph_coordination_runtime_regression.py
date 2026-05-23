from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from runtime.shared.event_log import RuntimeEventLog
from runtime.agent_assembly import WorkOrder, validate_work_order
from runtime.coordination_runtime.runtime import (
    LangGraphCoordinationRuntime,
    _active_scope_key_for_scheduler,
    _apply_loop_derived_fields,
    _memory_edge_allows_refs_only_auto_candidate,
    _review_gate_event_is_accepted,
    _pending_inputs_for_stage_quality_retry,
    _rewind_preserved_pending_inputs,
    _agent_visible_checkout_explicit_inputs,
    _stage_execution_message,
    _stage_quality_retry_target,
)
from runtime.coordination_runtime.node_result_committer import build_node_result_acceptance_draft
from runtime.coordination_runtime.context_packet_resolver import build_revision_packet_from_review
from runtime.coordination_runtime.context_packet_resolver import resolve_artifact_context_packet
from runtime.shared.models import CoordinationRun, TaskRun
from runtime.execution.node_execution_request import NodeResultReadyEvent
from runtime.memory.state_index import RuntimeStateIndex
from runtime.unit_runtime.loop import _render_standard_input_package_for_model
from task_system import TaskContractRegistry
from task_system.registry.flow_models import CoordinationTaskDefinition, SpecificTaskRecord, TaskCommunicationProtocol, TopologyTemplate
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition
from runtime.contracts.continuation_policy import parse_stage_contracts
from tests.support.trace_stubs import TraceReaderStub


def _chapter_loop_derived_fields_for_test() -> list[dict]:
    return [
        {"key": "volume_index_padded", "op": "format", "template": "{volume_index:03d}"},
        {"key": "volume_label", "op": "format", "template": "第{volume_index}卷"},
        {"key": "chapter_index_padded", "op": "format", "template": "{chapter_index:03d}"},
        {"key": "chapter_label", "op": "format", "template": "第{chapter_index}章"},
        {"key": "chapter_file_prefix", "op": "format", "template": "chapter_{chapter_index:03d}"},
        {"key": "batch_start_index", "op": "copy", "from_key": "chapter_index"},
        {"key": "batch_end_index", "op": "add", "from_key": "chapter_index", "value_key": "chapters_per_round", "offset": -1, "value": 5},
        {"key": "batch_index", "op": "ordinal_group", "from_key": "chapter_index", "size_key": "chapters_per_round", "size": 5},
        {"key": "batch_index_padded", "op": "format", "template": "{batch_index:03d}"},
        {"key": "batch_start_index_padded", "op": "format", "template": "{batch_start_index:03d}"},
        {"key": "batch_end_index_padded", "op": "format", "template": "{batch_end_index:03d}"},
        {"key": "batch_chapter_range", "op": "format", "template": "{batch_start_index:03d}-{batch_end_index:03d}"},
        {"key": "batch_label", "op": "format", "template": "第{batch_start_index}章至第{batch_end_index}章"},
        {"key": "batch_chapter_numbers", "op": "range", "start_key": "batch_start_index", "end_key": "batch_end_index"},
        {"key": "batch_chapter_list", "op": "join", "from_key": "batch_chapter_numbers", "prefix": "第", "suffix": "章", "separator": "、"},
        {"key": "batch_target_words", "op": "multiply", "from_key": "chapter_target_words", "value_key": "chapters_per_round", "value": 5},
        {"key": "runtime_loop_summary", "op": "format", "template": "当前卷：{volume_label}；当前批次：{batch_label}；本批允许范围：{batch_chapter_list}；全书累计约 {current_words}/{target_words} 字；本卷累计约 {volume_current_words}/{volume_target_words} 字。"},
    ]


def test_loop_derived_fields_recompute_stale_batch_descriptions_without_overriding_scope() -> None:
    result = _apply_loop_derived_fields(
        {
            "volume_index": 1,
            "chapter_index": 1,
            "batch_start_index": 1,
            "batch_end_index": 5,
            "batch_end_index_padded": "010",
            "batch_chapter_range": "001-010",
            "batch_label": "第1章至第10章",
            "batch_chapter_numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "batch_chapter_list": "第1章、第2章、第3章、第4章、第5章、第6章、第7章、第8章、第9章、第10章",
            "runtime_loop_summary": "当前卷：第1卷；当前批次：第1章至第10章；本批允许范围：第1章、第2章、第3章、第4章、第5章、第6章、第7章、第8章、第9章、第10章。",
            "chapters_per_round": 5,
            "chapter_target_words": 2000,
            "current_words": 0,
            "target_words": 1000000,
            "volume_current_words": 0,
            "volume_target_words": 200000,
        },
        _chapter_loop_derived_fields_for_test(),
        preserve_existing_batch_scope=True,
    )

    assert result["batch_start_index"] == 1
    assert result["batch_end_index"] == 5
    assert result["batch_end_index_padded"] == "005"
    assert result["batch_chapter_range"] == "001-005"
    assert result["batch_label"] == "第1章至第5章"
    assert result["batch_chapter_numbers"] == [1, 2, 3, 4, 5]
    assert result["batch_chapter_list"] == "第1章、第2章、第3章、第4章、第5章"
    assert "第1章至第10章" not in result["runtime_loop_summary"]
    assert "第6章" not in result["runtime_loop_summary"]


def test_rewind_preserved_pending_inputs_drops_checkout_runtime_residue() -> None:
    preserved = _rewind_preserved_pending_inputs(
        {
            "project_id": "project:honghuang-times",
            "artifact_root": "output/novel_artifacts/modular_novel/runs/project-honghuang-times",
            "volume_index": 1,
            "contract.writing.modular_novel.world_candidate:artifact_refs": "artifact:world/world_review_round_002.md",
            "contract.writing.modular_novel.world_review:artifact_refs": "artifact:world/world_review_round_002_v002.md",
            "previous_review_stage_id": "world_review",
            "previous_review_ref": "artifact:world/world_review_round_001.md",
            "revision_requirements": "上一轮审核未通过",
            "revision_required": True,
            "force_replay": True,
            "force_replay_after": 1779478772.0,
            "upstream_output_refs": ["artifact:stale.md"],
            "world_review_ref": "artifact:world/world_review_round_002.md",
        },
        invalidated_stage_ids=["memory_commit_world", "character_design"],
        stage_results={
            "world_design": {"artifact_refs": ["artifact:world/world_candidate_round_002.md"]},
            "world_review": {"artifact_refs": ["artifact:world/world_review_round_002.md"]},
        },
    )

    assert preserved["project_id"] == "project:honghuang-times"
    assert preserved["artifact_root"] == "output/novel_artifacts/modular_novel/runs/project-honghuang-times"
    assert preserved["volume_index"] == 1
    assert "contract.writing.modular_novel.world_candidate:artifact_refs" not in preserved
    assert "contract.writing.modular_novel.world_review:artifact_refs" not in preserved
    assert "previous_review_stage_id" not in preserved
    assert "previous_review_ref" not in preserved
    assert "revision_requirements" not in preserved
    assert "revision_required" not in preserved
    assert "force_replay" not in preserved
    assert "force_replay_after" not in preserved
    assert "upstream_output_refs" not in preserved
    assert "world_review_ref" in preserved


def test_agent_visible_checkout_explicit_inputs_hide_runtime_artifact_controls() -> None:
    visible = _agent_visible_checkout_explicit_inputs(
        {
            "project_id": "project:honghuang-times",
            "artifact_root": "output/novel_artifacts/modular_novel/runs/project-honghuang-times",
            "contract.writing.modular_novel.world_candidate:artifact_refs": "artifact:world/world_review_round_002.md",
            "contract.writing.modular_novel.world_review:artifact_refs": "artifact:world/world_review_round_002_v002.md",
            "force_replay": True,
            "force_replay_after": 1779478772.0,
            "rewind_from_stage": "memory_commit_world",
            "rewind_reason": "checkout_pollution_repair",
            "revision_requirements": "旧审核意见",
            "previous_review_ref": "artifact:world/world_review_round_001.md",
            "upstream_output_refs": ["artifact:stale.md"],
        }
    )

    assert visible == {
        "project_id": "project:honghuang-times",
        "artifact_root": "output/novel_artifacts/modular_novel/runs/project-honghuang-times",
    }


def test_artifact_checkout_skips_accepted_stage_result_with_wrong_contract_artifact(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "output" / "world"
    artifact_dir.mkdir(parents=True)
    candidate_path = artifact_dir / "world_candidate_round_002.md"
    review_path = artifact_dir / "world_review_round_002.md"
    candidate_path.write_text("世界观设定候选：五域为人族退守地，洪荒为多层世界。", encoding="utf-8")
    review_path.write_text("世界观审核报告：结论为通过，但这里不是候选正文。", encoding="utf-8")
    candidate_ref = f"artifact:{candidate_path}"
    review_ref = f"artifact:{review_path}"
    state = {
        "stage_results_by_instance": {
            "tlresult:good-world-design": {
                "accepted": True,
                "artifact_refs": [candidate_ref, "artifact:output/debug/run_report_world_design.md"],
                "trace_refs": ["artifact:output/debug/run_report_world_design_trace.md"],
                "timeline_result_record": {
                    "result_record_id": "tlresult:good-world-design",
                    "stage_id": "world_design",
                    "node_id": "world_design",
                    "accepted": True,
                },
            },
            "tlresult:bad-world-design": {
                "accepted": True,
                "artifact_refs": [review_ref],
                "timeline_result_record": {
                    "result_record_id": "tlresult:bad-world-design",
                    "stage_id": "world_design",
                    "node_id": "world_design",
                    "accepted": True,
                },
            },
            "tlresult:world-review": {
                "accepted": True,
                "artifact_refs": [review_ref],
                "timeline_result_record": {
                    "result_record_id": "tlresult:world-review",
                    "stage_id": "world_review",
                    "node_id": "world_review",
                    "accepted": True,
                },
            },
        },
        "result_record_index": {
            "tlresult:bad-world-design": {"accepted": True},
            "tlresult:world-review": {"accepted": True},
        },
        "accepted_result_records_by_scope": {
            "run/volume[001]/round[002]": {
                "world_design": "tlresult:bad-world-design",
                "world_review": "tlresult:world-review",
            }
        },
        "diagnostics": {
            "coordination_graph_spec": {
                "edges": [
                    {
                        "edge_id": "edge.world.commit_candidate",
                        "source_node_id": "world_design",
                        "target_node_id": "memory_commit_world",
                        "payload_contract_id": "contract.writing.modular_novel.world_candidate",
                        "artifact_ref_policy": {"target_input_key": "通过候选正文", "max_chars": 30000},
                    },
                    {
                        "edge_id": "edge.world_review.commit",
                        "source_node_id": "world_review",
                        "target_node_id": "memory_commit_world",
                        "payload_contract_id": "contract.writing.modular_novel.world_review",
                        "artifact_ref_policy": {"target_input_key": "审核裁决报告", "max_chars": 30000},
                    },
                ]
            }
        },
    }

    packet = resolve_artifact_context_packet(
        state=state,
        stage_id="memory_commit_world",
        node_id="memory_commit_world",
        explicit_inputs={},
        dispatch_context={"scope_path": ["run", "volume[001]", "round[002]"]},
    )

    assert candidate_ref in packet["artifact_refs"]
    assert review_ref in packet["artifact_refs"]
    assert "artifact:output/debug/run_report_world_design.md" not in packet["artifact_refs"]
    assert "artifact:output/debug/run_report_world_design.md" not in packet["trace_refs"]
    assert "artifact:output/debug/run_report_world_design_trace.md" not in packet["trace_refs"]
    assert "世界观设定候选" in packet["expanded_text_by_input_key"]["通过候选正文"]
    assert "世界观审核报告" not in packet["expanded_text_by_input_key"]["通过候选正文"]
    assert "世界观审核报告" in packet["expanded_text_by_input_key"]["审核裁决报告"]
    assert "tlresult:good-world-design" in packet["source_result_record_ids"]


def test_memory_commit_world_checkout_filters_unrelated_explicit_artifact_refs() -> None:
    state = {
        "stage_results_by_instance": {
            "tlresult:world-design": {
                "accepted": True,
                "artifact_refs": ["artifact:output/world/world_candidate_round_002.md"],
                "timeline_result_record": {
                    "result_record_id": "tlresult:world-design",
                    "stage_id": "world_design",
                    "node_id": "world_design",
                    "accepted": True,
                },
            }
        },
        "result_record_index": {"tlresult:world-design": {"accepted": True}},
        "accepted_result_records_by_scope": {"run": {"world_design": "tlresult:world-design"}},
        "diagnostics": {
            "coordination_graph_spec": {
                "edges": [
                    {
                        "edge_id": "edge.world.commit_candidate",
                        "source_node_id": "world_design",
                        "target_node_id": "memory_commit_world",
                        "payload_contract_id": "contract.writing.modular_novel.world_candidate",
                        "artifact_ref_policy": {"target_input_key": "通过候选正文", "max_chars": 30000},
                    }
                ]
            }
        },
    }

    packet = resolve_artifact_context_packet(
        state=state,
        stage_id="memory_commit_world",
        node_id="memory_commit_world",
        explicit_inputs={"contract.writing.modular_novel.world_candidate:artifact_refs": "artifact:output/world/world_review_round_002.md"},
        dispatch_context={"scope_path": ["run"]},
    )

    assert "artifact:output/world/world_candidate_round_002.md" in packet["artifact_refs"]
    assert "artifact:output/world/world_review_round_002.md" not in packet["artifact_refs"]


def test_node_result_acceptance_keeps_debug_reports_out_of_formal_artifact_refs() -> None:
    draft = build_node_result_acceptance_draft(
        state={},
        event={
            "accepted": True,
            "artifact_refs": [
                "artifact:output/project/memory/world/world_commit_round_002.md",
                "artifact:output/project/debug/run_report_task-writing-modular-novel-node-memory-commit-world.md",
                "trace:event:debug",
            ],
        },
        stage_id="memory_commit_world",
        contract={
            "node_id": "memory_commit_world",
            "output_mappings": [
                {
                    "output_key": "contract.writing.modular_novel.world_commit:artifact_refs",
                    "required": True,
                }
            ],
            "artifact_policy": {"enabled": True, "required": True},
        },
        request_payload={},
        stage_scope={"scope_path": ["run"]},
        event_accepted_by_policy=False,
        committed_identities=[],
    )

    assert draft.accepted is True
    assert draft.artifact_refs == ["artifact:output/project/memory/world/world_commit_round_002.md"]
    assert "artifact:output/project/debug/run_report_task-writing-modular-novel-node-memory-commit-world.md" in draft.trace_refs
    assert "trace:event:debug" in draft.trace_refs


def test_quality_retry_pending_inputs_normalize_stale_loop_fields() -> None:
    state = {
        "pending_inputs": {
            "volume_index": 1,
            "chapter_index": 1,
            "batch_start_index": 1,
            "batch_end_index": 5,
            "batch_end_index_padded": "010",
            "batch_chapter_range": "001-010",
            "batch_label": "第1章至第10章",
            "batch_chapter_numbers": [1, 2, 3, 4, 5],
            "batch_chapter_list": "第1章、第2章、第3章、第4章、第5章",
            "runtime_loop_summary": "当前卷：第1卷；当前批次：第1章至第10章；本批允许范围：第1章、第2章、第3章、第4章、第5章、第6章、第7章、第8章、第9章、第10章。",
            "chapters_per_round": 5,
            "chapter_target_words": 2000,
            "current_words": 0,
            "target_words": 1000000,
            "volume_current_words": 0,
            "volume_target_words": 200000,
        },
        "diagnostics": {
            "runtime_loop_policy": {
                "enabled": True,
                "derived_fields": _chapter_loop_derived_fields_for_test(),
            }
        },
    }
    pending_inputs = _pending_inputs_for_stage_quality_retry(
        state=state,
        stage_id="chapter_outline",
        contract={
            "quality_retry_policy": {
                "enabled": True,
                "requirements_input_key": "chapter_revision_requirements",
                "requirements_template": "范围：{batch_label}；清单：{batch_chapter_list}；问题：{quality_issues}",
            }
        },
        event={
            "diagnostics": {
                "stage_business_acceptance": {
                    "accepted": False,
                    "issues": ["unexpected_unit_indexes:6,7,8,9,10"],
                }
            },
            "artifact_refs": ["artifact:old-outline"],
        },
    )

    assert pending_inputs["round_index"] == 2
    assert pending_inputs["revision_required"] is True
    assert pending_inputs["batch_end_index_padded"] == "005"
    assert pending_inputs["batch_chapter_range"] == "001-005"
    assert pending_inputs["batch_label"] == "第1章至第5章"
    assert pending_inputs["batch_chapter_numbers"] == [1, 2, 3, 4, 5]
    assert "第1章至第5章" in pending_inputs["chapter_revision_requirements"]
    assert "第1章至第10章" not in pending_inputs["chapter_revision_requirements"]
    assert "第1章至第10章" not in pending_inputs["runtime_loop_summary"]
    assert "第6章" not in pending_inputs["runtime_loop_summary"]


def test_quality_retry_target_accepts_combined_quality_gate_policy() -> None:
    target = _stage_quality_retry_target(
        contract={
            "quality_retry_policy": {
                "enabled": True,
                "acceptance_policies": ["sectioned_text_batch_quality"],
            }
        },
        stage_id="chapter_draft",
        event={
            "diagnostics": {
                "stage_business_acceptance": {
                    "accepted": False,
                    "policy": "length_budget+sectioned_text_batch_quality",
                    "quality_gate_policies": ["length_budget", "sectioned_text_batch_quality"],
                    "issues": ["insufficient_metric:4500<5400", "insufficient_unit_metric:2:700<1800"],
                }
            }
        },
    )

    assert target == "chapter_draft"


def test_quality_retry_template_can_render_quality_issue_summary() -> None:
    state = {
        "pending_inputs": {
            "round_index": 1,
            "batch_start_index": 1,
            "batch_end_index": 3,
            "chapters_per_round": 3,
        }
    }

    pending_inputs = _pending_inputs_for_stage_quality_retry(
        state=state,
        stage_id="chapter_draft",
        contract={
            "quality_retry_policy": {
                "enabled": True,
                "requirements_input_key": "chapter_revision_requirements",
                "requirements_template": "问题：{quality_issues}\n统计：{quality_issue_summary}",
            }
        },
        event={
            "diagnostics": {
                "stage_business_acceptance": {
                    "accepted": False,
                    "policy": "length_budget+sectioned_text_batch_quality",
                    "quality_gate_policies": ["length_budget", "sectioned_text_batch_quality"],
                    "issues": ["insufficient_metric:4500<5400", "insufficient_unit_metric:2:700<1800"],
                    "quality_issue_summary": "总量约4500字，低于最低要求5400字，需至少补约900字；逐单元统计：第1章约1900字；第2章约700字，低于1800字，需补约1100字；第3章约1900字",
                }
            },
            "artifact_refs": ["artifact:short-draft"],
        },
    )

    requirements = pending_inputs["chapter_revision_requirements"]
    assert "insufficient_metric:4500<5400" in requirements
    assert "第2章约700字" in requirements
    assert "需补约1100字" in requirements


def test_review_gate_pass_verdict_overrides_missing_artifact_ref_technical_failure() -> None:
    event = {
        "accepted": False,
        "diagnostics": {
            "stage_business_acceptance": {
                "accepted": False,
                "base_accepted": False,
                "business_accepted": True,
                "artifact_ok": False,
                "policy": "review_gate_verdict",
                "verdict": "pass",
            }
        },
    }
    contract = {
        "node_type": "review_gate",
        "review_gate_policy": {"revision_stage_id": "world_design"},
    }

    assert _review_gate_event_is_accepted(event=event, contract=contract) is True


def test_review_gate_revise_verdict_does_not_override_failure() -> None:
    event = {
        "accepted": False,
        "diagnostics": {
            "stage_business_acceptance": {
                "business_accepted": False,
                "policy": "review_gate_verdict",
                "verdict": "revise",
            }
        },
    }
    contract = {
        "node_type": "review_gate",
        "review_gate_policy": {"revision_stage_id": "world_design"},
    }

    assert _review_gate_event_is_accepted(event=event, contract=contract) is False


def test_rewind_refresh_uses_live_graph_loop_policy_instead_of_stale_snapshot(tmp_path) -> None:
    stale_fields = _chapter_loop_derived_fields_for_test()
    live_fields = [dict(item) for item in _chapter_loop_derived_fields_for_test()]
    for item in stale_fields:
        if item["key"] == "batch_end_index":
            item.pop("value_key", None)
            item["value"] = 9
        if item["key"] == "batch_index":
            item.pop("size_key", None)
            item["size"] = 10
        if item["key"] == "batch_target_words":
            item.pop("value_key", None)
            item["value"] = 10

    live_graph = _loop_graph_from_derived_fields(live_fields)
    stale_graph = _loop_graph_from_derived_fields(stale_fields)
    registry = _RefreshGraphRegistry(live_graph)
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    stale_graph_ref = runtime.runtime_objects.put_json_once(
        "task_graph_definitions",
        "coordrun:loop-refresh",
        stale_graph.to_dict(),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:loop-refresh",
        task_run_id="taskrun:loop-refresh",
        graph_ref=live_graph.graph_id,
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.loop_refresh",
        communication_protocol_id="protocol.test.loop_refresh",
        status="running",
        diagnostics={
            "coordination_flow": {"current_stage_id": "chapter_outline"},
            "task_graph_definition_ref": stale_graph_ref,
        },
    )
    state_index.upsert_coordination_run(coordination_run)

    initialized = runtime.initialize(coordination_run=coordination_run)
    assert initialized.state["diagnostics"]["runtime_loop_policy"]["derived_fields"][6]["value"] == 9

    result = runtime.rewind_from_stage(
        coordination_run_id="coordrun:loop-refresh",
        stage_id="chapter_outline",
        reason="refresh_live_policy",
        inherited_inputs={
            "chapter_index": 1,
            "batch_start_index": 1,
            "batch_end_index": 5,
            "chapters_per_round": 5,
            "chapter_target_words": 2000,
        },
        refresh_graph_spec=True,
    )

    derived = {
        item["key"]: item
        for item in result.state["diagnostics"]["runtime_loop_policy"]["derived_fields"]
    }
    explicit_inputs = result.state["stage_execution_request"]["explicit_inputs"]

    assert derived["batch_end_index"]["value_key"] == "chapters_per_round"
    assert derived["batch_target_words"]["value_key"] == "chapters_per_round"
    assert explicit_inputs["batch_end_index"] == 5
    assert explicit_inputs["batch_chapter_range"] == "001-005"
    assert explicit_inputs["batch_target_words"] == 10000
    assert "第1章至第5章" in explicit_inputs["runtime_loop_summary"]


def test_stage_execution_message_declares_runtime_batch_boundary_over_stale_project_brief() -> None:
    message = _stage_execution_message(
        stage_id="chapter_outline",
        task_ref="task.test.chapter_outline",
        contract={
            "title": "当前批次细纲",
            "executor_policy": {
                "runtime_batch_boundary_policy": {
                    "start_key": "batch_start_index",
                    "end_key": "batch_end_index",
                    "count_key": "chapters_per_round",
                    "list_key": "batch_chapter_list",
                    "target_metric_key": "batch_target_words",
                    "unit_label": "章",
                    "unit_label_prefix": "第",
                    "unit_label_suffix": "章",
                    "range_template": "本节点只允许处理第{start}章至第{end}章。",
                    "list_template": "允许章号清单：{unit_list}。",
                    "size_template": "当前运行时每轮批次大小为 {unit_count} 章。",
                    "metric_template": "当前批次目标正文量约 {target_metric} 字。",
                    "conflict_template": "如果项目启动包、上游旧产物或历史摘要出现其他批次大小或其他章号范围，以本轮处理边界为准。",
                }
            },
        },
        explicit_inputs={
            "project_title": "洪荒时代",
            "project_brief": "硬设定：每轮连续创作 10 章。",
            "batch_start_index": 1,
            "batch_end_index": 5,
            "batch_chapter_list": "第1章、第2章、第3章、第4章、第5章",
            "chapters_per_round": 5,
            "batch_target_words": 10000,
            "runtime_loop_summary": "当前卷：第1卷；当前批次：第1章至第5章；本批允许范围：第1章、第2章、第3章、第4章、第5章。",
        },
    )

    boundary_pos = message.index("本轮处理边界：")
    hard_setting_pos = message.index("用户约束：")

    assert boundary_pos < hard_setting_pos
    assert "本节点只允许处理第1章至第5章" in message
    assert "当前运行时每轮批次大小为 5 章" in message
    assert "以本轮处理边界为准" in message


def test_stage_execution_message_uses_generic_batch_boundary_without_domain_defaults() -> None:
    message = _stage_execution_message(
        stage_id="batch_worker",
        task_ref="task.test.batch_worker",
        contract={"title": "批处理节点"},
        explicit_inputs={
            "batch_start_index": 2,
            "batch_end_index": 4,
            "unit_label": "项",
            "unit_batch_list": "2项、3项、4项",
            "unit_batch_size": 3,
            "batch_target_units": 900,
        },
    )

    assert "本节点只允许处理2项至4项" in message
    assert "允许单元清单：2项、3项、4项" in message
    assert "章" not in message


def test_stage_execution_message_expands_revision_artifact_text(tmp_path) -> None:
    previous = tmp_path / "previous_outline.md"
    review = tmp_path / "outline_review.md"
    previous.write_text("# 上一版大纲\n\n这里是上一版正文。", encoding="utf-8")
    review.write_text("# 审核意见\n\n需要补强卷级推进和伏笔回收。", encoding="utf-8")

    message = _stage_execution_message(
        stage_id="outline_design",
        task_ref="task.test.outline_design",
        contract={"title": "大纲返修"},
        explicit_inputs={},
        revision_packet={
            "review_verdict": "revise",
            "required_changes": ["补强卷级推进"],
            "review_result_refs": [f"artifact:{review}"],
            "previous_candidate_artifact_refs": [f"artifact:{previous}"],
        },
    )

    assert "审核报告内容" in message
    assert "需要补强卷级推进和伏笔回收" in message
    assert "上一版候选产物内容" in message
    assert "这里是上一版正文" in message
    assert "不要输出 read_file" in message


def test_revision_packet_prefers_node_work_order_over_stage_request() -> None:
    state = {
        "node_work_order": {
            "work_order_id": "nodeexec:new",
            "dispatch_context": {
                "dispatch_event_id": "tlevent:new",
                "clock_seq": 9,
            },
            "artifact_context_packet": {"artifact_refs": ["artifact:new.md"]},
            "explicit_inputs": {"candidate_ref": "artifact:new-fallback.md"},
        },
        "stage_execution_request": {
            "request_id": "nodeexec:old",
            "dispatch_context": {
                "dispatch_event_id": "tlevent:old",
                "clock_seq": 1,
            },
            "artifact_context_packet": {"artifact_refs": ["artifact:old.md"]},
            "explicit_inputs": {"candidate_ref": "artifact:old-fallback.md"},
        },
    }

    packet = build_revision_packet_from_review(
        state=state,
        review_stage_id="review",
        target_stage_id="draft",
        event={"artifact_refs": ["artifact:review.md"], "diagnostics": {"verdict": "revise"}},
        accepted=False,
    )

    assert packet["source_dispatch_event_id"] == "tlevent:new"
    assert packet["source_clock_seq"] == 9
    assert packet["previous_candidate_artifact_refs"] == ["artifact:new.md"]


def test_scheduler_scope_prefers_node_work_order_dispatch_context() -> None:
    state = {
        "node_work_order": {
            "dispatch_context": {
                "dependency_scope_key": "scope:new",
                "scope_path": ["run", "phase.new"],
            }
        },
        "stage_execution_request": {
            "dispatch_context": {
                "dependency_scope_key": "scope:old",
                "scope_path": ["run", "phase.old"],
            }
        },
    }

    assert _active_scope_key_for_scheduler(state) == "scope:new"


def test_standard_input_package_materials_render_to_model_visible_text() -> None:
    message = _render_standard_input_package_for_model(
        {
            "standard_input_package": {
                "input_items": [
                    {
                        "input_key": "outline_review",
                        "source_node_id": "outline_review",
                        "content_type": "artifact_text",
                        "usage_instruction": "作为大纲审核结论使用。",
                        "content_preview": "预览不应覆盖全文。",
                        "metadata": {"text": "# 大纲审核\n\n裁决：通过。伏笔与卷级推进成立。"},
                    }
                ]
            }
        }
    )

    assert "标准节点输入材料" in message
    assert "outline_review" in message
    assert "裁决：通过" in message
    assert "伏笔与卷级推进成立" in message
    assert "<read_file" not in message
    assert "tool_call" not in message


def test_standard_input_package_renderer_skips_internal_protocol_inputs() -> None:
    message = _render_standard_input_package_for_model(
        {
            "standard_input_package": {
                "input_items": [
                    {
                        "input_key": "importing_stage_execution_request",
                        "content_type": "runtime_protocol",
                        "content_preview": "父级调度协议不应进入模型。",
                        "metadata": {"text": "parent protocol leak"},
                    },
                    {
                        "input_key": "runtime_protocol.trace",
                        "content_type": "runtime_protocol",
                        "content_preview": "runtime protocol trace leak",
                    },
                    {
                        "input_key": "user_goal",
                        "content_type": "text",
                        "content_preview": "启动导入模块并完成世界观设计。",
                    },
                ]
            }
        }
    )

    assert "标准节点输入材料" in message
    assert "user_goal" in message
    assert "启动导入模块并完成世界观设计" in message
    assert "importing_stage_execution_request" not in message
    assert "parent protocol leak" not in message
    assert "runtime_protocol.trace" not in message


def test_loop_derived_fields_use_runtime_batch_size_for_ten_chapter_request() -> None:
    result = _apply_loop_derived_fields(
        {
            "volume_index": 1,
            "chapter_index": 1,
            "chapters_per_round": 10,
            "chapter_target_words": 2000,
            "current_words": 0,
            "target_words": 1000000,
            "volume_current_words": 0,
            "volume_target_words": 200000,
        },
        _chapter_loop_derived_fields_for_test(),
    )

    assert result["batch_start_index"] == 1
    assert result["batch_end_index"] == 10
    assert result["batch_index"] == 1
    assert result["batch_chapter_numbers"] == list(range(1, 11))
    assert result["batch_chapter_list"].endswith("第10章")
    assert result["batch_target_words"] == 20000

    next_result = _apply_loop_derived_fields(
        {
            **result,
            "chapter_index": 11,
        },
        _chapter_loop_derived_fields_for_test(),
        preserve_existing_batch_scope=False,
    )

    assert next_result["batch_start_index"] == 11
    assert next_result["batch_end_index"] == 20
    assert next_result["batch_index"] == 2
    assert next_result["batch_chapter_numbers"] == list(range(11, 21))


_Trace = TraceReaderStub


def _loop_graph_from_derived_fields(derived_fields: list[dict], *, graph_id: str = "graph.test.loop_refresh") -> TaskGraphDefinition:
    nodes = (
        TaskGraphNodeDefinition(
            node_id="chapter_outline",
            node_type="agent",
            title="Chapter Outline",
            task_id="task.test.chapter_outline",
            agent_id="agent:0",
            phase_id="phase.chapter_loop",
            sequence_index=1,
        ),
        TaskGraphNodeDefinition(
            node_id="chapter_draft",
            node_type="agent",
            title="Chapter Draft",
            task_id="task.test.chapter_draft",
            agent_id="agent:0",
            phase_id="phase.chapter_loop",
            sequence_index=2,
        ),
    )
    return TaskGraphDefinition(
        graph_id=graph_id,
        title="Loop Refresh",
        task_family="test",
        graph_kind="multi_agent",
        nodes=nodes,
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="chapter_outline_draft",
                source_node_id="chapter_outline",
                target_node_id="chapter_draft",
                edge_type="structured_handoff",
            ),
        ),
        default_protocol_id="protocol.test.loop_refresh",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        metadata={
            "topology_template_id": "topology.test.loop_refresh",
            "stage_contracts": [
                {"stage_id": "chapter_outline", "task_ref": "task.test.chapter_outline", "node_id": "chapter_outline"},
                {"stage_id": "chapter_draft", "task_ref": "task.test.chapter_draft", "node_id": "chapter_draft"},
            ],
            "runtime_loop_policy": {
                "enabled": True,
                "initial_inputs": {
                    "volume_index": 1,
                    "chapter_index": 1,
                    "chapter_target_words": 2000,
                    "current_words": 0,
                    "target_words": 1000000,
                    "volume_current_words": 0,
                    "volume_target_words": 200000,
                },
                "derived_fields": derived_fields,
            },
        },
        publish_state="published",
        enabled=True,
    )


class _RefreshGraphRegistry:
    def __init__(self, live_graph: TaskGraphDefinition) -> None:
        self.live_graph = live_graph
        self.topology = TopologyTemplate(
            template_id="topology.test.loop_refresh",
            title="Loop Refresh Topology",
            nodes=tuple(node.to_dict() for node in live_graph.nodes),
            edges=tuple(edge.to_dict() for edge in live_graph.edges),
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.loop_refresh",
            title="Loop Refresh Protocol",
            message_types=("message/send",),
            enabled=True,
        )
        self.tasks = (
            SpecificTaskRecord(task_id="task.test.chapter_outline", task_title="Chapter Outline", task_family="test"),
            SpecificTaskRecord(task_id="task.test.chapter_draft", task_title="Chapter Draft", task_family="test"),
        )

    def get_task_graph(self, graph_id: str):
        return self.live_graph if graph_id == self.live_graph.graph_id else None

    def derive_coordination_task_view_from_graph(self, graph):
        nodes = tuple(node.to_dict() for node in graph.nodes)
        return CoordinationTaskDefinition(
            graph_id=graph.graph_id,
            title=graph.title,
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.loop_refresh",
            graph_nodes=nodes,
            graph_edges=tuple(edge.to_dict() for edge in graph.edges),
            metadata=dict(graph.metadata or {}),
        )

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


def _task_graph_from_coordination(coordination: CoordinationTaskDefinition, *, protocol_id: str = "") -> TaskGraphDefinition:
    nodes = tuple(
        TaskGraphNodeDefinition(
            node_id=str(node.get("node_id") or ""),
            node_type=str(node.get("node_type") or "agent"),
            title=str(node.get("title") or node.get("node_id") or ""),
            task_id=str(node.get("task_id") or ""),
            agent_id=str(node.get("agent_id") or ""),
            runtime_lane=str(node.get("runtime_lane") or node.get("lane") or ""),
            work_posture=str(node.get("role") or ""),
            phase_id=str(node.get("phase_id") or ""),
            sequence_index=int(node.get("sequence_index") or 0),
            metadata={key: value for key, value in dict(node).items() if key not in {"node_id", "node_type", "title", "task_id", "agent_id", "runtime_lane", "lane", "role", "phase_id", "sequence_index"}},
        )
        for node in coordination.graph_nodes
    )
    edges = tuple(
        TaskGraphEdgeDefinition(
            edge_id=str(edge.get("edge_id") or edge.get("id") or ""),
            source_node_id=str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or ""),
            target_node_id=str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or ""),
            edge_type=str(edge.get("edge_type") or edge.get("mode") or "handoff"),
            payload_contract_id=str(edge.get("payload_contract_id") or edge.get("contract_id") or ""),
            artifact_ref_policy=dict(edge.get("artifact_ref_policy") or {}),
            metadata=dict(edge.get("metadata") or {}),
        )
        for edge in coordination.graph_edges
    )
    return TaskGraphDefinition(
        graph_id=coordination.graph_id,
        title=coordination.title,
        task_family=coordination.task_family,
        graph_kind="multi_agent",
        nodes=nodes,
        edges=edges,
        default_protocol_id=protocol_id,
        runtime_policy={"coordinator_agent_id": coordination.coordinator_agent_id},
        metadata=dict(coordination.metadata or {}),
        publish_state="published",
        enabled=True,
    )


class _Registry:
    def __init__(self) -> None:
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.bootstrap",
            title="测试协调任务",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.bootstrap",
            subtask_refs=("task.test.project", "task.test.novel_bible"),
            graph_nodes=(
                {"node_id": "project_scope", "agent_id": "agent:0", "task_id": "task.test.project", "role": "coordinator"},
                {"node_id": "novel_bible", "agent_id": "agent:1", "task_id": "task.test.novel_bible", "role": "writer"},
            ),
            graph_edges=({"from": "project_scope", "to": "novel_bible", "mode": "structured_handoff"},),
            metadata={
                "stage_sequence": [
                    {"stage_id": "project_scope", "task_ref": "task.test.project"},
                    {"stage_id": "novel_bible", "task_ref": "task.test.novel_bible"},
                ],
                "stage_contracts": [
                    {
                        "stage_id": "project_scope",
                        "task_ref": "task.test.project",
                        "node_id": "project_scope",
                        "output_mappings": [{"output_key": "project_spec_ref", "required": True}],
                    },
                    {
                        "stage_id": "novel_bible",
                        "task_ref": "task.test.novel_bible",
                        "node_id": "novel_bible",
                        "required_inputs": ["project_spec_ref"],
                        "input_bindings": [
                            {
                                "source": "stage_output",
                                "source_stage_id": "project_scope",
                                "output_key": "project_spec_ref",
                                "input_key": "project_spec_ref",
                                "required": True,
                            }
                        ],
                    },
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.bootstrap",
            title="测试拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.a2a",
            title="官方 A2A 测试协议",
            message_types=("message/send", "message/stream", "task/status", "task/artifact"),
            payload_contracts=("contract.payload.project_spec",),
            enabled=True,
            metadata={"a2a_protocol": "official", "protocol_locked": True},
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return []


class _WorkingMemoryRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.source",
                task_title="Source",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
            SpecificTaskRecord(
                task_id="task.test.target",
                task_title="Target",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.working_memory_runtime",
            title="工作记忆运行时测试",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.working_memory_runtime",
            graph_nodes=(
                {"node_id": "source", "agent_id": "agent:0", "task_id": "task.test.source", "role": "writer"},
                {"node_id": "target", "agent_id": "agent:0", "task_id": "task.test.target", "role": "writer"},
            ),
            graph_edges=({"edge_id": "source_target", "from": "source", "to": "target", "mode": "structured_handoff"},),
            metadata={
                "stage_contracts": [
                    {"stage_id": "source", "task_ref": "task.test.source", "node_id": "source"},
                    {"stage_id": "target", "task_ref": "task.test.target", "node_id": "target"},
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.working_memory_runtime",
            title="工作记忆运行时拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.working_memory_runtime",
            title="工作记忆 A2A 测试协议",
            message_types=("message/send",),
            payload_contracts=("contract.agent_output.markdown",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return TaskGraphDefinition(
            graph_id=self.coordination.graph_id,
            title=self.coordination.title,
            task_family=self.coordination.task_family,
            graph_kind="multi_agent",
            nodes=(
                TaskGraphNodeDefinition(
                    node_id="source",
                    node_type="agent",
                    title="Source",
                    task_id="task.test.source",
                    agent_id="agent:0",
                    work_posture="writer",
                    memory_writeback_policy={
                        "writable_kinds": ["approved_world"],
                        "writable_scopes": ["graph_scope"],
                        "default_status": "accepted",
                        "default_visibility": "shared_in_graph",
                    },
                ),
                TaskGraphNodeDefinition(
                    node_id="target",
                    node_type="agent",
                    title="Target",
                    task_id="task.test.target",
                    agent_id="agent:0",
                    work_posture="writer",
                    memory_read_policy={
                        "readable_kinds": ["approved_world"],
                        "readable_scopes": ["graph_scope"],
                        "max_items": 3,
                    },
                ),
            ),
            edges=(
                TaskGraphEdgeDefinition(
                    edge_id="source_target",
                    source_node_id="source",
                    target_node_id="target",
                    edge_type="structured_handoff",
                    working_memory_handoff_policy={"carry_kinds": ["approved_world"], "carry_scopes": ["graph_scope"]},
                ),
            ),
            default_protocol_id=self.protocol.protocol_id,
            working_memory_policy={"memory_sharing_policy": "explicit_graph_scope"},
            runtime_policy={"coordinator_agent_id": self.coordination.coordinator_agent_id},
            publish_state="published",
            enabled=True,
        )

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


class _FormalMemoryRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.world_author",
                task_title="World Author",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
            SpecificTaskRecord(
                task_id="task.test.memory_repo",
                task_title="Memory Repo",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
            SpecificTaskRecord(
                task_id="task.test.world_review",
                task_title="World Review",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.formal_memory_runtime",
            title="正式记忆库运行时测试",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.formal_memory_runtime",
            graph_nodes=(
                {"node_id": "world_author", "agent_id": "agent:0", "task_id": "task.test.world_author", "role": "writer"},
                {"node_id": "world_review", "agent_id": "agent:0", "task_id": "task.test.world_review", "role": "reviewer"},
                {
                    "node_id": "memory.world",
                    "node_type": "memory_repository",
                    "agent_id": "agent:0",
                    "task_id": "task.test.memory_repo",
                    "role": "resource",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.world",
                            "collections": [
                                {"collection_id": "world", "record_kinds": ["world_bible"]},
                            ],
                        }
                    },
                },
            ),
            graph_edges=(
                {
                    "edge_id": "edge.world_author.world_review",
                    "from": "world_author",
                    "to": "world_review",
                    "mode": "structured_handoff",
                },
                {
                    "edge_id": "edge.world_author.memory.world",
                    "from": "world_author",
                    "to": "memory.world",
                    "mode": "memory_write_candidate",
                    "metadata": {
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "source_output_key": "world_candidate",
                    },
                },
                {
                    "edge_id": "edge.world_review.memory.world",
                    "from": "world_review",
                    "to": "memory.world",
                    "mode": "memory_commit",
                    "metadata": {
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "candidate_ref_key": "reviewed_candidate_ref",
                        "verdict_key": "verdict",
                        "required_verdict": "pass",
                        "commit_visibility_policy": {"visible_after": "next_clock"},
                    },
                },
            ),
            metadata={
                "stage_contracts": [
                    {
                        "stage_id": "world_author",
                        "task_ref": "task.test.world_author",
                        "node_id": "world_author",
                    },
                    {
                        "stage_id": "world_review",
                        "task_ref": "task.test.world_review",
                        "node_id": "world_review",
                    },
                    {
                        "stage_id": "memory.world",
                        "task_ref": "task.test.memory_repo",
                        "node_id": "memory.world",
                    },
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.formal_memory_runtime",
            title="正式记忆库拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.formal_memory_runtime",
            title="正式记忆库 A2A 测试协议",
            message_types=("message/send",),
            payload_contracts=("contract.agent_output.markdown",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return TaskGraphDefinition(
            graph_id=self.coordination.graph_id,
            title=self.coordination.title,
            task_family=self.coordination.task_family,
            graph_kind="multi_agent",
            nodes=(
                TaskGraphNodeDefinition(
                    node_id="world_author",
                    node_type="agent",
                    title="World Author",
                    task_id="task.test.world_author",
                    agent_id="agent:0",
                    work_posture="writer",
                    memory_writeback_policy={
                        "writable_kinds": ["world_bible"],
                        "writable_scopes": ["graph_scope"],
                        "default_status": "draft",
                        "default_visibility": "shared_in_graph",
                    },
                ),
                TaskGraphNodeDefinition(
                    node_id="world_review",
                    node_type="agent",
                    title="World Review",
                    task_id="task.test.world_review",
                    agent_id="agent:0",
                    work_posture="reviewer",
                    review_gate_policy={"commit_working_memory": True},
                ),
                TaskGraphNodeDefinition(
                    node_id="memory.world",
                    node_type="memory_repository",
                    title="World Memory",
                    task_id="task.test.memory_repo",
                    agent_id="agent:0",
                    work_posture="resource",
                    metadata={
                        "memory_repository": {
                            "repository_id": "memory.world",
                            "collections": [
                                {"collection_id": "world", "record_kinds": ["world_bible"]},
                            ],
                        }
                    },
                ),
            ),
            edges=(
                TaskGraphEdgeDefinition(
                    edge_id="edge.world_author.world_review",
                    source_node_id="world_author",
                    target_node_id="world_review",
                    edge_type="structured_handoff",
                ),
                TaskGraphEdgeDefinition(
                    edge_id="edge.world_author.memory.world",
                    source_node_id="world_author",
                    target_node_id="memory.world",
                    edge_type="memory_write_candidate",
                    payload_contract_id="contract.memory.write_candidate",
                    metadata={
                        "repository": "memory.world",
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "source_output_key": "world_candidate",
                    },
                ),
                TaskGraphEdgeDefinition(
                    edge_id="edge.world_review.memory.world",
                    source_node_id="world_review",
                    target_node_id="memory.world",
                    edge_type="memory_commit",
                    payload_contract_id="contract.memory.commit",
                    metadata={
                        "repository": "memory.world",
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "candidate_ref_key": "reviewed_candidate_ref",
                        "verdict_key": "verdict",
                        "required_verdict": "pass",
                        "commit_visibility_policy": {"visible_after": "next_clock"},
                    },
                ),
            ),
            default_protocol_id=self.protocol.protocol_id,
            runtime_policy={"coordinator_agent_id": self.coordination.coordinator_agent_id},
            publish_state="published",
            enabled=True,
        )

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


class _ApprovalSourceFormalMemoryRegistry(_FormalMemoryRegistry):
    def __init__(self) -> None:
        super().__init__()
        edges = []
        resource_edges = []
        for edge in self.coordination.graph_edges:
            payload = dict(edge)
            if payload.get("edge_id") == "edge.world_review.memory.world":
                metadata = dict(payload.get("metadata") or {})
                metadata.pop("candidate_ref_key", None)
                metadata.pop("verdict_key", None)
                metadata.pop("required_verdict", None)
                metadata["approval_source_node_id"] = "world_author"
                metadata["approval_policy"] = "approved_upstream_review_gate"
                payload["metadata"] = metadata
            if payload.get("edge_id") in {"edge.world_author.memory.world", "edge.world_review.memory.world"}:
                resource_edges.append(payload)
            edges.append(payload)
        metadata = {**dict(self.coordination.metadata or {}), "memory_edges": resource_edges}
        self.coordination = replace(self.coordination, graph_edges=tuple(edges), metadata=metadata)
        self.topology = TopologyTemplate(
            template_id=self.topology.template_id,
            title=self.topology.title,
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        graph = super().get_task_graph(graph_id)
        if graph is None:
            return None
        edges = []
        resource_edges = []
        for edge in graph.edges:
            if edge.edge_id != "edge.world_review.memory.world":
                if edge.edge_id == "edge.world_author.memory.world":
                    resource_edges.append(edge)
                edges.append(edge)
                continue
            metadata = dict(edge.metadata or {})
            metadata.pop("candidate_ref_key", None)
            metadata.pop("verdict_key", None)
            metadata.pop("required_verdict", None)
            metadata["approval_source_node_id"] = "world_author"
            metadata["approval_policy"] = "approved_upstream_review_gate"
            edges.append(
                TaskGraphEdgeDefinition(
                    edge_id=edge.edge_id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    edge_type=edge.edge_type,
                    payload_contract_id=edge.payload_contract_id,
                    metadata=metadata,
                )
            )
            resource_edges.append(edges[-1])
        return TaskGraphDefinition(
            graph_id=graph.graph_id,
            title=graph.title,
            task_family=graph.task_family,
            graph_kind=graph.graph_kind,
            nodes=graph.nodes,
            edges=tuple(edges),
            default_protocol_id=graph.default_protocol_id,
            runtime_policy=graph.runtime_policy,
            metadata={"memory_edges": [edge.to_dict() for edge in resource_edges]},
            publish_state=graph.publish_state,
            enabled=graph.enabled,
        )


class _ArtifactContextRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.outline",
                task_title="Outline",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.test.outline",
            ),
            SpecificTaskRecord(
                task_id="task.test.writer",
                task_title="Writer",
                task_family="test",
                input_contract_id="contract.test.outline",
                output_contract_id="contract.test.draft",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.artifact_context",
            title="产物交接测试",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.artifact_context",
            graph_nodes=(
                {"node_id": "outline", "agent_id": "agent:0", "task_id": "task.test.outline", "role": "writer"},
                {
                    "node_id": "writer",
                    "agent_id": "agent:0",
                    "task_id": "task.test.writer",
                    "role": "writer",
                    "artifact_context_policy": {
                        "items": [
                            {
                                "source": "input_key",
                                "input_key": "contract.test.outline:artifact_refs",
                                "label": "当前批次细纲",
                                "max_chars": 20000,
                            }
                        ],
                        "default_max_chars": 20000,
                        "max_items": 1,
                    },
                },
            ),
            graph_edges=(
                {
                    "edge_id": "outline_writer",
                    "from": "outline",
                    "to": "writer",
                    "contract_id": "contract.test.outline",
                    "artifact_ref_policy": {
                        "target_input_key": "contract.test.outline:artifact_refs",
                        "max_chars": 20000,
                    },
                    "metadata": {"on_missing": "block"},
                },
            ),
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.artifact_context",
            title="产物交接拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.artifact_context",
            title="产物交接协议",
            message_types=("message/send",),
            payload_contracts=("contract.test.outline", "contract.test.draft"),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


def test_stage_message_expands_current_artifact_handoff(tmp_path) -> None:
    outline_path = tmp_path / "outline.md"
    outline_path.write_text("# 当前细纲\n\n第1章：主角入泽。", encoding="utf-8")
    registry = _ArtifactContextRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:artifact-context",
        task_run_id="taskrun:outline",
        graph_ref="graph.test.artifact_context",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.artifact_context",
        communication_protocol_id="protocol.test.artifact_context",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "outline"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:artifact-context",
            task_run_id="taskrun:outline",
            stage_id="outline",
            task_ref="task.test.outline",
            task_result_ref="taskresult:outline",
            artifact_refs=(f"artifact:{outline_path.as_posix()}",),
            accepted=True,
        ),
    )

    assert result.stage_execution_request is not None
    assert "当前批次细纲" in result.stage_execution_request.message
    assert "第1章：主角入泽" in result.stage_execution_request.message


def test_langgraph_coordination_runtime_injects_working_memory_context(tmp_path) -> None:
    registry = _WorkingMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:wm",
        task_run_id="taskrun:wm",
        graph_ref="graph.test.working_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.working_memory_runtime",
        communication_protocol_id="protocol.test.working_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "source"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:wm",
            task_run_id="taskrun:source",
            stage_id="source",
            task_ref="task.test.source",
            task_result_ref="taskresult:source",
            accepted=True,
            diagnostics={
                "working_memory_candidates": [
                    {
                        "title": "世界观基线",
                        "summary": "大泽少年是洪荒时代的主角。",
                        "kind": "approved_world",
                        "scope": "graph_scope",
                        "status": "accepted",
                        "visibility": "shared_in_graph",
                    }
                ]
            },
        ),
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "target"
    assert result.stage_execution_request.working_memory_refs
    assembly = result.stage_execution_request.runtime_assembly
    assert assembly["diagnostics"]["working_memory_enabled"] is True
    assert assembly["diagnostics"]["working_memory_required_count"] == 1
    section_ids = [item["section_id"] for item in assembly["context_sections"]]
    assert "working_memory.required" in section_ids
    operations = list(result.state.get("working_memory_operations") or [])
    assert operations[0]["operation"] == "memory_write"
    assert operations[0]["candidate_count"] == 1
    assert operations[1]["operation"] == "memory_handoff"
    assert operations[1]["status"] == "committed"


def test_formal_memory_write_edge_uses_source_output_key(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:formal-memory",
        task_run_id="taskrun:formal-memory",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "world_candidate": {
                    "canonical_text": "天地初辟，万族争道。",
                    "summary": "世界观候选正文",
                },
                "unrelated_output": {
                    "canonical_text": "这段内容不应进入世界观记忆库。",
                },
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )

    assert result.state["stage_results"]["world_author"]["outputs"]["world_candidate"]["canonical_text"] == "天地初辟，万族争道。"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["candidate"]},
        version_selector={"mode": "all"},
        node_run_id="taskrun:formal-memory:assert",
        edge_id="assert",
    )

    assert len(versions) == 1
    assert versions[0].record_kind == "world_bible"
    assert versions[0].canonical_text == "天地初辟，万族争道。"
    assert versions[0].summary == "世界观候选正文"
    assert "unrelated_output" not in versions[0].payload


def test_formal_memory_write_edge_blocks_missing_source_output_key(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:formal-memory-missing",
        task_run_id="taskrun:formal-memory-missing",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-missing",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "unrelated_output": {
                    "canonical_text": "没有 world_candidate 字段。",
                },
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )

    operations = list(result.state.get("working_memory_operations") or [])
    write_operation = next(item for item in operations if item.get("operation") == "memory_write")
    assert write_operation["created_working_memory_refs"] == []
    assert write_operation["formal_memory_errors"][0]["error"] == "source_output_key_not_found"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["candidate"]},
        version_selector={"mode": "all"},
        node_run_id="taskrun:formal-memory-missing:assert",
        edge_id="assert",
    )
    assert versions == ()


def test_formal_memory_commit_edge_uses_candidate_ref_and_verdict(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:formal-memory-commit",
        task_run_id="taskrun:formal-memory-commit",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    source_result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-commit",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "world_candidate": {
                    "canonical_text": "洪荒世界观候选。",
                    "summary": "待审核世界观",
                }
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )
    candidate_ref = source_result.state["stage_results"]["world_author"]["working_memory_refs"][0]
    assert source_result.stage_execution_request is not None
    assert source_result.stage_execution_request.stage_id == "world_review"

    review_result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-commit",
            task_run_id="taskrun:world-review",
            stage_id="world_review",
            task_ref="task.test.world_review",
            task_result_ref="taskresult:world-review",
            accepted=True,
        ),
        current_task_result={
            "final_outputs": {
                "reviewed_candidate_ref": candidate_ref,
                "verdict": "pass",
            }
        },
    )

    operations = list(review_result.state.get("working_memory_operations") or [])
    commit_operation = [item for item in operations if item.get("operation") == "memory_commit"][-1]
    assert commit_operation["formal_memory_acknowledgements"][0]["status"] == "committed"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["committed"]},
        version_selector={"mode": "latest_committed_before_clock"},
        clock_seq=999,
        node_run_id="taskrun:formal-memory-commit:assert",
        edge_id="assert",
    )
    assert len(versions) == 1
    assert versions[0].canonical_text == "洪荒世界观候选。"


def test_formal_memory_commit_edge_uses_approval_source_candidate_refs(tmp_path) -> None:
    registry = _ApprovalSourceFormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:formal-memory-approval-source",
        task_run_id="taskrun:formal-memory-approval-source",
        graph_ref="graph.test.formal_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.formal_memory_runtime",
        communication_protocol_id="protocol.test.formal_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "world_author"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    source_result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-approval-source",
            task_run_id="taskrun:world-author",
            stage_id="world_author",
            task_ref="task.test.world_author",
            task_result_ref="taskresult:world-author",
            accepted=True,
            artifact_refs=("artifact:world_candidate.md",),
        ),
        current_task_result={
            "final_outputs": {
                "world_candidate": {
                    "canonical_text": "由批准来源提交的候选。",
                    "summary": "批准来源候选",
                }
            },
            "output_refs": ["artifact:world_candidate.md"],
        },
    )
    candidate_ref = source_result.state["stage_results"]["world_author"]["working_memory_refs"][0]

    review_result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:formal-memory-approval-source",
            task_run_id="taskrun:world-review",
            stage_id="world_review",
            task_ref="task.test.world_review",
            task_result_ref="taskresult:world-review",
            accepted=True,
        ),
        current_task_result={"final_outputs": {"verdict": "pass"}},
    )

    operations = list(review_result.state.get("working_memory_operations") or [])
    commit_operation = [item for item in operations if item.get("operation") == "memory_commit"][-1]
    assert commit_operation["accepted_working_memory_refs"] == [candidate_ref]
    assert commit_operation["formal_memory_acknowledgements"][0]["status"] == "committed"
    versions, _read_log = runtime.formal_memory.store.select_versions(
        repository_id="memory.world",
        collection_id="world",
        selector={"record_key": "world_bible.current", "status_filter": ["committed"]},
        version_selector={"mode": "latest_committed_before_clock"},
        clock_seq=999,
        node_run_id="taskrun:formal-memory-approval-source:assert",
        edge_id="assert",
    )
    assert len(versions) == 1
    assert versions[0].canonical_text == "由批准来源提交的候选。"


def test_formal_memory_read_edge_does_not_fallback_to_working_memory(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    graph_spec = {
        "graph_id": "graph.test.formal_memory_read",
        "graph_ref": "graph.test.formal_memory_read",
        "nodes": [
            {
                "node_id": "memory.world",
                "node_type": "memory_repository",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.world",
                        "collections": [{"collection_id": "world", "record_kinds": ["world_bible"]}],
                    }
                },
            },
            {"node_id": "chapter_writer", "node_type": "agent"},
        ],
        "edges": [
            {
                "edge_id": "edge.memory.chapter.world",
                "source_node_id": "memory.world",
                "target_node_id": "chapter_writer",
                "mode": "memory_read",
                "metadata": {
                    "collection": "world",
                    "selector": {
                        "collection": "world",
                        "record_key": "world_bible.current",
                        "record_kind": "world_bible",
                        "status_filter": ["committed"],
                    },
                    "version_selector": {"mode": "latest_committed_before_clock"},
                    "on_missing": "block",
                },
            }
        ],
    }
    runtime.formal_memory.sync_graph_spec(graph_id="graph.test.formal_memory_read", graph_spec=graph_spec)
    candidate, _write_txn = runtime.formal_memory.write_candidate_from_edge(
        edge={
            "edge_id": "edge.world_author.memory.world",
            "repository": "memory.world",
            "collection": "world",
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
        },
        candidate={
            "kind": "world_bible",
            "summary": "正式世界观",
            "payload": {"canonical_text": "正式仓库中的世界观。"},
        },
        task_run_id="taskrun:formal-read",
        node_run_id="taskrun:formal-read:world_author",
        source_node_id="world_author",
        source_clock_seq=0,
    )
    runtime.formal_memory.commit_from_edge(
        edge={
            "edge_id": "edge.world_review.memory.world",
            "repository": "memory.world",
            "collection": "world",
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
            "commit_visibility_policy": {"visible_after": "same_clock"},
        },
        candidate_version_id=candidate.version_id,
        node_run_id="taskrun:formal-read:world_review",
        source_clock_seq=0,
    )
    legacy_item = runtime.working_memory.create_item(
        task_run_id="taskrun:formal-read",
        graph_id="graph.test.formal_memory_read",
        owner_node_id="legacy_seed",
        node_run_id="taskrun:formal-read:legacy_seed",
        kind="world_bible",
        scope="graph_scope",
        status="accepted",
        visibility="shared_in_graph",
        title="旧工作记忆世界观",
        summary="这条旧工作记忆不应该通过正式 memory_read 边进入上下文。",
        metadata={
            "formal_memory": {
                "repository_id": "memory.world",
                "collection_id": "world",
                "record_key": "world_bible.current",
                "record_kind": "world_bible",
                "commit_state": "committed",
            }
        },
    )

    context = runtime._select_stage_working_memory_context(
        state={
            "coordination_run_id": "coordrun:formal-read",
            "root_task_run_id": "taskrun:formal-read",
            "diagnostics": {"coordination_graph_spec": graph_spec},
            "retry_counts": {},
        },
        stage_id="chapter_writer",
        node_id="chapter_writer",
        contract={"stage_id": "chapter_writer", "node_id": "chapter_writer", "agent_id": "agent:writer"},
    )

    assert context["diagnostics"]["formal_memory_primary"] is True
    assert context["diagnostics"]["working_memory_legacy_read_enabled"] is False
    assert dict(context["working_memory.required"])["item_count"] == 0
    assert legacy_item.work_memory_id not in context.get("required_refs", [])
    assert context["formal_memory.required_records"][0]["canonical_text"] == "正式仓库中的世界观。"
    assert context["formal_memory.required_records"][0]["version_id"] == candidate.version_id


def test_formal_memory_missing_required_blocks_stage_dispatch(tmp_path) -> None:
    registry = _FormalMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    graph_spec = {
        "graph_id": "graph.test.formal_memory_block",
        "graph_ref": "graph.test.formal_memory_block",
        "nodes": [
            {
                "node_id": "memory.world",
                "node_type": "memory_repository",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.world",
                        "collections": [
                            {
                                "collection_id": "world",
                                "content_requirement": {
                                    "canonical_text_required": True,
                                    "artifact_ref_only_allowed": False,
                                },
                            }
                        ],
                    }
                },
            },
            {"node_id": "chapter_writer", "node_type": "agent"},
        ],
        "edges": [
            {
                "edge_id": "edge.memory.chapter.world",
                "source_node_id": "memory.world",
                "target_node_id": "chapter_writer",
                "mode": "memory_read",
                "metadata": {
                    "collection": "world",
                    "selector": {"record_key": "world_bible.current", "status_filter": ["committed"]},
                    "content_requirement": {
                        "canonical_text_required": True,
                        "artifact_ref_only_allowed": False,
                    },
                    "on_missing": "block",
                },
            }
        ],
    }
    state = {
        "coordination_run_id": "coordrun:formal-memory-block",
        "root_task_run_id": "taskrun:formal-memory-block",
        "active_stage_id": "chapter_writer",
        "active_task_ref": "task.test.world_review",
        "stage_contracts": {
            "chapter_writer": {
                "stage_id": "chapter_writer",
                "node_id": "chapter_writer",
                "task_ref": "task.test.world_review",
                "agent_id": "agent:0",
            }
        },
        "pending_inputs": {},
        "current_event": {},
        "stage_results": {},
        "retry_counts": {},
        "stage_order": ["chapter_writer"],
        "node_statuses": {},
        "diagnostics": {"coordination_graph_spec": graph_spec},
    }

    result = runtime._stage_execute(state)

    assert result["terminal_status"] == "blocked"
    assert result["node_statuses"]["chapter_writer"] == "blocked"
    assert result["diagnostics"]["stage_blocked_by_memory"] is True
    assert result["missing_required_memory_records"][0]["collection"] == "world"
    assert "node_execution_request" not in result


def test_refs_only_auto_candidate_requires_explicit_memory_edge_contract() -> None:
    assert _memory_edge_allows_refs_only_auto_candidate(
        {
            "edge_id": "edge.write.artifacts",
            "collection": "draft_refs",
            "content_requirement": {
                "canonical_text_required": False,
                "artifact_ref_only_allowed": True,
            },
        }
    ) is True
    assert _memory_edge_allows_refs_only_auto_candidate(
        {
            "edge_id": "edge.write.legacy_named_refs",
            "collection": "draft_refs",
            "content_requirement": {},
            "materialization_policy": {},
        }
    ) is False
    assert _memory_edge_allows_refs_only_auto_candidate(
        {
            "edge_id": "edge.write.canon",
            "collection": "canon",
            "content_requirement": {
                "canonical_text_required": True,
                "artifact_ref_only_allowed": False,
            },
            "materialization_policy": {"canonical_text_mode": "refs_only"},
        }
    ) is False


def test_langgraph_coordination_runtime_commits_working_memory_decisions(tmp_path) -> None:
    registry = _WorkingMemoryRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:wm-commit",
        task_run_id="taskrun:wm-commit",
        graph_ref="graph.test.working_memory_runtime",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.working_memory_runtime",
        communication_protocol_id="protocol.test.working_memory_runtime",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "source"}},
    )
    state_index.upsert_coordination_run(coordination_run)
    item = runtime.working_memory.create_item(
        task_run_id="taskrun:wm-commit",
        graph_id="graph.test.working_memory_runtime",
        owner_node_id="source",
        node_run_id="taskrun:wm-commit:source",
        kind="approved_world",
        scope="graph_scope",
        status="proposed",
        visibility="shared_in_graph",
        title="候选设定",
        summary="候选设定等待审核。",
    )

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:wm-commit",
            task_run_id="taskrun:source",
            stage_id="source",
            task_ref="task.test.source",
            task_result_ref="taskresult:source",
            accepted=True,
            diagnostics={"working_memory_commit": {"accepted_working_memory_refs": [item.work_memory_id]}},
        ),
    )

    committed = runtime.working_memory.get_item(item.work_memory_id)
    assert committed is not None
    assert committed.status == "accepted"
    operations = list(result.state.get("working_memory_operations") or [])
    commit_operations = [item for item in operations if item.get("operation") == "memory_commit"]
    assert commit_operations
    assert commit_operations[-1]["accepted_working_memory_refs"] == [item.work_memory_id]
    sequence_indexes = [int(item.get("sequence_index") or 0) for item in operations if isinstance(item, dict)]
    assert sequence_indexes == sorted(sequence_indexes)


def test_langgraph_coordination_runtime_advances_by_stage_contract(tmp_path) -> None:
    registry = _Registry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:project",
            session_id="session",
            task_id="taskinst:project",
            task_contract_ref="task.dev.light_web_game",
            status="completed",
            updated_at=10,
        )
    )
    trace = _Trace({"taskrun:project": {"task_result": {"output_refs": ["ref:project_spec"]}}})
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=trace,
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:test",
        task_run_id="taskrun:project",
        graph_ref="graph.test.bootstrap",
        coordinator_agent_id="agent:20",
        topology_template_id="topology.test.bootstrap",
        communication_protocol_id="protocol.test.a2a",
        status="running",
        diagnostics={
            "coordination_flow": {
                "current_stage_id": "project_scope",
                "stages": [
                    {"stage_id": "project_scope", "status": "running", "task_ref": "task.test.project"},
                    {"stage_id": "novel_bible", "status": "pending", "task_ref": "task.test.novel_bible"},
                ],
            }
        },
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:test",
            task_run_id="taskrun:project",
            stage_id="project_scope",
            task_ref="task.test.project",
            task_result_ref="taskresult:project",
            artifact_refs=("ref:project_spec",),
            accepted=True,
        ),
        inherited_inputs={},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "novel_bible"
    assert result.stage_execution_request.task_ref == "task.test.novel_bible"
    assert result.stage_execution_request.explicit_inputs["project_spec_ref"] == "ref:project_spec"
    assert result.stage_execution_request.a2a_payload["protocol_version"] == "0.3.0"
    assert result.stage_execution_request.a2a_payload["transport"] == "JSONRPC"
    assert result.stage_execution_request.a2a_payload["message"]["kind"] == "message"
    assert result.stage_execution_request.a2a_payload["message"]["metadata"]["target_stage_id"] == "novel_bible"
    assert result.stage_execution_request.dispatch_context["dispatch_event_id"].startswith("tlevent:")
    assert result.stage_execution_request.dispatch_context["clock_seq"] > 0
    assert result.stage_execution_request.artifact_context_packet["artifact_refs"] == ["ref:project_spec"]
    assert result.state["timeline"]["current_clock_seq"] >= result.stage_execution_request.dispatch_context["clock_seq"]
    work_order = result.node_work_order
    assert work_order["authority"] == "runtime.agent_assembly.work_order"
    assert work_order["work_kind"] == "node"
    assert work_order["work_order_id"] == result.stage_execution_request.request_id
    assert work_order["task_ref"] == result.stage_execution_request.task_ref
    assert work_order["agent_id"] == result.stage_execution_request.agent_id
    assert work_order["agent_profile_id"] == result.stage_execution_request.agent_profile_id
    assert work_order["input_package"]["package_id"] == result.stage_execution_request.standard_input_package["package_id"]
    assert work_order["graph_state"]["contract_manifest_ref"] == result.state["contract_manifest"]["manifest_id"]
    assert work_order["graph_state"]["authority"] == "task_graph.node_work_order_graph_state_snapshot"
    assert validate_work_order(WorkOrder.from_dict(work_order)).passed
    continuation = result.continuation_payload(session_id="session")
    assert continuation["runtime_control"]["node_work_order"]["work_order_id"] == work_order["work_order_id"]
    assert continuation["runtime_control"]["stage_execution_request"]["a2a_payload"]["message"]["metadata"]["target_task_ref"] == "task.test.novel_bible"
    assert "a2a_payload" not in continuation["current_turn_context"]
    assert "node_work_order" not in continuation["current_turn_context"]
    assert continuation["task_selection"]["selected_task_id"] == work_order["task_ref"]
    assert result.stage_execution_request.runtime_assembly["authority"] == "orchestration.node_runtime_assembly"
    assert result.stage_execution_request.a2a_payload["message"]["metadata"]["runtime_assembly_ref"]
    scheduler_state = dict(dict(result.state["diagnostics"]).get("task_graph_scheduler_state") or {})
    assert scheduler_state["authority"] == "task_system.task_graph_scheduler_state"
    assert scheduler_state["mode"] == "active"
    updated = state_index.get_coordination_run("coordrun:test")
    assert updated is not None
    flow = dict(updated.diagnostics.get("coordination_flow") or {})
    assert flow["current_stage_id"] == "novel_bible"
    assert "langgraph_runtime_state" not in updated.diagnostics
    runtime_state = runtime.checkpoints.get_state(thread_id="coordrun:test")
    assert dict(runtime_state["diagnostics"])["contract_manifest_ref"].startswith("contract-manifest:coordination:")
    assert "project_scope" in runtime_state["completed_nodes"]
    handoffs = state_index.list_coordination_handoffs("coordrun:test")
    assert len(handoffs) == 1
    assert handoffs[0].diagnostics["source_stage_id"] == "project_scope"
    assert handoffs[0].diagnostics["target_stage_id"] == "novel_bible"


class _DiamondRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(
                task_id="task.test.a",
                task_title="A",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.b",
                task_title="B",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.c",
                task_title="C",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.artifact_refs.bundle",
            ),
            SpecificTaskRecord(
                task_id="task.test.d",
                task_title="D",
                task_family="test",
                input_contract_id="contract.user_request.basic",
                output_contract_id="contract.agent_output.markdown",
            ),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.diamond",
            title="测试汇聚拓扑",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.diamond",
            graph_nodes=(
                {"node_id": "a", "agent_id": "agent:0", "task_id": "task.test.a", "role": "coordinator", "runtime_lane": "task_dispatch"},
                {"node_id": "b", "agent_id": "agent:0", "task_id": "task.test.b", "role": "participant", "runtime_lane": "task_dispatch"},
                {"node_id": "c", "agent_id": "agent:0", "task_id": "task.test.c", "role": "participant", "runtime_lane": "task_dispatch"},
                {"node_id": "d", "agent_id": "agent:0", "task_id": "task.test.d", "role": "acceptance", "runtime_lane": "final_integration"},
            ),
            graph_edges=(
                {"edge_id": "a_b", "from": "a", "to": "b", "contract_id": "contract.artifact_refs.bundle"},
                {"edge_id": "a_c", "from": "a", "to": "c", "contract_id": "contract.artifact_refs.bundle"},
                {"edge_id": "b_d", "from": "b", "to": "d", "contract_id": "contract.artifact_refs.bundle"},
                {"edge_id": "c_d", "from": "c", "to": "d", "contract_id": "contract.artifact_refs.bundle"},
            ),
            metadata={
                "stage_contracts": [
                    {
                        "stage_id": "a",
                        "task_ref": "task.test.a",
                        "node_id": "a",
                        "output_mappings": [{"output_key": "a_ref", "required": True}],
                        "on_failure": "retry_once",
                        "retry_policy": {"retry_limit": 1},
                    },
                    {
                        "stage_id": "b",
                        "task_ref": "task.test.b",
                        "node_id": "b",
                        "required_inputs": ["a_ref"],
                        "input_bindings": [{"source": "stage_output", "output_key": "a_ref", "input_key": "a_ref", "required": True}],
                        "output_mappings": [{"output_key": "b_ref", "required": True}],
                    },
                    {
                        "stage_id": "c",
                        "task_ref": "task.test.c",
                        "node_id": "c",
                        "required_inputs": ["a_ref"],
                        "input_bindings": [{"source": "stage_output", "output_key": "a_ref", "input_key": "a_ref", "required": True}],
                        "output_mappings": [{"output_key": "c_ref", "required": True}],
                    },
                    {
                        "stage_id": "d",
                        "task_ref": "task.test.d",
                        "node_id": "d",
                        "required_inputs": ["b_ref", "c_ref"],
                        "input_bindings": [
                            {"source": "stage_output", "output_key": "b_ref", "input_key": "b_ref", "required": True},
                            {"source": "stage_output", "output_key": "c_ref", "input_key": "c_ref", "required": True},
                        ],
                    },
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.diamond",
            title="测试汇聚拓扑",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.diamond",
            title="官方 A2A 汇聚测试协议",
            message_types=("message/send", "message/stream", "task/status", "task/artifact"),
            payload_contracts=("contract.artifact_refs.bundle",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


def _diamond_runtime(tmp_path):
    registry = _DiamondRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:diamond",
        task_run_id="taskrun:a",
        graph_ref="graph.test.diamond",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.diamond",
        communication_protocol_id="protocol.test.diamond",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "a"}},
    )
    state_index.upsert_coordination_run(coordination_run)
    TaskContractRegistry(tmp_path)
    return runtime, state_index, coordination_run


def test_langgraph_coordination_runtime_routes_ready_nodes_before_join(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)

    result_a = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )
    assert result_a.stage_execution_request is not None
    assert result_a.stage_execution_request.stage_id == "b"
    assert result_a.state["running_nodes"] == ["b"]
    assert result_a.state["ready_nodes"] == ["c"]
    assert result_a.state["blocked_nodes"] == ["d"]

    result_b = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:b",
            stage_id="b",
            task_ref="task.test.b",
            task_result_ref="taskresult:b",
            artifact_refs=("ref:b",),
            accepted=True,
        ),
    )
    assert result_b.stage_execution_request is not None
    assert result_b.stage_execution_request.stage_id == "c"
    assert "d" in result_b.state["blocked_nodes"]

    result_c = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:c",
            stage_id="c",
            task_ref="task.test.c",
            task_result_ref="taskresult:c",
            artifact_refs=("ref:c",),
            accepted=True,
        ),
    )
    assert result_c.stage_execution_request is not None
    assert result_c.stage_execution_request.stage_id == "d"
    assert result_c.stage_execution_request.runtime_assembly["node_id"] == "d"
    assert result_c.stage_execution_request.a2a_payload["message"]["metadata"]["contract_manifest_ref"]
    assert len(result_c.stage_execution_request.a2a_payload["message"]["parts"][-1]["data"]["handoff_packets"]) == 2


def test_langgraph_coordination_runtime_ignores_stale_dispatch_result(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)
    first = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )
    assert first.stage_execution_request is not None
    active_request_id = first.stage_execution_request.request_id

    stale = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:b:old",
            stage_id="b",
            task_ref="task.test.b",
            task_result_ref="taskresult:b:old",
            artifact_refs=("ref:b:old",),
            accepted=True,
            request_id="nodeexec:stale",
            dispatch_event_id="tlevent:stale",
        ),
    )

    assert stale.state["stage_execution_request"]["request_id"] == active_request_id
    assert "b" not in stale.state.get("stage_results", {})
    assert stale.state["stale_stage_results"]
    assert stale.state["diagnostics"]["last_stale_result_reason"] == "request_id_does_not_match_active_request"

    updated = state_index.get_coordination_run("coordrun:diamond")
    assert updated is not None
    assert "langgraph_runtime_state" not in updated.diagnostics
    runtime_state = runtime.checkpoints.get_state(thread_id="coordrun:diamond")
    assert runtime_state["completed_nodes"] == ["a"]
    assert runtime_state["running_nodes"] == ["b"]
    assert runtime_state["ready_nodes"] == ["c"]


def test_langgraph_coordination_runtime_accepts_result_by_node_work_order_not_stale_stage_request(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)
    first = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )
    active_work_order = dict(first.state["node_work_order"])
    assert active_work_order["stage_id"] == "b"
    assert active_work_order["work_order_id"] == first.stage_execution_request.request_id

    corrupted_state = dict(runtime.checkpoints.get_state(thread_id="coordrun:diamond"))
    corrupted_state["stage_execution_request"] = {
        **dict(corrupted_state["stage_execution_request"]),
        "request_id": "nodeexec:old-stage-request",
        "dispatch_context": {
            **dict(corrupted_state["stage_execution_request"].get("dispatch_context") or {}),
            "dispatch_event_id": "tlevent:old-stage-request",
        },
    }
    runtime.checkpoints.put_state(
        thread_id="coordrun:diamond",
        state=corrupted_state,
        metadata={"event": "test_corrupt_stage_request"},
    )

    accepted = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:b",
            stage_id="b",
            task_ref="task.test.b",
            task_result_ref="taskresult:b",
            artifact_refs=("ref:b",),
            accepted=True,
            request_id=active_work_order["work_order_id"],
            dispatch_event_id=active_work_order["dispatch_context"]["dispatch_event_id"],
        ),
    )

    assert "b" in accepted.state["stage_results"]
    assert accepted.state["stage_results"]["b"]["accepted"] is True
    assert accepted.state["stage_results"]["b"]["timeline_result_record"]["request_id"] == active_work_order["work_order_id"]
    assert accepted.state["diagnostics"].get("last_stale_result_reason") in {None, ""}


def test_langgraph_coordination_runtime_initialize_does_not_redispatch_when_work_order_exists(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)
    first = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )
    active_work_order_id = first.state["node_work_order"]["work_order_id"]
    state = dict(runtime.checkpoints.get_state(thread_id="coordrun:diamond"))
    state["stage_execution_request"] = {}
    state["node_execution_request"] = {}
    runtime.checkpoints.put_state(
        thread_id="coordrun:diamond",
        state=state,
        metadata={"event": "test_keep_work_order_only"},
    )

    initialized = runtime.initialize(coordination_run=coordination_run)

    assert initialized.node_work_order["work_order_id"] == active_work_order_id
    assert initialized.stage_execution_request is not None
    assert initialized.stage_execution_request.request_id == active_work_order_id
    assert initialized.stage_execution_request.stage_id == "b"


def test_langgraph_coordination_runtime_rewinds_stage_and_invalidates_downstream(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)

    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:b",
            stage_id="b",
            task_ref="task.test.b",
            task_result_ref="taskresult:b",
            artifact_refs=("artifact:bad-b.md",),
            accepted=True,
        ),
    )
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:c",
            stage_id="c",
            task_ref="task.test.c",
            task_result_ref="taskresult:c",
            artifact_refs=("artifact:bad-c.md",),
            accepted=True,
        ),
    )
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:d",
            stage_id="d",
            task_ref="task.test.d",
            task_result_ref="taskresult:d",
            artifact_refs=("artifact:bad-d.md",),
            accepted=True,
        ),
    )

    result = runtime.rewind_from_stage(
        coordination_run_id="coordrun:diamond",
        stage_id="b",
        reason="bad_branch_output",
        inherited_inputs={"artifact_root": str(tmp_path), "b_ref": "artifact:stale-b.md"},
        refresh_graph_spec=True,
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "b"
    assert result.stage_execution_request.explicit_inputs["a_ref"] == "ref:a"
    assert result.stage_execution_request.explicit_inputs.get("b_ref") is None
    assert result.diagnostics["invalidated_stage_ids"] == ["b", "d"]
    assert result.state["node_statuses"]["a"] == "completed"
    assert result.state["node_statuses"]["b"] == "running"
    assert result.state["node_statuses"]["c"] == "completed"
    assert result.state["node_statuses"]["d"] == "pending"
    assert set(result.state["stage_results"].keys()) == {"a", "c"}
    assert "taskresult:b" not in result.state["latest_stage_result_records"].values()
    assert "taskresult:d" not in result.state["latest_stage_result_records"].values()
    assert all(item["stage_id"] not in {"b", "d"} for item in result.state["timeline_result_records"])
    assert all(item["stage_id"] not in {"b", "d"} for item in result.state["artifact_refs"])
    assert "b" not in result.state["contract_status"]["acceptance_results"]
    assert result.state["contract_status"]["node_status"]["b"]["status"] == "pending_rewind"
    assert result.state["contract_status"]["node_status"]["d"]["status"] == "invalidated_downstream"
    assert "force_replay" in result.state["pending_inputs"]
    assert "artifact:stale-b.md" not in str(result.state["pending_inputs"])

    updated = state_index.get_coordination_run("coordrun:diamond")
    assert updated is not None
    flow = dict(updated.diagnostics.get("coordination_flow") or {})
    assert flow["current_stage_id"] == "b"


def test_langgraph_coordination_runtime_rewind_ignores_feedback_edges(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    runtime.initialize(coordination_run=coordination_run)
    state = runtime.checkpoints.get_state(thread_id="coordrun:diamond")
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    graph_spec["edges"] = [
        *list(graph_spec.get("edges") or []),
        {
            "edge_id": "d_b_feedback",
            "source_node_id": "d",
            "target_node_id": "b",
            "mode": "review_feedback",
            "metadata": {"dependency_role": "feedback"},
        },
    ]
    state["diagnostics"] = {**dict(state.get("diagnostics") or {}), "coordination_graph_spec": graph_spec}
    runtime.checkpoints.put_state(thread_id="coordrun:diamond", state=state, metadata={"event": "test_feedback_edge"})

    result = runtime.rewind_from_stage(
        coordination_run_id="coordrun:diamond",
        stage_id="d",
        reason="bad_final_output",
        refresh_graph_spec=False,
    )

    assert result.diagnostics["invalidated_stage_ids"] == ["d"]


class _SequencedRegistry:
    def __init__(self) -> None:
        self.tasks = (
            SpecificTaskRecord(task_id="task.test.a", task_title="A", task_family="test"),
            SpecificTaskRecord(task_id="task.test.b", task_title="B", task_family="test"),
            SpecificTaskRecord(task_id="task.test.c", task_title="C", task_family="test"),
        )
        self.coordination = CoordinationTaskDefinition(
            graph_id="graph.test.sequence",
            title="测试显式时序",
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family="test",
            topology_template_id="topology.test.sequence",
            graph_nodes=(
                {"node_id": "a", "agent_id": "agent:0", "task_id": "task.test.a", "role": "coordinator", "phase_id": "phase.write", "sequence_index": 1},
                {"node_id": "b", "agent_id": "agent:0", "task_id": "task.test.b", "role": "participant", "phase_id": "phase.write", "sequence_index": 2},
                {"node_id": "c", "agent_id": "agent:0", "task_id": "task.test.c", "role": "participant", "phase_id": "phase.write", "sequence_index": 3},
            ),
            graph_edges=(
                {"edge_id": "a_b", "from": "a", "to": "b", "mode": "structured_handoff"},
                {"edge_id": "b_c", "from": "b", "to": "c", "mode": "structured_handoff"},
            ),
            metadata={
                "stage_contracts": [
                    {"stage_id": "a", "task_ref": "task.test.a", "node_id": "a"},
                    {"stage_id": "b", "task_ref": "task.test.b", "node_id": "b"},
                    {"stage_id": "c", "task_ref": "task.test.c", "node_id": "c"},
                ],
            },
        )
        self.topology = TopologyTemplate(
            template_id="topology.test.sequence",
            title="测试显式时序",
            nodes=self.coordination.graph_nodes,
            edges=self.coordination.graph_edges,
            enabled=True,
        )
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.sequence",
            title="官方 A2A 时序测试协议",
            message_types=("message/send",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        if graph_id != self.coordination.graph_id:
            return None
        return _task_graph_from_coordination(self.coordination, protocol_id=self.protocol.protocol_id)

    def derive_coordination_task_view_from_graph(self, graph):
        return self.coordination if graph.graph_id == self.coordination.graph_id else None

    def get_topology_template(self, template_id: str):
        return self.topology if template_id == self.topology.template_id else None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return list(self.tasks)


def test_langgraph_coordination_runtime_uses_explicit_edges_for_sequence(tmp_path) -> None:
    registry = _SequencedRegistry()
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:sequence",
        task_run_id="taskrun:sequence",
        graph_ref="graph.test.sequence",
        coordinator_agent_id="agent:0",
        topology_template_id="topology.test.sequence",
        communication_protocol_id="protocol.test.sequence",
        status="running",
        diagnostics={"coordination_flow": {"current_stage_id": "a"}},
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:sequence",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=True,
        ),
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "b"
    assert result.state["running_nodes"] == ["b"]
    assert result.state["ready_nodes"] == []
    assert result.state["blocked_nodes"] == ["c"]
    scheduler_state = dict(dict(result.state["diagnostics"]).get("task_graph_scheduler_state") or {})
    c_state = next(item for item in scheduler_state["node_states"] if item["node_id"] == "c")
    assert "upstream:b" in c_state["blocked_reasons"]
    assert not any(str(reason).startswith("sequence_wait") for reason in c_state["blocked_reasons"])
    assert scheduler_state["diagnostics"]["legacy_timing_gate_enabled"] is False


def test_langgraph_coordination_runtime_blocks_when_required_input_missing(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=(),
            accepted=True,
        ),
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "blocked"
    assert result.state["missing_required_inputs"] == ["a_ref"]
    assert result.state["contract_status"]["node_status"]["b"]["missing_required_inputs"] == ["a_ref"]


def test_langgraph_coordination_runtime_retries_failed_stage_when_policy_allows(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "a"
    assert result.state["retry_counts"]["a"] == 1
    assert result.state["retry_stage_id"] == ""
    assert "retry_stage_id" not in result.state["diagnostics"]
    assert result.state["running_nodes"] == ["a"]


def test_langgraph_coordination_runtime_commit_identity_is_authoritative_state(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["artifact_policy"] = {
        "commit_identity_policy": {
            "mode": "input_keys_and_artifact_refs",
            "include_result_artifact_refs": True,
        }
    }

    accepted = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )

    committed = list(accepted.state["committed_stage_identities"])
    assert committed
    assert "committed_stage_identities" not in accepted.state["diagnostics"]
    assert accepted.state["diagnostics"]["last_committed_stage_identity"] == committed[0]

    duplicate = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a:duplicate",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a:duplicate",
            artifact_refs=("ref:a",),
            accepted=True,
        ),
    )

    assert duplicate.state["terminal_status"] == "duplicate_commit_ignored"
    assert duplicate.state["committed_stage_identities"] == committed
    assert "committed_stage_identities" not in duplicate.state["diagnostics"]
    assert duplicate.state["diagnostics"]["last_duplicate_commit_identity"] == committed[0]


def test_failed_file_artifact_stage_does_not_satisfy_required_outputs(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["artifact_policy"] = {"enabled": True}
    stage_contracts[0]["output_mappings"] = [
        {"output_key": "contract.test.a:artifact_refs", "required": True}
    ]

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("artifact:debug/run_report_task-test-a.md",),
            accepted=False,
        ),
    )

    record = result.state["timeline_result_records"][-1]
    assert record["status"] == "rejected"
    assert record["validation_result"]["required_artifact_outputs_satisfied"] is False
    assert record["validation_result"]["requires_file_artifact_refs"] is True


def test_langgraph_coordination_runtime_enters_human_gate_when_policy_requires(tmp_path) -> None:
    runtime, state_index, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "waiting_for_human"
    assert result.state["waiting_nodes"] == ["a"]
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "human_gate"
    updated = state_index.get_coordination_run("coordrun:diamond")
    assert updated is not None
    assert "langgraph_runtime_state" not in updated.diagnostics
    runtime_state = runtime.checkpoints.get_state(thread_id="coordrun:diamond")
    assert runtime_state["human_gate"]["status"] == "waiting"


def test_langgraph_coordination_runtime_does_not_block_human_gate_when_auto_continue(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    runtime.task_flow_registry.coordination.metadata["continuation_policy"] = {"human_gate_mode": "auto_continue"}
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}

    result = runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "failed"
    assert result.state["failed_nodes"] == ["a", "b", "c", "d"]
    assert result.state["node_statuses"] == {"a": "failed", "b": "failed", "c": "failed", "d": "failed"}
    scheduler_state = dict(dict(result.state["diagnostics"]).get("task_graph_scheduler_state") or {})
    assert scheduler_state["diagnostics"]["failure_propagated_node_ids"] == ["b", "c", "d"]
    assert result.state["human_gate"] == {}


def test_langgraph_coordination_runtime_preserves_node_human_gate_policy_in_contract(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    node = runtime.task_flow_registry.coordination.graph_nodes[0]
    node["human_gate_policy"] = {"enabled": True, "mode": "non_blocking", "trigger_verdict": "human_review_required"}
    contracts = runtime._contracts_for_run(
        coordination_run=coordination_run,
        coordination_task=runtime.task_flow_registry.coordination,
    )

    assert contracts[0].human_gate_policy == {
        "enabled": True,
        "mode": "non_blocking",
        "trigger_verdict": "human_review_required",
    }


def test_langgraph_coordination_runtime_human_gate_approve_routes_next(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            artifact_refs=("ref:a",),
            accepted=False,
        ),
    )

    result = runtime.resume_human_gate(
        coordination_run_id="coordrun:diamond",
        resume_payload={"decision": "approve", "task_result_ref": "taskresult:a:approved", "artifact_refs": ["ref:a"]},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id in {"b", "c"}
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "satisfied"
    assert result.state["completed_nodes"] == ["a"]


def test_langgraph_coordination_runtime_human_gate_retry_routes_same_stage(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    result = runtime.resume_human_gate(
        coordination_run_id="coordrun:diamond",
        resume_payload={"decision": "retry"},
    )

    assert result.stage_execution_request is not None
    assert result.stage_execution_request.stage_id == "a"
    assert result.state["retry_counts"]["a"] == 1
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "pending_retry"


def test_langgraph_coordination_runtime_human_gate_reject_fails_closed(tmp_path) -> None:
    runtime, _, coordination_run = _diamond_runtime(tmp_path)
    stage_contracts = runtime.task_flow_registry.coordination.metadata["stage_contracts"]
    stage_contracts[0]["on_failure"] = "human_gate"
    stage_contracts[0]["retry_policy"] = {"retry_limit": 0}
    runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=NodeResultReadyEvent(
            event_type="task_result_ready",
            coordination_run_id="coordrun:diamond",
            task_run_id="taskrun:a",
            stage_id="a",
            task_ref="task.test.a",
            task_result_ref="taskresult:a",
            accepted=False,
        ),
    )

    result = runtime.resume_human_gate(
        coordination_run_id="coordrun:diamond",
        resume_payload={"decision": "reject"},
    )

    assert result.stage_execution_request is None
    assert result.state["terminal_status"] == "failed"
    assert result.state["failed_nodes"] == ["a", "b", "c", "d"]
    scheduler_state = dict(dict(result.state["diagnostics"]).get("task_graph_scheduler_state") or {})
    assert scheduler_state["diagnostics"]["failure_propagated_node_ids"] == ["b", "c", "d"]
    assert result.state["contract_status"]["node_status"]["a"]["status"] == "failed"


def test_parse_stage_contracts_derives_from_graph_nodes_when_metadata_is_missing() -> None:
    coordination_task = CoordinationTaskDefinition(
        graph_id="graph.test.derived_contracts",
        title="测试派生契约",
        coordination_mode="pipeline",
        coordinator_agent_id="agent:0",
        task_family="test",
        topology_template_id="topology.test.derived_contracts",
        graph_nodes=(
            {
                "node_id": "a",
                "agent_id": "agent:a",
                "task_id": "task.test.a",
                "output_contract_id": "contract.test.a",
            },
            {
                "node_id": "b",
                "agent_id": "agent:b",
                "task_id": "task.test.b",
                "input_contract_id": "contract.test.a",
                "output_contract_id": "contract.test.b",
            },
        ),
        graph_edges=(
            {
                "edge_id": "a_b",
                "from": "a",
                "to": "b",
                "payload_contract_id": "contract.test.a",
            },
        ),
    )

    contracts = parse_stage_contracts(coordination_task=coordination_task, topology_nodes=list(coordination_task.graph_nodes), topology_edges=list(coordination_task.graph_edges))

    assert [contract.stage_id for contract in contracts] == ["a", "b"]
    assert contracts[1].required_inputs == ("contract.test.a:artifact_refs",)
    assert contracts[1].input_bindings[0]["source_stage_id"] == "a"
    assert contracts[1].output_mappings[0]["output_key"] == "contract.test.b:artifact_refs"


def test_langgraph_runtime_emits_graph_module_stage_request(tmp_path) -> None:
    importing_graph = TaskGraphDefinition(
        graph_id="graph.test.importing_graph_module_runtime",
        title="导入方图模块运行",
        graph_kind="coordination",
        default_protocol_id="protocol.test.graph_module",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        metadata={
            "timeline_blocks": [
                {
                    "block_id": "block.child",
                    "block_type": "imported_graph",
                    "title": "导入模块阶段",
                    "phase_id": "phase.child",
                    "linked_graph_id": "graph.test.imported_graph_module_runtime",
                    "version_ref": "v1",
                    "handoff_contract_id": "contract.test.graph_module.handoff",
                    "input_port_id": "input.child",
                    "output_port_id": "output.child",
                }
            ],
        },
        publish_state="published",
        enabled=True,
    )
    registry = _GraphModuleRegistry(importing_graph)
    state_index = RuntimeStateIndex(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    runtime = LangGraphCoordinationRuntime(
        root_dir=tmp_path,
        state_index=state_index,
        event_log=event_log,
        task_flow_registry=registry,
        trace_reader=_Trace({}),
    )
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:graph-module",
        task_run_id="taskrun:graph-module",
        graph_ref=importing_graph.graph_id,
        coordinator_agent_id="agent:0",
        communication_protocol_id="protocol.test.graph_module",
        status="running",
    )
    state_index.upsert_coordination_run(coordination_run)

    result = runtime.initialize(
        coordination_run=coordination_run,
        inherited_inputs={"user_goal": "运行导入模块"},
    )

    assert result.stage_execution_request is not None
    request = result.stage_execution_request
    assert request.stage_id == "graph_module.block.child"
    assert request.executor_type == "graph_module"
    assert request.task_ref == "task_graph.node.graph.test.importing_graph_module_runtime.graph_module.block.child"
    assert request.executor_binding["selected_executor"] == "graph_module"
    handle = request.runtime_assembly["graph_module_runtime_handle"]
    assert handle["authority"] == "runtime.subruntime.graph_module_runtime_handle"
    assert handle["linked_graph_id"] == "graph.test.imported_graph_module_runtime"
    assert handle["graph_module_runtime_plan_id"] == "graph_module_runtime.block.child"
    assert handle["importing_coordination_run_id"] == "coordrun:graph-module"
    assert handle["handoff_contract_id"] == "contract.test.graph_module.handoff"
    assert handle["explicit_inputs"]["user_goal"] == "运行导入模块"
    assert handle["executor_policy"]["auto_start_imported_initial_stage"] is True
    work_order = result.node_work_order
    assert work_order["work_kind"] == "subruntime"
    assert work_order["executor_type"] == "subruntime"
    assert work_order["subruntime_kind"] == "graph_module"
    assert work_order["task_ref"] == request.task_ref
    continuation = result.continuation_payload(session_id="session")
    assert continuation["runtime_control"]["node_work_order"]["subruntime_kind"] == "graph_module"
    assert continuation["runtime_control"]["node_work_order"]["work_kind"] == "subruntime"
    assert continuation["next_stage_id"] == "graph_module.block.child"
    assert "node_work_order" not in continuation["current_turn_context"]


class _GraphModuleRegistry:
    def __init__(self, graph: TaskGraphDefinition) -> None:
        self.graph = graph
        self.protocol = TaskCommunicationProtocol(
            protocol_id="protocol.test.graph_module",
            title="GraphModule Protocol",
            message_types=("message/send",),
            enabled=True,
        )

    def get_task_graph(self, graph_id: str):
        return self.graph if graph_id == self.graph.graph_id else None

    def derive_coordination_task_view_from_graph(self, graph):
        from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec

        runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph, communication_protocol=self.protocol)
        return CoordinationTaskDefinition(
            graph_id=graph.graph_id,
            title=graph.title,
            coordination_mode="pipeline",
            coordinator_agent_id="agent:0",
            task_family=graph.task_family,
            graph_nodes=tuple(node.to_dict() for node in runtime_spec.nodes),
            graph_edges=tuple(edge.to_dict() for edge in runtime_spec.edges),
            communication_modes=("handoff",),
            enabled=True,
            metadata=dict(graph.metadata or {}),
        )

    def get_topology_template(self, template_id: str):
        return None

    def get_task_communication_protocol(self, protocol_id: str):
        return self.protocol if not protocol_id or protocol_id == self.protocol.protocol_id else None

    def list_specific_task_records(self):
        return []
