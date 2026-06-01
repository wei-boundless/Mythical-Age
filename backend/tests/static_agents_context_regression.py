from __future__ import annotations

from pathlib import Path

from memory_system.static_loader import load_static_context


def test_static_context_loads_system_and_project_agents_md(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    system_agents = backend_dir / "agent_context" / "AGENTS.md"
    project_agents = tmp_path / "AGENTS.md"
    system_agents.parent.mkdir(parents=True)
    system_agents.write_text("## 系统规则\n\n- 系统规则测试标记。", encoding="utf-8")
    project_agents.write_text("## 项目规则\n\n- 项目规则测试标记。", encoding="utf-8")

    bundle = load_static_context(backend_dir)
    sections = {entry.key: entry for entry in bundle.ordered_sections()}

    assert tuple(sections) == ("system_agents_rules", "project_agents_rules")
    assert sections["system_agents_rules"].prompt_heading == "系统 AGENTS 规则"
    assert sections["system_agents_rules"].relative_path == "backend/agent_context/AGENTS.md"
    assert "系统规则测试标记" in sections["system_agents_rules"].content
    assert sections["project_agents_rules"].prompt_heading == "项目 AGENTS 规则"
    assert sections["project_agents_rules"].relative_path == "AGENTS.md"
    assert "项目规则测试标记" in sections["project_agents_rules"].content
