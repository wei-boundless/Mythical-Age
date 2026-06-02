from __future__ import annotations

from pathlib import Path

from memory_system.static_loader import load_static_context
from prompting.long_term_context import build_long_term_context_bundle


def test_static_context_does_not_load_development_agents_md(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    system_agents = backend_dir / "agent_context" / "AGENTS.md"
    project_agents = tmp_path / "AGENTS.md"
    system_agents.parent.mkdir(parents=True)
    system_agents.write_text("## 系统规则\n\n- 系统规则测试标记。", encoding="utf-8")
    project_agents.write_text("## 项目规则\n\n- 项目规则测试标记。", encoding="utf-8")

    bundle = load_static_context(backend_dir)
    sections = bundle.ordered_sections()

    assert sections == []


def test_long_term_context_does_not_promote_agents_md_to_runtime_prompt(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    system_agents = backend_dir / "agent_context" / "AGENTS.md"
    project_agents = tmp_path / "AGENTS.md"
    system_agents.parent.mkdir(parents=True)
    system_agents.write_text("## 系统规则\n\n- 不应进入模型。", encoding="utf-8")
    project_agents.write_text("## 项目规则\n\n- 不应进入模型。", encoding="utf-8")

    bundle = build_long_term_context_bundle(backend_dir, persistent_memory="")

    assert bundle.static_sections == []
