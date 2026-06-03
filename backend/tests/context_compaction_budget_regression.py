from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from context_system.compaction.compactor import ContextCompactor
from context_system.compaction.hooks import CompactHookDecision
from context_system.compaction.semantic_worker import SemanticCompactionWorkerResult
from harness.runtime.assembly import assemble_runtime
from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.semantic_compaction_adapter import build_registered_semantic_compaction_worker
from memory_system.facade import MemoryFacade
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

    def __init__(self, *, summary: str = "用户目标：继续压缩系统。\n已验证事实：worker 已注册。") -> None:
        self.summary = summary
        self.requests = []

    def compact(self, request):
        self.requests.append(request)
        return SemanticCompactionWorkerResult(
            ok=bool(self.summary),
            summary_content=self.summary,
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


def test_context_compactor_falls_back_when_registered_worker_returns_empty_summary(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    manager.overwrite("# Active Goal\n- 使用确定性摘要兜底\n")
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
    assert result.did_full_compact is True
    assert result.messages[0].meta["compaction_source"] == "deterministic_session_memory"
    assert "使用确定性摘要兜底" in result.messages[0].content
    assert result.diagnostics["semantic_compactor_result"]["ok"] is False
    assert result.diagnostics["compaction_source"] == "deterministic_session_memory"


def test_context_compactor_agent_profile_is_registered_and_tool_restricted() -> None:
    profile = AgentRuntimeRegistry(Path(__file__).resolve().parents[1]).get_profile("agent:context_compactor")

    assert profile is not None
    assert profile.agent_profile_id == "context_compactor_agent"
    assert profile.metadata["agent_prompt_refs_by_invocation"]["semantic_compaction"] == [
        "agent.context_compactor_agent.semantic_compaction.work_role.v1"
    ]
    assert profile.metadata["worker_kind"] == "semantic_compaction"
    assert profile.metadata["runtime_config"]["runtime_kind"] == "context_compactor"
    assert set(profile.allowed_operations) == {"op.model_response"}
    assert {"op.web_search", "op.fetch_url", "op.read_file", "op.write_file", "op.shell"} <= set(profile.blocked_operations)
    assert profile.subagent_policy.enabled is False


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
        request_task_selection={"task_environment_id": "env.coding.vibe_workspace"},
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
    assert "runtime.pack.semantic_compaction.v1" in result.packet.prompt_pack_refs
    joined = "\n".join(str(item.get("content") or "") for item in result.packet.model_messages)
    assert "你是一名上下文压缩员" in joined
    assert "Semantic compaction request" in joined
    assert "env.coding.vibe_workspace" in joined


class _SemanticCompactionModelRuntime:
    def __init__(self) -> None:
        self.calls = []

    async def invoke_messages(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return SimpleNamespace(
            content=json.dumps({"summary_content": "用户目标：继续压缩系统。\n下一步：保留环境边界。"}, ensure_ascii=False),
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
    assert "保留环境边界" in result.summary_content
    assert model_runtime.calls
    call = model_runtime.calls[0]
    assert call["kwargs"]["accounting_context"]["cache_metric_scope"] == "semantic_compaction_worker"
    assert any("Semantic compaction request" in str(message.get("content") or "") for message in call["messages"])
    assert result.diagnostics["model_response_protocol"]["json_payload"]["summary_content"].startswith("用户目标")


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
