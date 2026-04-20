from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.definitions import ToolDefinition, build_tool_registry_payload, get_tool_definition_map, get_tool_definitions


class ToolRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.registry_path = base_dir / "TOOLS_REGISTRY.json"
        self._tools: list[ToolDefinition] = []
        self.reload()

    def reload(self) -> None:
        self._tools = get_tool_definitions()

    @property
    def tools(self) -> list[ToolDefinition]:
        return list(self._tools)

    def get_by_name(self, name: str | None) -> ToolDefinition | None:
        if not name:
            return None
        return get_tool_definition_map().get(name.strip())

    def filter_names(self, names: list[str] | None, *, safe_only: bool = False) -> list[ToolDefinition]:
        if not names:
            return []
        allowed = {name.strip().lower() for name in names if name.strip()}
        results: list[ToolDefinition] = []
        for tool in self._tools:
            if tool.name.lower() not in allowed:
                continue
            if safe_only and not tool.safe_for_auto_route:
                continue
            results.append(tool)
        return results

    def select_best(
        self,
        message: str,
        *,
        candidate_names: list[str] | None = None,
        modality: str | None = None,
        route: str | None = None,
        safe_only: bool = True,
    ) -> ToolDefinition | None:
        candidates = self.filter_names(candidate_names, safe_only=safe_only) if candidate_names else [
            tool for tool in self._tools if (tool.safe_for_auto_route or not safe_only)
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        normalized = (message or "").strip().lower()
        best_tool: ToolDefinition | None = None
        best_score = float("-inf")

        for tool in candidates:
            score = 0.0
            if modality and modality in tool.supported_modalities:
                score += 4.0
            if route == "tool" and tool.safe_for_auto_route:
                score += 1.0
            for query in tool.typical_queries:
                if query and query.lower() in normalized:
                    score += 5.0
            for term in tool.search_terms:
                if term and term.lower() in normalized:
                    score += 3.0
            for tag in tool.capability_tags:
                if tag and tag.lower() in normalized:
                    score += 2.0
            if score > best_score:
                best_score = score
                best_tool = tool

        if best_score <= 0:
            return None
        return best_tool


def build_tool_registry() -> dict[str, Any]:
    return build_tool_registry_payload()


def refresh_tool_registry(base_dir: Path) -> Path:
    registry_path = base_dir / "TOOLS_REGISTRY.json"
    registry_path.write_text(
        json.dumps(build_tool_registry(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry_path
