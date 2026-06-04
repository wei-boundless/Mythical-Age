from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from memory_system import MemoryFacade
from memory_system.maintenance import MemoryMaintenanceAgent
from memory_system.storage.models import MemoryNote


def _agent_payload(*, durable_actions=None):
    normalized_durable_actions = []
    for action in durable_actions or []:
        normalized = {
            "memory_origin": "user_confirmed_project_rule",
            "evidence_source_kind": "user_message",
            "preference_scope": "environment",
            "preference_horizon": "durable_active",
            "proposed_target_layer": "environment_durable",
        }
        normalized.update(action)
        normalized_durable_actions.append(normalized)
    return {
        "session_memory": {
            "session_title": "记忆系统接线",
            "active_goal": "接通记忆管理 Agent",
            "flow_state": ["记忆维护已进入提交后整理"],
            "current_task_state": ["已生成 agent draft"],
            "key_user_requests": ["记忆语义判断交给记忆管理 Agent"],
            "decisions_and_learnings": ["模型失败时不写长期记忆"],
            "key_results": ["Session Memory 由 agent:1 维护"],
            "worklog": ["完成一次记忆维护"],
        },
        "session_emphasis_actions": [],
        "durable_memory": {
            "actions": normalized_durable_actions,
            "skipped_reason": "" if normalized_durable_actions else "no_cross_session_memory",
            "reasoning_summary": "只保留稳定跨会话信息",
        },
    }


def _fake_invoker(payload):
    async def invoke(_messages):
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    return invoke


def test_memory_maintenance_agent_prompt_is_natural_role_instruction() -> None:
    prompt = MemoryMaintenanceAgent().system_prompt()

    assert "你是一名记忆管理员" in prompt
    assert "你不回答用户" in prompt
    assert "Session Emphasis 只保存用户在本会话中显式强调" in prompt
    assert "runtime 节点" not in prompt
    assert "根据任务图执行" not in prompt


def test_background_memory_maintenance_skips_without_opportunity_signal(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    calls = []

    async def invoker(messages):
        calls.append(messages)
        return SimpleNamespace(content=json.dumps(_agent_payload(), ensure_ascii=False))

    facade.set_model_invoker(invoker)

    receipt = facade.enqueue_memory_maintenance_after_commit(
        session_id="session-maintenance-gate",
        messages=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好。"},
        ],
        turn_id="turn:maintenance-gate:1",
    )

    assert receipt.status == "skipped"
    assert receipt.attempted is False
    assert receipt.durable_skip_reason == "below_maintenance_threshold"
    assert calls == []


def test_session_emphasis_action_writes_pinned_user_steer(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            {
                **_agent_payload(),
                "session_emphasis_actions": [
                    {
                        "action": "upsert",
                        "emphasis_id": "phase-plan-first",
                        "content": "本会话内涉及 runtime/memory 大改时，先按计划执行，不要临时扩范围。",
                        "scope": "session_task",
                        "priority": "high",
                        "source_message_ref": "message:0",
                    }
                ],
            }
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-emphasis-write",
        messages=[
            {"role": "user", "content": "强调一下：这轮先按计划执行，不要临时扩范围。"},
            {"role": "assistant", "content": "收到。"},
        ],
    )

    assert receipt.status == "succeeded"
    assert receipt.session_emphasis_succeeded is True
    assert receipt.session_emphasis_write_count == 1
    pinned = facade.session_emphasis.render_pinned_facts("session-emphasis-write")
    assert pinned[0]["kind"] == "session_emphasis"
    assert "不要临时扩范围" in pinned[0]["content"]


def test_short_horizon_preference_is_routed_out_of_durable_memory(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "turn-only-short-answer",
                        "memory_type": "user",
                        "memory_class": "preference",
                        "title": "本轮简短回答",
                        "canonical_statement": "用户本轮希望回答简短。",
                        "summary": "本轮简短回答。",
                        "confidence": "high",
                        "reason": "用户只说本轮。",
                        "evidence_excerpt": "这轮回答简短一点。",
                        "source_message_refs": ["message:0"],
                        "memory_origin": "explicit_user_preference",
                        "preference_scope": "session_task",
                        "preference_horizon": "session",
                        "proposed_target_layer": "session",
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-short-horizon",
        messages=[
            {"role": "user", "content": "这轮回答简短一点。"},
            {"role": "assistant", "content": "好的。"},
        ],
    )

    assert receipt.status == "succeeded"
    assert receipt.durable_write_count == 0
    assert receipt.durable_skipped is True
    assert receipt.durable_skip_reason == "durable_actions_routed_to_non_durable_layer"
    assert facade.memory_manager.list_notes() == []


