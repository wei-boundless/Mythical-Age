from __future__ import annotations

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from structured_memory import ExtractionConfig, ExtractionScheduler, Message, MemoryNote


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


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    extractor = FakeExtractor()
    scheduler = ExtractionScheduler(
        extractor,
        config=ExtractionConfig(min_messages_between_runs=1),
    )

    messages = [
        Message(role="user", content="记住我们以后默认用 PowerShell"),
        Message(role="assistant", content="我会按这个约定执行。"),
    ]

    first_saved = scheduler.submit(messages)
    _assert(first_saved == 1, "first submission should trigger extraction")
    _assert(len(extractor.calls) == 1, "extractor should run on first submission")

    second_saved = scheduler.submit(messages)
    _assert(second_saved == 0, "identical transcript should be skipped on second submission")
    _assert(len(extractor.calls) == 1, "extractor should not rerun for identical transcript")

    updated_messages = messages + [Message(role="user", content="再记住：项目重点是优化 memory 和 rag")]
    third_saved = scheduler.submit(updated_messages)
    _assert(third_saved == 1, "new transcript content should trigger extraction again")
    _assert(len(extractor.calls) == 2, "extractor should rerun when transcript changes")

    print("ALL PASSED (memory scheduler)")


if __name__ == "__main__":
    main()
