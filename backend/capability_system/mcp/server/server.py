from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from capability_system.mcp.local_registry import default_local_mcp_units
from capability_system.paths import resolve_capability_backend_dir
from capability_system.skills.registry import SkillRegistry
from .local_capability_server import LocalCapabilityMCPExecutor, LocalMCPToolRequest
from .tool_pool import build_mcp_tool_pool


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Natural-language knowledge query.", min_length=1)
    session_id: str = Field(default="mcp-session", description="Optional caller session id.")
    top_k: int = Field(default=5, description="Maximum retrieval hits.", ge=1, le=20)


class PDFAnalysisInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Question or instruction for the PDF.", min_length=1)
    path: str = Field(..., description="Workspace-relative PDF path or filename.", min_length=1)
    session_id: str = Field(default="mcp-session", description="Optional caller session id.")
    mode: str = Field(default="document", description="PDF analysis mode, such as document, page, or section.")
    max_chunks: int = Field(default=4, description="Maximum PDF chunks/pages to inspect.", ge=1, le=12)


class StructuredDataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Question or analysis instruction for the dataset.", min_length=1)
    path: str = Field(..., description="Workspace-relative CSV/XLSX/JSON dataset path.", min_length=1)
    session_id: str = Field(default="mcp-session", description="Optional caller session id.")
    semantic_hints: dict[str, Any] = Field(default_factory=dict, description="Optional domain hints for analysis.")


def build_server(*, backend_dir: Path | None = None, executor: LocalCapabilityMCPExecutor | None = None) -> FastMCP:
    server = FastMCP(
        "langchain_agent_mcp",
        instructions=(
            "Standard MCP server for this local langchain-agent workspace. "
            "It exposes knowledge retrieval, PDF analysis, and structured-data analysis as MCP tools."
        ),
    )
    root = resolve_capability_backend_dir(backend_dir or _default_backend_dir())
    active_executor = executor or _executor_for_backend(root)
    readonly_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.resource(
        "local-mcp://catalog",
        name="local_mcp_catalog",
        description="Catalog of local MCP capability units.",
        mime_type="application/json",
    )
    def local_mcp_catalog() -> str:
        return json.dumps(list_capabilities(), ensure_ascii=False, indent=2)

    @server.resource(
        "local-mcp://tool-pool",
        name="local_mcp_tool_pool",
        description="Stable merged tool-pool view for builtin tools and local MCP tools.",
        mime_type="application/json",
    )
    def local_mcp_tool_pool() -> str:
        return json.dumps(build_mcp_tool_pool(backend_dir=root), ensure_ascii=False, indent=2)

    @server.resource(
        "local-mcp://capability/{route}",
        name="local_mcp_capability",
        description="One local MCP capability record by route.",
        mime_type="application/json",
    )
    def local_mcp_capability(route: str) -> str:
        for unit in default_local_mcp_units():
            if unit.route == route or route in set(unit.route_aliases):
                return json.dumps(unit.to_dict(), ensure_ascii=False, indent=2)
        return json.dumps({"status": "missing", "route": route}, ensure_ascii=False, indent=2)

    @server.resource(
        "skill://catalog",
        name="skill_catalog",
        description="Catalog of local skills exposed as MCP resources.",
        mime_type="application/json",
    )
    def skill_catalog() -> str:
        return json.dumps(_skill_catalog(root), ensure_ascii=False, indent=2)

    @server.resource(
        "skill://{name}",
        name="skill_resource",
        description="One local skill prompt/runtime contract exposed as a skill resource.",
        mime_type="application/json",
    )
    def skill_resource(name: str) -> str:
        registry = SkillRegistry(root)
        skill = registry.get_by_name(name)
        if skill is None:
            return json.dumps({"status": "missing", "name": name}, ensure_ascii=False, indent=2)
        return json.dumps(_skill_resource_payload(skill), ensure_ascii=False, indent=2)

    @server.prompt(
        name="langchain_agent_capability_prompt",
        description="Build a concise prompt for using one local MCP capability.",
    )
    def capability_prompt(route: str, query: str = "") -> str:
        unit = next((item for item in default_local_mcp_units() if item.route == route), None)
        if unit is None:
            return f"Use the local MCP server only if a matching capability exists. Requested route: {route}."
        return (
            f"Use local MCP capability `{unit.route}` for this task.\n"
            f"Capability: {unit.summary}\n"
            f"Operation: {unit.operation_id}\n"
            f"User query: {query}"
        )

    @server.prompt(
        name="langchain_agent_skill_prompt",
        description="Render a local skill prompt block by skill name.",
    )
    def skill_prompt(name: str) -> str:
        skill = SkillRegistry(root).get_by_name(name)
        if skill is None:
            return f"Skill `{name}` is not available."
        return skill.render_prompt_block()

    @server.tool(
        name="langchain_agent_list_capabilities",
        description="List local capability units exposed through this standard MCP server.",
        annotations=readonly_annotations,
        structured_output=True,
    )
    def list_capabilities() -> dict[str, Any]:
        return {
            "server": "langchain_agent_mcp",
            "backend_dir": str(root),
            "capabilities": [
                {
                    "name": unit.name,
                    "route": unit.route,
                    "operation_id": unit.operation_id,
                    "summary": unit.summary,
                    "source_kind": unit.source_kind,
                    "resource_kinds": list(unit.resource_kinds),
                    "tags": list(unit.tags),
                }
                for unit in default_local_mcp_units()
            ],
        }

    @server.tool(
        name="langchain_agent_search_knowledge",
        description="Search local knowledge through the retrieval MCP unit and return evidence with traceable metadata.",
        annotations=readonly_annotations,
        structured_output=True,
    )
    async def search_knowledge(params: KnowledgeSearchInput) -> dict[str, Any]:
        return await active_executor.execute(
            LocalMCPToolRequest(
                route="retrieval",
                query=params.query,
                session_id=params.session_id,
                top_k=params.top_k,
            )
        )

    @server.tool(
        name="langchain_agent_analyze_pdf",
        description="Analyze a local PDF through the PDF MCP unit and return canonical answer/evidence handles.",
        annotations=readonly_annotations,
        structured_output=True,
    )
    async def analyze_pdf(params: PDFAnalysisInput) -> dict[str, Any]:
        return await active_executor.execute(
            LocalMCPToolRequest(
                route="pdf",
                query=params.query,
                path=params.path,
                session_id=params.session_id,
                mode=params.mode,
                constraints={"max_chunks": params.max_chunks},
            )
        )

    @server.tool(
        name="langchain_agent_analyze_structured_data",
        description="Analyze a local structured dataset through the structured-data MCP unit.",
        annotations=readonly_annotations,
        structured_output=True,
    )
    async def analyze_structured_data(params: StructuredDataInput) -> dict[str, Any]:
        return await active_executor.execute(
            LocalMCPToolRequest(
                route="structured_data",
                query=params.query,
                path=params.path,
                session_id=params.session_id,
                constraints={"semantic_hints": dict(params.semantic_hints or {})},
            )
        )

    return server


