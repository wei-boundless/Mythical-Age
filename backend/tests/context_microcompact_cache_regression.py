from __future__ import annotations

from context_system.compaction.compactor import ContextCompactor
from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager


def test_cache_warm_microcompact_does_not_rewrite_local_history(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=12,
        keep_recent_messages=2,
        effective_history_token_budget=900,
        low_authority_text_token_threshold=10,
        low_authority_text_target_chars=140,
    )
    old_assistant_prose = "这是一段旧的过程性解释，主要记录当时如何理解问题，并不构成证据。 " * 90
    messages = [
        Message(role="user", content="旧请求"),
        Message(role="assistant", content=old_assistant_prose),
        Message(role="assistant", content="最近回复必须保留"),
        Message(role="user", content="当前请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="microcompact",
        request_id="ctxcompact:cache-warm",
        microcompact_cache_state={
            "status": "hit",
            "cached_tokens": 800,
            "provider_cache_editing_supported": False,
            "cache_record_id": "pcache:warm",
        },
    )

    assert result.strategy == "microcompact_skipped_cache_warm"
    assert result.did_microcompact is False
    assert result.replaced_message_count == 0
    assert result.messages[1].content == old_assistant_prose
    decision = result.diagnostics["microcompact_cache_decision"]
    assert decision["local_rewrite_allowed"] is False
    assert decision["cache_temperature"] == "warm"
    assert decision["reason"] == "cache_warm_provider_cache_editing_unavailable"
    assert result.diagnostics["low_authority_text_compressed_count"] == 0


def test_cache_cold_microcompact_can_compress_low_authority_history(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=12,
        keep_recent_messages=2,
        effective_history_token_budget=900,
        low_authority_text_token_threshold=10,
        low_authority_text_target_chars=140,
    )
    old_assistant_prose = "这是一段旧的过程性解释，主要记录当时如何理解问题，并不构成证据。 " * 90
    messages = [
        Message(role="user", content="旧请求"),
        Message(role="assistant", content=old_assistant_prose),
        Message(role="assistant", content="最近回复必须保留"),
        Message(role="user", content="当前请求必须保留"),
    ]

    result = compactor.apply_strategy(
        messages,
        pressure_level="microcompact",
        request_id="ctxcompact:cache-cold",
        microcompact_cache_state={
            "status": "miss",
            "cached_tokens": 0,
            "provider_cache_editing_supported": False,
            "cache_record_id": "pcache:cold",
        },
    )

    assert result.strategy == "microcompact"
    assert result.did_microcompact is True
    assert result.replaced_message_count == 1
    assert result.messages[1].meta["kind"] == "low_authority_text_compressed"
    decision = result.diagnostics["microcompact_cache_decision"]
    assert decision["local_rewrite_allowed"] is True
    assert decision["cache_temperature"] == "cold"
