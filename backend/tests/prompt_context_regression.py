from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.prompt_builder import (
    build_session_memoized_prompt,
    build_static_prompt,
    build_system_prompt,
    build_turn_prompt,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_prompt_builder_splits_static_session_and_turn_layers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root / "SKILLS_SNAPSHOT.md", "# Skills Snapshot\n\n- prompt-test")
        _write(root / "context_profile" / "constitution" / "SOUL.md", "# Soul\n\nCalm and direct.")
        _write(root / "context_profile" / "constitution" / "IDENTITY.md", "# Identity\n\nLocal-first agent.")
        _write(root / "context_profile" / "profile" / "USER.md", "# User\n\nPrefer concise answers.")
        _write(root / "context_profile" / "profile" / "AGENTS.md", "# Agents\n\nPrefer transparent execution.")

        package = SimpleNamespace(
            sections={
                "active_process_context": ["# Active Goal\n\nKeep the prompt clean."],
                "retrieval_evidence": ["knowledge/a.md | knowledge: grounded evidence"],
                "exact_durable_context": ["Exact durable memory: Prefer PowerShell commands in this repo."],
            },
            model_visible_sections={
                "active_process_context": ["# Active Goal\n\nKeep the prompt clean."],
                "retrieval_evidence": ["knowledge/a.md | knowledge: grounded evidence"],
                "exact_durable_context": ["Exact durable memory: Prefer PowerShell commands in this repo."],
            },
            debug_sections={
                "active_process_context": ["# Active Goal\n\nKeep the prompt clean."],
                "retrieval_evidence": ["knowledge/a.md | knowledge: grounded evidence"],
                "exact_durable_context": ["Exact durable memory: Prefer PowerShell commands in this repo."],
                "debug_session_trace": ["# Next Step\n\n- Debug-only next step should stay out of prompt."],
            },
            pressure_level="warning",
            selected_sections=["active_process_context", "retrieval_evidence", "exact_durable_context"],
            debug_selected_sections=[
                "active_process_context",
                "retrieval_evidence",
                "exact_durable_context",
                "debug_session_trace",
            ],
            dropped_sections=["warm_snapshots"],
            compaction_strategy="warning_only",
            compaction_decisions=["warning pressure"],
            rebuild_reason="prompt_assembly",
        )

        static_prompt = build_static_prompt(root, True)
        session_prompt = build_session_memoized_prompt(
            context_package=package,
            active_skill="Prompt hygiene skill is active.",
        )
        turn_prompt = build_turn_prompt(
            persistent_memory=None,
            context_package=package,
        )
        full_prompt = build_system_prompt(
            root,
            rag_mode=True,
            persistent_memory=None,
            context_package=package,
            active_skill="Prompt hygiene skill is active.",
        )

        _assert("<!-- Skills Snapshot -->" in static_prompt, "static layer should include skills snapshot")
        _assert("<!-- Long-Term Context -->" in static_prompt, "static layer should include long-term context")
        _assert("<!-- Session Memory -->" in session_prompt, "session layer should include session memory")
        _assert("grounded evidence" in session_prompt, "session layer should carry summarized retrieval evidence")
        _assert("<!-- Durable Memory -->" in turn_prompt, "turn layer should include durable memory")
        _assert("<!-- Context Management -->" not in full_prompt, "full prompt should exclude context-management notes")
        _assert("Selected Sections:" not in full_prompt, "full prompt should exclude selection metadata")
        _assert("Dropped Sections:" not in full_prompt, "full prompt should exclude dropped-section metadata")
        _assert("Debug-only next step" not in full_prompt, "full prompt should stay on model-visible sections only")


def main() -> None:
    test_prompt_builder_splits_static_session_and_turn_layers()
    print("ALL PASSED (prompt context regression)")


if __name__ == "__main__":
    main()