def test_memory_maintenance_coordinator_writes_session_and_durable_via_agent(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "memory-agent-boundary",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "记忆管理 Agent 负责记忆整理",
                        "canonical_statement": "记忆整理由 agent:1 在提交后统一执行。",
                        "summary": "agent:1 统一维护 session 与 durable memory。",
                        "retrieval_hints": ["记忆管理", "agent:1"],
                        "confidence": "high",
                        "reason": "这是系统架构层面的稳定约定。",
                        "how_to_apply": "后续调整记忆链路时保持主链与记忆整理解耦。",
                        "evidence_excerpt": "把记忆管理agent接通，要求真能按照设计原则来工作",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-memory-maintenance",
        messages=[
            {"role": "user", "content": "把记忆管理agent接通"},
            {"role": "assistant", "content": "已经接通"},
        ],
        turn_id="turn:session-memory-maintenance:1",
    )

    assert receipt.status == "succeeded"
    assert receipt.session_memory_succeeded is True
    assert receipt.durable_memory_succeeded is True
    assert receipt.durable_write_count == 1
    assert "接通记忆管理 Agent" in facade.session_memory.manager("session-memory-maintenance").load()
    assert facade.memory_manager.note_path("memory-agent-boundary").exists()


def test_memory_maintenance_model_call_has_prompt_accounting_context(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    calls: list[dict[str, object]] = []

    async def invoker(messages, *, accounting_context=None):
        calls.append({"messages": list(messages), "accounting_context": dict(accounting_context or {})})
        return SimpleNamespace(content=json.dumps(_agent_payload(), ensure_ascii=False))

    facade.set_model_invoker(invoker)

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-maintenance-accounting",
        messages=[
            {"role": "user", "content": "继续检查 prompt cache"},
            {"role": "assistant", "content": "已完成一轮检查"},
        ],
        turn_id="turn:session-maintenance-accounting:1",
    )

    assert receipt.status == "succeeded"
    assert calls
    messages = calls[0]["messages"]
    context = calls[0]["accounting_context"]
    assert len(messages) == 3
    assert messages[1]["role"] == "system"
    assert "请严格输出符合以下结构的 JSON" in messages[1]["content"]
    assert "output_schema" not in messages[2]["content"]
    assert context["cache_metric_scope"] == "memory_maintenance"
    assert context["session_id"] == "session-maintenance-accounting"
    assert context["run_id"] == "memory-maintenance:session-maintenance-accounting:2"
    assert context["prompt_manifest"]["utility_purpose"] == "memory.maintenance_after_commit"
    segments = context["segment_plan"]["segments"]
    assert [segment["kind"] for segment in segments] == ["utility_static", "utility_stable", "utility_volatile"]
    assert [segment["prefix_tier"] for segment in segments] == ["provider_global", "session", "volatile"]


def test_memory_maintenance_agent_session_draft_does_not_overwrite_process_state(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(_fake_invoker(_agent_payload()))

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-maintenance-state-boundary",
        messages=[
            {"role": "user", "content": "继续推进记忆系统重构"},
            {"role": "assistant", "content": "已经整理当前状态"},
        ],
        main_context={"active_goal": "系统权威目标：重构 runtime 读取链"},
        task_summary_refs=[{"query": "重构 runtime 读取链", "summary": "读取链已由 plan 控制。"}],
    )

    manager = facade.session_memory.manager("session-maintenance-state-boundary")
    state = manager.load_state()
    rendered_view = manager.load()

    assert receipt.status == "succeeded"
    assert state.active_goal == "系统权威目标：重构 runtime 读取链"
    assert "接通记忆管理 Agent" in rendered_view
    assert state.active_goal not in rendered_view
    assert receipt.diagnostics["proposal_authority"] == "memory_maintenance_agent.proposal"
    assert receipt.diagnostics["commit_authority"] == "memory_system.memory_committer"


