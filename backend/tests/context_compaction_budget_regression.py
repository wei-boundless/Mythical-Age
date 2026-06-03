from __future__ import annotations

from context_system.compaction.compactor import ContextCompactor
from context_system.compaction.hooks import CompactHookDecision
from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager
from runtime.prompt_accounting import CompressionBudgetPlanner, PromptSegment


def test_compression_budget_planner_reports_required_reduction_and_summary_target() -> None:
    segments = [
        PromptSegment(
            segment_id="seg:system",
            request_id="modelreq:test",
            kind="global_static",
            predicted_tokens=120,
            cache_role="cacheable_prefix",
            compression_role="preserve",
        ),
        PromptSegment(
            segment_id="seg:task-stable",
            request_id="modelreq:test",
            kind="task_stable",
            predicted_tokens=80,
            cache_role="session_stable",
            compression_role="summarize",
        ),
        PromptSegment(
            segment_id="seg:history",
            request_id="modelreq:test",
            kind="recent_history",
            predicted_tokens=900,
            cache_role="volatile",
            compression_role="summarize",
        ),
        PromptSegment(
            segment_id="seg:tool",
            request_id="modelreq:test",
            kind="tool_observations",
            predicted_tokens=300,
            cache_role="volatile",
            compression_role="drop_if_cold",
        ),
    ]

    decision = CompressionBudgetPlanner().plan(
        segments,
        context_window_tokens=1000,
        reserved_output_tokens=200,
    )

    assert decision.decision == "microcompact"
    assert decision.hard_required_tokens == 200
    assert decision.compressible_tokens == 1200
    assert decision.compressible_budget == 600
    assert decision.required_reduction_tokens == 600
    assert "seg:task-stable" in decision.preserved_segments
    assert decision.summary_target_tokens > 0
    assert decision.summarized_segments == ("seg:history",)
    assert decision.dropped_segments == ("seg:tool",)
    assert decision.cache_impact == "preserved"
    assert decision.cache_impact_tiers["provider_global"] == "preserved"
    assert decision.cache_impact_tiers["task"] == "preserved"
    assert decision.cache_impact_tiers["volatile"] == "volatile_preserved"
    assert decision.strategy == "ref_projection"


def test_compression_budget_planner_preserves_authority_class_current_user_intent() -> None:
    segments = [
        PromptSegment(
            segment_id="seg:current-user",
            request_id="modelreq:test",
            kind="recent_history",
            predicted_tokens=400,
            cache_role="volatile",
            compression_role="summarize",
            authority_class="current_user_intent",
        ),
        PromptSegment(
            segment_id="seg:old-history",
            request_id="modelreq:test",
            kind="recent_history",
            predicted_tokens=900,
            cache_role="volatile",
            compression_role="summarize",
            authority_class="natural_history",
        ),
    ]

    decision = CompressionBudgetPlanner().plan(
        segments,
        context_window_tokens=900,
        reserved_output_tokens=200,
    )

    assert "seg:current-user" in decision.preserved_segments
    assert "seg:old-history" in decision.compressible_segments
    assert decision.strategy == "session_memory_compact"


def test_context_compactor_builds_semantic_request_for_context_compactor_agent(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=8,
        keep_recent_messages=3,
        effective_history_token_budget=500,
        full_compact_recent_messages=2,
    )
    messages = [
        Message(role="system", content="Runtime Context Package\n旧运行时状态"),
        Message(role="user", content="请审查监控系统"),
        Message(role="assistant", content="旧工具输出 " + ("证据 " * 300)),
        Message(role="user", content="最近纠错：不要暴露原 id"),
        Message(role="assistant", content="已确认要改成自然任务名"),
    ]

    request = compactor.build_semantic_compaction_request(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:test",
        reserved_output_tokens=100,
    )

    payload = request.to_dict()
    assert payload["authority"] == "context_system.semantic_compaction_request"
    assert "你是一名上下文压缩员" in payload["instructions"]
    assert payload["recent_messages"][-1]["content"] == "已确认要改成自然任务名"
    assert all("Runtime Context Package" not in item["content"] for item in payload["messages"])
    assert payload["diagnostics"]["compression_budget_decision"]["summary_target_tokens"] > 0


