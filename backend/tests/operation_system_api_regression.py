from __future__ import annotations

from pathlib import Path

from api.operations import _safe_skill_name
from capabilities import (
    agent_tool_bindings,
    default_tool_type,
    operation_tool_metadata,
    set_skill_allowed_tools,
)


def test_operation_system_default_tool_types_are_user_readable() -> None:
    assert default_tool_type({"name": "web_search", "capability_tags": ["web", "realtime"], "supported_modalities": []}) == "实时查询"
    assert default_tool_type({"name": "read_file", "capability_tags": ["file", "workspace"], "supported_modalities": []}) == "本地文件"
    assert default_tool_type({"name": "pdf_analysis", "capability_tags": ["pdf", "document"], "supported_modalities": []}) == "文档数据"
    assert default_tool_type({"name": "terminal", "capability_tags": [], "supported_modalities": [], "safety_tags": ["shell"]}) == "系统执行"


def test_operation_system_rejects_unsafe_skill_names() -> None:
    assert _safe_skill_name("demo-skill_1") == "demo-skill_1"

    for name in ["../bad", "x", "bad/name", "bad name"]:
        try:
            _safe_skill_name(name)
        except Exception:
            continue
        raise AssertionError(f"unsafe skill name was accepted: {name}")


def test_operation_tool_metadata_exposes_boundary_risk_and_skill_bindings() -> None:
    tool = {
        "name": "terminal",
        "capability_tags": ["shell", "terminal"],
        "supported_modalities": ["system"],
        "safety_tags": ["write", "shell", "destructive"],
        "route_hints": ["local_command"],
        "runtime_visibility": "agent_internal",
        "prompt_exposure_policy": "hidden",
        "resource_exposure_policy": "none",
        "safe_for_auto_route": False,
        "is_read_only": False,
        "is_destructive": True,
        "is_concurrency_safe": False,
    }
    skills = [
        {
            "runtime": {
                "name": "workspace-ops",
                "title": "工作区操作",
                "allowed_tools": ["terminal"],
                "activation_policy": "manual",
                "context_mode": "isolated",
            }
        }
    ]

    metadata = operation_tool_metadata(tool, {"tool_type": "系统执行", "note": "requires review"}, skills)

    assert metadata["tool_boundary"] == "系统执行"
    assert metadata["adapter_type"] == "本地命令"
    assert metadata["risk_level"] == "极高"
    assert metadata["runtime_policy"] == "需要显式触发"
    assert metadata["bound_skills"][0]["title"] == "工作区操作"
    assert "建议保持人工确认" in metadata["governance_hints"]


def test_operation_agent_bindings_keep_pdf_tools_off_main_agent() -> None:
    tools = [
        {"name": "web_search", "runtime_visibility": "main_runtime"},
        {"name": "pdf_analysis", "runtime_visibility": "agent_internal"},
        {"name": "analyze_multimodal_file", "runtime_visibility": "agent_internal"},
    ]

    bindings = agent_tool_bindings(tools)

    assert "web_search" in bindings["agent:main:conversation"]
    assert "pdf_analysis" not in bindings["agent:main:conversation"]
    assert "pdf_analysis" in bindings["agent:document:pdf"]


def test_operation_skill_tool_binding_updates_frontmatter(tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        """---
name: demo
description: demo skill
metadata:
  display_name: Demo
  allowed_tools:
    - old_tool
---

# Demo
""",
        encoding="utf-8",
    )

    allowed = set_skill_allowed_tools(skill_path, ["pdf_analysis", "unknown", "pdf_analysis"], {"pdf_analysis"})
    text = skill_path.read_text(encoding="utf-8")

    assert allowed == ["pdf_analysis"]
    assert "pdf_analysis" in text
    assert "unknown" not in text
