from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime_objects.read_observation_artifacts import ReadObservationArtifactStore

from ..context_budget_policy import (
    DEFAULT_READ_EVIDENCE_PER_WINDOW_CHARS,
    DEFAULT_READ_EVIDENCE_TOTAL_EXACT_CHARS,
)


READ_EVIDENCE_PROJECTOR_AUTHORITY = "harness.runtime.dynamic_context.read_evidence_projector"


def build_read_evidence_projection_payload(
    *,
    storage_root: Path,
    file_state: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    packet_id: str,
    budget_policy: dict[str, Any] | None = None,
    current_observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    include_historical_refs: bool = True,
) -> dict[str, Any]:
    current_refs = _current_exact_read_refs(current_observations)
    budget_payload = _read_evidence_budget_payload(budget_policy)
    total_budget = _positive_int(
        budget_payload.get("read_evidence_total_exact_chars"),
        DEFAULT_READ_EVIDENCE_TOTAL_EXACT_CHARS,
    )
    per_window_budget = _positive_int(
        budget_payload.get("read_evidence_per_window_chars"),
        DEFAULT_READ_EVIDENCE_PER_WINDOW_CHARS,
    )
    try:
        artifact_store = ReadObservationArtifactStore(storage_root)
    except Exception:
        return {}

    injections: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    read_required: list[dict[str, Any]] = []
    consumed_chars = 0

    for item in list(file_state or []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        for segment in _active_read_ranges(item):
            window = _read_evidence_window(path=path, segment=segment)
            if not window:
                continue
            should_inject = _is_current_exact_window(window, current_refs=current_refs)
            ref_payload = {
                **window,
            }
            if should_inject:
                ref_payload["model_visible_exact_in_current_packet"] = True
            if include_historical_refs or should_inject:
                evidence_refs.append(_drop_empty(ref_payload))
            if not should_inject:
                continue
            try:
                payload = artifact_store.read_payload(str(window.get("artifact_ref") or ""))
            except Exception as exc:
                read_required.append(
                    _read_required_window(
                        window,
                        reason="artifact_missing_or_invalid",
                        error=str(exc),
                    )
                )
                continue
            metadata = dict(payload.get("metadata") or {})
            if not _artifact_metadata_matches_window(metadata, window):
                read_required.append(_read_required_window(window, reason="artifact_metadata_mismatch"))
                continue
            text = str(payload.get("text") or "")
            chars = len(text)
            if chars > per_window_budget or consumed_chars + chars > total_budget:
                read_required.append(
                    _read_required_window(
                        window,
                        reason="budget_exceeded",
                        required_line_count=max(1, int(window["end_line"]) - int(window["start_line"]) + 1),
                    )
                )
                continue
            consumed_chars += chars
            injections.append(
                _drop_empty(
                    {
                        **window,
                        "content": text,
                        "visible_exact_in_packet": True,
                        "packet_id": packet_id,
                        "authority": READ_EVIDENCE_PROJECTOR_AUTHORITY,
                    }
                )
            )

    payload = _drop_empty(
        {
            "kind": "read_evidence_injection",
            "authority": READ_EVIDENCE_PROJECTOR_AUTHORITY,
            "packet_id": packet_id,
            "visible_exact_in_packet": bool(injections),
            "read_evidence_injections": injections[-4:],
            "read_evidence_refs": evidence_refs[-12:],
            "read_required_windows": read_required[-8:],
            "projection_policy": {
                "exact_content_injection": "current_packet_exact_refs_only",
                "historical_read_evidence": "ref_only" if include_historical_refs else "evidence_index_cursor",
                "rehydration": "read_again_or_artifact_lookup_when_exact_text_is_needed",
            },
        }
    )
    return payload


def _read_evidence_budget_payload(budget_policy: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for candidate in (
        budget_policy,
        dict(budget_policy or {}).get("context_budget_policy"),
    ):
        if isinstance(candidate, dict):
            payload.update(candidate)
    return payload


def _current_exact_read_refs(observations: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> set[str]:
    refs: set[str] = set()
    for observation in list(observations or []):
        if not isinstance(observation, dict):
            continue
        source = _source_observation_payload(observation)
        envelope = dict(source.get("result_envelope") or dict(source.get("payload") or {}).get("result_envelope") or {})
        tool_result = _tool_result_payload(source)
        if tool_result and tool_result.get("visible_exact") is True:
            _add_ref(refs, tool_result.get("exact_artifact_ref"))
            _add_ref(refs, tool_result.get("reusable_result_ref"))
        for payload in (observation, source, envelope, tool_result):
            _add_ref(refs, payload.get("observation_id"))
            _add_ref(refs, payload.get("observation_ref"))
            _add_ref(refs, payload.get("tool_call_id"))
            _add_ref(refs, payload.get("tool_result_ref"))
    return refs


def _source_observation_payload(observation: dict[str, Any]) -> dict[str, Any]:
    wrapped = dict(observation.get("observation") or {})
    return wrapped if wrapped else dict(observation or {})


def _tool_result_payload(source: dict[str, Any]) -> dict[str, Any]:
    envelope = dict(source.get("result_envelope") or {})
    structured = dict(envelope.get("structured_payload") or {})
    if isinstance(structured.get("tool_result"), dict):
        return dict(structured.get("tool_result") or {})
    structured = dict(source.get("structured_payload") or {})
    if isinstance(structured.get("tool_result"), dict):
        return dict(structured.get("tool_result") or {})
    payload = dict(source.get("payload") or {})
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(envelope.get("structured_payload") or {})
    if isinstance(structured.get("tool_result"), dict):
        return dict(structured.get("tool_result") or {})
    structured = dict(payload.get("structured_payload") or source.get("structured") or {})
    if isinstance(structured.get("tool_result"), dict):
        return dict(structured.get("tool_result") or {})
    if isinstance(source.get("tool_result"), dict):
        return dict(source.get("tool_result") or {})
    return {}


def _active_read_ranges(item: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(item.get("status") or "").strip().lower()
    if status in {"stale", "missing"}:
        return []
    ranges: list[dict[str, Any]] = []
    for segment in list(item.get("read_ranges") or item.get("read_window_refs") or []):
        if not isinstance(segment, dict) or segment.get("stale") is True:
            continue
        if str(segment.get("artifact_ref_status") or "").strip() not in {"", "exact"}:
            continue
        start_line = _safe_int(segment.get("start_line"))
        end_line = _safe_int(segment.get("end_line"))
        if start_line <= 0 or end_line < start_line:
            continue
        artifact_ref = str(segment.get("exact_artifact_ref") or segment.get("reusable_result_ref") or "").strip()
        if not artifact_ref.startswith("read_observation:"):
            continue
        ranges.append(segment)
    return ranges


def _read_evidence_window(*, path: str, segment: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = str(segment.get("exact_artifact_ref") or segment.get("reusable_result_ref") or "").strip()
    start_line = _safe_int(segment.get("start_line"))
    end_line = _safe_int(segment.get("end_line"))
    if not artifact_ref or start_line <= 0 or end_line < start_line:
        return {}
    return _drop_empty(
        {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "artifact_ref": artifact_ref,
            "observation_ref": str(segment.get("observation_ref") or ""),
            "content_sha256": str(segment.get("content_sha256") or ""),
            "text_sha256": str(segment.get("text_sha256") or ""),
            "has_more": segment.get("has_more") if isinstance(segment.get("has_more"), bool) else None,
            "next_start_line": segment.get("next_start_line"),
        }
    )


def _is_current_exact_window(window: dict[str, Any], *, current_refs: set[str]) -> bool:
    if not current_refs:
        return False
    return any(
        str(window.get(key) or "").strip() in current_refs
        for key in ("artifact_ref", "observation_ref")
    )


def _artifact_metadata_matches_window(metadata: dict[str, Any], window: dict[str, Any]) -> bool:
    path = str(window.get("path") or "").replace("\\", "/").strip().strip("/")
    metadata_path = str(metadata.get("path") or "").replace("\\", "/").strip().strip("/")
    return (
        bool(path)
        and path == metadata_path
        and _safe_int(metadata.get("start_line")) == _safe_int(window.get("start_line"))
        and _safe_int(metadata.get("end_line")) == _safe_int(window.get("end_line"))
    )


def _read_required_window(window: dict[str, Any], *, reason: str, error: str = "", required_line_count: int = 0) -> dict[str, Any]:
    return _drop_empty(
        {
            "path": str(window.get("path") or ""),
            "start_line": window.get("start_line"),
            "end_line": window.get("end_line"),
            "artifact_ref": str(window.get("artifact_ref") or ""),
            "observation_ref": str(window.get("observation_ref") or ""),
            "decision": "read_required",
            "reason": reason,
            "error": error,
            "required_line_count": required_line_count,
        }
    )


def _add_ref(refs: set[str], value: Any) -> None:
    text = str(value or "").strip()
    if text:
        refs.add(text)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return parsed if parsed > 0 else default


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }
