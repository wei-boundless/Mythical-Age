from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from memory_system import MemoryFacade
from memory_system.layout import durable_memory_namespace_id_for_task_environment
from memory_system.storage.models import MemoryNote


def _fake_invoker(payload):
    async def invoke(_messages, *, accounting_context=None):
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    return invoke


def _maintenance_payload(*, durable_actions=None):
    return {
        "session_memory": {
            "session_title": "治理 tick",
            "active_goal": "验证 durable governance tick",
            "flow_state": ["正在验证低频治理"],
            "current_task_state": ["已生成 durable 候选"],
            "key_user_requests": ["长期记忆按环境隔离"],
            "key_results": ["治理状态由后台 tick 管理"],
        },
        "session_emphasis_actions": [],
        "durable_memory": {
            "actions": durable_actions or [],
            "skipped_reason": "" if durable_actions else "no_cross_session_memory",
            "reasoning_summary": "只记录用户显式长期偏好",
        },
    }


def test_governance_tick_persists_report_and_respects_minimum_interval(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    service = facade.governance_service

    service.mark_namespaces_dirty({"global_common": 2}, reason="test_initial_save")
    first = service.run_governance_tick(min_interval_seconds=3600, reason="test_first_tick")

    assert first["ran"][0]["namespace_id"] == "global_common"
    report_path = Path(first["ran"][0]["report_path"])
    assert report_path.exists()

    service.mark_namespaces_dirty({"global_common": 1}, reason="test_second_save")
    second = service.run_governance_tick(min_interval_seconds=3600, reason="test_second_tick")
    state = service.describe_runtime_state()["namespaces"]["global_common"]

    assert second["ran"] == []
    assert second["skipped"][0]["reason"] == "minimum_interval_not_elapsed"
    assert state["dirty"] is True
    assert state["pending_save_count"] == 1

    forced = service.run_governance_tick(
        namespace_ids=["global_common"],
        force=True,
        min_interval_seconds=3600,
        reason="test_forced_tick",
    )
    state = service.describe_runtime_state()["namespaces"]["global_common"]

    assert forced["ran"][0]["namespace_id"] == "global_common"
    assert state["dirty"] is False
    assert state["pending_save_count"] == 0


def test_governance_dirty_flags_are_isolated_by_namespace(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    service = facade.governance_service
    coding_namespace = durable_memory_namespace_id_for_task_environment("env.coding.test")
    writing_namespace = durable_memory_namespace_id_for_task_environment("env.writing.test")

    service.mark_namespaces_dirty(
        {
            coding_namespace: 1,
            writing_namespace: 1,
        },
        reason="test_environment_saves",
    )
    result = service.run_governance_tick(
        namespace_ids=[coding_namespace],
        force=True,
        min_interval_seconds=0,
        reason="test_scoped_tick",
    )
    namespaces = service.describe_runtime_state()["namespaces"]

    assert result["ran"][0]["namespace_id"] == coding_namespace
    assert namespaces[coding_namespace]["dirty"] is False
    assert namespaces[writing_namespace]["dirty"] is True
    assert namespaces[writing_namespace]["pending_save_count"] == 1


def test_facade_marks_dirty_and_forwards_namespaced_durable_save_event(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    saved_events: list[dict[str, int]] = []
    facade.set_durable_memory_saved_callback(lambda payload: saved_events.append(dict(payload)))
    facade.set_model_invoker(
        _fake_invoker(
            _maintenance_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "coding-quality-standard",
                        "memory_type": "user",
                        "memory_class": "preference",
                        "title": "Coding 质量标准",
                        "canonical_statement": "coding 环境中要优先做结构化修复和真实测试。",
                        "summary": "coding 环境偏好结构化修复和真实测试。",
                        "confidence": "high",
                        "reason": "用户明确要求 coding 环境的工作方式。",
                        "how_to_apply": "coding 任务执行前检查测试闭环。",
                        "evidence_excerpt": "coding 环境里以后优先做结构化修复和真实测试。",
                        "source_message_refs": ["message:0"],
                        "memory_origin": "explicit_user_preference",
                        "evidence_source_kind": "user_message",
                        "preference_scope": "environment",
                        "preference_horizon": "durable_active",
                        "proposed_target_layer": "environment_durable",
                        "task_environment_id": "env.coding.test",
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-governance-event",
        messages=[
            {"role": "user", "content": "coding 环境里以后优先做结构化修复和真实测试。"},
            {"role": "assistant", "content": "收到。"},
        ],
        main_context={"task_environment": {"environment_id": "env.coding.test"}},
    )
    namespace_id = durable_memory_namespace_id_for_task_environment("env.coding.test")
    namespaces = facade.governance_service.describe_runtime_state()["namespaces"]

    assert receipt.status == "succeeded"
    assert saved_events == [{namespace_id: 1}]
    assert namespaces[namespace_id]["dirty"] is True
    assert namespaces[namespace_id]["pending_save_count"] == 1


def test_durable_recall_does_not_run_governance_on_read_path(tmp_path: Path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="answer-style",
            title="回答风格",
            summary="复杂问题先讲结论。",
            canonical_statement="复杂问题先讲结论。",
            body="用户偏好复杂问题先讲结论。",
            memory_type="user",
            memory_class="preference",
        )
    )

    def fail_governance():
        raise AssertionError("durable recall must not run govern_note_store on the hot path")

    facade.memory_manager.govern_note_store = fail_governance  # type: ignore[method-assign]

    result = facade.bundle_service.recall_durable_memories(query="回答风格", note_limit=5)

    assert result.selection.reason == "no_durable_memory_selector_configured"
    assert result.selected_notes == []
