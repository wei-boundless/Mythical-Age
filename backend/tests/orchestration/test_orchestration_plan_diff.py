from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.diff import actual_from_runtime_event, build_plan_actual_diff, update_actual_trace


def test_plan_actual_diff_reports_matched_core_fields() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "rag",
            "execution_kind": "agent",
        },
        "executions": [
            {
                "execution_id": "main",
                "tool_name": "",
                "worker_route": "",
                "execution_kind": "agent",
            }
        ],
    }

    actual = actual_from_runtime_event(
        {
            "type": "done",
            "answer_source": "model",
        },
        plan=plan,
    )
    diff = build_plan_actual_diff(plan, actual=actual)

    assert diff["status"] == "matched"
    assert {item["field"]: item["status"] for item in diff["items"]}["topology.route"] == "matched"


def test_plan_actual_diff_reports_mismatch() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "tool",
            "execution_kind": "direct_tool",
        },
        "executions": [
            {
                "execution_id": "main",
                "tool_name": "get_weather",
                "worker_route": "",
                "execution_kind": "direct_tool",
            }
        ],
    }

    diff = build_plan_actual_diff(
        plan,
        actual={
            "status": "done",
            "execution_mode": "single_execution",
            "route": "rag",
            "execution_kind": "agent",
            "tool_name": "",
            "worker_route": "",
        },
    )

    assert diff["status"] == "mismatch"
    mismatch_fields = {item["field"] for item in diff["items"] if item["status"] == "mismatch"}
    assert {"topology.route", "topology.execution_kind", "execution.tool_name"} <= mismatch_fields


def test_plan_actual_diff_reports_unexpected_actual_tool() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "rag",
            "execution_kind": "agent",
        },
        "executions": [{"execution_id": "main", "tool_name": "", "worker_route": ""}],
    }

    diff = build_plan_actual_diff(
        plan,
        actual={
            "status": "done",
            "execution_mode": "single_execution",
            "route": "rag",
            "execution_kind": "agent",
            "tool_name": "get_weather",
            "worker_route": "",
        },
    )

    assert diff["status"] == "mismatch"
    tool_item = next(item for item in diff["items"] if item["field"] == "execution.tool_name")
    assert tool_item["reason"] == "unexpected_actual"


def test_agent_internal_tool_call_does_not_change_top_level_execution() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "agent",
            "execution_kind": "agent",
        },
        "executions": [{"execution_id": "main", "execution_kind": "agent", "tool_name": "", "worker_route": ""}],
    }
    trace: dict[str, object] = {}
    trace = update_actual_trace(
        trace,
        {
            "type": "tool_start",
            "execution_id": "main",
            "execution_kind": "agent",
            "tool": "read_file",
            "input": "workspace/tmp.txt",
        },
    )
    trace = update_actual_trace(
        trace,
        {
            "type": "tool_end",
            "execution_id": "main",
            "execution_kind": "agent",
            "tool": "read_file",
            "output": "Read failed: file does not exist.",
        },
    )

    actual = actual_from_runtime_event({"type": "done", "answer_source": "segment.visible_text"}, plan=plan, actual_trace=trace)
    diff = build_plan_actual_diff(plan, actual=actual)

    assert diff["status"] == "matched"
    assert actual["tool_name"] == ""
    assert actual["executions"][0]["execution_kind"] == "agent"
    assert actual["agent_tool_calls"][-1]["tool_name"] == "read_file"


def test_actual_trace_captures_context_and_prompt_manifest() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "agent",
            "execution_kind": "agent",
        },
        "context_policy": {"mode": "runtime"},
        "prompt_policy": {"mode": "runtime"},
        "executions": [{"execution_id": "main", "execution_kind": "agent"}],
    }
    trace: dict[str, object] = {}
    trace = update_actual_trace(trace, {"type": "context_management", "context": {"pressure_level": "normal"}})
    trace = update_actual_trace(
        trace,
        {
            "type": "prompt_manifest",
            "prompt_manifest": {"prompt_id": "prompt-a", "total_sections": 4, "total_chars": 120},
        },
    )

    actual = actual_from_runtime_event({"type": "done", "answer_source": "model"}, plan=plan, actual_trace=trace)
    diff = build_plan_actual_diff(plan, actual=actual)
    by_field = {item["field"]: item for item in diff["items"]}

    assert diff["status"] == "matched"
    assert by_field["context_policy.context_management"]["status"] == "matched"
    assert by_field["prompt_policy.prompt_manifest"]["status"] == "matched"
    assert diff["actual"]["prompt_manifest_id"] == "prompt-a"


