from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.capability_system import ResourcePolicyCandidateRequest, resource_policy_candidate, _safe_skill_name
from capability_system import (
    agent_tool_bindings,
    build_capability_catalog,
    build_capability_supply_package_from_catalog,
    default_tool_type,
    operation_tool_metadata,
    set_skill_prompt_view,
)
from capability_system.validation import validate_capability_catalog
from capability_system import build_default_operation_registry


def test_capability_system_default_tool_types_are_user_readable() -> None:
    assert default_tool_type({"name": "web_search", "capability_tags": ["web", "realtime"], "supported_modalities": []}) == "实时查询"
    assert default_tool_type({"name": "read_file", "capability_tags": ["file", "workspace"], "supported_modalities": []}) == "本地文件"
    assert default_tool_type({"name": "mcp_pdf", "capability_tags": ["pdf", "document"], "supported_modalities": []}) == "文档数据"
    assert default_tool_type({"name": "terminal", "capability_tags": [], "supported_modalities": [], "safety_tags": ["shell"]}) == "系统执行"


def test_capability_system_rejects_unsafe_skill_names() -> None:
    assert _safe_skill_name("demo-skill_1") == "demo-skill_1"

    for name in ["../bad", "x", "bad/name", "bad name"]:
        try:
            _safe_skill_name(name)
        except Exception:
            continue
        raise AssertionError(f"unsafe skill name was accepted: {name}")


def test_operation_tool_metadata_exposes_boundary_risk_and_agent_bindings() -> None:
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
    metadata = operation_tool_metadata(tool, {"tool_type": "系统执行", "note": "requires review"})

    assert metadata["tool_boundary"] == "系统执行"
    assert metadata["adapter_type"] == "本地命令"
    assert metadata["risk_level"] == "极高"
    assert metadata["runtime_policy"] == "需要显式触发"
    assert "建议保持人工确认" in metadata["governance_hints"]


def test_operation_agent_bindings_keep_pdf_tools_off_main_agent() -> None:
    tools = [
        {"name": "web_search", "runtime_visibility": "main_runtime"},
        {"name": "mcp_pdf", "runtime_visibility": "agent_internal"},
    ]

    bindings = agent_tool_bindings(tools)

    assert "web_search" in bindings["agent:0"]
    assert "mcp_pdf" not in bindings["agent:0"]
    assert set(bindings) == {"agent:0"}


def test_skill_prompt_view_updates_frontmatter(tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        """---
name: demo
description: demo skill
metadata:
  display_name: Demo
---

# Demo
""",
        encoding="utf-8",
    )

    prompt = set_skill_prompt_view(
        skill_path,
        {
            "name": "demo",
            "title": "Demo Skill",
            "capability": "Describe a repeatable method.",
            "use_when": "Use when the user asks for this workflow.",
            "output_rule": "Answer directly.",
        },
    )
    text = skill_path.read_text(encoding="utf-8")

    assert prompt["title"] == "Demo Skill"
    assert "prompt:" in text
    assert "Describe a repeatable method." in text


def test_capability_validation_detects_contract_edges() -> None:
    tools = [
        {
            "name": "terminal",
            "operation_id": "op.shell",
            "is_read_only": False,
            "is_destructive": True,
            "safety_tags": ["shell"],
        },
        {
            "name": "ghost",
            "operation_id": "op.ghost",
            "is_read_only": True,
        },
    ]
    operations = [
        {
            "operation_id": "op.shell",
            "aliases": ["terminal"],
            "requires_approval_by_default": True,
        },
        {
            "operation_id": "op.mcp_shell",
            "aliases": ["terminal"],
            "requires_approval_by_default": False,
        },
    ]

    issues = validate_capability_catalog(
        skills=[],
        tools=tools,
        agent_bindings={"agent:test": ["ghost", "missing_agent_tool"]},
        operations=operations,
        task_operation_ids=["op.unknown_task"],
    )
    codes = {issue.code for issue in issues}

    assert "tool_unknown_operation" in codes
    assert "agent_unknown_tool" in codes
    assert "duplicate_operation_alias" in codes
    assert "task_unknown_operation" in codes


def test_default_operation_registry_has_no_duplicate_aliases() -> None:
    operations = [operation.to_dict() for operation in build_default_operation_registry().list_operations()]
    issues = validate_capability_catalog(skills=[], tools=[], agent_bindings={}, operations=operations)

    assert not [issue for issue in issues if issue.code == "duplicate_operation_alias"]


