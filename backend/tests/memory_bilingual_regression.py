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
    _assert("project" in intent.preferred_types, "terminal convention should resolve to work/project preference if queried")
    _assert("work" in intent.preferred_memory_classes, "terminal convention should prefer work memory class")


def test_english_memory_read_intent() -> None:
    intent = analyze_memory_intent("What terminal syntax should we use by default from now on?")
    _assert(intent.intent == "memory_read_signal", "english semantic recall should become a weak durable-memory signal")
    _assert(intent.memory_read_mode == "none", "english semantic recall should no longer force durable read mode")
    _assert(intent.should_skip_rag is False, "english semantic recall should not bypass retrieval by default")
    _assert("project" in intent.preferred_types, "terminal recall should resolve to work/project preference if queried")


def test_english_manual_memory_inventory_query_stays_strong() -> None:
    intent = analyze_memory_intent("What do you remember about me?")
    _assert(intent.intent == "durable_memory_query", "explicit memory inventory query should stay a strong durable route")
    _assert(intent.memory_read_mode == "durable_exact", "explicit memory inventory query should use durable exact read")
    _assert(intent.should_skip_rag is True, "explicit memory inventory query should bypass retrieval")


def test_english_memory_policy_partitioning() -> None:
    work = evaluate_memory_write("Remember that from now on we always prefer PowerShell for terminal commands.")
    _assert(work.action == "ignore", "english workflow rule should stay out of dynamic durable memory")
    _assert(work.reason == "static_profile_rule", "english workflow rule should be treated as a static profile rule")

    pref = evaluate_memory_write("Remember that I prefer you to give the conclusion first and then explain.")
    _assert(pref.action == "durable_fact", "english answer-style preference should be durable")
    _assert(pref.memory_class == "preference", "english answer-style preference should map to preference")
    _assert(pref.memory_type == "user", "english answer-style preference should map to user durable type")


def test_english_extractor_filters_static_rules_and_saves_user_preference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        facade = MemoryFacade(Path(tmp))
        messages = [
            Message(role="user", content="Remember that from now on we always prefer PowerShell for terminal commands."),
            Message(role="user", content="Remember that I prefer you to give the conclusion first and then explain."),
        ]
        notes = facade.extractor.save_extracted(messages)
        classes = {note.memory_class for note in notes}
        titles = {note.title for note in notes}

        _assert("work" not in classes, "english workflow rule should not be saved into dynamic durable memory")
        _assert("preference" in classes, "english answer-style memory should be saved as preference")
        _assert(all("PowerShell" not in title for title in titles), "saved note titles should not retain static workflow rules")


def main() -> None:
    tests = [
        test_english_memory_write_intent,
        test_english_memory_read_intent,
        test_english_manual_memory_inventory_query_stays_strong,
        test_english_memory_policy_partitioning,
        test_english_extractor_filters_static_rules_and_saves_user_preference,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
