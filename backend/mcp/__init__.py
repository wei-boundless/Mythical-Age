"""MCP extension layer scaffolding.

This package is intentionally lightweight for now. It defines the place where
future MCP clients, resource adapters, and tool bridges can live without
affecting the current local durable-memory/RAG/tooling pipeline.
"""

from .layer import MCPLayer, MCPResource, MCPTool

__all__ = ["MCPLayer", "MCPResource", "MCPTool"]
