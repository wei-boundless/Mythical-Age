from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CONTEXT_COMPACTOR_AGENT_ID = "agent:context_compactor"
CONTEXT_COMPACTOR_PROFILE_ID = "context_compactor_agent"
CONTEXT_COMPACTOR_RUNTIME_KIND = "context_compactor"
CONTEXT_COMPACTOR_TEMPLATE_IDS = ("runtime.template.context_compactor", "builtin.system.context_compactor")
ALLOWED_CONTEXT_COMPACTOR_OPERATIONS = {"op.model_response"}


@dataclass(frozen=True, slots=True)
class SemanticCompactorRegistration:
    agent_id: str
    agent_profile_id: str
    runtime_template_id: str = ""
    runtime_kind: str = ""
    allowed_operations: tuple[str, ...] = ()
    blocked_operations: tuple[str, ...] = ()
    allow_nested_subagents: bool = False
    authority: str = "context_system.compaction.semantic_compactor_registration"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_operations"] = list(self.allowed_operations)
        payload["blocked_operations"] = list(self.blocked_operations)
        return payload


@dataclass(frozen=True, slots=True)
class SemanticCompactionWorkerResult:
    ok: bool
    summary_content: str = ""
    structured_summary: dict[str, Any] = field(default_factory=dict)
    source: str = "registered_semantic_compactor"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "context_system.compaction.semantic_compactor_result"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticCompactionSummaryQuality:
    status: Literal["pass", "unpass"]
    coverage_signals: dict[str, bool] = field(default_factory=dict)
    issue_summary: str = ""
    missing_fields: tuple[str, ...] = ()
    authority: str = "context_system.compaction.summary_quality"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_fields"] = list(self.missing_fields)
        return payload


@dataclass(frozen=True, slots=True)
class SemanticCompactionFailedSample:
    request_id: str
    session_id: str
    summary_source: str
    quality_status: Literal["unpass"]
    issue_summary: str
    missing_fields: tuple[str, ...] = ()
    created_at: float = 0.0
    authority: str = "context_system.compaction.summary_quality_failed_sample"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_fields"] = list(self.missing_fields)
        return payload


def semantic_compactor_registration_from_worker(worker: Any) -> SemanticCompactorRegistration:
    registration = getattr(worker, "registration", None) or getattr(worker, "semantic_compactor_registration", None)
    if hasattr(registration, "to_dict"):
        registration = registration.to_dict()
    if not isinstance(registration, dict):
        raise ValueError("semantic_compactor must expose orchestration registration metadata")
    normalized = SemanticCompactorRegistration(
        agent_id=str(registration.get("agent_id") or ""),
        agent_profile_id=str(registration.get("agent_profile_id") or registration.get("profile_id") or ""),
        runtime_template_id=str(registration.get("runtime_template_id") or registration.get("template_id") or ""),
        runtime_kind=str(registration.get("runtime_kind") or ""),
        allowed_operations=tuple(str(item) for item in list(registration.get("allowed_operations") or []) if str(item)),
        blocked_operations=tuple(str(item) for item in list(registration.get("blocked_operations") or []) if str(item)),
        allow_nested_subagents=bool(registration.get("allow_nested_subagents", False)),
    )
    _validate_registration(normalized)
    return normalized


def normalize_semantic_compaction_worker_result(value: Any) -> SemanticCompactionWorkerResult:
    if isinstance(value, SemanticCompactionWorkerResult):
        return value
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, str):
        return SemanticCompactionWorkerResult(ok=bool(value.strip()), summary_content=value.strip())
    if isinstance(value, dict):
        summary = str(value.get("summary_content") or value.get("summary") or value.get("content") or "").strip()
        structured = _structured_summary_from_payload(value)
        return SemanticCompactionWorkerResult(
            ok=bool(value.get("ok", bool(summary or structured))) and bool(summary or structured),
            summary_content=summary,
            structured_summary=structured,
            source=str(value.get("source") or "registered_semantic_compactor"),
            diagnostics=dict(value.get("diagnostics") or {}),
        )
    return SemanticCompactionWorkerResult(
        ok=False,
        diagnostics={"reason": "semantic_compactor_returned_unsupported_result"},
    )


def evaluate_semantic_compaction_summary_quality(
    *,
    request_id: str,
    session_id: str,
    summary_source: str,
    before_messages: list[Any] | tuple[Any, ...],
    after_messages: list[Any] | tuple[Any, ...],
    summary_content: str,
    structured_summary: dict[str, Any] | None = None,
) -> SemanticCompactionSummaryQuality:
    before = list(before_messages or [])
    after = list(after_messages or [])
    summary_text = _normalized_text(summary_content)
    after_text = _normalized_text(" ".join(_message_content(message) for message in after))
    structured = dict(structured_summary or {})
    current_user = _last_message_content(before, role="user")
    current_user_preserved = (
        True
        if not current_user
        else _contains_material_fragment(after_text, current_user) or _contains_material_fragment(summary_text, current_user)
    )
    before_tool_result_ids = _tool_result_ids(before)
    after_tool_result_ids = _tool_result_ids(after)
    open_tool_result_refs_preserved = (
        True
        if not before_tool_result_ids
        else bool(before_tool_result_ids.intersection(after_tool_result_ids))
        or _mentions_tool_observation(summary_text)
    )
    active_task_goal_preserved = bool(
        _structured_field_present(structured, "current_goal")
        or _mentions_goal(summary_text)
        or (current_user and _contains_material_fragment(after_text, current_user))
    )
    unresolved_required = any(_mentions_unresolved(_message_content(message)) for message in before)
    unresolved_questions_preserved = (
        True
        if not unresolved_required
        else _mentions_unresolved(summary_text) or any(_mentions_unresolved(_message_content(message)) for message in after)
    )
    coverage = {
        "current_user_message_preserved": current_user_preserved,
        "open_tool_result_refs_preserved": open_tool_result_refs_preserved,
        "active_task_goal_preserved": active_task_goal_preserved,
        "unresolved_questions_preserved": unresolved_questions_preserved,
    }
    missing = [key for key, value in coverage.items() if not value]
    if not summary_text and not structured:
        missing.insert(0, "summary_content")
    status: Literal["pass", "unpass"] = "pass" if not missing else "unpass"
    return SemanticCompactionSummaryQuality(
        status=status,
        coverage_signals=coverage,
        issue_summary=(
            ""
            if status == "pass"
            else f"semantic compaction summary did not preserve required recovery signals for {request_id or 'unknown_request'}"
        ),
        missing_fields=tuple(_dedupe(missing)),
    )