def _skill_catalog(root: Path) -> dict[str, Any]:
    registry = SkillRegistry(root)
    return {
        "authority": "capability_system.mcp.server.skill_resources",
        "resource_protocol": "skill://",
        "skills": [
            {
                "name": skill.name,
                "title": skill.title,
                "description": skill.description,
                "resource_uri": f"skill://{skill.name}",
                "activation_policy": skill.activation_policy,
                "context_mode": skill.context_mode,
                "preferred_route": skill.preferred_route,
                "capability_tags": list(skill.capability_tags),
            }
            for skill in registry.skills
        ],
    }


def _skill_resource_payload(skill: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "resource_uri": f"skill://{skill.name}",
        "kind": "skill",
        "runtime": skill.runtime.to_dict(),
        "prompt": skill.prompt_view.to_dict(),
        "prompt_block": skill.render_prompt_block(),
        "validation_errors": list(skill.validation_errors),
        "security": {
            "shell_command_embedding": "disabled",
            "resource_trust": "local_project",
        },
    }


@lru_cache(maxsize=4)
def _executor_for_backend(backend_dir_text: str | Path) -> LocalCapabilityMCPExecutor:
    return LocalCapabilityMCPExecutor(backend_dir=resolve_capability_backend_dir(backend_dir_text))


def _default_backend_dir() -> Path:
    env = str(os.getenv("LANGCHAIN_AGENT_BACKEND_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


mcp = build_server()


def main() -> None:
    transport = str(os.getenv("LANGCHAIN_AGENT_MCP_TRANSPORT") or "stdio").strip() or "stdio"
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()


