from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from context_system.compaction.compactor import ContextCompactor
from context_system.compaction.hooks import CompactHookDecision
from context_system.compaction.semantic_worker import (
    SemanticCompactionWorkerResult,
    evaluate_semantic_compaction_summary_quality,
    failed_sample_from_summary_quality,
)
from harness.runtime.assembly import assemble_runtime
from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.semantic_compaction_adapter import build_registered_semantic_compaction_worker
from memory_system.facade import MemoryFacade
from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager
from runtime.prompt_accounting import CompressionBudgetPlanner, PromptSegment


def _write_valid_session_memory(manager: SessionMemoryManager, messages: list[Message], content: str) -> None:
    manager.overwrite(content)
    manager.write_compaction_state(
        messages=messages,
        run_id="test:session-memory",
        source="test",
        source_message_refs=[f"message:{index}" for index, _message in enumerate(messages)],
        summary_content=content,
    )


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


def test_session_memory_manager_does_not_persist_template_as_summary(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)

    assert manager.agent_view_path.exists()
    assert manager.load() == ""
    assert manager.compact_view() == ""
    assert not manager.summary_path.exists()
    assert not manager.compaction_view_path.exists()
    assert not manager.context_recovery_package_path.exists()


def test_session_memory_compaction_state_writes_context_recovery_package(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    messages = [
        Message(role="user", content="请升级压缩交接系统", meta={"message_id": "msg:1"}),
        Message(role="assistant", content="已确认采用 context recovery package", meta={"message_id": "msg:2"}),
    ]
    summary = "\n".join(
        [
            "# Active Goal",
            "- 升级压缩交接系统",
            "",
            "# Key User Requests",
            "- 压缩摘要必须服务下一轮上下文交接",
            "",
            "# Files and Functions",
            "- backend/runtime/context_management/recovery_package.py",
            "",
            "# Next Step",
            "- 接入 pre-turn recovery package freshness",
        ]
    )
    manager.overwrite(summary)

    state = manager.write_compaction_state(
        messages=messages,
        run_id="memory-maintenance:recovery-package-test",
        source="agent:1",
        source_message_refs=["message:msg:1", "message:msg:2"],
        summary_content=summary,
    )
    package = manager.load_context_recovery_package()

    assert manager.context_recovery_package_path.exists()
    assert state["context_recovery_package_hash"] == package["coverage"]["summary_hash"]
    assert package["schema_version"] == "runtime-context-recovery-package.v1"
    assert package["current_task"] == "升级压缩交接系统"
    assert package["key_user_constraints"] == ["压缩摘要必须服务下一轮上下文交接"]
    assert package["files_artifacts_refs"] == ["backend/runtime/context_management/recovery_package.py"]
    assert package["next_steps"] == ["接入 pre-turn recovery package freshness"]
    assert package["coverage"]["covered_message_count"] == 2
    assert package["coverage"]["covered_message_ids"] == ["msg:1", "msg:2"]
    assert package["freshness"]["status"] == "fresh"
    assert "## 当前任务" in manager.context_recovery_markdown()


def test_context_compactor_blocks_full_compact_when_only_template_summary_exists(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=6,
        keep_recent_messages=3,
        effective_history_token_budget=220,
        full_compact_recent_messages=2,
    )
    messages = [
        Message(role="user", content="请继续"),
        Message(role="assistant", content="旧输出 " + ("证据 " * 400)),
        Message(role="user", content="当前请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:template-only",
        reserved_output_tokens=100,
        force_full_compact=True,
    )

    assert result.did_compact is False
    assert result.messages == messages
    assert result.summary_message is None
    assert result.strategy == "blocked_by_empty_compaction_summary"
    assert result.diagnostics["compact_boundary_receipt"]["blocked"] is True
    assert result.diagnostics["compact_boundary_receipt"]["block_reason"] == "compaction_summary_unavailable"


def test_context_compactor_uses_valid_session_memory_watermark_and_preserves_unsummarized_tail(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    messages = [
        Message(role="user", content="旧请求", meta={"message_id": "msg:1"}),
        Message(role="assistant", content="旧输出 " + ("证据 " * 240), meta={"message_id": "msg:2"}),
        Message(role="user", content="水位之后的新请求必须原文保留", meta={"message_id": "msg:3"}),
        Message(role="assistant", content="水位之后的新回复必须原文保留", meta={"message_id": "msg:4"}),
    ]
    summary = "# Active Goal\n- 使用有覆盖水位的 session memory\n"
    manager.overwrite(summary)
    manager.write_compaction_state(
        messages=messages[:2],
        run_id="memory-maintenance:test:2",
        source="agent:1",
        source_message_refs=["message:msg:1", "message:msg:2"],
        summary_content=summary,
    )
    compactor = ContextCompactor(
        manager,
        max_messages=4,
        keep_recent_messages=2,
        effective_history_token_budget=260,
        full_compact_recent_messages=2,
    )

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:valid-watermark",
        force_full_compact=True,
    )

    assert result.did_full_compact is True
    assert result.messages[0].meta["compaction_source"] == "validated_session_memory"
    assert [message.content for message in result.messages[1:]] == [
        "水位之后的新请求必须原文保留",
        "水位之后的新回复必须原文保留",
    ]
    assert result.diagnostics["session_compaction_state"]["status"] == "valid"


def test_context_compactor_blocks_stale_session_memory_watermark_without_semantic_worker(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    original = [
        Message(role="user", content="原始请求", meta={"message_id": "msg:1"}),
        Message(role="assistant", content="原始回复", meta={"message_id": "msg:2"}),
    ]
    current = [
        Message(role="user", content="原始请求被改写", meta={"message_id": "msg:1"}),
        Message(role="assistant", content="原始回复", meta={"message_id": "msg:2"}),
        Message(role="user", content="当前请求必须保留", meta={"message_id": "msg:3"}),
    ]
    summary = "# Active Goal\n- 这条摘要覆盖的是旧消息\n"
    manager.overwrite(summary)
    manager.write_compaction_state(
        messages=original,
        run_id="memory-maintenance:test:stale",
        source="agent:1",
        source_message_refs=["message:msg:1", "message:msg:2"],
        summary_content=summary,
    )
    compactor = ContextCompactor(
        manager,
        max_messages=4,
        keep_recent_messages=2,
        effective_history_token_budget=180,
        full_compact_recent_messages=2,
    )

    result = compactor.apply_strategy(
        current,
        pressure_level="full_compact",
        request_id="ctxcompact:stale-watermark",
        force_full_compact=True,
    )

    assert result.did_compact is False
    assert result.strategy == "blocked_by_empty_compaction_summary"
    assert result.diagnostics["session_compaction_state"]["status"] == "stale"
    assert result.diagnostics["session_compaction_state"]["reason"] == "message_fingerprint_mismatch"


def test_microcompact_compresses_only_old_low_authority_assistant_prose(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=10,
        keep_recent_messages=2,
        effective_history_token_budget=800,
        low_authority_text_token_threshold=10,
        low_authority_text_target_chars=140,
    )
    old_assistant_prose = "这是一段旧的过程性解释，主要记录当时如何理解问题，并不构成证据。 " * 80
    code_evidence = "```python\nprint('must keep source-shaped evidence')\n```\n" + ("代码说明 " * 80)
    messages = [
        Message(role="system", content="stable contract must stay"),
        Message(role="user", content="旧用户意图也不能被低权威压缩"),
        Message(role="assistant", content=old_assistant_prose),
        Message(role="assistant", content=code_evidence),
        Message(role="tool", content="tool result " + ("事实 " * 80)),
        Message(role="assistant", content="最近回复必须保留"),
        Message(role="user", content="当前用户请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="microcompact",
        request_id="ctxcompact:low-authority-text",
    )

    compressed = [
        message
        for message in result.messages
        if dict(message.meta or {}).get("kind") == "low_authority_text_compressed"
    ]
    assert len(compressed) == 1
    assert "low-authority assistant prose" in compressed[0].content
    assert len(compressed[0].content) < len(old_assistant_prose)
    assert result.messages[0].content == "stable contract must stay"
    assert result.messages[1].content == "旧用户意图也不能被低权威压缩"
    assert result.messages[3].content == code_evidence
    assert result.messages[4].role == "tool"
    assert result.messages[-1].content == "当前用户请求必须保留"
    assert result.diagnostics["low_authority_text_compressed_count"] == 1


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
    assert result.diagnostics["summary_quality"]["status"] == "pass"
    assert result.diagnostics["summary_quality"]["coverage_signals"]["current_user_message_preserved"] is True
    assert result.diagnostics["summary_quality_failed_sample_ledger"] == []


def test_context_compactor_rejects_unregistered_semantic_worker(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)

    with pytest.raises(ValueError, match="semantic_compactor must expose orchestration registration metadata"):
        ContextCompactor(
            manager,
            max_messages=6,
            keep_recent_messages=3,
            effective_history_token_budget=220,
            semantic_compactor=lambda request: "summary",
        )


class _RegisteredSemanticWorker:
    registration = {
        "agent_id": "agent:context_compactor",
        "agent_profile_id": "context_compactor_agent",
        "runtime_template_id": "runtime.template.context_compactor",
        "runtime_kind": "context_compactor",
        "allowed_operations": ["op.model_response"],
        "blocked_operations": ["op.web_search", "op.fetch_url", "op.read_file", "op.write_file", "op.shell"],
        "allow_nested_subagents": False,
    }

    def __init__(
        self,
        *,
        summary: str = "用户目标：继续压缩系统。\n已验证事实：worker 已注册。",
        structured_summary: dict[str, object] | None = None,
    ) -> None:
        self.summary = summary
        self.structured_summary = structured_summary or {}
        self.requests = []

    def compact(self, request):
        self.requests.append(request)
        return SemanticCompactionWorkerResult(
            ok=bool(self.summary or self.structured_summary),
            summary_content=self.summary,
            structured_summary=dict(self.structured_summary),
            diagnostics={"request_id": request.request_id},
        )


def test_context_compactor_invokes_registered_semantic_worker(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    worker = _RegisteredSemanticWorker()
    compactor = ContextCompactor(
        manager,
        max_messages=6,
        keep_recent_messages=3,
        effective_history_token_budget=220,
        full_compact_recent_messages=2,
        semantic_compactor=worker,
    )
    messages = [
        Message(role="user", content="请继续压缩系统"),
        Message(role="assistant", content="旧工具输出 " + ("证据 " * 400)),
        Message(role="user", content="当前请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:registered-worker",
        reserved_output_tokens=100,
    )

    assert worker.requests
    assert result.did_full_compact is True
    assert result.messages[0].meta["compaction_source"] == "registered_semantic_compactor"
    assert "worker 已注册" in result.messages[0].content
    assert result.diagnostics["semantic_compactor_registered"] is True
    assert result.diagnostics["semantic_compactor_binding"]["agent_profile_id"] == "context_compactor_agent"
    assert result.diagnostics["semantic_compactor_result"]["ok"] is True


def test_context_compactor_renders_semantic_context_recovery_package(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    worker = _RegisteredSemanticWorker(
        summary="",
        structured_summary={
            "current_goal": "修正上下文压缩质量",
            "active_constraints": ["压缩结果必须服务恢复工作，不替主 Agent 继续任务"],
            "verified_facts": ["semantic compactor 只能调用模型响应"],
            "invalidated_items": ["旧工具原文不应整段保留"],
            "next_actions": ["检查压缩输出是否保留当前用户要求"],
        },
    )
    compactor = ContextCompactor(
        manager,
        max_messages=6,
        keep_recent_messages=3,
        effective_history_token_budget=220,
        full_compact_recent_messages=2,
        semantic_compactor=worker,
    )
    messages = [
        Message(role="user", content="请修正上下文压缩质量"),
        Message(role="assistant", content="旧工具输出 " + ("证据 " * 400)),
        Message(role="user", content="当前用户要求不能丢"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:structured-worker",
        reserved_output_tokens=100,
    )

    assert result.did_full_compact is True
    assert result.messages[0].meta["compaction_source"] == "registered_semantic_compactor"
    assert "# Context Recovery Package" in result.messages[0].content
    assert "## 当前任务" in result.messages[0].content
    assert "修正上下文压缩质量" in result.messages[0].content
    assert "## 错误与纠正" in result.messages[0].content
    assert "旧工具原文不应整段保留" in result.messages[0].content
    assert result.diagnostics["semantic_structured_summary_present"] is True


def test_context_compactor_blocks_when_registered_worker_returns_empty_summary_without_valid_session_state(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    manager.overwrite("# Active Goal\n- 旧摘要没有覆盖水位\n")
    worker = _RegisteredSemanticWorker(summary="")
    compactor = ContextCompactor(
        manager,
        max_messages=6,
        keep_recent_messages=3,
        effective_history_token_budget=220,
        full_compact_recent_messages=2,
        semantic_compactor=worker,
    )
    messages = [
        Message(role="user", content="请继续压缩系统"),
        Message(role="assistant", content="旧工具输出 " + ("证据 " * 400)),
        Message(role="user", content="当前请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:registered-worker-empty",
        reserved_output_tokens=100,
    )

    assert worker.requests
    assert result.did_full_compact is False
    assert result.summary_message is None
    assert result.strategy == "blocked_by_empty_compaction_summary"
    assert result.diagnostics["semantic_compactor_result"]["ok"] is False
    assert result.diagnostics["compaction_source"] == "unavailable"
    assert result.diagnostics["session_compaction_state"]["status"] == "missing"
    assert result.diagnostics["summary_quality"]["status"] == "unpass"
    assert "context_recovery_package" in result.diagnostics["summary_quality"]["missing_fields"]
    assert result.diagnostics["summary_quality_failed_sample_ledger"][0]["quality_status"] == "unpass"


def test_semantic_summary_quality_failed_sample_tracks_lost_current_user_message() -> None:
    before = [
        Message(role="user", content="旧请求"),
        Message(role="assistant", content="旧回复"),
        Message(role="user", content="当前请求必须保留"),
    ]
    after = [Message(role="system", content="旧摘要只记录历史背景")]

    quality = evaluate_semantic_compaction_summary_quality(
        request_id="ctxcompact:lost-current-user",
        session_id="session:quality",
        summary_source="semantic_compactor",
        before_messages=before,
        after_messages=after,
        summary_content="旧摘要只记录历史背景",
    )
    sample = failed_sample_from_summary_quality(
        quality,
        request_id="ctxcompact:lost-current-user",
        session_id="session:quality",
        summary_source="semantic_compactor",
    )

    assert quality.status == "unpass"
    assert quality.coverage_signals["current_user_message_preserved"] is False
    assert "current_user_message_preserved" in quality.missing_fields
    assert sample is not None
    assert sample.to_dict()["request_id"] == "ctxcompact:lost-current-user"
    assert sample.to_dict()["session_id"] == "session:quality"
    assert sample.to_dict()["summary_source"] == "semantic_compactor"


def test_context_compactor_agent_profile_is_registered_and_tool_restricted() -> None:
    profile = AgentRuntimeRegistry(Path(__file__).resolve().parents[1]).get_profile("agent:context_compactor")

    assert profile is not None
    assert profile.agent_profile_id == "context_compactor_agent"
    assert profile.metadata["agent_prompt_refs_by_invocation"]["semantic_compaction"] == [
        "agent.context_compactor_agent.semantic_compaction.work_role"
    ]
    assert profile.metadata["worker_kind"] == "semantic_compaction"
    assert profile.metadata["runtime_config"]["runtime_kind"] == "context_compactor"
    assert set(profile.allowed_operations) == {"op.model_response"}
    assert {"op.web_search", "op.fetch_url", "op.read_file", "op.write_file", "op.shell"} <= set(profile.blocked_operations)
    assert profile.subagent_policy.enabled is False
    assert profile.model_profile.temperature == 0
    assert profile.model_profile.max_output_tokens == 4096
    assert profile.model_profile.thinking_mode == "disabled"
    assert profile.model_profile.stream_policy["enabled"] is False
    assert profile.model_profile.response_format == {"type": "json_object"}
    assert profile.metadata["runtime_config"]["stop_policy"] == "recovery_point_ready_or_blocked"
    assert profile.metadata["runtime_config"]["context_compaction"]["unavailable_summary_policy"] == "block_compaction"
    assert profile.metadata["output_contract"]["required_fields"] == ("context_recovery_package",)
    assert "fallback" not in profile.metadata["runtime_config"]["context_compaction"]


def test_runtime_compiler_builds_model_only_semantic_compaction_packet(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    profile = AgentRuntimeRegistry(backend_dir).get_profile("agent:context_compactor")
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(manager, max_messages=6, keep_recent_messages=3, effective_history_token_budget=220)
    request = compactor.build_semantic_compaction_request(
        [
            Message(role="user", content="请保留当前目标"),
            Message(role="assistant", content="旧输出 " + ("证据 " * 260)),
            Message(role="user", content="最近要求：不要丢掉环境"),
        ],
        pressure_level="full_compact",
        request_id="ctxcompact:runtime-packet",
        session_id="session-a",
        turn_id="turn-a",
        task_environment_id="env.coding.vibe_workspace",
    )
    runtime_assembly = assemble_runtime(
        backend_dir=backend_dir,
        session_id="session-a",
        turn_id="turn-a",
        agent_invocation_id="aginvoke:semantic",
        runtime_contract={"task_environment_id": "env.coding.vibe_workspace"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=(),
        definitions_by_name={},
    )

    result = RuntimeCompiler(base_dir=backend_dir).compile_semantic_compaction_packet(
        semantic_request=request,
        runtime_assembly=runtime_assembly,
        agent_runtime_profile=profile,
        session_id="session-a",
        turn_id="turn-a",
    )

    assert result.packet.invocation_kind == "semantic_compaction"
    assert result.packet.available_tools == ()
    assert result.packet.allowed_action_types == ("model_response",)
    assert result.envelope.task_environment_ref == "env.coding.vibe_workspace"
    assert result.packet.prompt_pack_refs == ()
    manifest = result.packet.diagnostics["prompt_manifest"]
    assert manifest["prompt_pack_refs"] == []
    assert "general.runtime_protocol.system_call_protocol" in manifest["rendered_prompt_refs"]
    assert "coding.cycles.session_compaction.way.route" in manifest["rendered_prompt_refs"]
    joined = "\n".join(str(item.get("content") or "") for item in result.packet.model_messages)
    assert "你是一名上下文压缩员" in joined
    assert "context_recovery_package" in joined
    assert "Semantic compaction request" in joined
    assert "env.coding.vibe_workspace" in joined


class _SemanticCompactionModelRuntime:
    def __init__(self) -> None:
        self.calls = []

    async def invoke_messages(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return SimpleNamespace(
            content=json.dumps(
                {
                    "context_recovery_package": {
                        "current_task": "继续压缩系统",
                        "next_steps": ["保留环境边界"],
                    },
                    "summary_content": "用户目标：继续压缩系统。",
                },
                ensure_ascii=False,
            ),
            additional_kwargs={"provider": "test"},
        )


def test_registered_semantic_compaction_worker_invokes_runtime_model(tmp_path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    model_runtime = _SemanticCompactionModelRuntime()
    worker = build_registered_semantic_compaction_worker(
        base_dir=backend_dir,
        model_runtime=model_runtime,
    )
    assert worker is not None
    manager = SessionMemoryManager(tmp_path)
    request = ContextCompactor(manager, max_messages=6, keep_recent_messages=3, effective_history_token_budget=220).build_semantic_compaction_request(
        [
            Message(role="user", content="继续推进"),
            Message(role="assistant", content="旧输出 " + ("证据 " * 260)),
            Message(role="user", content="当前环境不能丢"),
        ],
        pressure_level="full_compact",
        request_id="ctxcompact:adapter",
        session_id="session-adapter",
        turn_id="turn-adapter",
        task_environment_id="env.coding.vibe_workspace",
    )

    result = worker.compact(request)

    assert result.ok is True
    assert result.structured_summary["next_steps"] == ["保留环境边界"]
    assert model_runtime.calls
    call = model_runtime.calls[0]
    assert call["kwargs"]["accounting_context"]["cache_metric_scope"] == "semantic_compaction_worker"
    assert call["kwargs"]["model_spec"]["temperature"] == 0
    assert call["kwargs"]["model_spec"]["max_output_tokens"] == 4096
    assert call["kwargs"]["model_spec"]["stream_policy"]["enabled"] is False
    assert call["kwargs"]["model_spec"]["response_format"] == {"type": "json_object"}
    assert any("Semantic compaction request" in str(message.get("content") or "") for message in call["messages"])
    assert result.diagnostics["model_response_protocol"]["json_payload"]["context_recovery_package"]["current_task"] == "继续压缩系统"


def test_memory_facade_compactor_uses_only_injected_semantic_worker(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    worker = _RegisteredSemanticWorker()

    plain_compactor = facade.session_memory.compactor("session-no-worker")
    assert plain_compactor.semantic_compactor is None

    facade.set_session_compactor_kwargs_provider(lambda session_id: {"semantic_compactor": worker})
    injected_compactor = facade.session_memory.compactor("session-with-worker")

    assert injected_compactor.semantic_compactor is worker
    assert injected_compactor.semantic_compactor_registration.agent_profile_id == "context_compactor_agent"


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
    _write_valid_session_memory(manager, messages, "# Active Goal\n- 保留工具协议\n")

    result = compactor.apply_strategy(
        messages,
        pressure_level="full_compact",
        request_id="ctxcompact:tool-pair",
        reason="tool invariant test",
        force_full_compact=True,
    )

    assert result.did_compact is False
    assert result.messages == messages
    assert result.strategy == "blocked_by_compaction_invariants"
    assert result.diagnostics["compaction_invariants"]["orphan_tool_result_ids"] == ["call_1"]
    assert result.diagnostics["compact_boundary_receipt"]["blocked"] is True