def test_direct_tool_contract_denial_is_reported_as_mismatch() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "tool",
            "execution_kind": "direct_tool",
        },
        "context_policy": {"mode": "runtime"},
        "executions": [
            {
                "execution_id": "main",
                "tool_name": "pdf_analysis",
                "worker_route": "",
                "execution_kind": "direct_tool",
            }
        ],
    }
    trace: dict[str, object] = {}
    trace = update_actual_trace(trace, {"type": "context_management", "context": {"pressure_level": "normal"}})
    actual = actual_from_runtime_event(
        {
            "type": "done",
            "answer_source": "tool_contract_gate",
            "execution_protocol": "direct_tool",
            "contract": {
                "tool_name": "pdf_analysis",
                "action": "deny",
                "reason": "missing_required_binding",
            },
        },
        plan=plan,
        actual_trace=trace,
    )
    diff = build_plan_actual_diff(plan, actual=actual)
    by_field = {item["field"]: item for item in diff["items"]}

    assert diff["status"] == "mismatch"
    assert by_field["contract.tool_name"]["status"] == "matched"
    assert by_field["contract.runtime_block"]["status"] == "mismatch"
    assert by_field["contract.runtime_block"]["reason"] == "missing_required_binding"


def test_contract_preview_expected_action_is_compared() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "single_execution",
            "route": "tool",
            "execution_kind": "direct_tool",
        },
        "executions": [
            {
                "execution_id": "main",
                "tool_name": "pdf_analysis",
                "worker_route": "",
                "execution_kind": "direct_tool",
            }
        ],
        "decisions": [
            {
                "node_id": "contract-policy",
                "outputs": {
                    "contract_previews": [
                        {
                            "tool_name": "pdf_analysis",
                            "contract_action": "allow",
                            "contract_reason": "contract_satisfied",
                            "permission_allowed": True,
                        }
                    ]
                },
            }
        ],
    }
    actual = actual_from_runtime_event(
        {
            "type": "done",
            "execution_protocol": "direct_tool",
            "contract": {
                "tool_name": "pdf_analysis",
                "action": "allow",
                "reason": "contract_satisfied",
            },
        },
        plan=plan,
    )
    diff = build_plan_actual_diff(plan, actual=actual)
    by_field = {item["field"]: item for item in diff["items"]}

    assert diff["status"] == "matched"
    assert by_field["contract.action"]["status"] == "matched"


def test_multi_execution_diff_matches_bundle_items_by_execution_id() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "bundle_execution",
            "route": "bundle",
            "execution_kind": "agent",
            "branch_count": 2,
        },
        "executions": [
            {"execution_id": "bundle-a-item-1", "execution_kind": "worker", "worker_route": "pdf", "tool_name": ""},
            {"execution_id": "bundle-a-item-2", "execution_kind": "worker", "worker_route": "structured_data", "tool_name": ""},
        ],
    }
    trace: dict[str, object] = {}
    trace = update_actual_trace(
        trace,
        {
            "type": "subtask_start",
            "index": 1,
            "task_id": "task-1",
            "bundle_item": {"bundle_id": "bundle-a", "bundle_item_id": "bundle-a-item-1"},
        },
    )
    trace = update_actual_trace(
        trace,
        {
            "type": "worker_start",
            "task_id": "task-1",
            "worker": "pdf",
            "bundle_item": {"bundle_id": "bundle-a", "bundle_item_id": "bundle-a-item-1"},
        },
    )
    trace = update_actual_trace(
        trace,
        {
            "type": "subtask_start",
            "index": 2,
            "task_id": "task-2",
            "bundle_item": {"bundle_id": "bundle-a", "bundle_item_id": "bundle-a-item-2"},
        },
    )
    trace = update_actual_trace(
        trace,
        {
            "type": "worker_start",
            "task_id": "task-2",
            "worker": "structured_data",
            "bundle_item": {"bundle_id": "bundle-a", "bundle_item_id": "bundle-a-item-2"},
        },
    )

    actual = actual_from_runtime_event({"type": "done", "answer_source": "answer_assembler"}, plan=plan, actual_trace=trace)
    diff = build_plan_actual_diff(plan, actual=actual)
    by_field = {item["field"]: item for item in diff["items"]}

    assert diff["status"] == "matched"
    assert by_field["executions.count"]["status"] == "matched"
    assert by_field["executions[0].worker_route"]["status"] == "matched"
    assert by_field["executions[1].worker_route"]["status"] == "matched"
    assert diff["actual"]["executions"][1]["execution_id"] == "bundle-a-item-2"


