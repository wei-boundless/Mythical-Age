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
from query.context_models import MainContextState


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
        _write(root / "soul" / "agent_core" / "CORE.md", "# Agent Core\n\nCalm and direct.")
        _write(root / "soul" / "agent_core" / "ACTIVE_SEED.md", "# Active Soul Seed\n\nRiver-like and restrained.")
        _write(root / "soul" / "agent.md", "# Agent Profile\n\nPrefer concise answers.")

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

        _assert("## 当前可用能力摘要" in static_prompt, "static layer should include capability summary heading")
        _assert("## 当前延续生效的设定" in static_prompt, "static layer should include semantic stable-context heading")
        _assert("River-like and restrained." in static_prompt, "static layer should include active soul seed")
        _assert(
            static_prompt.index("## 当前可用能力摘要") < static_prompt.index("## 当前延续生效的设定"),
            "capability summary should be assembled before the static soul block",
        )
        _assert(
            static_prompt.index("### 当前风格")
            < static_prompt.index("### 稳定原则")
            < static_prompt.index("### 用户与项目偏好"),
            "static soul block should follow the fixed order: active seed -> core -> profile",
        )
        _assert("## 当前情境" in session_prompt, "session layer should include current situation heading")
        _assert("grounded evidence" in session_prompt, "session layer should carry summarized retrieval evidence")
        _assert("## 当前最相关的已记住事实" in turn_prompt, "turn layer should include remembered-facts heading")
        _assert("<!-- Context Management -->" not in full_prompt, "full prompt should exclude context-management notes")
        _assert("Selected Sections:" not in full_prompt, "full prompt should exclude selection metadata")
        _assert("Dropped Sections:" not in full_prompt, "full prompt should exclude dropped-section metadata")
        _assert("Debug-only next step" not in full_prompt, "full prompt should stay on model-visible sections only")
        _assert(
            full_prompt.index("## 当前延续生效的设定")
            < full_prompt.index("## 当前情境")
            < full_prompt.index("## 当前最相关的已记住事实"),
            "system prompt should assemble in the fixed order: static -> session -> durable",
        )
        _assert("long-term context" not in full_prompt.lower(), "prompt should not expose long-term-context implementation term")
        _assert("constitution" not in full_prompt.lower(), "prompt should not expose constitution implementation term")
        _assert("profile" not in full_prompt.lower(), "prompt should not expose profile implementation term")


def test_main_context_prompt_masks_bindings_and_handles() -> None:
    block = MainContextState(
        active_goal="继续分析 PDF。",
        active_binding_identity="knowledge/reports/report.pdf",
        active_object_handle_id="source:pdf:secret",
        active_result_handle_id="result:pdf_summary:secret",
        active_subset_handle_id="subset:selection:secret",
        followup_target_task_id="task-secret",
        followup_target_task_ids=["task-secret", "task-other"],
        followup_binding_identity="knowledge/reports/report.pdf",
        followup_binding_owner_task_id="task-secret",
        active_constraints={
            "active_pdf": "knowledge/reports/report.pdf",
            "active_dataset": "knowledge/data/inventory.xlsx",
            "active_binding_identity": "knowledge/reports/report.pdf",
            "source_kind": "pdf",
            "page": 3,
            "active_pdf_mode": "page",
        },
    ).to_prompt_block()

    _assert("knowledge/reports/report.pdf" not in block, "prompt block must not expose concrete PDF paths")
    _assert("knowledge/data/inventory.xlsx" not in block, "prompt block must not expose concrete dataset paths")
    _assert("source:pdf:secret" not in block, "prompt block must not expose object handle ids")
    _assert("result:pdf_summary:secret" not in block, "prompt block must not expose result handle ids")
    _assert("task-secret" not in block, "prompt block must not expose task ids")
    _assert("Active Binding: available" in block, "prompt block should preserve availability signal")
    _assert("Active Evidence Result: available" in block, "prompt block should preserve result availability signal")
    _assert("page=3" in block, "prompt block should keep safe page constraint")
    _assert("pdf_mode=page" in block, "prompt block should keep safe pdf mode constraint")


def main() -> None:
    test_prompt_builder_splits_static_session_and_turn_layers()
    test_main_context_prompt_masks_bindings_and_handles()
    print("ALL PASSED (prompt context regression)")


if __name__ == "__main__":
    main()
