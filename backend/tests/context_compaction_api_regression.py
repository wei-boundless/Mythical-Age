from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import tokens as tokens_api
from context_system.compaction.compactor import ContextCompactor
from memory_system.continuity import MemoryMessageAdapter
from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager
from runtime.context_management.session_compaction import _protocol_pressure_message, _stored_messages_after_compact, auto_compact_session_if_needed, compact_session_history
from runtime.prompt_accounting import ModelTokenUsageRecord, PromptAccountingLedger
from sessions import SessionManager


def test_compact_preview_does_not_mutate_session_messages(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)
    before = runtime.session_manager.load_session(session_id)

    response = asyncio.run(
        tokens_api.preview_session_compaction(
            session_id,
            tokens_api.CompactSessionRequest(pressure_level="microcompact"),
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert response["mode"] == "preview"
    assert response["applied"] is False
    assert response["did_microcompact"] is True
    assert response["compact_boundary_receipt"]["trigger"] == "preview"
    assert runtime.session_manager.load_session(session_id) == before
    assert old_assistant_prose in before[1]["content"]


def test_compact_run_rewrites_runtime_history_and_preserves_api_transcript(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)

    response = asyncio.run(
        tokens_api.run_session_compaction(
            session_id,
            tokens_api.CompactSessionRequest(pressure_level="microcompact"),
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    stored = runtime.session_manager.load_session(session_id)
    api_transcript = runtime.session_manager.load_session_for_api(session_id)

    assert response["mode"] == "run"
    assert response["applied"] is True
    assert response["did_microcompact"] is True
    assert response["compact_boundary_receipt"]["trigger"] == "manual"
    assert stored[1]["meta"]["kind"] == "low_authority_text_compressed"
    assert old_assistant_prose not in stored[1]["content"]
    assert api_transcript[1]["content"] == old_assistant_prose


def test_microcompact_run_preserves_existing_full_compact_boundary(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)
    original_messages = runtime.session_manager.load_session(session_id)
    runtime.session_manager.replace_runtime_context(
        session_id,
        messages=original_messages,
        compressed_context="此前已经生成的 full compact checkpoint",
    )
    before_record = runtime.session_manager.get_history(session_id)
    before_boundary = before_record["provider_protocol_compaction_created_at"]

    response = asyncio.run(
        tokens_api.run_session_compaction(
            session_id,
            tokens_api.CompactSessionRequest(pressure_level="microcompact"),
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    record = runtime.session_manager.get_history(session_id)

    assert response["applied"] is True
    assert response["did_microcompact"] is True
    assert response["did_full_compact"] is False
    assert record["compressed_context"] == "此前已经生成的 full compact checkpoint"
    assert record["provider_protocol_compaction_created_at"] == before_boundary


def test_full_compact_run_stores_summary_as_compressed_context(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)

    response = asyncio.run(
        tokens_api.run_session_compaction(
            session_id,
            tokens_api.CompactSessionRequest(pressure_level="full_compact"),
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    record = runtime.session_manager.get_history(session_id)
    api_transcript = runtime.session_manager.load_session_for_api(session_id)

    assert response["applied"] is True
    assert response["did_full_compact"] is True
    assert response["compressed_context_present"] is True
    assert "Conversation history was compacted into a checkpoint" in record["compressed_context"]
    assert record["provider_protocol_compaction_created_at"] > 0
    assert all(item["role"] != "system" for item in record["messages"])
    assert len(record["messages"]) <= 2
    assert api_transcript[1]["content"] == old_assistant_prose
    assert api_transcript[1]["created_at"] > 0


def test_session_tokens_exposes_context_meter_and_billing_totals(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)
    before = runtime.session_manager.load_session(session_id)

    response = asyncio.run(
        tokens_api.session_tokens(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert "billing_totals" in response
    assert "context_meter" in response
    assert "cache_metrics" in response
    assert "compaction_readiness" in response
    assert "context_recovery_package" in response
    assert response["context_meter"]["authority"] == "runtime.context_management.session_pressure_snapshot"
    assert response["context_meter"]["estimate_mode"] == "session_pressure"
    assert response["context_meter"]["current_context_tokens"] > 0
    assert response["context_meter"]["diagnostics"]["session_pressure"]["provider_protocol_message_count"] == 0
    assert response["context_meter"]["reserved_output_tokens"] == 65_536
    assert response["context_meter"]["input_capacity_tokens"] == 926_272
    assert response["context_meter"]["replacement_threshold_tokens"] == 850_000
    assert response["context_meter"]["compaction_remaining_tokens"] <= response["context_meter"]["replacement_threshold_tokens"]
    assert response["cumulative_transcript_message_count"] == 4
    assert response["cumulative_transcript_tokens"] >= response["raw_history_tokens"]
    assert response["compression_saved_tokens"] == response["cumulative_transcript_tokens"] - response["history_tokens"]
    assert 0 < response["compression_ratio"] <= 1
    assert response["history_did_compact"] is True
    assert response["history_compaction_strategy"] in {"microcompact", "full_compact"}
    assert response["history_tokens"] < response["raw_history_tokens"]
    assert response["context_recovery_package"]["present"] is True
    assert response["context_recovery_package"]["fresh"] is True
    assert response["context_recovery_package"]["source"] == "agent:1"
    assert response["context_recovery_package"]["covered_message_count"] == len(before)
    assert response["compaction_readiness"]["context_recovery_package_present"] is True
    assert response["compaction_readiness"]["context_recovery_package_fresh"] is True
    assert runtime.session_manager.load_session(session_id) == before


def test_session_tokens_current_context_uses_latest_model_request_accounting(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.harness_runtime = SimpleNamespace(
        single_agent_runtime_host=SimpleNamespace(prompt_accounting_ledger=ledger)
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:assembled:local_prediction",
            request_id="modelreq:assembled",
            session_id=session_id,
            provider="deepseek",
            model="deepseek-v4-pro",
            source="local_prediction",
            prompt_tokens=72_000,
            total_tokens=72_000,
            created_at=1.0,
            diagnostics={
                "cache_metric_scope": "agent_runtime",
                "packet_ref": "rtpacket:assembled",
                "prompt_manifest": {
                    "context_window": {
                        "active_history_fingerprint": "sha256:old-history",
                    }
                },
            },
        )
    )
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)

    response = asyncio.run(
        tokens_api.session_tokens(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    meter = response["context_meter"]
    diagnostics = meter["diagnostics"]
    assert meter["authority"] == "runtime.prompt_accounting.context_usage_snapshot"
    assert meter["estimate_mode"] == "local_predicted_anchor_invalid"
    assert meter["current_context_tokens"] > 72_000
    assert meter["estimated_pending_tokens"] > 0
    assert diagnostics["current_context_authority"] == "runtime.prompt_accounting.model_request_accounting"
    assert diagnostics["session_pressure_used_as_current_context"] is False
    assert diagnostics["session_pressure"]["public_history_tokens"] > 0
    assert meter["compaction_pressure_tokens"] == meter["current_context_tokens"]


def test_session_tokens_adds_pending_messages_after_local_prediction(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.harness_runtime = SimpleNamespace(
        single_agent_runtime_host=SimpleNamespace(prompt_accounting_ledger=ledger)
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:pending:local_prediction",
            request_id="modelreq:pending",
            session_id=session_id,
            provider="deepseek",
            model="deepseek-v4-pro",
            source="local_prediction",
            prompt_tokens=40_000,
            total_tokens=40_000,
            created_at=10.0,
            diagnostics={"cache_metric_scope": "agent_runtime", "packet_ref": "rtpacket:pending"},
        )
    )
    runtime.session_manager.append_messages(
        session_id,
        [{"role": "assistant", "content": "新提交的模型输出应被计入下一轮上下文。", "created_at": 11.0}],
    )
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)

    response = asyncio.run(
        tokens_api.session_tokens(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    meter = response["context_meter"]
    assert meter["current_context_tokens"] > 40_000
    assert meter["estimated_pending_tokens"] > 0
    assert meter["diagnostics"]["observed_context_source"] == "local_prediction"


def test_session_tokens_cache_invalidates_when_prompt_accounting_changes(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.harness_runtime = SimpleNamespace(
        single_agent_runtime_host=SimpleNamespace(prompt_accounting_ledger=ledger)
    )
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)

    first = asyncio.run(
        tokens_api.session_tokens(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:cache-invalidates:local_prediction",
            request_id="modelreq:cache-invalidates",
            session_id=session_id,
            provider="deepseek",
            model="deepseek-v4-pro",
            source="local_prediction",
            prompt_tokens=88_000,
            total_tokens=88_000,
            created_at=1.0,
            diagnostics={"cache_metric_scope": "agent_runtime", "packet_ref": "rtpacket:cache-invalidates"},
        )
    )

    second = asyncio.run(
        tokens_api.session_tokens(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert first["context_meter"]["current_context_tokens"] != 88_000
    assert second["context_meter"]["current_context_tokens"] > 88_000


def test_session_tokens_counts_only_provider_protocol_messages_as_protocol_pressure(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)
    runtime.session_manager.append_api_messages(
        session_id,
        [
            {
                "role": "assistant",
                "turn_id": "turn:tool",
                "tool_calls": [
                    {
                        "id": "call:read-file",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{\"path\":\"app.py\"}"},
                    }
                ],
            },
            {
                "role": "tool",
                "turn_id": "turn:tool",
                "tool_call_id": "call:read-file",
                "content": "tool result line\n" * 80,
            },
        ],
    )

    response = asyncio.run(
        tokens_api.session_tokens(
            session_id,
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    pressure = response["context_meter"]["diagnostics"]["session_pressure"]
    assert pressure["provider_protocol_message_count"] == 2
    assert pressure["provider_protocol_tokens"] > 0
    assert pressure["public_message_count"] == 4


def test_auto_compact_not_applied_reports_preserved_message_count(tmp_path: Path) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)

    response = compact_session_history(
        runtime,
        session_id=session_id,
        mode="auto",
        context_snapshot=_ContextSnapshot(auto_replacement_allowed=False),
    )

    assert response["applied"] is False
    assert response["skipped_reason"] == "below_replacement_threshold"
    assert response["preserved_recent_count"] == len(runtime.session_manager.load_session(session_id))


def test_auto_compact_skips_when_history_compactor_is_unavailable(tmp_path: Path) -> None:
    session_manager = SessionManager(tmp_path)
    session_id = session_manager.create_session(title="No compactor")["id"]
    session_manager.append_messages(session_id, [{"role": "user", "content": "hello"}])
    runtime = SimpleNamespace(
        session_manager=session_manager,
        memory_facade=SimpleNamespace(),
        settings=SimpleNamespace(static=SimpleNamespace(llm_provider="deepseek", llm_model="deepseek-v4-pro", llm_max_output_tokens=65_536)),
    )

    response = auto_compact_session_if_needed(runtime, session_id=session_id)

    assert response["applied"] is False
    assert response["skipped_reason"] == "history_compactor_unavailable"
    assert response["preserved_recent_count"] == 1


def test_auto_compact_if_needed_does_not_use_history_fallback_when_session_pressure_is_below_threshold(tmp_path: Path) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    original_count = len(runtime.session_manager.load_session(session_id))

    response = auto_compact_session_if_needed(runtime, session_id=session_id)
    record = runtime.session_manager.get_history(session_id)

    assert response["applied"] is False
    assert response["skipped_reason"] == "below_replacement_threshold"
    assert response["pressure_level"] == "normal"
    assert response["history_pressure_level"] in {"microcompact", "full_compact"}
    assert response["context_meter"]["estimate_mode"] == "session_pressure"
    assert response["context_meter"]["diagnostics"]["session_pressure_used_as_current_context"] is True
    assert response["context_meter"]["auto_replacement_allowed"] is False
    assert len(record["messages"]) == original_count


def test_compaction_writeback_keeps_structured_tool_messages_out_of_public_history() -> None:
    stored = _stored_messages_after_compact(
        [
            Message(role="user", content="修复 bug"),
            Message(role="tool", content="Edit failed: old_text not found"),
            Message(role="assistant", content="已完成修复。"),
        ]
    )

    assert stored == [
        {"role": "user", "content": "修复 bug"},
        {"role": "assistant", "content": "已完成修复。"},
    ]


def test_protocol_pressure_reasoning_only_does_not_duplicate_public_content() -> None:
    projected, stats = _protocol_pressure_message(
        {
            "role": "assistant",
            "content": "visible final answer already lives in public history",
            "reasoning_content": "private reasoning estimate",
        }
    )

    assert projected == {
        "role": "assistant",
        "reasoning_content": "private reasoning estimate",
    }
    assert stats["bounded_chars"] == len("private reasoning estimate")


def _runtime_with_session(tmp_path: Path):
    session_manager = SessionManager(tmp_path)
    session = session_manager.create_session(title="Compact API")
    session_id = session["id"]
    old_assistant_prose = "这是一段旧的过程性解释，主要记录当时如何理解问题，并不构成证据。 " * 90
    session_manager.append_messages(
        session_id,
        [
            {"role": "user", "content": "旧请求"},
            {"role": "assistant", "content": old_assistant_prose},
            {"role": "assistant", "content": "最近回复必须保留"},
            {"role": "user", "content": "当前请求必须保留"},
        ],
    )
    fake_session_memory = _FakeSessionMemory(tmp_path / "session-memory")
    fake_session_memory.manager.write_compaction_state(
        messages=session_manager.load_session(session_id),
        run_id="memory-maintenance:test-api",
        source="agent:1",
        source_message_refs=["message:api"],
        summary_content=fake_session_memory.manager.load(),
    )
    return (
        SimpleNamespace(
            session_manager=session_manager,
            settings=SimpleNamespace(
                static=SimpleNamespace(
                    llm_provider="deepseek",
                    llm_model="deepseek-v4-pro",
                    llm_max_output_tokens=65_536,
                ),
            ),
            memory_facade=SimpleNamespace(
                adapter=MemoryMessageAdapter(),
                session_memory=fake_session_memory,
            ),
        ),
        session_id,
        old_assistant_prose,
    )


class _FakeSessionMemory:
    def __init__(self, root: Path) -> None:
        self.manager = SessionMemoryManager(root)
        self.manager.overwrite("# Active Goal\n- 手动 compact API\n")

    def compactor(self, _session_id: str) -> ContextCompactor:
        return ContextCompactor(
            self.manager,
            max_messages=12,
            keep_recent_messages=2,
            full_compact_recent_messages=2,
            effective_history_token_budget=700,
            low_authority_text_token_threshold=10,
            low_authority_text_target_chars=140,
        )


class _ContextSnapshot:
    def __init__(self, *, auto_replacement_allowed: bool) -> None:
        self.auto_replacement_allowed = auto_replacement_allowed
        self.pressure_level = "normal"
        self.current_context_tokens = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "authority": "test.context_snapshot",
            "auto_replacement_allowed": self.auto_replacement_allowed,
            "pressure_level": self.pressure_level,
            "current_context_tokens": self.current_context_tokens,
        }
