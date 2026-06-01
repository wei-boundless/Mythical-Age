from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptStabilitySection:
    section_id: str
    kind: str
    ordinal: int
    source_ref: str = ""
    cache_role: str = "volatile"
    content_hash: str = ""
    predicted_tokens: int = 0
    volatility_reason: str = ""
    authority: str = "runtime.prompt_accounting.prompt_stability_section"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromptStabilitySection":
        return cls(
            section_id=str(payload.get("section_id") or ""),
            kind=str(payload.get("kind") or ""),
            ordinal=_int(payload.get("ordinal")),
            source_ref=str(payload.get("source_ref") or ""),
            cache_role=str(payload.get("cache_role") or "volatile"),
            content_hash=str(payload.get("content_hash") or ""),
            predicted_tokens=_int(payload.get("predicted_tokens")),
            volatility_reason=str(payload.get("volatility_reason") or ""),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.prompt_stability_section"),
        )


@dataclass(frozen=True, slots=True)
class PromptStabilityReport:
    report_id: str
    request_id: str
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    packet_id: str = ""
    invocation_kind: str = ""
    provider: str = ""
    model: str = ""
    session_cache_key: str = ""
    context_window_generation: int = 0
    compaction_generation: int = 0
    stable_prefix_hash: str = ""
    stable_prefix_tokens: int = 0
    stable_section_count: int = 0
    volatile_token_count: int = 0
    stable_sections: tuple[PromptStabilitySection, ...] = ()
    volatile_sections: tuple[PromptStabilitySection, ...] = ()
    dynamic_param_hash: str = ""
    dynamic_param_summary: dict[str, Any] = field(default_factory=dict)
    previous_report_ref: str = ""
    first_changed_section: dict[str, Any] = field(default_factory=dict)
    changed_sections: tuple[dict[str, Any], ...] = ()
    provider_usage: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    authority: str = "runtime.prompt_accounting.prompt_stability_report"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stable_sections"] = [section.to_dict() for section in self.stable_sections]
        payload["volatile_sections"] = [section.to_dict() for section in self.volatile_sections]
        payload["changed_sections"] = [dict(item) for item in self.changed_sections]
        payload["dynamic_param_summary"] = dict(self.dynamic_param_summary)
        payload["provider_usage"] = dict(self.provider_usage)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromptStabilityReport":
        return cls(
            report_id=str(payload.get("report_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            packet_id=str(payload.get("packet_id") or ""),
            invocation_kind=str(payload.get("invocation_kind") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            session_cache_key=str(payload.get("session_cache_key") or ""),
            context_window_generation=_int(payload.get("context_window_generation")),
            compaction_generation=_int(payload.get("compaction_generation")),
            stable_prefix_hash=str(payload.get("stable_prefix_hash") or ""),
            stable_prefix_tokens=_int(payload.get("stable_prefix_tokens")),
            stable_section_count=_int(payload.get("stable_section_count")),
            volatile_token_count=_int(payload.get("volatile_token_count")),
            stable_sections=tuple(
                PromptStabilitySection.from_dict(dict(item))
                for item in list(payload.get("stable_sections") or [])
                if isinstance(item, dict)
            ),
            volatile_sections=tuple(
                PromptStabilitySection.from_dict(dict(item))
                for item in list(payload.get("volatile_sections") or [])
                if isinstance(item, dict)
            ),
            dynamic_param_hash=str(payload.get("dynamic_param_hash") or ""),
            dynamic_param_summary=dict(payload.get("dynamic_param_summary") or {}),
            previous_report_ref=str(payload.get("previous_report_ref") or ""),
            first_changed_section=dict(payload.get("first_changed_section") or {}),
            changed_sections=tuple(dict(item) for item in list(payload.get("changed_sections") or []) if isinstance(item, dict)),
            provider_usage=dict(payload.get("provider_usage") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
            created_at=float(payload.get("created_at") or 0.0),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.prompt_stability_report"),
        )


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
