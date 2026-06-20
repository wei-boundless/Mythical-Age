from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime.memory.file_evidence_scope import normalize_file_evidence_scope


TOOL_MEMORY_EVENTS_AUTHORITY = "runtime.memory.tool_memory_events"
TOOL_MEMORY_COMMIT_AUTHORITY = "runtime.memory.tool_memory_events.commit"


@dataclass(frozen=True, slots=True)
class ToolMemoryEvent:
    event_type: str
    memory_target: str
    payload: dict[str, Any] = field(default_factory=dict)
    path: str = ""
    resource_ref: str = ""
    scope: str = ""
    source_tool_name: str = ""
    source_observation_ref: str = ""
    tool_call_id: str = ""
    authority: str = TOOL_MEMORY_EVENTS_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


def build_tool_memory_events_from_file_state_events(
    file_state_events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    source_tool_name: str = "",
    observation_ref: str = "",
    tool_call_id: str = "",
) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    for raw in list(file_state_events or []):
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        event_type = str(payload.get("event_type") or payload.get("type") or "").strip()
        if not event_type:
            continue
        path = _normalize_path(payload.get("path"))
        events.append(
            ToolMemoryEvent(
                event_type=event_type,
                memory_target="file_state",
                payload=payload,
                path=path,
                source_tool_name=str(payload.get("source_tool_name") or source_tool_name or "").strip(),
                source_observation_ref=str(payload.get("observation_ref") or observation_ref or "").strip(),
                tool_call_id=str(payload.get("tool_call_id") or tool_call_id or "").strip(),
            ).to_dict()
        )
    return tuple(events)


def build_tool_memory_events_from_envelope(
    envelope: Any,
    *,
    source_tool_name: str = "",
    observation_ref: str = "",
    tool_call_id: str = "",
) -> tuple[dict[str, Any], ...]:
    tool_name = source_tool_name or _envelope_value(envelope, "tool_name")
    call_id = tool_call_id or _envelope_value(envelope, "tool_call_id")
    events: list[dict[str, Any]] = list(
        build_tool_memory_events_from_file_state_events(
            _file_state_events_from_envelope(envelope),
            source_tool_name=tool_name,
            observation_ref=observation_ref,
            tool_call_id=call_id,
        )
    )
    events.extend(
        _artifact_memory_events_from_envelope(
            envelope,
            source_tool_name=tool_name,
            observation_ref=observation_ref,
            tool_call_id=call_id,
        )
    )
    events.extend(
        _command_memory_events_from_envelope(
            envelope,
            source_tool_name=tool_name,
            observation_ref=observation_ref,
            tool_call_id=call_id,
        )
    )
    events.extend(
        _verification_memory_events_from_envelope(
            envelope,
            source_tool_name=tool_name,
            observation_ref=observation_ref,
            tool_call_id=call_id,
        )
    )
    events.extend(
        _git_memory_events_from_envelope(
            envelope,
            source_tool_name=tool_name,
            observation_ref=observation_ref,
            tool_call_id=call_id,
        )
    )
    failure = _tool_failure_memory_event(
        envelope,
        source_tool_name=tool_name,
        observation_ref=observation_ref,
        tool_call_id=call_id,
    )
    if failure:
        events.append(failure)
    return tuple(_dedupe_memory_events(events))


