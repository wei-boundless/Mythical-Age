from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade
from structured_memory import Message
from understanding.memory_intent import analyze_memory_intent
from understanding.memory_policy import evaluate_memory_write


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_english_memory_write_intent() -> None:
    intent = analyze_memory_intent("Remember that from now on we always prefer PowerShell for terminal commands.")
    _assert(intent.intent == "durable_memory_statement", "english remember statement should map to durable memory write")
    _assert(intent.memory_write_mode == "durable_fact", "english remember statement should request durable write")
    _assert("workflow" in intent.preferred_types, "terminal convention should prefer workflow type")
    _assert("work" in intent.preferred_memory_classes, "terminal convention should prefer work memory class")


def test_english_memory_read_intent() -> None:
    intent = analyze_memory_intent("What terminal syntax should we use by default from now on?")
    _assert(intent.intent == "durable_memory_query", "english recall query should map to durable memory read")
    _assert(intent.memory_read_mode == "durable_exact", "english recall query should request durable exact read")
    _assert("workflow" in intent.preferred_types, "terminal recall should prefer workflow type")


def test_english_memory_policy_partitioning() -> None:
    work = evaluate_memory_write("Remember that from now on we always prefer PowerShell for terminal commands.")
    _assert(work.action == "durable_fact", "english workflow rule should be durable")
    _assert(work.memory_class == "work", "english workflow rule should map to work")
    _assert(work.memory_type == "workflow", "english workflow rule should map to workflow")

    pref = evaluate_memory_write("Remember that I prefer you to give the conclusion first and then explain.")
    _assert(pref.action == "durable_fact", "english answer-style preference should be durable")
    _assert(pref.memory_class == "preference", "english answer-style preference should map to preference")
    _assert(pref.memory_type == "preference", "english answer-style preference should map to preference type")


def test_english_extractor_saves_both_work_and_preference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        facade = MemoryFacade(Path(tmp))
        messages = [
            Message(role="user", content="Remember that from now on we always prefer PowerShell for terminal commands."),
            Message(role="user", content="Remember that I prefer you to give the conclusion first and then explain."),
        ]
        notes = facade.extractor.save_extracted(messages)
        classes = {note.memory_class for note in notes}
        titles = {note.title for note in notes}

        _assert("work" in classes, "english workflow memory should be saved as work")
        _assert("preference" in classes, "english answer-style memory should be saved as preference")
        _assert(any("PowerShell" in title for title in titles), "saved note titles should preserve the PowerShell convention")


def main() -> None:
    tests = [
        test_english_memory_write_intent,
        test_english_memory_read_intent,
        test_english_memory_policy_partitioning,
        test_english_extractor_saves_both_work_and_preference,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