def test_context_compactor_uses_semantic_summary_as_checkpoint_and_keeps_recent_messages(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    manager.overwrite(
        """# Key User Requests
- 用户要求重构监控系统

# Key Results
- 已确认 token 账本是事实源
"""
    )
    compactor = ContextCompactor(
        manager,
        max_messages=6,
        keep_recent_messages=3,
        effective_history_token_budget=220,
        full_compact_recent_messages=2,
    )
    messages = [
        Message(role="user", content="请重构监控系统"),
        Message(role="assistant", content="旧工具输出 " + ("证据 " * 400)),
        Message(role="user", content="最近纠错：状态不要浅色"),
        Message(role="assistant", content="已确认回复正文要深色"),
        Message(role="user", content="继续修复压缩算法"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:semantic",
        reserved_output_tokens=100,
        semantic_summary_content="用户目标：重构监控系统。\n已验证事实：token 账本是统一事实源。\n下一步：优化压缩算法。",
    )

    assert result.did_full_compact is True
    assert result.summary_message is not None
    assert result.messages[0].meta["compaction_source"] == "semantic_compactor"
    assert "用户目标：重构监控系统" in result.messages[0].content
    assert [message.content for message in result.messages[-2:]] == ["已确认回复正文要深色", "继续修复压缩算法"]
    assert result.diagnostics["compaction_source"] == "semantic_compactor"
    assert result.diagnostics["compression_budget_decision"]["summary_target_tokens"] > 0
    receipt = result.diagnostics["compact_boundary_receipt"]
    assert receipt["authority"] == "context_system.compaction.boundary_receipt"
    assert receipt["planned_strategy"] in {"session_memory_compact", "ref_projection", "microcompact"}
    assert receipt["applied_strategy"] == "full_compact"
    assert receipt["invariant_status"] == "ok"
    assert result.diagnostics["compaction_invariants"]["current_user_message_preserved"] is True


def test_pre_compact_hook_can_block_with_boundary_receipt(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=4,
        keep_recent_messages=2,
        effective_history_token_budget=120,
        pre_compact_hook=lambda request: CompactHookDecision(
            allowed=False,
            reason=f"blocked:{request.trigger}",
        ),
    )
    messages = [
        Message(role="user", content="请继续"),
        Message(role="assistant", content="旧输出 " + ("证据 " * 200)),
        Message(role="user", content="当前请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:blocked",
        trigger="manual",
        reason="test hook",
    )

    assert result.did_compact is False
    assert result.messages == messages
    assert result.strategy == "blocked_by_pre_compact_hook"
    receipt = result.diagnostics["compact_boundary_receipt"]
    assert receipt["blocked"] is True
    assert receipt["block_reason"] == "blocked:manual"


def test_compactor_blocks_replacement_that_would_orphan_tool_result(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    manager.overwrite("# Active Goal\n- 保留工具协议\n")
    compactor = ContextCompactor(
        manager,
        max_messages=4,
        keep_recent_messages=2,
        effective_history_token_budget=120,
        full_compact_recent_messages=2,
    )
    messages = [
        Message(role="user", content="先准备"),
        Message(role="assistant", content="准备完成"),
        Message(role="user", content="读取文件"),
        Message(role="assistant", content='<tool_call id="call_1">read_file</tool_call>'),
        Message(role="tool", content='<tool_result tool_call_id="call_1">文件内容</tool_result>'),
        Message(role="user", content="继续，且不要切断工具结果"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:tool-pair",
        reason="tool invariant test",
    )

    assert result.did_compact is False
    assert result.messages == messages
    assert result.strategy == "blocked_by_compaction_invariants"
    assert result.diagnostics["compaction_invariants"]["orphan_tool_result_ids"] == ["call_1"]
    assert result.diagnostics["compact_boundary_receipt"]["blocked"] is True
