from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade
from query import QueryRuntime


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return False


class _SessionManagerStub:
    def load_session_for_agent(self, _session_id: str, *, include_compressed_context: bool = False):
        return []


class _ToolRuntimeStub:
    registry = None
    instances: list[object] = []

    def get_instance(self, _name: str | None):
        return None


class _SkillRegistryStub:
    def format_active_skill_block(self, _active_skill):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])


class _ModelRuntimeStub:
    request_timeout_seconds = 30.0
    max_retries = 0


def _tempdir():
    tmp_root = REPO_ROOT / ".tmp-tests-runtime"
    tmp_root.mkdir(parents=True, exist_ok=True)
    path = tmp_root / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_runtime(root: Path) -> QueryRuntime:
    return QueryRuntime(
        base_dir=root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=MemoryFacade(root),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
        task_coordinator=SimpleNamespace(),
    )


def _capture(runtime: QueryRuntime, session_id: str, active_goal: str) -> None:
    runtime._capture_session_memory_projection(
        session_id,
        main_context_payload={
            "active_goal": active_goal,
            "active_work_item": "memory",
            "latest_correction": "",
            "next_step": "answer_current_request",
        },
        task_summary_payloads=[],
    )


def test_commit_durable_memory_extraction_drains_all_pending_projections() -> None:
    root = _tempdir()
    runtime = _build_runtime(root)
    session_id = "projection-queue"

    _capture(runtime, session_id, "记住：以后复杂问题先给结论。")
    _capture(runtime, session_id, "记住：回答我时可以直接称呼我岩。")

    saved = runtime.commit_durable_memory_extraction(session_id)
    notes = runtime.memory_facade.memory_manager.list_notes()
    canonicals = {note.canonical_statement for note in notes}

    assert saved >= 2
    assert "记住：以后复杂问题先给结论。" in canonicals
    assert "记住：回答我时可以直接称呼我岩。" in canonicals


def test_schedule_durable_memory_extraction_commits_explicit_write_without_waiting_for_threshold() -> None:
    root = _tempdir()
    runtime = _build_runtime(root)
    session_id = "projection-explicit-write"

    _capture(runtime, session_id, "记住：回答我时可以直接称呼我岩。")

    saved = runtime.schedule_durable_memory_extraction(session_id)
    notes = runtime.memory_facade.memory_manager.list_notes()

    assert saved >= 1
    assert any(note.canonical_statement == "记住：回答我时可以直接称呼我岩。" for note in notes)


def main() -> None:
    tests = [
        test_commit_durable_memory_extraction_drains_all_pending_projections,
        test_schedule_durable_memory_extraction_commits_explicit_write_without_waiting_for_threshold,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