def commit_tool_memory_events_from_envelope(
    *,
    envelope: Any,
    file_evidence_scope: dict[str, Any] | None,
    observation_ref: str,
    tool_call_id: str = "",
    source_tool_name: str = "",
    runtime_host: Any | None = None,
    execution_store: Any | None = None,
    task_run_id: str = "",
    session_id: str = "",
    caller_kind: str = "",
    authority: str = TOOL_MEMORY_COMMIT_AUTHORITY,
) -> dict[str, Any]:
    file_state_events = _file_state_events_from_envelope(envelope)
    tool_memory_events = build_tool_memory_events_from_envelope(
        envelope,
        source_tool_name=source_tool_name or _envelope_value(envelope, "tool_name"),
        observation_ref=observation_ref,
        tool_call_id=tool_call_id or _envelope_value(envelope, "tool_call_id"),
    )
    base = _base_commit_payload(
        tool_memory_events=tool_memory_events,
        file_state_events=file_state_events,
        observation_ref=observation_ref,
        tool_call_id=tool_call_id,
        authority=authority,
    )
    if not tool_memory_events:
        return {}
    if not file_state_events:
        return {
            **base,
            "committed_targets": [],
            "status": "observed",
        }

    scope = normalize_file_evidence_scope(
        file_evidence_scope,
        task_run_id=task_run_id,
        session_id=session_id,
        caller_kind=caller_kind,
    )
    if not scope:
        return {
            **base,
            "skipped_reason": "missing_file_evidence_scope",
            "status": "skipped",
        }

    store = _file_state_store(runtime_host=runtime_host, execution_store=execution_store)
    if store is None:
        return {
            **base,
            "file_evidence_scope": scope,
            "skipped_reason": "file_state_store_unavailable",
            "status": "skipped",
        }

    authority_state = store.apply_events_scope(
        scope,
        file_state_events,
        observation_ref=observation_ref,
        tool_call_id=tool_call_id,
    )
    file_state_commit = {
        "file_evidence_scope": scope,
        "observation_ref": str(observation_ref or ""),
        "tool_call_id": str(tool_call_id or ""),
        "event_count": len(file_state_events),
        "file_count": len(authority_state.files),
        "authority": f"{authority}.file_state",
    }
    return {
        **base,
        "file_evidence_scope": scope,
        "file_count": len(authority_state.files),
        "committed_targets": ["file_state"],
        "file_state_commit": file_state_commit,
        "status": "committed",
    }


def _base_commit_payload(
    *,
    tool_memory_events: tuple[dict[str, Any], ...],
    file_state_events: tuple[dict[str, Any], ...],
    observation_ref: str,
    tool_call_id: str,
    authority: str,
) -> dict[str, Any]:
    memory_targets = _memory_targets(tool_memory_events)
    target_counts = _memory_target_counts(tool_memory_events)
    persistent_targets = ["file_state"] if file_state_events else []
    non_persistent_targets = [target for target in memory_targets if target not in persistent_targets]
    non_persistent_event_count = sum(
        1
        for item in tool_memory_events
        if str(item.get("memory_target") or "") != "file_state"
    )
    return _drop_empty(
        {
            "observation_ref": str(observation_ref or ""),
            "tool_call_id": str(tool_call_id or ""),
            "tool_memory_event_count": len(tool_memory_events),
            "file_state_event_count": len(file_state_events),
            "non_persistent_event_count": non_persistent_event_count,
            "ledger_event_count": 0,
            "event_count": len(file_state_events),
            "memory_targets": memory_targets,
            "observed_targets": memory_targets,
            "memory_target_counts": target_counts,
            "memory_delta": {
                "observed_targets": memory_targets,
                "persistent_targets": persistent_targets,
                "non_persistent_targets": non_persistent_targets,
                "file_state_event_count": len(file_state_events),
                "non_persistent_event_count": non_persistent_event_count,
                "authority_boundary": "observation_feedback_only",
            },
            "event_types": sorted(
                {
                    str(item.get("event_type") or item.get("type") or "")
                    for item in tool_memory_events
                    if str(item.get("event_type") or "").strip()
                }
            ),
            "persistent_targets": persistent_targets,
            "authority": authority,
        }
    )


