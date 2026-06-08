from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_CACHE_SCOPES = {"global", "session", "task", "none"}
VALID_CACHE_ROLES = {"cacheable_prefix", "session_stable", "volatile", "never_cache"}
VALID_PREFIX_TIERS = {"provider_global", "session", "task", "volatile", "none"}
VALID_COMPRESSION_ROLES = {"preserve", "summarize", "drop_if_cold", "ref_only"}
STABLE_CACHE_ROLES = {"cacheable_prefix", "session_stable"}


@dataclass(frozen=True, slots=True)
class CachePolicyBinding:
    cache_scope: str
    cache_role: str
    prefix_tier: str

    @property
    def cache_eligible(self) -> bool:
        return is_cache_eligible_prefix(cache_role=self.cache_role, prefix_tier=self.prefix_tier)


def cache_policy_binding(
    *,
    cache_scope: Any,
    cache_role: Any,
    prefix_tier: Any,
) -> CachePolicyBinding:
    role = str(cache_role or "volatile").strip() or "volatile"
    scope = str(cache_scope or default_cache_scope(cache_role=role, prefix_tier=prefix_tier)).strip()
    tier = str(prefix_tier or default_prefix_tier(cache_role=role, cache_scope=scope)).strip()
    return CachePolicyBinding(cache_scope=scope, cache_role=role, prefix_tier=tier)


def cache_policy_findings(
    *,
    cache_scope: Any,
    cache_role: Any,
    prefix_tier: Any,
    kind: str = "",
    source_ref: str = "",
) -> tuple[dict[str, Any], ...]:
    binding = cache_policy_binding(cache_scope=cache_scope, cache_role=cache_role, prefix_tier=prefix_tier)
    findings: list[dict[str, Any]] = []
    base = {
        "kind": str(kind or ""),
        "source_ref": str(source_ref or ""),
        "cache_scope": binding.cache_scope,
        "cache_role": binding.cache_role,
        "prefix_tier": binding.prefix_tier,
        "authority": "prompt_cache_policy",
    }
    if binding.cache_scope not in VALID_CACHE_SCOPES:
        findings.append({**base, "issue": "invalid_cache_scope"})
    if binding.cache_role not in VALID_CACHE_ROLES:
        findings.append({**base, "issue": "invalid_cache_role"})
    if binding.prefix_tier not in VALID_PREFIX_TIERS:
        findings.append({**base, "issue": "invalid_prefix_tier"})
    if findings:
        return tuple(findings)

    if binding.cache_role == "cacheable_prefix":
        if binding.cache_scope != "global":
            findings.append({**base, "issue": "cacheable_prefix_scope_must_be_global"})
        if binding.prefix_tier != "provider_global":
            findings.append({**base, "issue": "cacheable_prefix_tier_must_be_provider_global"})
    elif binding.cache_role == "session_stable":
        if binding.cache_scope not in {"session", "task"}:
            findings.append({**base, "issue": "session_stable_scope_must_be_session_or_task"})
        if binding.prefix_tier not in {"session", "task"}:
            findings.append({**base, "issue": "session_stable_tier_must_be_session_or_task"})
        elif binding.cache_scope == "session" and binding.prefix_tier != "session":
            findings.append({**base, "issue": "session_scope_tier_must_be_session"})
        elif binding.cache_scope == "task" and binding.prefix_tier != "task":
            findings.append({**base, "issue": "task_scope_tier_must_be_task"})
    elif binding.cache_role == "volatile":
        if binding.cache_scope not in {"none", "task"}:
            findings.append({**base, "issue": "volatile_scope_must_be_none_or_task"})
        if binding.prefix_tier != "volatile":
            findings.append({**base, "issue": "volatile_tier_must_be_volatile"})
    elif binding.cache_role == "never_cache":
        if binding.cache_scope != "none":
            findings.append({**base, "issue": "never_cache_scope_must_be_none"})
        if binding.prefix_tier != "none":
            findings.append({**base, "issue": "never_cache_tier_must_be_none"})
    return tuple(findings)


def require_valid_cache_policy(
    *,
    cache_scope: Any,
    cache_role: Any,
    prefix_tier: Any,
    kind: str = "",
    source_ref: str = "",
) -> CachePolicyBinding:
    binding = cache_policy_binding(cache_scope=cache_scope, cache_role=cache_role, prefix_tier=prefix_tier)
    findings = cache_policy_findings(
        cache_scope=binding.cache_scope,
        cache_role=binding.cache_role,
        prefix_tier=binding.prefix_tier,
        kind=kind,
        source_ref=source_ref,
    )
    if findings:
        raise ValueError(
            "invalid prompt cache policy: "
            + "; ".join(
                f"{item['issue']} kind={item.get('kind') or ''} "
                f"cache_scope={item.get('cache_scope') or ''} "
                f"cache_role={item.get('cache_role') or ''} "
                f"prefix_tier={item.get('prefix_tier') or ''}"
                for item in findings
            )
        )
    return binding


def default_cache_scope(*, cache_role: Any, prefix_tier: Any = "") -> str:
    role = str(cache_role or "").strip()
    tier = str(prefix_tier or "").strip()
    if role == "cacheable_prefix":
        return "global"
    if role == "session_stable":
        return "task" if tier == "task" else "session"
    return "none"


def default_prefix_tier(*, cache_role: Any, cache_scope: Any = "") -> str:
    role = str(cache_role or "").strip()
    scope = str(cache_scope or "").strip()
    if role == "cacheable_prefix":
        return "provider_global"
    if role == "session_stable":
        return "task" if scope == "task" else "session"
    if role == "never_cache":
        return "none"
    return "volatile"


def normalize_cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in VALID_CACHE_ROLES else "volatile"


def normalize_prefix_tier(value: Any, *, cache_scope: Any, cache_role: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in VALID_PREFIX_TIERS:
        return normalized
    return default_prefix_tier(cache_role=cache_role, cache_scope=cache_scope)


def normalize_compression_role(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in VALID_COMPRESSION_ROLES else "summarize"


def is_stable_cache_role(cache_role: Any) -> bool:
    return str(cache_role or "").strip() in STABLE_CACHE_ROLES


def is_cache_eligible_prefix(*, cache_role: Any, prefix_tier: Any) -> bool:
    role = str(cache_role or "").strip()
    tier = str(prefix_tier or "").strip()
    if role == "cacheable_prefix":
        return tier == "provider_global"
    if role == "session_stable":
        return tier in {"session", "task"}
    return False


def is_prefix_eligible_for_tier(*, cache_role: Any, prefix_tier: Any, tier: str) -> bool:
    role = str(cache_role or "").strip()
    prefix = str(prefix_tier or "").strip()
    target = str(tier or "").strip()
    if role == "cacheable_prefix" and prefix == "provider_global":
        return target in {"provider_global", "session", "task"}
    if role == "session_stable" and prefix == "session":
        return target in {"session", "task"}
    if role == "session_stable" and prefix == "task":
        return target == "task"
    return False