def test_operation_catalog_includes_mcps_without_prompt_authorization_lists() -> None:
    class _Runtime:
        base_dir = ROOT

        def __init__(self) -> None:
            self.skill_registry = type("SkillRegistryStub", (), {"skills": []})()
            self.tool_runtime = type("ToolRuntimeStub", (), {"definitions": []})()

    catalog = build_capability_catalog(_Runtime())
    mcps = catalog["mcps"]
    endpoints = catalog["capability_endpoints"]
    text = str(catalog)

    assert catalog["summary"]["mcp_count"] == 3
    assert catalog["summary"]["capability_endpoint_count"] == len(endpoints)
    assert {mcp["operation_id"] for mcp in mcps} == {
        "op.mcp_retrieval",
        "op.mcp_pdf",
        "op.mcp_structured_data",
    }
    assert all(mcp["model_visibility"] == "not_direct_model_tool" for mcp in mcps)
    assert {endpoint["endpoint_id"] for endpoint in endpoints if endpoint["kind"] == "mcp_endpoint"} == {
        "endpoint:mcp:retrieval",
        "endpoint:mcp:pdf",
        "endpoint:mcp:structured_data",
    }
    assert "Denied:" not in text
    assert "preview_only" not in text


def test_capability_catalog_exposes_canonical_capability_units() -> None:
    class _Runtime:
        base_dir = ROOT

        def __init__(self) -> None:
            self.skill_registry = type("SkillRegistryStub", (), {"skills": []})()
            self.tool_runtime = type("ToolRuntimeStub", (), {"definitions": []})()

    catalog = build_capability_catalog(_Runtime())
    units = {item["capability_id"]: item for item in catalog["capability_units"]}

    assert "mcp:local:mcp:document:pdf:pdf" in units
    assert units["mcp:local:mcp:document:pdf:pdf"]["operation_ids"] == ["op.mcp_pdf"]
    assert units["mcp:local:mcp:document:pdf:pdf"]["provider_kind"] == "local"
    assert units["mcp:local:mcp:document:pdf:pdf"]["model_visibility"] == "not_direct_model_tool"
    assert units["mcp:local:mcp:document:pdf:pdf"]["permission_view"]["gate_state"] == "not_checked"
    assert units["mcp:local:mcp:document:pdf:pdf"]["permission_view"]["diagnostics"]["management_view_only"] is True
    assert catalog["summary"]["capability_unit_count"] == len(catalog["capability_units"])


def test_capability_validation_checks_capability_units() -> None:
    issues = validate_capability_catalog(
        skills=[],
        tools=[],
        agent_bindings={},
        operations=[{"operation_id": "op.known"}],
        capability_units=[
            {
                "capability_id": "mcp:local:bad",
                "kind": "mcp",
                "provider_kind": "local",
                "model_visibility": "schema_only",
                "operation_ids": ["op.missing"],
            },
            {
                "capability_id": "mcp:local:bad",
                "kind": "mcp",
                "provider_kind": "local",
                "model_visibility": "schema_only",
                "operation_ids": [],
            },
        ],
    )
    codes = {issue.code for issue in issues}

    assert "capability_unit_duplicate_id" in codes
    assert "capability_unit_unknown_operation" in codes
    assert "capability_unit_local_mcp_model_visibility_invalid" in codes


def test_capability_unit_projection_uses_skill_declared_operation_dependencies() -> None:
    from capability_system.capability_units import build_capability_units

    units = build_capability_units(
        {
            "skills": [
                {
                    "runtime": {
                        "name": "skill-creator",
                        "title": "Skill 创建顾问",
                        "description": "Skill authoring workflow.",
                        "path": "capability_system/units/skills/skill-creator/SKILL.md",
                        "preferred_route": "capability_authoring",
                        "activation_policy": "model_visible",
                        "context_mode": "inline",
                        "requires_operations": ["op.read_file", "op.write_file", "op.edit_file"],
                        "requires_capabilities": ["tool:read_file", "tool:write_file", "tool:edit_file"],
                    },
                    "prompt_view": {"title": "Skill 创建顾问", "capability": "Skill authoring workflow."},
                }
            ],
            "tools": [],
            "mcp_management": {"servers": []},
            "operations": [
                {"operation_id": "op.read_file", "risk_tags": ["read_only"]},
                {"operation_id": "op.write_file", "risk_tags": ["local_write"]},
                {"operation_id": "op.edit_file", "risk_tags": ["local_write"]},
            ],
        }
    )

    unit = units[0]
    assert unit["capability_id"] == "skill:skill-creator"
    assert unit["operation_ids"] == ["op.read_file", "op.write_file", "op.edit_file"]
    assert unit["display_facets"]["preferred_route"] == "capability_authoring"
    assert unit["permission_view"]["reasons"] == ["skill_declares_operation_dependencies"]


