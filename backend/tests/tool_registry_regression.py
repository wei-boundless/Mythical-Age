from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "tools" / "tool_registry.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_registry_module():
    spec = importlib.util.spec_from_file_location("tool_registry_test", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load tool_registry.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    registry_module = load_registry_module()
    registry_module.refresh_tool_registry(ROOT)

    search_tool_source = (ROOT / "tools" / "search_knowledge_tool.py").read_text(encoding="utf-8")
    assert 'name: str = "search_knowledge"' in search_tool_source

    payload = json.loads((ROOT / "TOOLS_REGISTRY.json").read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["tool_count"] >= 6

    by_name = {tool["name"]: tool for tool in payload["tools"]}
    assert by_name["get_weather"]["safe_for_auto_route"] is True
    assert "weather" in by_name["get_weather"]["capability_tags"]
    assert "search_terms" not in by_name["get_weather"]
    assert "typical_queries" not in by_name["get_weather"]

    assert by_name["get_gold_price"]["safe_for_auto_route"] is True
    assert "gold" in by_name["get_gold_price"]["capability_tags"]
    assert "typical_queries" not in by_name["get_gold_price"]

    assert by_name["structured_data_analysis"]["safe_for_auto_route"] is True
    assert "table" in by_name["structured_data_analysis"]["supported_modalities"]
    assert by_name["structured_data_analysis"]["contract"]["owner_scope"] == "active_binding_or_explicit_path"
    assert by_name["structured_data_analysis"]["contract"]["required_bindings"] == ["active_dataset"]

    assert by_name["search_knowledge"]["safe_for_auto_route"] is True
    assert "faq" in by_name["search_knowledge"]["capability_tags"]
    assert "retrieval" in by_name["search_knowledge"]["safety_tags"]
    assert by_name["search_knowledge"]["contract"]["missing_binding_behavior"] == "fallback_to_rag"

    assert by_name["pdf_analysis"]["contract"]["owner_scope"] == "active_binding_or_explicit_path"
    assert by_name["pdf_analysis"]["contract"]["required_bindings"] == ["active_pdf"]

    assert by_name["python_repl"]["safe_for_auto_route"] is False
    assert by_name["terminal"]["safe_for_auto_route"] is False

    runtime_registry = registry_module.ToolRegistry(ROOT)
    assert runtime_registry.select_best(
        "北京今天天气怎么样",
        candidate_names=["get_weather", "web_search"],
        modality="realtime",
        route="tool",
        capability_requests=["weather"],
    ).name == "get_weather"
    assert runtime_registry.select_best(
        "白皮书第五页讲得什么",
        candidate_names=["pdf_analysis", "search_knowledge"],
        modality="pdf",
        route="tool",
        capability_requests=["document_analysis"],
    ).name == "pdf_analysis"
    assert runtime_registry.select_best(
        "查询黄金价格",
        candidate_names=["get_gold_price", "web_search"],
        modality="realtime",
        route="tool",
        capability_requests=["gold_price"],
    ).name == "get_gold_price"

    assert runtime_registry.resolve_candidate_names(
        capability_requests=["knowledge_lookup", "latest_information"],
        route="agent",
        modality="general",
    ) == ["search_knowledge", "web_search"]

    print(f"ALL PASSED ({payload['tool_count']} tools)")


if __name__ == "__main__":
    main()