def test_durable_memory_recall_model_call_has_prompt_accounting_context(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="prompt-cache-policy",
            title="Prompt cache policy",
            summary="Prompt cache must use runtime segment plans.",
            canonical_statement="Utility model calls must carry prompt accounting context.",
            body="Utility model calls must carry prompt accounting context.",
            memory_type="project",
            memory_class="work",
        )
    )
    calls: list[dict[str, object]] = []

    async def invoker(messages, *, accounting_context=None):
        calls.append({"messages": list(messages), "accounting_context": dict(accounting_context or {})})
        return SimpleNamespace(
            content=json.dumps(
                {
                    "should_recall": True,
                    "selected_note_ids": ["prompt-cache-policy"],
                    "reason": "matches query",
                    "confidence": 0.9,
                    "needs_verification": False,
                    "manifest_only": False,
                    "ignore_memory": False,
                },
                ensure_ascii=False,
            )
        )

    facade.durable_memory.set_message_invoker(invoker)

    result = facade.durable_memory.recall_memories(query="prompt cache accounting", note_limit=2)

    assert result.selection.selected_note_ids == ["prompt-cache-policy"]
    assert calls
    context = calls[0]["accounting_context"]
    assert context["cache_metric_scope"] == "durable_memory_recall"
    assert context["prompt_manifest"]["utility_purpose"] == "memory.durable_recall_selector"
    assert context["segment_plan"]["segments"]


def test_memory_maintenance_model_failure_does_not_fallback_write_durable(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    async def failing_invoker(_messages):
        raise RuntimeError("model unavailable")

    facade.set_model_invoker(failing_invoker)

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-memory-failure",
        messages=[
            {"role": "user", "content": "请记住：我偏好复杂问题先讲结论。"},
            {"role": "assistant", "content": "好的。"},
        ],
    )

    assert receipt.status == "failed"
    assert receipt.durable_write_count == 0
    assert facade.memory_manager.list_notes() == []


def test_memory_maintenance_rejects_durable_action_without_evidence(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "missing-evidence",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "缺少证据",
                        "canonical_statement": "这条长期记忆缺少来源证据。",
                        "summary": "缺少证据",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-memory-reject",
        messages=[
            {"role": "user", "content": "测试"},
            {"role": "assistant", "content": "测试完成"},
        ],
    )

    assert receipt.status == "succeeded"
    assert receipt.session_memory_succeeded is True
    assert receipt.durable_memory_succeeded is False
    assert receipt.durable_write_count == 0
    assert receipt.durable_skip_reason == "durable_write_rejected_by_committer"
    assert receipt.diagnostics["durable_error"]
    assert facade.memory_manager.list_notes() == []


def test_durable_update_requires_existing_target(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "update",
                        "target_note_id": "missing-target",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "不存在的目标",
                        "canonical_statement": "不能静默创建不存在的 update 目标。",
                        "summary": "update 必须命中已有 note。",
                        "evidence_excerpt": "用户要求长期记忆更新必须真实可追踪",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-update-missing",
        messages=[{"role": "user", "content": "更新长期记忆"}, {"role": "assistant", "content": "收到"}],
    )

    assert receipt.status == "succeeded"
    assert receipt.durable_memory_succeeded is False
    assert receipt.durable_write_count == 0
    assert receipt.durable_skip_reason == "durable_write_rejected_by_committer"
    assert "Unknown durable memory update target" in receipt.diagnostics["durable_error"]


def test_durable_plan_partial_failure_reports_written_namespace(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    saved_events: list[dict[str, int]] = []
    facade.set_durable_memory_saved_callback(lambda payload: saved_events.append(dict(payload)))
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "partial-valid",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "部分成功写入",
                        "canonical_statement": "部分成功的长期记忆写入必须触发治理 dirty 事件。",
                        "summary": "部分成功也要准确报告。",
                        "evidence_excerpt": "用户要求记忆提交不能误报 skipped",
                        "source_message_refs": ["message:0"],
                    },
                    {
                        "action": "update",
                        "target_note_id": "missing-after-partial",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "不存在的目标",
                        "canonical_statement": "这条 update 应该被拒绝。",
                        "summary": "缺少目标。",
                        "evidence_excerpt": "用户要求记忆提交不能误报 skipped",
                        "source_message_refs": ["message:0"],
                    },
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-partial-durable",
        messages=[{"role": "user", "content": "记忆提交不能误报 skipped。"}],
    )

    assert receipt.status == "succeeded"
    assert receipt.durable_memory_succeeded is False
    assert receipt.durable_write_count == 1
    assert receipt.durable_skipped is False
    assert receipt.durable_skip_reason == "durable_plan_partially_rejected_by_committer"
    assert receipt.diagnostics["durable_actions"]["created"] == ["partial-valid"]
    assert "Unknown durable memory update target" in receipt.diagnostics["durable_error"]
    assert facade.memory_manager.note_path("partial-valid").exists()
    assert saved_events == [{"global_common": 1}]


