from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MicrocompactCacheDecision:
    local_rewrite_allowed: bool
    cache_temperature: str = "unknown"
    provider_cache_editing_supported: bool = False
    reason: str = "cache_state_unknown"
    diagnostics: dict[str, Any] | None = None
    authority: str = "context_system.compaction.microcompact_cache_decision"

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_rewrite_allowed": self.local_rewrite_allowed,
            "cache_temperature": self.cache_temperature,
            "provider_cache_editing_supported": self.provider_cache_editing_supported,
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics or {}),
            "authority": self.authority,
        }


def decide_microcompact_cache_policy(cache_state: dict[str, Any] | None) -> MicrocompactCacheDecision:
    payload = dict(cache_state or {})
    if not payload:
        return MicrocompactCacheDecision(
            local_rewrite_allowed=True,
            cache_temperature="unknown",
            reason="cache_state_absent",
        )
    temperature = _cache_temperature(payload)
    edit_supported = bool(
        payload.get("provider_cache_editing_supported")
        or payload.get("provider_supports_cache_editing")
        or payload.get("cache_editing_supported")
    )
    if temperature == "warm":
        reason = "cache_warm_requires_provider_cache_editing" if edit_supported else "cache_warm_provider_cache_editing_unavailable"
        return MicrocompactCacheDecision(
            local_rewrite_allowed=False,
            cache_temperature=temperature,
            provider_cache_editing_supported=edit_supported,
            reason=reason,
            diagnostics=_diagnostics(payload),
        )
    return MicrocompactCacheDecision(
        local_rewrite_allowed=True,
        cache_temperature=temperature,
        provider_cache_editing_supported=edit_supported,
        reason="cache_cold_or_unknown",
        diagnostics=_diagnostics(payload),
    )


def _cache_temperature(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("cache_temperature") or payload.get("temperature") or "").strip().lower()
    if explicit in {"warm", "cold", "unknown"}:
        return explicit
    status = str(payload.get("status") or payload.get("cache_status") or "").strip().lower()
    cached_tokens = _int(payload.get("cached_tokens")) or _int(payload.get("cache_read_tokens")) or _int(payload.get("provider_cached_tokens"))
    if status == "hit" or cached_tokens > 0:
        return "warm"
    if status in {"miss", "eligible", "bypassed", "invalidated"}:
        return "cold"
    return "unknown"


def _diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "cache_record_id": str(payload.get("cache_record_id") or ""),
        "cache_key": str(payload.get("cache_key") or "")[:80],
        "prefix_hash": str(payload.get("prefix_hash") or ""),
        "status": str(payload.get("status") or payload.get("cache_status") or ""),
        "cached_tokens": _int(payload.get("cached_tokens")) or _int(payload.get("cache_read_tokens")) or _int(payload.get("provider_cached_tokens")),
        "source": str(payload.get("source") or ""),
    }


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
