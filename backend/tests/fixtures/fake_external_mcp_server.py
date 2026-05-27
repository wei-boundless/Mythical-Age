from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


mcp = FastMCP("fake_external_mcp")


@mcp.resource("skill://external-demo", name="external_demo_skill", mime_type="text/markdown")
def external_demo_skill() -> str:
    return "# External demo skill\n\nUse this skill only for MCP integration tests."


@mcp.prompt(name="external_demo_prompt")
def external_demo_prompt(topic: str = "demo") -> str:
    return f"Summarize external MCP topic: {topic}"


@mcp.tool(
    name="external_echo",
    description="Echo one message for MCP client integration tests.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=True,
)
def external_echo(message: str) -> dict[str, str]:
    return {"echo": message}


if __name__ == "__main__":
    mcp.run(transport="stdio")


