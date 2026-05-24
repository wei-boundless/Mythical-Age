from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


DEEPSEARCH_TEMPLATE_ID = "runtime.template.deepsearch"
GENERAL_TEMPLATE_ID = "runtime.template.general_agent"

SearchRuntimeMode = Literal["single_search", "deepsearch"]
SearchDepth = Literal["basic", "advanced"]


@dataclass(frozen=True, slots=True)
class SearchRuntimeConfig:
    runtime_mode: SearchRuntimeMode = "deepsearch"
    search_sources: tuple[str, ...] = ("web",)
    web_provider: str = "tavily"
    allow_fetch_url: bool = True
    allow_local_files: bool = False
    allow_memory_read: bool = False
    max_iterations: int = 4
    max_queries: int = 6
    max_fetches: int = 8
    max_sources: int = 12
    search_depth: SearchDepth = "advanced"
    include_raw_content: bool = False
    prefer_primary_sources: bool = True
    freshness_required_by_default: bool = False
    evidence_packet_required: bool = True
    stop_policy: str = "enough_evidence_or_budget_exhausted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_mode": self.runtime_mode,
            "search_sources": list(self.search_sources),
            "web_provider": self.web_provider,
            "allow_fetch_url": self.allow_fetch_url,
            "allow_local_files": self.allow_local_files,
            "allow_memory_read": self.allow_memory_read,
            "max_iterations": self.max_iterations,
            "max_queries": self.max_queries,
            "max_fetches": self.max_fetches,
            "max_sources": self.max_sources,
            "search_depth": self.search_depth,
            "include_raw_content": self.include_raw_content,
            "prefer_primary_sources": self.prefer_primary_sources,
            "freshness_required_by_default": self.freshness_required_by_default,
            "evidence_packet_required": self.evidence_packet_required,
            "stop_policy": self.stop_policy,
        }


@dataclass(frozen=True, slots=True)
class GenericRuntimeConfig:
    template_id: str = GENERAL_TEMPLATE_ID
    runtime_kind: str = "agent_loop"
    runtime_mode: str = "standard"
    max_iterations: int = 4
    max_tool_calls: int = 12
    max_sources: int = 12
    evidence_packet_required: bool = False
    stop_policy: str = "task_complete_or_budget_exhausted"
    search: SearchRuntimeConfig | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "template_id": self.template_id,
            "runtime_kind": self.runtime_kind,
            "runtime_mode": self.runtime_mode,
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "max_sources": self.max_sources,
            "evidence_packet_required": self.evidence_packet_required,
            "stop_policy": self.stop_policy,
        }
        if self.search is not None:
            payload["search"] = self.search.to_dict()
        return payload


def normalize_runtime_config(value: Any) -> GenericRuntimeConfig:
    raw = _as_record(value)
    search = normalize_search_runtime_config(raw.get("search")) if isinstance(raw.get("search"), dict) else None
    derived_tool_budget = (search.max_queries + search.max_fetches) if search else 12
    template_id = str(raw.get("template_id") or (DEEPSEARCH_TEMPLATE_ID if search else GENERAL_TEMPLATE_ID)).strip()
    if template_id == DEEPSEARCH_TEMPLATE_ID:
        runtime_kind = "search_agent"
        default_mode = search.runtime_mode if search else "deepsearch"
    else:
        runtime_kind = "agent_loop"
        default_mode = "standard"
    runtime_mode = str(raw.get("runtime_mode") or default_mode).strip()
    if template_id == DEEPSEARCH_TEMPLATE_ID and runtime_mode not in {"deepsearch", "single_search"}:
        runtime_mode = default_mode
    if template_id != DEEPSEARCH_TEMPLATE_ID:
        runtime_mode = "standard"
    return GenericRuntimeConfig(
        template_id=template_id,
        runtime_kind=runtime_kind,
        runtime_mode=runtime_mode,
        max_iterations=_clamp_int(raw.get("max_iterations"), 1, 30, search.max_iterations if search else 4),
        max_tool_calls=_clamp_int(raw.get("max_tool_calls"), 1, 100, derived_tool_budget),
        max_sources=_clamp_int(raw.get("max_sources"), 1, 100, search.max_sources if search else 12),
        evidence_packet_required=bool(raw.get("evidence_packet_required", search.evidence_packet_required if search else False)),
        stop_policy=str(raw.get("stop_policy") or (search.stop_policy if search else "task_complete_or_budget_exhausted")),
        search=search,
        raw=raw,
    )


def normalize_search_runtime_config(value: Any) -> SearchRuntimeConfig:
    raw = _as_record(value)
    runtime_mode = str(raw.get("runtime_mode") or "deepsearch").strip()
    search_depth = str(raw.get("search_depth") or "advanced").strip()
    return SearchRuntimeConfig(
        runtime_mode="single_search" if runtime_mode == "single_search" else "deepsearch",
        search_sources=_dedupe([str(item) for item in list(raw.get("search_sources") or ["web"])]),
        web_provider=str(raw.get("web_provider") or "tavily").strip() or "tavily",
        allow_fetch_url=bool(raw.get("allow_fetch_url", True)),
        allow_local_files=bool(raw.get("allow_local_files", False)),
        allow_memory_read=bool(raw.get("allow_memory_read", False)),
        max_iterations=_clamp_int(raw.get("max_iterations"), 1, 12, 4),
        max_queries=_clamp_int(raw.get("max_queries"), 1, 30, 6),
        max_fetches=_clamp_int(raw.get("max_fetches"), 0, 40, 8),
        max_sources=_clamp_int(raw.get("max_sources"), 1, 60, 12),
        search_depth="basic" if search_depth == "basic" else "advanced",
        include_raw_content=bool(raw.get("include_raw_content", False)),
        prefer_primary_sources=bool(raw.get("prefer_primary_sources", True)),
        freshness_required_by_default=bool(raw.get("freshness_required_by_default", False)),
        evidence_packet_required=bool(raw.get("evidence_packet_required", True)),
        stop_policy=str(raw.get("stop_policy") or "enough_evidence_or_budget_exhausted"),
    )


def required_operations_for_search_config(config: SearchRuntimeConfig) -> tuple[str, ...]:
    operations = ["op.model_response", "op.web_search"]
    if config.allow_fetch_url and config.max_fetches > 0:
        operations.append("op.fetch_url")
    if config.allow_local_files:
        operations.extend(["op.search_files", "op.search_text", "op.read_file"])
    if config.allow_memory_read:
        operations.append("op.memory_read")
    return _dedupe(operations)


def _as_record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return max(minimum, min(maximum, parsed))


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)
