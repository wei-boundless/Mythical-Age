from __future__ import annotations

import tempfile
from pathlib import Path
import sys
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.long_term_context import build_long_term_context_bundle
from query.prompt_builder import build_system_prompt
from structured_memory import MemoryManager


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_long_term_context_bundle_layers_workspace_and_memory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root / "context_profile" / "agent_core" / "CORE.md", "# Agent Core\n\nCalm and direct.")
        _write(root / "context_profile" / "agent_core" / "ACTIVE_SEED.md", "# Active Soul Seed\n\nRiver-like and restrained.")
        _write(root / "context_profile" / "profile" / "agent.md", "# Agent Profile\n\nPrefer Chinese.")
        _write(root / "durable_memory" / "index" / "MEMORY.md", "# Memory Index\n\n- [PowerShell](powershell.md) - Prefer PowerShell.")

        bundle = build_long_term_context_bundle(root)
        rendered = bundle.render(truncate=lambda text, _limit: text, limit=9999)

        _assert("## 当前延续生效的设定" in rendered, "bundle should render semantic stable-settings section")
        _assert("## 你记得的长期事实" in rendered, "bundle should render semantic remembered-facts section")
        _assert("### 稳定原则" in rendered and "Calm and direct." in rendered, "agent core should map into semantic stable-principles label")
        _assert("### 当前风格" in rendered and "River-like and restrained." in rendered, "active seed should map into semantic current-style label")
        _assert("### 用户与项目偏好" in rendered and "Prefer Chinese." in rendered, "agent profile should map into semantic preferences label")
        _assert("PowerShell" in rendered, "durable memory should be included as dynamic memory")


def test_system_prompt_uses_unified_long_term_context_block() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root / "SKILLS_SNAPSHOT.md", "# Skills Snapshot\n\n- structured-data-analysis")
        _write(root / "context_profile" / "agent_core" / "CORE.md", "# Agent Core\n\nCalm and direct.")
        _write(root / "context_profile" / "agent_core" / "ACTIVE_SEED.md", "# Active Soul Seed\n\nRiver-like and restrained.")
        _write(root / "context_profile" / "profile" / "agent.md", "# Agent Profile\n\nPrefer Chinese.")
        _write(root / "durable_memory" / "index" / "MEMORY.md", "# Memory Index\n\n- [PowerShell](powershell.md) - Prefer PowerShell.")

        prompt = build_system_prompt(
            root,
            rag_mode=True,
            persistent_memory="## Exact Durable Memory Matches\n\n### PowerShell\nPrefer PowerShell syntax.",
            session_memory="# Active Goal\n\nKeep working.",
            active_skill="Structured data analysis is active.",
        )

        _assert("## 当前延续生效的设定" in prompt, "prompt should include semantic stable-settings block")
        _assert("## 当前最相关的已记住事实" in prompt, "prompt should expose turn-relevant remembered facts")
        _assert(
            prompt.index("## 当前情境") < prompt.index("## 当前最相关的已记住事实"),
            "session runtime context should appear before durable memory in the final prompt",
        )
        _assert("<!-- Soul -->" not in prompt, "legacy separate soul injection should be removed")
        _assert("<!-- Identity -->" not in prompt, "legacy separate identity injection should be removed")
        _assert("<!-- User Profile -->" not in prompt, "legacy separate user profile injection should be removed")
        _assert("<!-- Agents Guide -->" not in prompt, "legacy separate agents guide injection should be removed")
        _assert("Prefer PowerShell syntax." in prompt, "persistent memory override should flow into unified long-term context")
        _assert("constitution" not in prompt.lower(), "prompt should not expose constitution implementation term")
        _assert("profile" not in prompt.lower(), "prompt should not expose profile implementation term")
        _assert("long-term context" not in prompt.lower(), "prompt should not expose long-term-context implementation term")


def test_system_prompt_can_render_context_package_directly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root / "SKILLS_SNAPSHOT.md", "# Skills Snapshot\n\n- memory-system")

        package = SimpleNamespace(
            pressure_level="warning",
            sections={
                "active_process_context": [
                    "# Active Goal\n\nKeep the memory refactor moving.",
                    "# Current Task State\n\nPrompt assembly is being migrated to ContextPackage.",
                ],
                "retrieval_evidence": [
                    "knowledge/battery.md | knowledge: Battery chemistry affects energy density.",
                ],
                "warm_snapshots": [
                    "Return to PDF analysis if the user asks about report.pdf again.",
                ],
                "exact_durable_context": [
                    "Exact durable memory: Prefer PowerShell commands in this repo.",
                ],
            },
            selected_sections=[
                "active_process_context",
                "retrieval_evidence",
                "warm_snapshots",
                "exact_durable_context",
            ],
            dropped_sections=[],
            compaction_strategy="warning_only",
            compaction_decisions=[
                "warning pressure: keep active-process context intact and trim warm layers first if pressure grows",
            ],
            rebuild_reason="prompt_assembly",
        )

        prompt = build_system_prompt(
            root,
            rag_mode=True,
            persistent_memory=None,
            context_package=package,
            active_skill="Memory architecture refinement is active.",
        )

        _assert("## 当前情境" in prompt, "prompt should render current situation from the context package")
        _assert("Keep the memory refactor moving." in prompt, "active process context should render into the prompt")
        _assert("## Retrieval Evidence" in prompt, "retrieval section should render from the context package")
        _assert("Battery chemistry affects energy density." in prompt, "retrieval evidence should survive direct package rendering")
        _assert("<!-- Context Management -->" not in prompt, "context-management notes should stay out of the model-visible prompt")
        _assert("Pressure Level: warning" not in prompt, "prompt should not expose package pressure notes")
        _assert("## 当前最相关的已记住事实" in prompt, "durable memory section should still render with semantic heading")
        _assert("Prefer PowerShell commands in this repo." in prompt, "package durable context should be usable as a fallback durable block")


def test_memory_manager_stops_emitting_root_index_mirror() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        durable_root = root / "durable_memory"
        durable_root.mkdir(parents=True, exist_ok=True)
        _write(durable_root / "MEMORY.md", "# Legacy Memory Index\n\n- [Old](old.md) - legacy")

        MemoryManager(durable_root)
        bundle = build_long_term_context_bundle(root)

        _assert("Legacy Memory Index" in bundle.memory_block, "legacy root index should be migrated into the new index path")
        _assert((durable_root / "index" / "MEMORY.md").exists(), "new index path should exist after migration")
        _assert(not (durable_root / "MEMORY.md").exists(), "root durable index mirror should be removed after migration")


def main() -> None:
    tests = [
        test_long_term_context_bundle_layers_workspace_and_memory,
        test_system_prompt_uses_unified_long_term_context_block,
        test_system_prompt_can_render_context_package_directly,
        test_memory_manager_stops_emitting_root_index_mirror,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
