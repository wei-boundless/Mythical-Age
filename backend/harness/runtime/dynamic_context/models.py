from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DynamicContextInput:
    invocation_kind: str
    session_id: str
    turn_id: str = ""
    task_run_id: str = ""
    task_run: dict[str, Any] = field(default_factory=dict)
    history: tuple[dict[str, Any], ...] = ()
    observations: tuple[dict[str, Any], ...] = ()
    tool_results: tuple[dict[str, Any], ...] = ()
    execution_state: dict[str, Any] = field(default_factory=dict)
    work_rollout: dict[str, Any] = field(default_factory=dict)
    session_context: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)
    runtime_envelope: dict[str, Any] = field(default_factory=dict)
    current_user_message: str = ""
    editor_context: dict[str, Any] = field(default_factory=dict)
    projection_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VolatileSectionReport:
    section_id: str
    source: str
    volatility_reason: str
    input_chars: int = 0
    output_chars: int = 0
    projection_strategy: str = ""
    cache_impact: str = "volatile"
    refs: tuple[str, ...] = ()
    authority: str = "harness.runtime.dynamic_context.section_report"

    def __post_init__(self) -> None:
        if not str(self.section_id or "").strip():
            raise ValueError("VolatileSectionReport requires section_id")
        if not str(self.source or "").strip():
            raise ValueError("VolatileSectionReport requires source")
        if not str(self.volatility_reason or "").strip():
            raise ValueError("VolatileSectionReport requires volatility_reason")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["refs"] = list(self.refs)
        return payload


@dataclass(frozen=True, slots=True)
class DynamicContextProjection:
    stable_runtime_baseline_refs: dict[str, Any] = field(default_factory=dict)
    dynamic_runtime_delta: dict[str, Any] = field(default_factory=dict)
    dynamic_runtime_projection: dict[str, Any] = field(default_factory=dict)
    volatile_request_projection: dict[str, Any] = field(default_factory=dict)
    volatile_state_projection: dict[str, Any] = field(default_factory=dict)
    tool_result_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    budget_report: dict[str, Any] = field(default_factory=dict)
    section_reports: tuple[VolatileSectionReport, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.dynamic_context.projection"

    def to_report_dict(self) -> dict[str, Any]:
        return drop_empty(
            {
                "authority": self.authority,
                "stable_runtime_baseline_refs": dict(self.stable_runtime_baseline_refs),
                "dynamic_runtime_delta": dict(self.dynamic_runtime_delta),
                "tool_result_refs": list(self.tool_result_refs),
                "observation_refs": list(self.observation_refs),
                "context_refs": list(self.context_refs),
                "artifact_refs": list(self.artifact_refs),
                "budget_report": dict(self.budget_report),
                "section_reports": [item.to_dict() for item in self.section_reports],
                "diagnostics": dict(self.diagnostics),
            }
        )


def stable_json(value: Any) -> str:
    return json.dumps(json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_json_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(stable_json(value).encode("utf-8", errors="ignore")).hexdigest()


def stable_text_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def short_hash(value: Any, *, chars: int = 12) -> str:
    digest = stable_json_hash(value).removeprefix("sha256:")
    return digest[: max(4, int(chars or 12))]


def json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def compact_text(value: Any, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def string_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in list(value or []) if str(item).strip())


def estimate_chars(value: Any) -> int:
    return len(stable_json(value))
