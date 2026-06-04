from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import tokens as tokens_api
from context_system.compaction.compactor import ContextCompactor
from memory_system.continuity import MemoryMessageAdapter
from memory_system.storage.session_memory import SessionMemoryManager
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

    assert response["applied"] is True
    assert response["did_full_compact"] is True
    assert response["compressed_context_present"] is True
    assert "Conversation history was compacted into a checkpoint" in record["compressed_context"]
    assert all(item["role"] != "system" for item in record["messages"])
    assert len(record["messages"]) <= 2
    assert runtime.session_manager.load_session_for_api(session_id)[1]["content"] == old_assistant_prose


def test_session_tokens_exposes_context_meter_and_billing_totals(tmp_path: Path, monkeypatch) -> None:
    runtime, session_id, _old_assistant_prose = _runtime_with_session(tmp_path)
    monkeypatch.setattr(tokens_api, "require_runtime", lambda: runtime)

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
    assert response["context_meter"]["authority"] == "runtime.prompt_accounting.context_usage_snapshot"
    assert response["context_meter"]["current_context_tokens"] > 0


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
    return (
        SimpleNamespace(
            session_manager=session_manager,
            memory_facade=SimpleNamespace(
                adapter=MemoryMessageAdapter(),
                session_memory=_FakeSessionMemory(tmp_path / "session-memory"),
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
