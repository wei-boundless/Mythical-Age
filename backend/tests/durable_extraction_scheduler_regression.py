from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from structured_memory import ExtractionConfig, ExtractionScheduler, MemoryNote, Message


class FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    def save_extracted(self, messages: list[Message]) -> list[MemoryNote]:
        self.calls.append(list(messages))
        return [
            MemoryNote(
                slug=f"note-{len(self.calls)}",
                title="测试记忆",
                summary="测试记忆摘要",
                body="测试记忆正文",
            )
        ]


class FlakyExtractor:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.fail_next = True

    def save_extracted(self, messages: list[Message]) -> list[MemoryNote]:
        self.calls.append(list(messages))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated extraction failure")
        return [
            MemoryNote(
                slug=f"note-{len(self.calls)}",
                title="测试记忆",
                summary="测试记忆摘要",
                body="测试记忆正文",
            )
        ]


def test_scheduler_tracks_runtime_state_and_cursor() -> None:
    extractor = FakeExtractor()
    scheduler = ExtractionScheduler(
        extractor,
        config=ExtractionConfig(min_messages_between_runs=1),
    )

    messages = [
        Message(role="user", content="记住我以后喜欢先给结论。"),
        Message(role="assistant", content="我会默认先给结论。"),
    ]

    saved = scheduler.submit(messages)
    state = scheduler.describe_runtime_state()

    assert saved == 1
    assert state["in_progress"] is False
    assert state["has_pending_messages"] is False
    assert state["last_processed_signature"]
    assert "assistant:我会默认先给结论。" in state["last_processed_cursor"]


def test_scheduler_skips_identical_transcript_and_exposes_pending_defaults() -> None:
    extractor = FakeExtractor()
    scheduler = ExtractionScheduler(
        extractor,
        config=ExtractionConfig(min_messages_between_runs=1),
    )

    messages = [
        Message(role="user", content="记住项目重点是优化 memory。"),
        Message(role="assistant", content="我记下来了。"),
    ]

    first_saved = scheduler.submit(messages)
    second_saved = scheduler.submit(messages)
    state = scheduler.describe_runtime_state()

    assert first_saved == 1
    assert second_saved == 0
    assert state["pending_message_count"] == 0
    assert state["last_pending_signature"] == ""


def test_scheduler_failure_does_not_advance_cursor_and_next_run_can_recover() -> None:
    extractor = FlakyExtractor()
    scheduler = ExtractionScheduler(
        extractor,
        config=ExtractionConfig(min_messages_between_runs=1),
    )

    first_messages = [
        Message(role="user", content="记住这个失败场景。"),
        Message(role="assistant", content="第一次会失败。"),
    ]
    second_messages = [
        Message(role="user", content="记住这个恢复场景。"),
        Message(role="assistant", content="第二次应该成功。"),
    ]

    first_saved = scheduler.submit(first_messages)
    failed_state = scheduler.describe_runtime_state()
    second_saved = scheduler.submit(second_messages)
    recovered_state = scheduler.describe_runtime_state()

    assert first_saved == 0
    assert failed_state["last_run_status"] == "failed"
    assert failed_state["last_error"].startswith("RuntimeError:")
    assert failed_state["last_processed_signature"] == ""
    assert failed_state["last_processed_message_cursor"] == ""
    assert second_saved == 1
    assert recovered_state["last_run_status"] == "completed"
    assert "assistant:第二次应该成功。" in recovered_state["last_processed_message_cursor"]