def test_capability_supply_package_filters_to_requested_operation_scope() -> None:
    package = build_capability_supply_package_from_catalog(
        {
            "skills": [
                {
                    "runtime": {
                        "name": "pdf-analysis",
                        "title": "PDF 分析",
                        "activation_policy": "model_visible",
                        "context_mode": "isolated",
                        "preferred_route": "pdf",
                        "capability_tags": ["document_analysis", "pdf"],
                        "requires_operations": ["op.mcp_pdf"],
                        "requires_capabilities": ["mcp:local:pdf"],
                    }
                }
            ],
            "tools": [
                {
                    "name": "mcp_pdf",
                    "operation_id": "op.mcp_pdf",
                    "runtime_visibility": "agent_internal",
                    "prompt_exposure_policy": "schema_only",
                    "operation_metadata": {
                        "tool_type": "文档数据",
                        "risk_level": "低",
                        "source_class": "document",
                    },
                },
                {
                    "name": "web_search",
                    "operation_id": "op.web_search",
                    "runtime_visibility": "main_runtime",
                    "prompt_exposure_policy": "schema_only",
                    "operation_metadata": {
                        "tool_type": "实时查询",
                        "risk_level": "低",
                        "source_class": "web",
                    },
                },
            ],
            "mcps": [
                {
                    "mcp_id": "mcp:document:pdf",
                    "operation_id": "op.mcp_pdf",
                    "route": "pdf",
                    "unit_id": "local_mcp:pdf",
                    "transport": "in_process",
                    "model_visibility": "not_direct_model_tool",
                }
            ],
        },
        task_id="task-pdf",
        operation_scope=["op.mcp_pdf"],
    )

    assert package.task_id == "task-pdf"
    assert [item.tool_name for item in package.tool_refs] == ["mcp_pdf"]
    assert [item.skill_name for item in package.skill_refs] == ["pdf-analysis"]
    assert package.skill_refs[0].preferred_route == "pdf"
    assert package.skill_refs[0].capability_tags == ("document_analysis", "pdf")
    assert package.skill_refs[0].operation_ids == ("op.mcp_pdf",)
    assert package.skill_refs[0].capability_ids == ("mcp:local:pdf",)
    assert [item.operation_id for item in package.mcp_refs] == ["op.mcp_pdf"]


def test_capability_supply_package_filters_skills_by_declared_operation_scope() -> None:
    package = build_capability_supply_package_from_catalog(
        {
            "skills": [
                {
                    "runtime": {
                        "name": "pdf-analysis",
                        "title": "PDF 分析",
                        "activation_policy": "model_visible",
                        "context_mode": "isolated",
                        "preferred_route": "pdf",
                        "capability_tags": ["document_analysis", "pdf"],
                        "requires_operations": ["op.mcp_pdf"],
                    }
                },
                {
                    "runtime": {
                        "name": "web-summary",
                        "title": "网页摘要",
                        "activation_policy": "model_visible",
                        "context_mode": "inline",
                        "preferred_route": "realtime_network",
                        "capability_tags": ["web"],
                        "requires_operations": ["op.web_search"],
                    }
                },
            ],
            "tools": [],
            "mcps": [],
        },
        task_id="task-web",
        operation_scope=["op.web_search"],
    )

    assert [item.skill_name for item in package.skill_refs] == ["web-summary"]
    assert package.skill_refs[0].operation_ids == ("op.web_search",)
    assert package.capability_constraints["operation_scope"] == ["op.web_search"]


def test_resource_policy_candidate_api_is_read_only_and_fail_closed() -> None:
    payload = ResourcePolicyCandidateRequest(
        task_id="api-task-1",
        operation_scope=["op.read_file", "op.edit_file"],
        approval_context={
            "interactive_ui_available": False,
            "headless_mode": True,
            "approval_hook_available": False,
            "bubble_to_parent_allowed": False,
        },
    )

    response = asyncio.run(resource_policy_candidate(payload))
    decisions = {item["operation_id"]: item for item in response["decisions"]}
    views = {item["resource_id"]: item for item in response["resource_runtime_views"]}

    assert response["operation_requirement"]["authority"] == "candidate_only"
    assert response["resource_policy"]["authority"] == "resource_policy"
    assert response["resource_policy"]["runtime_view_only"] is True
    assert response["resource_policy"]["adopted"] is False
    assert response["diagnostics"]["fail_closed"] is True
    assert decisions["op.read_file"]["decision"] == "allow"
    assert decisions["op.edit_file"]["decision"] == "deny"
    assert decisions["op.edit_file"]["reason"] == "approval unavailable in headless context"
    assert views["op.read_file"]["available_to_model"] is True
    assert views["op.read_file"]["runtime_executable"] is False
