from __future__ import annotations

from api.operations import _operation_tool_metadata, _safe_skill_name, _default_tool_type


def test_operation_system_default_tool_types_are_user_readable() -> None:
    assert _default_tool_type({"name": "web_search", "capability_tags": ["web", "realtime"], "supported_modalities": []}) == "实时查询"
    assert _default_tool_type({"name": "read_file", "capability_tags": ["file", "workspace"], "supported_modalities": []}) == "本地文件"
    assert _default_tool_type({"name": "pdf_analysis", "capability_tags": ["pdf", "document"], "supported_modalities": []}) == "文档数据"
    assert _default_tool_type({"name": "terminal", "capability_tags": [], "supported_modalities": [], "safety_tags": ["shell"]}) == "系统执行"


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

    metadata = _operation_tool_metadata(tool, {"tool_type": "系统执行", "note": "requires review"}, skills)

    assert metadata["tool_boundary"] == "系统执行"
    assert metadata["adapter_type"] == "本地命令"
    assert metadata["risk_level"] == "极高"
    assert metadata["runtime_policy"] == "需要显式触发"
    assert metadata["bound_skills"][0]["title"] == "工作区操作"
    assert "建议保持人工确认" in metadata["governance_hints"]