def test_memory_maintenance_runtime_state_corruption_fails_visible(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    state_path = facade.maintenance_coordinator._session_dir("session-corrupt-maintenance") / "state.json"
    state_path.write_text("{broken-json", encoding="utf-8")

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-corrupt-maintenance",
        messages=[{"role": "user", "content": "触发维护"}],
    )

    assert receipt.status == "failed"
    assert "Expecting property name" in receipt.error
    assert receipt.durable_write_count == 0


def test_durable_merge_deprecates_sources(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="old-a",
            title="旧规则 A",
            summary="旧规则 A",
            canonical_statement="旧规则 A。",
            body="旧规则 A。",
            memory_type="project",
            memory_class="work",
        )
    )
    facade.memory_manager.save_note(
        MemoryNote(
            slug="old-b",
            title="旧规则 B",
            summary="旧规则 B",
            canonical_statement="旧规则 B。",
            body="旧规则 B。",
            memory_type="project",
            memory_class="work",
        )
    )
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "merge",
                        "target_note_id": "merged-rule",
                        "merge_note_ids": ["old-a", "old-b"],
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "合并规则",
                        "canonical_statement": "旧规则 A 与旧规则 B 已合并为一条规则。",
                        "summary": "合并后的规则。",
                        "evidence_excerpt": "用户要求合并长期记忆并废弃来源",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-merge",
        messages=[{"role": "user", "content": "合并长期记忆"}, {"role": "assistant", "content": "完成"}],
    )

    old_a = facade.memory_manager.load_note_record("old-a")
    old_b = facade.memory_manager.load_note_record("old-b")
    assert receipt.durable_memory_succeeded is True
    assert receipt.diagnostics["durable_actions"]["merged"] == ["merged-rule"]
    assert set(receipt.diagnostics["durable_actions"]["deprecated"]) == {"old-a", "old-b"}
    assert old_a is not None and old_a.status == "deprecated"
    assert old_b is not None and old_b.status == "deprecated"
    edges = facade.memory_manager.list_temporal_fact_edges()
    merge_edges = [
        edge
        for edge in edges
        if edge.relation == "merged_into" and edge.target_note_id == "merged-rule"
    ]
    assert {edge.source_note_id for edge in merge_edges} == {"old-a", "old-b"}
    assert all(edge.actor == "agent:1" for edge in merge_edges)
    assert all(edge.source_evidence_ref for edge in merge_edges)


def test_durable_update_records_refine_edge(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.memory_manager.save_note(
        MemoryNote(
            slug="memory-policy",
            title="记忆政策",
            summary="长期记忆只保存稳定事实。",
            canonical_statement="长期记忆只保存稳定事实。",
            body="旧描述。",
            memory_type="project",
            memory_class="work",
        )
    )
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "update",
                        "target_note_id": "memory-policy",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "记忆政策",
                        "canonical_statement": "长期记忆必须有证据和来源引用。",
                        "summary": "长期记忆写入必须保留证据。",
                        "evidence_excerpt": "用户要求长期记忆更新必须真实可追踪",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-update-edge",
        messages=[{"role": "user", "content": "更新长期记忆"}, {"role": "assistant", "content": "完成"}],
    )

    updated = facade.memory_manager.load_note_record("memory-policy")
    edges = facade.memory_manager.list_temporal_fact_edges()
    refine_edges = [
        edge
        for edge in edges
        if edge.relation == "refines" and edge.source_note_id == "memory-policy"
    ]

    assert receipt.durable_memory_succeeded is True
    assert receipt.diagnostics["durable_actions"]["updated"] == ["memory-policy"]
    assert updated is not None
    assert updated.canonical_statement == "长期记忆必须有证据和来源引用。"
    assert len(refine_edges) == 1
    assert refine_edges[0].target_note_id == "memory-policy"
    assert refine_edges[0].before_sha256
    assert refine_edges[0].after_sha256
    assert refine_edges[0].before_sha256 != refine_edges[0].after_sha256
    assert refine_edges[0].source_evidence_ref