def test_multi_execution_diff_reports_missing_branch() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "explicit_fanout",
            "route": "compound",
            "execution_kind": "agent",
            "branch_count": 2,
        },
        "executions": [
            {"execution_id": "subtask-1", "execution_kind": "agent", "worker_route": "", "tool_name": ""},
            {"execution_id": "subtask-2", "execution_kind": "agent", "worker_route": "", "tool_name": ""},
        ],
    }
    trace: dict[str, object] = {}
    trace = update_actual_trace(
        trace,
        {
            "type": "subtask_start",
            "index": 1,
            "task_id": "task-1",
            "subtask_plan": {"subtask_plan_id": "subtask-1"},
        },
    )

    actual = actual_from_runtime_event({"type": "done", "answer_source": "answer_assembler"}, plan=plan, actual_trace=trace)
    diff = build_plan_actual_diff(plan, actual=actual)

    assert diff["status"] == "mismatch"
    by_field = {item["field"]: item for item in diff["items"]}
    assert by_field["executions.count"]["status"] == "mismatch"
    assert by_field["executions[1].execution_id"]["reason"] == "execution_missing"


def test_actual_execution_keeps_branch_output_preview() -> None:
    plan = {
        "plan_id": "orch:test",
        "topology": {
            "mode": "explicit_fanout",
            "route": "compound",
            "execution_kind": "agent",
            "branch_count": 1,
        },
        "executions": [
            {"execution_id": "subtask-1", "execution_kind": "agent", "worker_route": "", "tool_name": ""},
        ],
    }
    trace: dict[str, object] = {}
    trace = update_actual_trace(
        trace,
        {
            "type": "subtask_end",
            "index": 1,
            "task_id": "task-1",
            "content": "第一条分支已经完成，并产出了可以展示给用户的结论。",
            "summary": {"response": "分支完成：产出用户可见结论。"},
            "subtask_plan": {"subtask_plan_id": "subtask-1"},
        },
    )

    actual = actual_from_runtime_event({"type": "done", "answer_source": "answer_assembler"}, plan=plan, actual_trace=trace)

    execution = actual["executions"][0]
    assert execution["execution_id"] == "subtask-1"
    assert execution["summary_preview"] == "分支完成：产出用户可见结论。"
    assert execution["content_preview"].startswith("第一条分支已经完成")
    assert execution["output_chars"] > 0


def test_answer_assembler_selection_is_exposed_in_actual() -> None:
    actual = actual_from_runtime_event(
        {
            "type": "done",
            "answer_source": "answer_assembler",
            "content": "最终答案由第一条分支和第二条分支合并而来。",
            "answer_assembly": {
                "selected_task_ids": ["task-1", "task-2"],
                "selected_count": 2,
                "dropped_count": 1,
                "dropped_segments": [
                    {
                        "task_id": "task-3",
                        "title": "第三条",
                        "reason": "dedupe_duplicate_body",
                        "detail": "重复正文。",
                    }
                ],
                "dedupe_targets": ["task-3"],
                "source_refs": [],
                "content_preview": "最终答案由第一条分支和第二条分支合并而来。",
                "content_chars": 21,
            },
            "task_summary_refs": [
                {"task_id": "task-1", "query": "第一条", "summary": "A"},
                {"task_id": "task-2", "query": "第二条", "summary": "B"},
            ],
        },
        plan={
            "plan_id": "orch:test",
            "topology": {"mode": "explicit_fanout", "route": "compound", "execution_kind": "agent"},
            "executions": [],
        },
        actual_trace={},
    )

    assembly = actual["answer_assembly"]
    assert assembly["answer_source"] == "answer_assembler"
    assert assembly["selected_task_ids"] == ["task-1", "task-2"]
    assert assembly["selected_count"] == 2
    assert assembly["dropped_count"] == 1
    assert assembly["dropped_segments"][0]["reason"] == "dedupe_duplicate_body"
    assert assembly["dedupe_targets"] == ["task-3"]
    assert assembly["content_preview"].startswith("最终答案")
