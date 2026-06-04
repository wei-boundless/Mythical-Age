from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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


def _structured_summary_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("structured_summary", "recovery_package", "checkpoint"):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


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
