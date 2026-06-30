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
    latest_health = _prefix_health(payload)
    latest_verdict = str(
        payload.get("prefix_health_verdict")
        or latest_health.get("verdict")
        or ""
    ).strip().lower()
    latest_under_read_tokens = _int(
        payload.get("latest_under_read_tokens")
        or payload.get("provider_under_read_tokens")
        or latest_health.get("under_read_tokens")
        or payload.get("provider_cache_read_physical_spine_under_read_tokens")
    )
    current_prefix_covered = _bool_or_none(payload.get("current_prefix_covered"))
    if current_prefix_covered is True and latest_under_read_tokens <= 0 and latest_verdict == "covered":
        return "warm"
    if current_prefix_covered is False or latest_under_read_tokens > 0:
        return "cold"
    if latest_verdict == "covered" and latest_under_read_tokens <= 0:
        return "warm"
    if latest_verdict in {"provider_under_read", "local_physical_mismatch", "cold_start", "miss", "bypassed"}:
        return "cold"
    status = str(payload.get("status") or payload.get("cache_status") or "").strip().lower()
    if status in {"provider_under_read", "local_physical_mismatch", "cold_start", "miss", "eligible", "bypassed", "invalidated"}:
        return "cold"
    return "unknown"


def _diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    latest_health = _prefix_health(payload)
    return {
        "cache_bus_record_id": str(payload.get("cache_bus_record_id") or ""),
        "provider_cache_bus_record_id": str(payload.get("provider_cache_bus_record_id") or payload.get("cache_bus_record_id") or ""),
        "cache_key": str(payload.get("cache_key") or "")[:80],
        "prefix_hash": str(payload.get("prefix_hash") or ""),
        "physical_cache_spine_hash": str(payload.get("physical_cache_spine_hash") or ""),
        "transport_contract_hash": str(payload.get("transport_contract_hash") or ""),
        "status": str(payload.get("status") or payload.get("cache_status") or ""),
        "prefix_health_verdict": str(payload.get("prefix_health_verdict") or latest_health.get("verdict") or ""),
        "current_prefix_covered": _bool_or_none(payload.get("current_prefix_covered")),
        "latest_under_read_tokens": _int(
            payload.get("latest_under_read_tokens")
            or payload.get("provider_under_read_tokens")
            or latest_health.get("under_read_tokens")
        ),
        "first_missing_expected_prefix_identity": dict(
            payload.get("first_missing_expected_prefix_identity")
            or latest_health.get("first_missing_expected_prefix_identity")
            or {}
        ),
        "cached_tokens": _int(payload.get("cached_tokens")) or _int(payload.get("cache_read_tokens")) or _int(payload.get("provider_cached_tokens")),
        "hit_rate": _float(payload.get("hit_rate")),
        "cache_temperature_source": str(payload.get("cache_temperature_source") or ""),
        "source": str(payload.get("source") or ""),
        "authority": str(payload.get("authority") or ""),
    }


def _prefix_health(payload: dict[str, Any]) -> dict[str, Any]:
    latest_health = payload.get("latest_prefix_health") or payload.get("provider_prefix_cache_health")
    return dict(latest_health) if isinstance(latest_health, dict) else {}


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "covered"}:
        return True
    if text in {"false", "0", "no", "cold", "miss", "provider_under_read"}:
        return False
    return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