def _file_state_events_from_envelope(envelope: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(envelope, dict):
        raw_events = list(envelope.get("file_state_events") or [])
    else:
        raw_events = list(getattr(envelope, "file_state_events", ()) or ())
    return tuple(dict(item) for item in raw_events if isinstance(item, dict))


def _artifact_memory_events_from_envelope(
    envelope: Any,
    *,
    source_tool_name: str,
    observation_ref: str,
    tool_call_id: str,
) -> tuple[dict[str, Any], ...]:
    raw_events = _dict_sequence_from_envelope(envelope, "artifact_state_events")
    artifact_refs = _dict_sequence_from_envelope(envelope, "artifact_refs")
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        payload = dict(raw)
        event_type = str(payload.get("event_type") or payload.get("type") or "artifact_observed").strip()
        resource_ref = _artifact_resource_ref(payload)
        events.append(
            ToolMemoryEvent(
                event_type=event_type,
                memory_target="artifact_state",
                payload=payload,
                path=_normalize_path(payload.get("path") or payload.get("artifact_path")),
                resource_ref=resource_ref,
                source_tool_name=source_tool_name,
                source_observation_ref=observation_ref,
                tool_call_id=tool_call_id,
            ).to_dict()
        )
    for ref in artifact_refs:
        payload = _drop_empty(
            {
                "event_type": "artifact_ref_observed",
                "artifact_ref": str(ref.get("artifact_ref") or ref.get("ref") or ""),
                "path": _normalize_path(ref.get("path") or ref.get("artifact_path")),
                "kind": str(ref.get("kind") or ref.get("artifact_kind") or ""),
                "mime_type": str(ref.get("mime_type") or ""),
                "metadata": dict(ref.get("metadata") or {}) if isinstance(ref.get("metadata"), dict) else {},
            }
        )
        if not payload:
            continue
        events.append(
            ToolMemoryEvent(
                event_type="artifact_ref_observed",
                memory_target="artifact_state",
                payload=payload,
                path=_normalize_path(payload.get("path")),
                resource_ref=_artifact_resource_ref(payload),
                source_tool_name=source_tool_name,
                source_observation_ref=observation_ref,
                tool_call_id=tool_call_id,
            ).to_dict()
        )
    return tuple(events)


def _command_memory_events_from_envelope(
    envelope: Any,
    *,
    source_tool_name: str,
    observation_ref: str,
    tool_call_id: str,
) -> tuple[dict[str, Any], ...]:
    receipt = _command_receipt_from_envelope(envelope)
    if not receipt:
        return ()
    payload = _drop_empty(
        {
            "event_type": "command_observed",
            "command": str(receipt.get("command") or ""),
            "exit_code": _int_or_none(receipt.get("exit_code")),
            "passed": receipt.get("passed") if isinstance(receipt.get("passed"), bool) else None,
            "failure_kind": str(receipt.get("failure_kind") or ""),
            "output_preview": _compact_text(receipt.get("output_preview") or receipt.get("output") or "", limit=500),
            "backend": str(receipt.get("backend") or ""),
        }
    )
    return (
        ToolMemoryEvent(
            event_type="command_observed",
            memory_target="command_state",
            payload=payload,
            resource_ref=_command_resource_ref(receipt, source_tool_name=source_tool_name, tool_call_id=tool_call_id),
            source_tool_name=source_tool_name,
            source_observation_ref=observation_ref,
            tool_call_id=tool_call_id,
        ).to_dict(),
    )


def _verification_memory_events_from_envelope(
    envelope: Any,
    *,
    source_tool_name: str,
    observation_ref: str,
    tool_call_id: str,
) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    receipt = _command_receipt_from_envelope(envelope)
    for raw in _dict_sequence_from_envelope(envelope, "verification_events"):
        payload = dict(raw)
        event_type = str(payload.get("event_type") or payload.get("type") or "verification_observed").strip()
        if receipt and "command_receipt" not in payload:
            payload["command_receipt"] = dict(receipt)
        events.append(
            ToolMemoryEvent(
                event_type=event_type,
                memory_target="verification_state",
                payload=_verification_payload(payload),
                resource_ref=str(payload.get("verification_ref") or payload.get("obligation") or payload.get("stage") or ""),
                source_tool_name=source_tool_name,
                source_observation_ref=observation_ref,
                tool_call_id=tool_call_id,
            ).to_dict()
        )
    intent = _verification_intent_from_envelope(envelope)
    if intent:
        payload = _verification_payload(
            {
                "event_type": "verification_intent_observed",
                **intent,
                "command_receipt": receipt,
            }
        )
        events.append(
            ToolMemoryEvent(
                event_type="verification_intent_observed",
                memory_target="verification_state",
                payload=payload,
                resource_ref=str(intent.get("verification_ref") or intent.get("obligation") or intent.get("stage") or ""),
                source_tool_name=source_tool_name,
                source_observation_ref=observation_ref,
                tool_call_id=tool_call_id,
            ).to_dict()
        )
    return tuple(events)


def _git_memory_events_from_envelope(
    envelope: Any,
    *,
    source_tool_name: str,
    observation_ref: str,
    tool_call_id: str,
) -> tuple[dict[str, Any], ...]:
    tool_name = source_tool_name or _envelope_value(envelope, "tool_name")
    if tool_name not in _GIT_TOOL_NAMES:
        return ()
    payload = _drop_empty(
        {
            "event_type": "git_tool_observed",
            "tool_name": tool_name,
            "status": _envelope_value(envelope, "status"),
            "tool_args": _tool_args_from_envelope(envelope),
            "observed_paths": list(_string_sequence_from_envelope(envelope, "observed_paths")),
            "matched_paths": list(_string_sequence_from_envelope(envelope, "matched_paths")),
            "command_receipt": _command_receipt_from_envelope(envelope),
        }
    )
    return (
        ToolMemoryEvent(
            event_type="git_tool_observed",
            memory_target="git_state",
            payload=payload,
            resource_ref=tool_name,
            source_tool_name=tool_name,
            source_observation_ref=observation_ref,
            tool_call_id=tool_call_id,
        ).to_dict(),
    )


def _tool_failure_memory_event(
    envelope: Any,
    *,
    source_tool_name: str,
    observation_ref: str,
    tool_call_id: str,
) -> dict[str, Any]:
    status = _envelope_value(envelope, "status")
    structured_payload = _structured_payload_from_envelope(envelope)
    structured_error = dict(structured_payload.get("structured_error") or {})
    error = _envelope_value(envelope, "error") or str(structured_payload.get("error") or "")
    if status in {"", "ok"} and not structured_error and not error:
        return {}
    payload = _drop_empty(
        {
            "event_type": "tool_failure_observed",
            "tool_name": source_tool_name,
            "status": status or "error",
            "error": _compact_text(error, limit=500),
            "structured_error": structured_error,
            "command_receipt": _command_receipt_from_envelope(envelope),
        }
    )
    return ToolMemoryEvent(
        event_type="tool_failure_observed",
        memory_target="tool_failure_state",
        payload=payload,
        resource_ref=tool_call_id or source_tool_name,
        source_tool_name=source_tool_name,
        source_observation_ref=observation_ref,
        tool_call_id=tool_call_id,
    ).to_dict()


def _file_state_store(*, runtime_host: Any | None, execution_store: Any | None) -> Any | None:
    store = getattr(runtime_host, "file_state_store", None) if runtime_host is not None else None
    if store is not None:
        return store
    root_dir = getattr(runtime_host, "root_dir", None) if runtime_host is not None else None
    if root_dir is None and execution_store is not None:
        root_dir = getattr(execution_store, "root_dir", None)
    if root_dir is None:
        return None
    from runtime.memory.file_state_store import FileStateAuthorityStore

    return FileStateAuthorityStore(Path(root_dir))


def _envelope_value(envelope: Any, key: str) -> str:
    if isinstance(envelope, dict):
        return str(envelope.get(key) or "").strip()
    return str(getattr(envelope, key, "") or "").strip()


def _structured_payload_from_envelope(envelope: Any) -> dict[str, Any]:
    if isinstance(envelope, dict):
        value = envelope.get("structured_payload")
    else:
        value = getattr(envelope, "structured_payload", {})
    return dict(value) if isinstance(value, dict) else {}


def _tool_args_from_envelope(envelope: Any) -> dict[str, Any]:
    if isinstance(envelope, dict):
        value = envelope.get("tool_args")
    else:
        value = getattr(envelope, "tool_args", {})
    return dict(value) if isinstance(value, dict) else {}


def _command_receipt_from_envelope(envelope: Any) -> dict[str, Any]:
    if isinstance(envelope, dict):
        value = envelope.get("command_receipt")
    else:
        value = getattr(envelope, "command_receipt", {})
    if isinstance(value, dict) and value:
        return dict(value)
    structured = _structured_payload_from_envelope(envelope)
    value = structured.get("command_receipt")
    return dict(value) if isinstance(value, dict) else {}


def _verification_intent_from_envelope(envelope: Any) -> dict[str, Any]:
    structured = _structured_payload_from_envelope(envelope)
    value = structured.get("verification_intent")
    return dict(value) if isinstance(value, dict) and value else {}


def _dict_sequence_from_envelope(envelope: Any, key: str) -> tuple[dict[str, Any], ...]:
    if isinstance(envelope, dict):
        raw_values = envelope.get(key)
    else:
        raw_values = getattr(envelope, key, ())
    return tuple(dict(item) for item in list(raw_values or ()) if isinstance(item, dict))


def _string_sequence_from_envelope(envelope: Any, key: str) -> tuple[str, ...]:
    if isinstance(envelope, dict):
        raw_values = envelope.get(key)
    else:
        raw_values = getattr(envelope, key, ())
    return tuple(str(item).replace("\\", "/").strip() for item in list(raw_values or ()) if str(item).strip())


def _verification_payload(value: dict[str, Any]) -> dict[str, Any]:
    receipt = dict(value.get("command_receipt") or {}) if isinstance(value.get("command_receipt"), dict) else {}
    return _drop_empty(
        {
            "event_type": str(value.get("event_type") or value.get("type") or "verification_observed"),
            "stage": str(value.get("stage") or ""),
            "obligation": str(value.get("obligation") or ""),
            "verification_ref": str(value.get("verification_ref") or ""),
            "passed": value.get("passed") if isinstance(value.get("passed"), bool) else receipt.get("passed") if isinstance(receipt.get("passed"), bool) else None,
            "command_receipt": receipt,
            "authority": str(value.get("authority") or ""),
        }
    )


def _artifact_resource_ref(value: dict[str, Any]) -> str:
    for key in ("artifact_ref", "ref", "artifact_id", "path", "artifact_path"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""


def _command_resource_ref(receipt: dict[str, Any], *, source_tool_name: str, tool_call_id: str) -> str:
    command = str(receipt.get("command") or "").strip()
    if command:
        return f"command:{_short_hash(command)}"
    return tool_call_id or source_tool_name


def _memory_targets(events: tuple[dict[str, Any], ...]) -> list[str]:
    return sorted(
        {
            str(item.get("memory_target") or "").strip()
            for item in events
            if str(item.get("memory_target") or "").strip()
        }
    )


def _memory_target_counts(events: tuple[dict[str, Any], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in events:
        target = str(item.get("memory_target") or "").strip()
        if not target:
            continue
        counts[target] = counts.get(target, 0) + 1
    return counts


def _dedupe_memory_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in events:
        key = "|".join(
            [
                str(item.get("memory_target") or ""),
                str(item.get("event_type") or ""),
                str(item.get("path") or ""),
                str(item.get("resource_ref") or ""),
                str(item.get("source_observation_ref") or ""),
                str(item.get("tool_call_id") or ""),
            ]
        )
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _compact_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)].rstrip() + "... <truncated>"


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}


_GIT_TOOL_NAMES = frozenset(
    {
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch_list",
        "git_branch_create",
        "git_stage",
        "git_unstage",
        "git_commit",
        "git_restore",
        "git_push",
    }
)
