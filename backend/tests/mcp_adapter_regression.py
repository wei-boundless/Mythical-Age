from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from tools.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION, build_mcp_tool_catalog, get_mcp_tool_view


def main() -> None:
    pdf_view = get_mcp_tool_view("pdf_analysis")
    assert pdf_view is not None
    assert pdf_view.protocol_version == MCP_COMPATIBLE_PROTOCOL_VERSION
    assert pdf_view.schema_identity == "local.tools/pdf_analysis"
    assert pdf_view.runtime_visibility == "agent_internal"
    assert pdf_view.prompt_exposure_policy == "hidden"
    assert pdf_view.resource_exposure_policy == "handle_only"
    assert pdf_view.input_schema["required"] == ["query"]
    assert pdf_view.input_schema["required_bindings"] == ["active_pdf"]
    assert pdf_view.output_schema["finalization_policy"] == "route_required"
    assert pdf_view.annotations["read_only_hint"] is True

    weather_view = get_mcp_tool_view("get_weather")
    assert weather_view is not None
    assert weather_view.runtime_visibility == "main_runtime"
    assert weather_view.prompt_exposure_policy == "schema_only"

    public_catalog = build_mcp_tool_catalog(include_agent_internal=False)
    public_tool_names = {tool["tool_name"] for tool in public_catalog["tools"]}
    assert "get_weather" in public_tool_names
    assert "pdf_analysis" not in public_tool_names
    assert "search_knowledge" not in public_tool_names

    full_catalog = build_mcp_tool_catalog()
    full_tool_names = {tool["tool_name"] for tool in full_catalog["tools"]}
    assert {"pdf_analysis", "search_knowledge", "structured_data_analysis"} <= full_tool_names

    print("ALL PASSED (mcp adapter regression)")


if __name__ == "__main__":
    main()
