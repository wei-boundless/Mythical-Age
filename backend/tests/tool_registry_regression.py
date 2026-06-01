from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "capability_system" / "tools" / "registry.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tools.paths import CapabilityToolPaths


def load_registry_module():
    spec = importlib.util.spec_from_file_location("tool_registry_test", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load tool_registry.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    tool_paths = CapabilityToolPaths.from_base_dir(ROOT)
    registry_module = load_registry_module()
    registry_module.refresh_tool_registry(ROOT)

    payload = json.loads(tool_paths.tools_registry_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["tool_count"] >= 23
    assert payload["tool_packages"]
    assert any(item["package_id"] == "pkg.development.python" and item["category"] == "开发工具" for item in payload["tool_packages"])
    assert any(item["package_id"] == "pkg.git.read" for item in payload["tool_packages"])
    assert any(item["package_id"] == "pkg.git.write" for item in payload["tool_packages"])

    by_name = {tool["name"]: tool for tool in payload["tools"]}
    assert "get_weather" not in by_name
    assert "get_gold_price" not in by_name
    assert "structured_data_analysis" not in by_name
    assert "pdf_analysis" not in by_name

    assert "workspace_path_search" in by_name["search_files"]["route_hints"]
    assert "workspace_search" not in by_name["search_files"]["route_hints"]
    assert "workspace_text_search" in by_name["search_text"]["route_hints"]
    assert "workspace_search" not in by_name["search_text"]["route_hints"]
    for name in [
        "list_dir",
        "stat_path",
        "path_exists",
        "glob_paths",
        "read_structured_file",
        "python_code_outline",
        "python_parse_check",
        "python_symbol_search",
        "text_metric",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch_list",
    ]:
        assert name in by_name
        assert by_name[name]["is_read_only"] is True
        assert by_name[name]["is_destructive"] is False

    for name in [
        "git_branch_create",
        "git_stage",
        "git_unstage",
        "git_commit",
        "git_restore",
        "git_push",
    ]:
        assert name in by_name
        assert by_name[name]["is_read_only"] is False

    assert by_name["python_repl"]["safe_for_auto_route"] is False
    assert by_name["python_code_outline"]["operation_id"] == "op.python_code_outline"
    assert by_name["python_parse_check"]["operation_id"] == "op.python_parse_check"
    assert by_name["python_symbol_search"]["operation_id"] == "op.python_symbol_search"
    assert "official_ast" in by_name["python_code_outline"]["safety_tags"]
    assert by_name["terminal"]["safe_for_auto_route"] is False
    assert by_name["text_metric"]["operation_id"] == "op.text_metric"
    assert "length_budget" in by_name["text_metric"]["capability_tags"]

    runtime_registry = registry_module.ToolRegistry(ROOT)
    assert runtime_registry.select_best(
        "北京今天天气怎么样",
        candidate_names=["web_search"],
        modality="realtime",
        route="realtime_network",
        capability_requests=["weather", "latest_information"],
    ).name == "web_search"
    assert runtime_registry.select_best(
        "查询黄金价格",
        candidate_names=["web_search"],
        modality="realtime",
        route="realtime_network",
        capability_requests=["gold_price", "latest_information"],
    ).name == "web_search"

    assert runtime_registry.resolve_candidate_names(
        capability_requests=["knowledge_lookup", "latest_information"],
        route="agent",
        modality="general",
    ) == ["web_search"]

    fake_tool = replace(runtime_registry.tools[0], name="dynamic_test_tool")
    runtime_registry._tools = [fake_tool]
    assert runtime_registry.get_by_name("dynamic_test_tool") is fake_tool
    assert runtime_registry.get_by_name("web_search") is None

    print(f"ALL PASSED ({payload['tool_count']} tools)")


if __name__ == "__main__":
    main()


