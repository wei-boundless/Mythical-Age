from __future__ import annotations

import json
from pathlib import Path

from capability_system.tools.paths import CapabilityToolPaths
from capability_system.tools.native_tool_catalog import (
    ToolDefinition,
    build_tool_registry_payload,
    get_tool_definitions,
)


class ToolRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.registry_path = CapabilityToolPaths.from_base_dir(base_dir).tools_registry_path
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
        target = name.strip().lower()
        for tool in self._tools:
            if tool.name.lower() == target:
                return tool
        return None

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

    def resolve_candidate_names(
        self,
        *,
        capability_requests: list[str] | None = None,
        route: str | None = None,
        modality: str | None = None,
        safe_only: bool = True,
    ) -> list[str]:
        requested = [str(item or "").strip().lower() for item in list(capability_requests or []) if str(item or "").strip()]
        if not requested:
            return []
        scored: list[tuple[float, str]] = []
        for tool in self._tools:
            if safe_only and not tool.safe_for_auto_route:
                continue
            metadata_terms = {
                *(str(item or "").strip().lower() for item in tool.route_hints),
                *(str(item or "").strip().lower() for item in tool.capability_tags),
                *(str(item or "").strip().lower() for item in tool.supported_modalities),
            }
            overlap = {item for item in requested if item in metadata_terms}
            if not overlap:
                continue
            score = float(len(overlap)) * 10.0
            if "latest_information" in requested and "latest_information" in metadata_terms:
                score += 4.0
            if route and str(route).strip().lower() in {str(item).lower() for item in tool.route_hints}:
                score += 2.0
            if modality and str(modality).strip().lower() in {str(item).lower() for item in tool.supported_modalities}:
                score += 1.0
            scored.append((score, tool.name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [name for _score, name in scored]

    def select_best(
        self,
        message: str,
        *,
        candidate_names: list[str] | None = None,
        modality: str | None = None,
        route: str | None = None,
        capability_requests: list[str] | None = None,
        safe_only: bool = True,
    ) -> ToolDefinition | None:
        candidates = self.filter_names(candidate_names, safe_only=safe_only) if candidate_names else [
            tool for tool in self._tools if (tool.safe_for_auto_route or not safe_only)
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        requested = {
            str(item or "").strip().lower()
            for item in list(capability_requests or [])
            if str(item or "").strip()
        }
        candidate_order = {
            tool.name: index
            for index, tool in enumerate(candidates)
        }
        best_tool: ToolDefinition | None = None
        best_score = float("-inf")

        for tool in candidates:
            score = self._selection_score(
                tool=tool,
                requested=requested,
                modality=modality,
                route=route,
            )
            if score > best_score:
                best_score = score
                best_tool = tool
                continue
            if score == best_score and best_tool is not None:
                if candidate_order.get(tool.name, 0) < candidate_order.get(best_tool.name, 0):
                    best_tool = tool

        if best_score <= 0:
            return None
        return best_tool

    def _selection_score(
        self,
        *,
        tool: ToolDefinition,
        requested: set[str],
        modality: str | None,
        route: str | None,
    ) -> float:
        metadata_terms = {
            *(str(item or "").strip().lower() for item in tool.route_hints),
            *(str(item or "").strip().lower() for item in tool.capability_tags),
            *(str(item or "").strip().lower() for item in tool.supported_modalities),
        }
        score = 0.0
        overlap = requested & metadata_terms
        if overlap:
            score += float(len(overlap)) * 12.0

        normalized_modality = str(modality or "").strip().lower()
        if normalized_modality and normalized_modality in {
            str(item or "").strip().lower() for item in tool.supported_modalities
        }:
            score += 6.0
            score += 1.0 / max(len(tool.supported_modalities), 1)

        normalized_route = str(route or "").strip().lower()
        if normalized_route and normalized_route in {
            str(item or "").strip().lower() for item in tool.route_hints
        }:
            score += 3.0
            score += 1.0 / max(len(tool.route_hints), 1)

        return score


def build_tool_registry() -> dict[str, Any]:
    return build_tool_registry_payload()


def refresh_tool_registry(base_dir: Path) -> Path:
    paths = CapabilityToolPaths.from_base_dir(base_dir)
    paths.ensure()
    registry_path = paths.tools_registry_path
    registry_path.write_text(
        json.dumps(build_tool_registry(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry_path


