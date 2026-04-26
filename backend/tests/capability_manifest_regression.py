from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from capabilities import build_operation_catalog
from capabilities.search_policy import classify_tool_source
from skill_system.contracts import SkillPromptContract, SkillRuntimeContract


@dataclass(slots=True)
class FakeToolDefinition:
    record: dict[str, Any]

    def to_registry_record(self) -> dict[str, Any]:
        return dict(self.record)


class FakeSkill:
    def __init__(self, runtime: SkillRuntimeContract) -> None:
        self.runtime = runtime
        self.prompt_view = SkillPromptContract(runtime.name, runtime.title, runtime.description)
        self.validation_errors: list[str] = []

    def render_prompt_block(self) -> str:
        return self.prompt_view.render_block()


def test_capability_manifest_exports_agent_tool_ownership(tmp_path: Path) -> None:
    skill_file = tmp_path / "skills" / "pdf-reading" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# PDF Reading\n", encoding="utf-8")
    skill = FakeSkill(
        SkillRuntimeContract(
            name="pdf-reading",
            title="PDF 阅读",
            description="读取 PDF 内容。",
            path="skills/pdf-reading/SKILL.md",
            allowed_tools=["pdf_analysis"],
        )
    )
    runtime = SimpleNamespace(
        base_dir=tmp_path,
        skill_registry=SimpleNamespace(skills=[skill]),
        tool_runtime=SimpleNamespace(
            definitions=[
                FakeToolDefinition(
                    {
                        "name": "web_search",
                        "module": "tools.web_search_tool",
                        "runtime_visibility": "main_runtime",
                        "capability_tags": ["web"],
                        "supported_modalities": ["realtime"],
                        "safety_tags": ["read", "network"],
                        "route_hints": ["latest_information"],
                        "resource_exposure_policy": "none",
                        "prompt_exposure_policy": "schema_only",
                        "safe_for_auto_route": True,
                        "is_read_only": True,
                        "is_destructive": False,
                        "is_concurrency_safe": True,
                        "contract": {},
                        "resolution_contract": {},
                        "output_contract": {},
                        "projection_contract": {},
                    }
                ),
                FakeToolDefinition(
                    {
                        "name": "pdf_analysis",
                        "module": "tools.pdf_analysis_tool",
                        "runtime_visibility": "agent_internal",
                        "capability_tags": ["pdf", "document"],
                        "supported_modalities": ["pdf"],
                        "safety_tags": ["read", "compute"],
                        "route_hints": ["document_analysis"],
                        "resource_exposure_policy": "handle_only",
                        "prompt_exposure_policy": "hidden",
                        "safe_for_auto_route": True,
                        "is_read_only": True,
                        "is_destructive": False,
                        "is_concurrency_safe": True,
                        "contract": {},
                        "resolution_contract": {},
                        "output_contract": {},
                        "projection_contract": {},
                    }
                ),
            ]
        ),
    )

    catalog = build_operation_catalog(runtime, {})
    pdf_tool = next(tool for tool in catalog["tools"] if tool["name"] == "pdf_analysis")
    web_tool = next(tool for tool in catalog["tools"] if tool["name"] == "web_search")

    assert web_tool["operation_metadata"]["ownership_label"] == "主会话智能体"
    assert "文档智能体" in pdf_tool["operation_metadata"]["ownership_label"]
    assert "PDF 阅读" in [item["title"] for item in pdf_tool["operation_metadata"]["bound_skills"]]
    assert catalog["summary"]["tool_sources"]["document"] == 1
    assert catalog["validation_issues"] == []


def test_capability_search_source_classification_is_stable() -> None:
    assert classify_tool_source({"name": "search_knowledge", "capability_tags": ["rag"]}) == "rag"
    assert classify_tool_source({"name": "search_files", "capability_tags": ["file", "workspace"]}) == "local_files"
    assert classify_tool_source({"name": "web_search", "supported_modalities": ["web"]}) == "web"
    assert classify_tool_source({"name": "terminal", "safety_tags": ["shell"]}) == "system_execution"