def failed_sample_from_summary_quality(
    quality: SemanticCompactionSummaryQuality,
    *,
    request_id: str,
    session_id: str,
    summary_source: str,
) -> SemanticCompactionFailedSample | None:
    if quality.status != "unpass":
        return None
    return SemanticCompactionFailedSample(
        request_id=str(request_id or ""),
        session_id=str(session_id or ""),
        summary_source=str(summary_source or ""),
        quality_status="unpass",
        issue_summary=quality.issue_summary,
        missing_fields=tuple(quality.missing_fields),
        created_at=time.time(),
    )


def _structured_summary_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("structured_summary", "recovery_package", "checkpoint"):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


_TOOL_RESULT_ID_RE = re.compile(r"(?:tool_call_id|call_id)\s*=\s*[\"']?([A-Za-z0-9_.:-]+)", re.IGNORECASE)


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "").strip()
    return str(getattr(message, "role", "") or "").strip()


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _last_message_content(messages: list[Any], *, role: str) -> str:
    for message in reversed(messages):
        if _message_role(message) == role:
            return _message_content(message).strip()
    return ""


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _contains_material_fragment(haystack: str, source: str) -> bool:
    haystack_text = _normalized_text(haystack)
    source_text = _normalized_text(source)
    if not source_text:
        return False
    if source_text in haystack_text:
        return True
    fragment = source_text[: min(48, len(source_text))].strip()
    return len(fragment) >= 8 and fragment in haystack_text


def _tool_result_ids(messages: list[Any]) -> set[str]:
    result: set[str] = set()
    for message in messages:
        if _message_role(message) not in {"tool", "tool_result"}:
            continue
        meta = dict(getattr(message, "meta", {}) or {}) if not isinstance(message, dict) else dict(message.get("meta") or {})
        for key in ("tool_call_id", "call_id"):
            value = str(meta.get(key) or "").strip()
            if value:
                result.add(value)
        result.update(_TOOL_RESULT_ID_RE.findall(_message_content(message)))
    return result


def _structured_field_present(structured_summary: dict[str, Any], key: str) -> bool:
    value = structured_summary.get(key)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value not in (None, "")


def _mentions_tool_observation(text: str) -> bool:
    normalized = _normalized_text(text)
    return any(marker in normalized for marker in ("工具", "tool", "观察", "observation", "结果", "result"))


def _mentions_goal(text: str) -> bool:
    normalized = _normalized_text(text)
    return any(marker in normalized for marker in ("目标", "用户目标", "current_goal", "goal", "任务"))


def _mentions_unresolved(text: str) -> bool:
    normalized = _normalized_text(text)
    return any(marker in normalized for marker in ("未解决", "待确认", "需要确认", "open question", "unresolved", "？", "?"))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def semantic_compaction_worker_exception(exc: Exception) -> SemanticCompactionWorkerResult:
    return SemanticCompactionWorkerResult(
        ok=False,
        diagnostics={
            "reason": "semantic_compactor_exception",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        },
    )


def _validate_registration(registration: SemanticCompactorRegistration) -> None:
    errors: list[str] = []
    if registration.agent_id != CONTEXT_COMPACTOR_AGENT_ID:
        errors.append("agent_id_must_be_agent_context_compactor")
    if registration.agent_profile_id != CONTEXT_COMPACTOR_PROFILE_ID:
        errors.append("agent_profile_id_must_be_context_compactor_agent")
    if registration.runtime_kind and registration.runtime_kind != CONTEXT_COMPACTOR_RUNTIME_KIND:
        errors.append("runtime_kind_must_be_context_compactor")
    if registration.runtime_template_id and registration.runtime_template_id not in CONTEXT_COMPACTOR_TEMPLATE_IDS:
        errors.append("runtime_template_id_must_be_context_compactor")
    allowed = set(registration.allowed_operations)
    if "op.model_response" not in allowed:
        errors.append("semantic_compactor_requires_model_response_operation")
    disallowed = sorted(allowed - ALLOWED_CONTEXT_COMPACTOR_OPERATIONS)
    if disallowed:
        errors.append("semantic_compactor_has_disallowed_operations:" + ",".join(disallowed))
    if registration.allow_nested_subagents:
        errors.append("semantic_compactor_must_not_allow_nested_subagents")
    if errors:
        raise ValueError("invalid registered semantic compactor: " + ";".join(errors))
