from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout
from runtime.model_gateway.lightweight_chat_model import provider_message_payloads

from .context_segment_policy import (
    CONTEXT_APPEND,
    CURRENT_CONTROL_TAIL_KINDS,
    DYNAMIC_TAIL,
    DEFAULT_PROVIDER_ADAPTER_CONTRACT,
    context_append_order_key,
    context_segment_policy_for_spec,
    context_segment_policy_metadata,
)
from .context_candidates import ContextCommitCandidate
from .tool_transcript import is_tool_transcript_kind


PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION = 2
PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT = DEFAULT_PROVIDER_ADAPTER_CONTRACT
PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS = "confirmed_provider_visible"
PROVIDER_VISIBLE_CONTEXT_PREFIX = "provider_visible_context_prefix"
_LEGACY_REPLAYABLE_COMMIT_STATUSES = {"materialized_for_provider_request"}


def assemble_provider_visible_context_specs(
    items: list[tuple[int, dict[str, Any]]],
    *,
    storage_root: Path | None,
    scope: str,
    inherited_scope: str = "",
    inherited_anchor: dict[str, Any] | None = None,
    compaction_generation: str = "",
    provider: str = "",
    model: str = "",
    adapter_contract: str = PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT,
) -> list[tuple[int, dict[str, Any]]]:
    """Return provider-visible context by ledger replay plus new append items.

    The ledger is the authority for previously materialized provider-visible
    context. Incoming specs are only candidates for new append entries; if a
    candidate is already represented in the ledger, the stored provider-visible
    message wins.

    """

    normalized_scope = str(scope or "default").strip() or "default"
    normalized_inherited_scope = str(inherited_scope or "").strip()
    normalized_generation = _normalize_compaction_generation(compaction_generation)
    normalized_adapter = str(adapter_contract or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT).strip()
    inherited_entries, inherited_recovery_events = _inherited_ledger_entries_for_anchor(
        storage_root=storage_root,
        scope=normalized_inherited_scope,
        anchor=dict(inherited_anchor or {}),
        compaction_generation=normalized_generation,
        adapter_contract=normalized_adapter,
    )
    ledger = load_provider_visible_context_ledger(storage_root=storage_root, scope=normalized_scope)
    failure = _ledger_failure(ledger, scope=normalized_scope, adapter_contract=normalized_adapter)
    if failure:
        ledger = _new_ledger(scope=normalized_scope, provider=provider, model=model, adapter_contract=normalized_adapter)
        ledger["status"] = "recovery_required"
        ledger["recovery_events"] = [failure]
        changed = True
    else:
        ledger = _ledger_for_append(
            ledger,
            scope=normalized_scope,
            provider=provider,
            model=model,
            adapter_contract=normalized_adapter,
        )

    all_existing_entries = [
        dict(item)
        for item in list(dict(ledger or {}).get("entries") or [])
        if isinstance(item, dict) and _ledger_entry_confirmed(item)
    ]
    existing_entries = _ledger_entries_for_compaction_generation(
        all_existing_entries,
        compaction_generation=normalized_generation,
    )
    inherited_entries_by_key = _entries_by_key({"entries": inherited_entries})
    entries_by_key = _entries_by_key({"entries": existing_entries})
    changed = bool(failure)
    current_append_specs: list[tuple[int, dict[str, Any]]] = []

    for original_order, raw_spec in sorted(list(items or []), key=context_append_order_key):
        spec = dict(raw_spec or {})
        policy = context_segment_policy_for_spec(spec)
        provider_message = _provider_visible_message_from_spec(spec)
        if not provider_message:
            continue
        provider_hash = _stable_json_hash(provider_message)
        item_key = _provider_visible_item_key(spec, provider_visible_hash=provider_hash, policy=policy)
        existing = dict(entries_by_key.get(item_key) or {})
        if existing:
            previous_hash = str(existing.get("provider_visible_hash") or "").strip()
            if previous_hash and previous_hash != provider_hash:
                failure = _structured_failure(
                    scope=normalized_scope,
                    code="provider_visible_hash_changed_for_entry",
                    message="provider-visible ledger item maps to different content",
                    details={
                        "entry_index": int(existing.get("entry_index") or 0),
                        "item_key": item_key,
                        "previous_provider_visible_hash": previous_hash,
                        "current_provider_visible_hash": provider_hash,
                        "kind": str(spec.get("kind") or existing.get("kind") or ""),
                        "source_ref": str(spec.get("source_ref") or existing.get("source_ref") or ""),
                    },
                )
                ledger = _record_recovery_event(ledger, failure)
                changed = True
                continue
            if _ledger_entry_confirmed(existing):
                continue
            continue
        inherited_existing = dict(inherited_entries_by_key.get(item_key) or {})
        if inherited_existing:
            inherited_hash = str(inherited_existing.get("provider_visible_hash") or "").strip()
            if inherited_hash and inherited_hash == provider_hash:
                continue
        current_append_specs.append(
            (
                int(original_order or 0),
                _current_context_append_spec_from_candidate(
                    spec,
                    item_key=item_key,
                    provider_visible_message=provider_message,
                    provider_visible_hash=provider_hash,
                    policy=policy,
                    scope=normalized_scope,
                    storage_root=storage_root,
                    provider=provider,
                    model=model,
                    adapter_contract=policy.provider_adapter_contract or normalized_adapter,
                ),
            )
        )

    ledger = _finalize_ledger(
        ledger,
        scope=normalized_scope,
        provider=provider,
        model=model,
        adapter_contract=normalized_adapter,
    )
    if changed:
        save_provider_visible_context_ledger(storage_root=storage_root, scope=normalized_scope, ledger=ledger)

    inherited_specs = [
        (
            order,
            _mark_inherited_provider_visible_spec(
                spec,
                inherited_scope=normalized_inherited_scope,
                write_scope=normalized_scope,
                anchor=dict(inherited_anchor or {}),
            ),
        )
        for order, spec in _materialize_ledger_entries(
            inherited_entries,
            scope=normalized_inherited_scope,
            recovery_events=inherited_recovery_events,
        )
    ]
    return [
        *inherited_specs,
        *_materialize_ledger_entries(existing_entries, scope=normalized_scope, recovery_events=list(ledger.get("recovery_events") or [])),
        *current_append_specs,
    ]


def provider_visible_context_append_candidate_spec(
    spec: dict[str, Any],
    *,
    storage_root: Path | None,
    scope: str,
    provider: str = "",
    model: str = "",
    adapter_contract: str = PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT,
) -> dict[str, Any]:
    """Return a provider-visible append candidate without replaying old context.

    This is for append-only callers that already hold the immutable provider
    prefix in memory. The ledger may confirm this candidate after provider
    success, but it must not inject or reorder replayed entries into the
    caller's current message sequence.
    """

    payload = dict(spec or {})
    normalized_scope = str(scope or "default").strip() or "default"
    normalized_adapter = str(adapter_contract or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT).strip()
    policy = context_segment_policy_for_spec(payload)
    if not _provider_visible_context_append_candidate_allowed(payload, policy=policy):
        return payload
    provider_message = _provider_visible_message_from_spec(payload)
    if not provider_message:
        return payload
    provider_hash = _stable_json_hash(provider_message)
    item_key = _provider_visible_item_key(payload, provider_visible_hash=provider_hash, policy=policy)
    return _current_context_append_spec_from_candidate(
        payload,
        item_key=item_key,
        provider_visible_message=provider_message,
        provider_visible_hash=provider_hash,
        policy=policy,
        scope=normalized_scope,
        storage_root=storage_root,
        provider=provider,
        model=model,
        adapter_contract=policy.provider_adapter_contract or normalized_adapter,
    )


def _provider_visible_context_append_candidate_allowed(payload: dict[str, Any], *, policy: Any) -> bool:
    metadata = dict(dict(payload or {}).get("metadata") or {})
    kind = str(payload.get("kind") or metadata.get("kind") or "").strip()
    if kind in CURRENT_CONTROL_TAIL_KINDS:
        return False
    section = str(getattr(policy, "section", "") or metadata.get("context_cache_section") or "").strip()
    if section != CONTEXT_APPEND or section == DYNAMIC_TAIL:
        return False
    if str(metadata.get("context_commit_policy") or getattr(policy, "commit_policy", "") or "").strip() == "never_commit":
        return False
    if str(metadata.get("memory_commit_policy") or "").strip() == "never_commit":
        return False
    if str(metadata.get("context_replay_policy") or getattr(policy, "replay_policy", "") or "").strip() == "current_dynamic_tail_only":
        return False
    if str(metadata.get("context_provider_visible_boundary") or "").strip() == "current_dynamic_tail":
        return False
    if str(metadata.get("physical_prefix_lane") or "").strip() == "never_replay_tail":
        return False
    if str(metadata.get("provider_visible_after_validity") or "").strip() == "not_replayed_after_current_request":
        return False
    semantic_commit_class = str(metadata.get("semantic_commit_class") or getattr(policy, "semantic_commit_class", "") or "").strip()
    return semantic_commit_class != "current_runtime_control"


def confirm_provider_visible_context_entries(
    candidates: list[ContextCommitCandidate] | tuple[ContextCommitCandidate, ...],
    *,
    default_storage_root: Path | str | None = None,
    default_scope: str = "",
    provider: str = "",
    model: str = "",
    request_id: str = "",
    response_ref: str = "",
    provider_payload_prefix_hash: str = "",
    provider_payload_messages_hash: str = "",
    provider_payload_message_prefix_hash: str = "",
    transport_contract_hash: str = "",
    request_message_count: int = 0,
) -> dict[str, Any]:
    """Append provider-visible context candidates after provider success.

    Assembly is not a commit boundary. The runtime calls this only after the
    provider accepted and returned a model response for the request carrying
    these exact provider-visible candidate messages.
    """

    typed_candidates = list(candidates or [])
    if any(not isinstance(item, ContextCommitCandidate) for item in typed_candidates):
        raise TypeError("confirm_provider_visible_context_entries requires ContextCommitCandidate items")

    grouped: dict[tuple[str, str], list[ContextCommitCandidate]] = {}
    for raw_candidate in list(candidates or []):
        candidate = raw_candidate
        scope = str(candidate.scope or default_scope or "").strip()
        if not scope:
            continue
        storage_value = str(candidate.storage_root or default_storage_root or "").strip()
        grouped.setdefault((storage_value, scope), []).append(candidate)

    confirmations: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    changed_groups = 0
    confirmed_count = 0
    anchor_update_count = 0

    for (storage_value, scope), refs in grouped.items():
        storage_root = Path(storage_value) if storage_value else (Path(default_storage_root) if default_storage_root else None)
        ledger = load_provider_visible_context_ledger(storage_root=storage_root, scope=scope)
        failure = _ledger_failure(
            ledger,
            scope=scope,
            adapter_contract=str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT),
        )
        if failure:
            failures.append(failure)
            continue
        ledger = _ledger_for_append(
            ledger,
            scope=scope,
            provider=provider,
            model=model,
            adapter_contract=str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT),
        )
        entries_by_key = _entries_by_key({"entries": _confirmed_ledger_entries(ledger)})
        changed = False
        group_failed = False
        group_confirmations: list[dict[str, Any]] = []
        for ref in refs:
            item_key = str(ref.item_key or "").strip()
            expected_hash = str(ref.provider_visible_hash or "").strip()
            provider_message = _provider_visible_message(
                dict(ref.provider_message or {})
            )
            if not item_key or not expected_hash or not provider_message:
                failure = _structured_failure(
                    scope=scope,
                    code="provider_visible_commit_candidate_incomplete",
                    message="provider-visible context commit candidate is missing identity, hash, or message content",
                    details={
                        "item_key": item_key,
                        "provider_visible_hash": expected_hash,
                        "request_id": str(request_id or ""),
                        "candidate_id": str(ref.candidate_id or ""),
                    },
                )
                ledger = _record_recovery_event(ledger, failure)
                failures.append(failure)
                changed = True
                group_failed = True
                continue
            computed_hash = _stable_json_hash(provider_message)
            if computed_hash != expected_hash:
                failure = _structured_failure(
                    scope=scope,
                    code="provider_visible_commit_candidate_hash_mismatch",
                    message="provider-visible context commit candidate hash does not match message content",
                    details={
                        "item_key": item_key,
                        "provider_visible_hash": expected_hash,
                        "computed_provider_visible_hash": computed_hash,
                        "request_id": str(request_id or ""),
                    },
                )
                ledger = _record_recovery_event(ledger, failure)
                failures.append(failure)
                changed = True
                group_failed = True
                continue
            candidate_adapter = str(ref.adapter_contract or ledger.get("adapter_contract") or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT)
            ledger_adapter = str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT)
            if candidate_adapter and ledger_adapter and candidate_adapter != ledger_adapter:
                failure = _structured_failure(
                    scope=scope,
                    code="provider_visible_commit_candidate_adapter_mismatch",
                    message="provider-visible context commit candidate adapter contract does not match ledger",
                    details={
                        "item_key": item_key,
                        "provider_visible_hash": expected_hash,
                        "adapter_contract": candidate_adapter,
                        "ledger_adapter_contract": ledger_adapter,
                        "request_id": str(request_id or ""),
                        "candidate_id": str(ref.candidate_id or ""),
                    },
                )
                ledger = _record_recovery_event(ledger, failure)
                failures.append(failure)
                changed = True
                group_failed = True
                continue
            existing = dict(entries_by_key.get(item_key) or {})
            if existing:
                stored_hash = str(existing.get("provider_visible_hash") or "").strip()
                if stored_hash and stored_hash != expected_hash:
                    failure = _structured_failure(
                        scope=scope,
                        code="provider_visible_confirmed_entry_hash_mismatch",
                        message="provider-visible context confirmed entry maps to different content",
                        details={
                            "entry_index": _safe_int(existing.get("entry_index")),
                            "item_key": item_key,
                            "provider_visible_hash": expected_hash,
                            "stored_provider_visible_hash": stored_hash,
                            "request_id": str(request_id or ""),
                        },
                    )
                    ledger = _record_recovery_event(ledger, failure)
                    failures.append(failure)
                    changed = True
                    group_failed = True
                    continue
                confirmation = {
                    "scope": scope,
                    "entry_index": _safe_int(existing.get("entry_index")),
                    "item_key": item_key,
                    "status": str(existing.get("commit_status") or ""),
                    "already_confirmed": True,
                }
                confirmations.append(confirmation)
                group_confirmations.append(confirmation)
                continue
            entries_by_index = _entries_by_index(ledger)
            next_index = _next_entry_index(ledger, entries_by_index=entries_by_index)
            entry = _ledger_entry(
                entry_index=next_index,
                item_key=item_key,
                provider_visible_message=provider_message,
                provider_visible_hash=expected_hash,
                kind=str(ref.kind or ""),
                source_ref=str(ref.source_ref or ""),
                semantic_commit_class=str(ref.semantic_commit_class or ""),
                previous_entry_hash=_previous_entry_hash({"entries": _confirmed_ledger_entries(ledger)}),
                provider=str(provider or ref.provider or ""),
                model=str(model or ref.model or ""),
                adapter_contract=candidate_adapter,
                confirmed_by_request_id=str(request_id or ""),
                confirmed_response_ref=str(response_ref or ""),
                semantic_visibility=str(ref.semantic_visibility or ""),
                validity_scope=str(ref.validity_scope or ""),
                compaction_generation=str(ref.compaction_generation or ""),
                cache_spine_hash=str(ref.cache_spine_hash or ""),
            )
            ledger["entries"] = [
                *[dict(item) for item in list(ledger.get("entries") or []) if isinstance(item, dict)],
                entry,
            ]
            ledger["items"] = {
                str(item.get("item_key") or ""): _safe_int(item.get("entry_index"))
                for item in list(ledger["entries"] or [])
                if isinstance(item, dict) and str(item.get("item_key") or "").strip()
            }
            ledger["next_entry_index"] = next_index + 1
            entries_by_key[item_key] = entry
            confirmation = {
                "scope": scope,
                "entry_index": next_index,
                "item_key": item_key,
                "status": PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS,
                "already_confirmed": False,
            }
            confirmations.append(confirmation)
            group_confirmations.append(confirmation)
            confirmed_count += 1
            changed = True
        if group_confirmations and not group_failed:
            ledger, anchor = _record_provider_success_anchor(
                ledger,
                scope=scope,
                provider=provider,
                model=model,
                request_id=request_id,
                response_ref=response_ref,
                provider_payload_prefix_hash=provider_payload_prefix_hash,
                provider_payload_messages_hash=provider_payload_messages_hash,
                provider_payload_message_prefix_hash=provider_payload_message_prefix_hash,
                transport_contract_hash=transport_contract_hash,
                request_message_count=request_message_count,
                request_entry_indexes=[
                    _safe_int(item.get("entry_index"))
                    for item in group_confirmations
                    if _safe_int(item.get("entry_index")) > 0
                ],
            )
            if anchor:
                anchors.append(anchor)
                anchor_update_count += 1
                changed = True
        if changed:
            changed_groups += 1
            ledger = _finalize_ledger(
                ledger,
                scope=scope,
                provider=provider,
                model=model,
                adapter_contract=str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT),
            )
            save_provider_visible_context_ledger(storage_root=storage_root, scope=scope, ledger=ledger)

    return {
        "status": "ok" if not failures else "recovery_required",
        "confirmed_count": confirmed_count,
        "confirmation_count": len(confirmations),
        "changed_group_count": changed_groups,
        "anchor_update_count": anchor_update_count,
        "confirmations": confirmations,
        "provider_success_anchors": anchors,
        "failures": failures,
        "authority": "runtime.context_management.provider_visible_context_ledger.confirm",
    }


def latest_provider_visible_context_success_anchor(*, storage_root: Path | str | None, scope: str) -> dict[str, Any]:
    ledger = load_provider_visible_context_ledger(
        storage_root=Path(storage_root) if storage_root else None,
        scope=scope,
    )
    return dict(ledger.get("last_provider_success_anchor") or {})


def load_provider_visible_context_ledger(*, storage_root: Path | None, scope: str) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    path = provider_visible_context_ledger_path(storage_root=storage_root, scope=normalized_scope)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "authority": "runtime.context_management.provider_visible_context_ledger.load",
            "schema_version": PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION,
            "adapter_contract": PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT,
            "scope": normalized_scope,
            "status": "recovery_required",
            "items": {},
            "entries": [],
            "ledger_failure": _structured_failure(
                scope=normalized_scope,
                code="ledger_json_corrupt",
                message="provider-visible context ledger could not be parsed",
                details={"path": str(path), "error": type(exc).__name__},
            ),
        }
    if not isinstance(payload, dict):
        return {
            "authority": "runtime.context_management.provider_visible_context_ledger.load",
            "schema_version": PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION,
            "adapter_contract": PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT,
            "scope": normalized_scope,
            "status": "recovery_required",
            "items": {},
            "entries": [],
            "ledger_failure": _structured_failure(
                scope=normalized_scope,
                code="ledger_not_object",
                message="provider-visible context ledger root is not an object",
                details={"path": str(path)},
            ),
        }
    return dict(payload or {})


def save_provider_visible_context_ledger(*, storage_root: Path | None, scope: str, ledger: dict[str, Any]) -> None:
    path = provider_visible_context_ledger_path(storage_root=storage_root, scope=scope)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_stable(dict(ledger or {})), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def provider_visible_context_ledger_path(*, storage_root: Path | None, scope: str) -> Path | None:
    if storage_root is None:
        return None
    try:
        runtime_state_dir = ProjectLayout.from_runtime_root(Path(storage_root)).runtime_state_dir.resolve()
    except Exception:
        runtime_state_dir = Path(storage_root).resolve()
    safe_scope = safe_provider_visible_context_ledger_filename(scope)
    if not safe_scope:
        return None
    return runtime_state_dir / "provider_visible_context_ledger" / f"{safe_scope}.json"


def safe_provider_visible_context_ledger_filename(value: str) -> str:
    text = str(value or "").strip()
    result = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("._")[:180] or "default"


def provider_visible_message_hash(message: dict[str, Any]) -> str:
    return _stable_json_hash(_provider_visible_message(message))


def _ledger_for_append(
    ledger: dict[str, Any],
    *,
    scope: str,
    provider: str,
    model: str,
    adapter_contract: str,
) -> dict[str, Any]:
    if not ledger:
        return _new_ledger(scope=scope, provider=provider, model=model, adapter_contract=adapter_contract)
    payload = dict(ledger or {})
    payload.setdefault("schema_version", PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION)
    payload.setdefault("adapter_contract", adapter_contract)
    payload.setdefault("scope", scope)
    payload.setdefault("status", "ok")
    payload.setdefault("provider", str(provider or payload.get("provider") or ""))
    payload.setdefault("model", str(model or payload.get("model") or ""))
    payload.setdefault("items", {})
    payload.setdefault("entries", [])
    return payload


def _new_ledger(*, scope: str, provider: str, model: str, adapter_contract: str) -> dict[str, Any]:
    return {
        "authority": "runtime.context_management.provider_visible_context_ledger",
        "schema_version": PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION,
        "adapter_contract": str(adapter_contract or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT),
        "scope": str(scope or "default"),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "status": "ok",
        "next_entry_index": 1,
        "items": {},
        "entries": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def _ledger_failure(ledger: dict[str, Any], *, scope: str, adapter_contract: str) -> dict[str, Any]:
    failure = dict(ledger.get("ledger_failure") or {}) if isinstance(ledger.get("ledger_failure"), dict) else {}
    if failure:
        return failure
    if not ledger:
        return {}
    schema_version = _safe_int(ledger.get("schema_version"))
    if schema_version != PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION:
        return _structured_failure(
            scope=scope,
            code="ledger_schema_version_mismatch",
            message="provider-visible context ledger schema version does not match",
            details={
                "schema_version": schema_version,
                "expected_schema_version": PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION,
            },
        )
    existing_adapter = str(ledger.get("adapter_contract") or "")
    if existing_adapter and existing_adapter != adapter_contract:
        return _structured_failure(
            scope=scope,
            code="adapter_contract_mismatch",
            message="provider-visible context ledger adapter contract does not match",
            details={
                "adapter_contract": existing_adapter,
                "expected_adapter_contract": adapter_contract,
            },
        )
    return {}


def _record_recovery_event(ledger: dict[str, Any], failure: dict[str, Any]) -> dict[str, Any]:
    payload = dict(ledger or {})
    events = [dict(item) for item in list(payload.get("recovery_events") or []) if isinstance(item, dict)]
    events.append(dict(failure or {}))
    payload["recovery_events"] = events
    payload["status"] = "recovery_required"
    return payload


def _record_provider_success_anchor(
    ledger: dict[str, Any],
    *,
    scope: str,
    provider: str,
    model: str,
    request_id: str,
    response_ref: str,
    provider_payload_prefix_hash: str,
    provider_payload_messages_hash: str,
    provider_payload_message_prefix_hash: str,
    transport_contract_hash: str,
    request_message_count: int,
    request_entry_indexes: list[int] | tuple[int, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return dict(ledger or {}), {}
    payload = dict(ledger or {})
    entries = sorted(
        _confirmed_ledger_entries(payload),
        key=lambda item: (_safe_int(item.get("entry_index")), str(item.get("item_key") or "")),
    )
    if not entries:
        return payload, {}
    entry_indexes = [_safe_int(item.get("entry_index")) for item in entries if _safe_int(item.get("entry_index")) > 0]
    if not entry_indexes:
        return payload, {}
    request_indexes = sorted({int(item) for item in list(request_entry_indexes or []) if int(item or 0) > 0})
    last_entry = dict(entries[-1])
    anchor_seed = {
        "scope": str(scope or "default"),
        "request_id": normalized_request_id,
        "response_ref": str(response_ref or ""),
        "entry_count": len(entry_indexes),
        "terminal_entry_index": entry_indexes[-1],
        "terminal_entry_hash": str(last_entry.get("entry_hash") or ""),
        "provider_payload_messages_hash": str(provider_payload_messages_hash or ""),
    }
    anchor = {
        "anchor_id": "provider-success-anchor:" + _stable_json_hash(anchor_seed).split(":", 1)[-1][:16],
        "request_id": normalized_request_id,
        "response_ref": str(response_ref or ""),
        "scope": str(scope or "default"),
        "provider": str(provider or payload.get("provider") or ""),
        "model": str(model or payload.get("model") or ""),
        "confirmed_ledger_entry_range": [entry_indexes[0], entry_indexes[-1]],
        "confirmed_ledger_entry_count": len(entry_indexes),
        "request_confirmed_entry_indexes": request_indexes,
        "terminal_entry_index": entry_indexes[-1],
        "terminal_entry_hash": str(last_entry.get("entry_hash") or ""),
        "terminal_cumulative_prefix_hash": str(last_entry.get("cumulative_prefix_hash") or ""),
        "compaction_generation": _normalize_compaction_generation(last_entry.get("compaction_generation")),
        "provider_payload_prefix_hash": str(provider_payload_prefix_hash or ""),
        "provider_payload_messages_hash": str(provider_payload_messages_hash or ""),
        "provider_payload_message_prefix_hash": str(provider_payload_message_prefix_hash or ""),
        "transport_contract_hash": str(transport_contract_hash or ""),
        "request_message_count": _safe_int(request_message_count),
        "created_at": time.time(),
        "authority": "runtime.context_management.provider_visible_context_ledger.provider_success_anchor",
    }
    existing = [
        dict(item)
        for item in list(payload.get("provider_success_anchors") or [])
        if isinstance(item, dict)
        and str(item.get("anchor_id") or "") != str(anchor.get("anchor_id") or "")
    ]
    payload["provider_success_anchors"] = [*existing, anchor][-32:]
    payload["last_provider_success_anchor"] = anchor
    payload["last_success_anchor_id"] = str(anchor.get("anchor_id") or "")
    return payload, anchor


def _finalize_ledger(
    ledger: dict[str, Any],
    *,
    scope: str,
    provider: str,
    model: str,
    adapter_contract: str,
) -> dict[str, Any]:
    payload = dict(ledger or {})
    payload["authority"] = "runtime.context_management.provider_visible_context_ledger"
    payload["schema_version"] = PROVIDER_VISIBLE_CONTEXT_LEDGER_SCHEMA_VERSION
    payload["adapter_contract"] = str(adapter_contract or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT)
    payload["scope"] = str(scope or payload.get("scope") or "default")
    payload["provider"] = str(provider or payload.get("provider") or "")
    payload["model"] = str(model or payload.get("model") or "")
    payload["entries"] = [dict(item) for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    payload["items"] = {
        str(entry.get("item_key") or ""): _safe_int(entry.get("entry_index"))
        for entry in _confirmed_ledger_entries(payload)
        if str(entry.get("item_key") or "").strip()
    }
    payload["entry_index"] = max([_safe_int(entry.get("entry_index")) for entry in payload["entries"]] or [0])
    payload["next_entry_index"] = max(_safe_int(payload.get("next_entry_index")), int(payload["entry_index"]) + 1)
    payload["updated_at"] = time.time()
    content_hash = _ledger_content_hash(payload)
    payload["ledger_hash"] = content_hash
    payload["ledger_id"] = "pvctx:" + content_hash[:16]
    return payload


def _ledger_entry(
    *,
    entry_index: int,
    item_key: str,
    provider_visible_message: dict[str, Any],
    provider_visible_hash: str,
    kind: str,
    source_ref: str,
    semantic_commit_class: str,
    previous_entry_hash: str,
    provider: str,
    model: str,
    adapter_contract: str,
    confirmed_by_request_id: str = "",
    confirmed_response_ref: str = "",
    semantic_visibility: str = "",
    validity_scope: str = "",
    compaction_generation: str = "",
    cache_spine_hash: str = "",
) -> dict[str, Any]:
    replay_only = str(semantic_commit_class or "").startswith("provider_visible_replay_only")
    payload = {
        "entry_index": int(entry_index or 0),
        "item_key": str(item_key or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "adapter_contract": str(adapter_contract or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT),
        "context_section": "context_memory_prefix",
        "ledger_lane": PROVIDER_VISIBLE_CONTEXT_PREFIX,
        "semantic_visibility": str(semantic_visibility or ("historical_only" if replay_only else "active")),
        "validity_scope": str(validity_scope or ""),
        "compaction_generation": str(compaction_generation or ""),
        "cache_spine_hash": str(cache_spine_hash or ""),
        "semantic_commit_class": str(semantic_commit_class or ""),
        "source_ref": str(source_ref or ""),
        "kind": str(kind or ""),
        "provider_visible_message": _provider_visible_message(provider_visible_message),
        "provider_visible_hash": str(provider_visible_hash or ""),
        "previous_entry_hash": str(previous_entry_hash or ""),
        "commit_status": PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS,
        "confirmed_at": time.time(),
        "confirmed_by_request_id": str(confirmed_by_request_id or ""),
        "confirmed_response_ref": str(confirmed_response_ref or ""),
        "confirmation_authority": "runtime.model_gateway.model_runtime.provider_success",
        "created_at": time.time(),
    }
    payload["entry_hash"] = _ledger_entry_hash(payload)
    payload["cumulative_prefix_hash"] = _stable_json_hash(
        {
            "previous_entry_hash": payload["previous_entry_hash"],
            "entry_hash": payload["entry_hash"],
        }
    )
    return payload


def _inherited_ledger_entries_for_anchor(
    *,
    storage_root: Path | None,
    scope: str,
    anchor: dict[str, Any],
    compaction_generation: str,
    adapter_contract: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_scope = str(scope or "").strip()
    normalized_anchor = dict(anchor or {})
    if not normalized_scope or not normalized_anchor:
        return [], []
    terminal_entry_index = _anchor_terminal_entry_index(normalized_anchor)
    if terminal_entry_index <= 0:
        return [], [
            _structured_failure(
                scope=normalized_scope,
                code="fork_inherited_provider_visible_anchor_missing_terminal_entry",
                message="fork provider-visible context anchor is missing a terminal ledger entry",
                details={
                    "anchor_id": str(normalized_anchor.get("anchor_id") or ""),
                    "anchor_scope": str(normalized_anchor.get("scope") or ""),
                },
            )
        ]
    ledger = load_provider_visible_context_ledger(storage_root=storage_root, scope=normalized_scope)
    failure = _ledger_failure(ledger, scope=normalized_scope, adapter_contract=adapter_contract)
    if failure:
        return [], [failure]
    entries = [
        dict(item)
        for item in _confirmed_ledger_entries(ledger)
        if 0 < _safe_int(item.get("entry_index")) <= terminal_entry_index
    ]
    entries = _ledger_entries_for_compaction_generation(
        entries,
        compaction_generation=_normalize_compaction_generation(compaction_generation),
    )
    if not entries:
        return [], [
            _structured_failure(
                scope=normalized_scope,
                code="fork_inherited_provider_visible_ledger_anchor_empty",
                message="fork provider-visible context anchor points to an empty or missing parent ledger range",
                details={
                    "anchor_id": str(normalized_anchor.get("anchor_id") or ""),
                    "terminal_entry_index": terminal_entry_index,
                },
            )
        ]
    entries = sorted(entries, key=lambda item: (_safe_int(item.get("entry_index")), str(item.get("item_key") or "")))
    terminal_entry = dict(entries[-1])
    expected_terminal_hash = str(normalized_anchor.get("terminal_entry_hash") or "").strip()
    expected_cumulative_hash = str(normalized_anchor.get("terminal_cumulative_prefix_hash") or "").strip()
    actual_terminal_hash = str(terminal_entry.get("entry_hash") or "").strip()
    actual_cumulative_hash = str(terminal_entry.get("cumulative_prefix_hash") or "").strip()
    if expected_terminal_hash and actual_terminal_hash and expected_terminal_hash != actual_terminal_hash:
        return [], [
            _structured_failure(
                scope=normalized_scope,
                code="fork_inherited_provider_visible_terminal_entry_hash_mismatch",
                message="fork provider-visible context anchor does not match the parent ledger terminal entry",
                details={
                    "anchor_id": str(normalized_anchor.get("anchor_id") or ""),
                    "terminal_entry_index": terminal_entry_index,
                    "expected_terminal_entry_hash": expected_terminal_hash,
                    "actual_terminal_entry_hash": actual_terminal_hash,
                },
            )
        ]
    if expected_cumulative_hash and actual_cumulative_hash and expected_cumulative_hash != actual_cumulative_hash:
        return [], [
            _structured_failure(
                scope=normalized_scope,
                code="fork_inherited_provider_visible_cumulative_hash_mismatch",
                message="fork provider-visible context anchor does not match the parent ledger cumulative prefix hash",
                details={
                    "anchor_id": str(normalized_anchor.get("anchor_id") or ""),
                    "terminal_entry_index": terminal_entry_index,
                    "expected_terminal_cumulative_prefix_hash": expected_cumulative_hash,
                    "actual_terminal_cumulative_prefix_hash": actual_cumulative_hash,
                },
            )
        ]
    return entries, []


def _ledger_entries_for_compaction_generation(
    entries: list[dict[str, Any]],
    *,
    compaction_generation: str,
) -> list[dict[str, Any]]:
    generation = _normalize_compaction_generation(compaction_generation)
    return [
        dict(item)
        for item in list(entries or [])
        if _normalize_compaction_generation(dict(item).get("compaction_generation")) == generation
    ]


def _normalize_compaction_generation(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return text or "0"


def _anchor_terminal_entry_index(anchor: dict[str, Any]) -> int:
    payload = dict(anchor or {})
    terminal_entry_index = _safe_int(payload.get("terminal_entry_index"))
    if terminal_entry_index > 0:
        return terminal_entry_index
    entry_range = payload.get("confirmed_ledger_entry_range")
    if isinstance(entry_range, (list, tuple)) and len(entry_range) >= 2:
        return _safe_int(entry_range[-1])
    return 0


def _mark_inherited_provider_visible_spec(
    spec: dict[str, Any],
    *,
    inherited_scope: str,
    write_scope: str,
    anchor: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(spec or {})
    metadata = {
        **dict(payload.get("metadata") or {}),
        "provider_visible_context_inherited_from_scope": str(inherited_scope or ""),
        "provider_visible_context_write_scope": str(write_scope or ""),
        "fork_point_provider_visible_anchor_id": str(dict(anchor or {}).get("anchor_id") or ""),
        "fork_point_provider_visible_terminal_entry_index": _anchor_terminal_entry_index(dict(anchor or {})),
        "context_replay_policy": "fork_inherited_provider_visible_ledger_replay",
        "provider_visible_inheritance_authority": "runtime.context_management.provider_visible_context_ledger.fork_inheritance",
    }
    payload["metadata"] = metadata
    return payload


def _materialize_ledger_specs(ledger: dict[str, Any], *, scope: str) -> list[tuple[int, dict[str, Any]]]:
    entries = sorted(
        [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)],
        key=lambda item: (_safe_int(item.get("entry_index")), str(item.get("item_key") or "")),
    )
    return _materialize_ledger_entries(
        entries,
        scope=scope,
        recovery_events=[dict(item) for item in list(dict(ledger or {}).get("recovery_events") or []) if isinstance(item, dict)],
    )


def _materialize_ledger_entries(
    entries: list[dict[str, Any]],
    *,
    scope: str,
    recovery_events: list[dict[str, Any]] | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    ordered_entries = sorted(
        [dict(item) for item in list(entries or []) if isinstance(item, dict)],
        key=lambda item: (_safe_int(item.get("entry_index")), str(item.get("item_key") or "")),
    )
    result: list[tuple[int, dict[str, Any]]] = []
    recovery_payloads = [dict(item) for item in list(recovery_events or []) if isinstance(item, dict)]
    if recovery_payloads and not ordered_entries:
        result.append((0, _recovery_spec_from_failure(recovery_payloads[-1], scope=scope)))
    index = 0
    while index < len(ordered_entries):
        entry = ordered_entries[index]
        order = _safe_int(entry.get("entry_index"))
        if order <= 0:
            index += 1
            continue
        if not _ledger_entry_confirmed(entry):
            index += 1
            continue
        message = _provider_visible_message(dict(entry.get("provider_visible_message") or {}))
        if _provider_visible_message_role(message) == "tool":
            index += 1
            continue
        expected_tool_call_ids = _provider_visible_assistant_tool_call_ids(message)
        if expected_tool_call_ids:
            group_entries, next_index = _closed_tool_round_entries(
                ordered_entries,
                start_index=index,
                expected_tool_call_ids=expected_tool_call_ids,
            )
            if not group_entries:
                index += 1
                continue
            for group_entry in group_entries:
                group_order = _safe_int(group_entry.get("entry_index"))
                if group_order > 0:
                    result.append((group_order, _spec_from_ledger_entry(group_entry, scope=scope)))
            index = next_index
            continue
        result.append((order, _spec_from_ledger_entry(entry, scope=scope)))
        index += 1
    return result


def _closed_tool_round_entries(
    entries: list[dict[str, Any]],
    *,
    start_index: int,
    expected_tool_call_ids: list[str],
) -> tuple[list[dict[str, Any]], int]:
    expected = [str(item).strip() for item in list(expected_tool_call_ids or []) if str(item).strip()]
    if not expected or start_index < 0 or start_index >= len(entries):
        return [], start_index + 1
    group = [dict(entries[start_index])]
    found: set[str] = set()
    index = start_index + 1
    while index < len(entries) and len(found) < len(set(expected)):
        candidate = dict(entries[index])
        if not _ledger_entry_confirmed(candidate):
            index += 1
            continue
        message = _provider_visible_message(dict(candidate.get("provider_visible_message") or {}))
        role = _provider_visible_message_role(message)
        if role != "tool":
            break
        tool_call_id = str(message.get("tool_call_id") or "").strip()
        if tool_call_id not in expected or tool_call_id in found:
            break
        group.append(candidate)
        found.add(tool_call_id)
        index += 1
    if set(expected).issubset(found):
        return group, index
    return [], start_index + 1


def _provider_visible_message_role(message: dict[str, Any]) -> str:
    return str(dict(message or {}).get("role") or "").strip()


def _provider_visible_assistant_tool_call_ids(message: dict[str, Any]) -> list[str]:
    payload = dict(message or {})
    if _provider_visible_message_role(payload) != "assistant":
        return []
    ids: list[str] = []
    for raw_call in list(payload.get("tool_calls") or []):
        if not isinstance(raw_call, dict):
            continue
        call_id = str(dict(raw_call).get("id") or "").strip()
        if call_id and call_id not in ids:
            ids.append(call_id)
    return ids


def _spec_from_ledger_entry(entry: dict[str, Any], *, scope: str) -> dict[str, Any]:
    order = _safe_int(entry.get("entry_index"))
    message = _provider_visible_message(dict(entry.get("provider_visible_message") or {}))
    missing_message = not bool(message)
    failure: dict[str, Any] = {}
    if missing_message:
        failure = _structured_failure(
            scope=scope,
            code="provider_visible_message_missing_for_entry",
            message="provider-visible ledger entry cannot be replayed because message content is absent",
            details={
                "entry_index": order,
                "item_key": str(entry.get("item_key") or ""),
                "provider_visible_hash": str(entry.get("provider_visible_hash") or ""),
            },
        )
        return _recovery_spec_from_failure(failure, scope=scope, order=order)
    semantic_commit_class = str(entry.get("semantic_commit_class") or "context_memory_append")
    replay_only = semantic_commit_class.startswith("provider_visible_replay_only")
    entry_kind = str(entry.get("kind") or "").strip()
    metadata = {
        "context_cache_section": "context_memory_prefix",
        "fixed_context_package": "context_memory_prefix",
        "physical_prefix_lane": PROVIDER_VISIBLE_CONTEXT_PREFIX,
        "semantic_visibility": str(entry.get("semantic_visibility") or ("historical_only" if replay_only else "active")),
        "validity_scope": str(entry.get("validity_scope") or ""),
        "compaction_generation": str(entry.get("compaction_generation") or ""),
        "cache_spine_hash": str(entry.get("cache_spine_hash") or ""),
        "provider_visible_context_ledger_scope": scope,
        "provider_visible_context_ledger_entry_index": order,
        "provider_visible_context_ledger_item_key": str(entry.get("item_key") or ""),
        "provider_visible_context_ledger_authority": "runtime.context_management.provider_visible_context_ledger",
        "provider_visible_hash": str(entry.get("provider_visible_hash") or provider_visible_message_hash(message)),
        "provider_visible_payload_form": "provider_chat_completion_message",
        "provider_visible_payload_authority": "runtime.context_management.provider_visible_context_ledger.replay",
        "semantic_commit_class": semantic_commit_class,
        "provider_visible_replay_original_kind": entry_kind,
        "provider_visible_replay_kind_authority": "runtime.context_management.provider_visible_context_ledger.replay_kind",
        "provider_visible_replay_only": replay_only,
        "semantic_memory_visible": not replay_only,
        "semantic_memory_commit_policy": "never_commit" if replay_only else "append_then_seal",
        "content_source": "runtime.context_management.provider_visible_context_ledger.replay",
    }
    spec = {
        "role": str(message.get("role") or "system"),
        "content": str(message.get("content") if message.get("content") is not None else ""),
        "kind": _provider_visible_ledger_replay_kind(entry_kind, semantic_commit_class, message),
        "source_ref": str(entry.get("source_ref") or entry.get("item_key") or ""),
        "cache_scope": "task",
        "cache_role": "session_stable",
        "prefix_tier": "task",
        "compression_role": "preserve",
        "metadata": metadata,
        "model_message": message,
    }
    policy = context_segment_policy_for_spec(spec, default_section="context_memory_prefix")
    spec["metadata"] = {
        **metadata,
        **context_segment_policy_metadata(policy),
    }
    return spec


def _provider_visible_ledger_replay_kind(
    entry_kind: str,
    semantic_commit_class: str,
    message: dict[str, Any],
) -> str:
    kind = str(entry_kind or "").strip()
    semantic_class = str(semantic_commit_class or "").strip()
    role = str(dict(message or {}).get("role") or "").strip()
    if semantic_class in {"tool_transcript", "provider_visible_replay_only_tool_transcript"}:
        return "provider_visible_tool_transcript_replay"
    if is_tool_transcript_kind(kind, include_historical=True):
        return "provider_visible_tool_transcript_replay"
    if role == "tool" or (role == "assistant" and dict(message or {}).get("tool_calls")):
        return "provider_visible_tool_transcript_replay"
    if semantic_class in {"current_user_context", "provider_visible_replay_only_user_steer"}:
        return "provider_visible_user_context_replay"
    if kind in {"current_turn_user_context", "single_agent_turn_user_steer_context", "user_steering_context_append"}:
        return "provider_visible_user_context_replay"
    if role == "user":
        return "provider_visible_user_message_replay"
    if role == "assistant":
        return "provider_visible_assistant_message_replay"
    return "provider_visible_context_replay"


def _current_context_append_spec_from_candidate(
    spec: dict[str, Any],
    *,
    item_key: str,
    provider_visible_message: dict[str, Any],
    provider_visible_hash: str,
    policy: Any,
    scope: str,
    storage_root: Path | None,
    provider: str,
    model: str,
    adapter_contract: str,
) -> dict[str, Any]:
    payload = dict(spec or {})
    storage_root_text = str(Path(storage_root).resolve()) if storage_root is not None else ""
    semantic_commit_class = str(
        dict(payload.get("metadata") or {}).get("semantic_commit_class")
        or getattr(policy, "semantic_slot", "")
        or ""
    )
    metadata = {
        **dict(payload.get("metadata") or {}),
        **context_segment_policy_metadata(policy),
        "context_cache_section": "context_append",
        "fixed_context_package": "context_memory_append",
        "provider_visible_context_ledger_scope": str(scope or ""),
        "provider_visible_context_ledger_storage_root": storage_root_text,
        "provider_visible_context_ledger_commit_stage": "provider_success_required",
        "provider_visible_context_ledger_item_key": str(item_key or ""),
        "provider_visible_context_ledger_authority": "runtime.context_management.provider_visible_context_ledger",
        "provider_visible_hash": str(provider_visible_hash or ""),
        "provider_visible_payload_form": "provider_chat_completion_message",
        "provider_visible_payload_authority": "runtime.context_management.provider_visible_context_ledger.current_append",
        "provider_visible_context_candidate_message": _provider_visible_message(provider_visible_message),
        "provider_visible_context_candidate_kind": str(payload.get("kind") or ""),
        "provider_visible_context_candidate_source_ref": str(payload.get("source_ref") or ""),
        "provider_visible_context_candidate_semantic_commit_class": semantic_commit_class,
        "provider_visible_context_candidate_provider": str(provider or ""),
        "provider_visible_context_candidate_model": str(model or ""),
        "provider_adapter_contract": str(adapter_contract or PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT),
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_ledger_replay",
    }
    payload["cache_scope"] = str(getattr(policy, "prefix_cache_scope", "") or payload.get("cache_scope") or "task")
    payload["cache_role"] = str(getattr(policy, "prefix_cache_role", "") or payload.get("cache_role") or "session_stable")
    payload["prefix_tier"] = str(getattr(policy, "prefix_tier", "") or payload.get("prefix_tier") or "task")
    payload["role"] = str(provider_visible_message.get("role") or payload.get("role") or "system")
    payload["content"] = str(provider_visible_message.get("content") if provider_visible_message.get("content") is not None else "")
    payload["model_message"] = _provider_visible_message(provider_visible_message)
    payload["metadata"] = metadata
    return payload


def _recovery_spec_from_failure(failure: dict[str, Any], *, scope: str, order: int = 0) -> dict[str, Any]:
    content = (
        "Provider-visible context ledger recovery checkpoint\n"
        + json.dumps(dict(failure or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    spec = {
        "role": "system",
        "content": content,
        "kind": "provider_visible_ledger_recovery_checkpoint",
        "source_ref": f"provider_visible_ledger_recovery:{scope}:{order}",
        "cache_scope": "task",
        "cache_role": "session_stable",
        "prefix_tier": "task",
        "compression_role": "preserve",
        "metadata": {
            "context_cache_section": "context_memory_prefix",
            "fixed_context_package": "context_memory_prefix",
            "provider_visible_context_ledger_scope": scope,
            "provider_visible_context_ledger_recovery_required": True,
            "provider_visible_context_ledger_structured_failure": dict(failure or {}),
            "semantic_commit_class": "ledger_recovery_context",
        },
        "model_message": {"role": "system", "content": content},
    }
    policy = context_segment_policy_for_spec(spec, default_section="context_memory_prefix")
    spec["metadata"] = {
        **dict(spec.get("metadata") or {}),
        **context_segment_policy_metadata(policy),
    }
    return spec


def _provider_visible_message_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    raw_message = spec.get("model_message") if isinstance(spec.get("model_message"), dict) else {}
    message = dict(raw_message or {})
    if not message:
        message = {
            "role": str(spec.get("role") or "user"),
            "content": str(spec.get("content") if spec.get("content") is not None else ""),
        }
    return _provider_visible_message(message)


def _provider_visible_message(message: dict[str, Any]) -> dict[str, Any]:
    payloads = provider_message_payloads([dict(message or {})])
    if not payloads:
        return {}
    return _json_stable(dict(payloads[0] or {}))


def _provider_visible_item_key(spec: dict[str, Any], *, provider_visible_hash: str, policy: Any) -> str:
    metadata = dict(spec.get("metadata") or {})
    explicit = str(
        metadata.get("provider_visible_context_ledger_item_key")
        or metadata.get("append_only_context_item_key")
        or ""
    ).strip()
    if explicit:
        return explicit
    identity_policy = str(getattr(policy, "identity_policy", "") or "").strip()
    if identity_policy == "source_ref_stable":
        source_ref = str(spec.get("source_ref") or "").strip()
        if source_ref:
            return _stable_json_hash(
                {
                    "normalization": PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT,
                    "kind": str(spec.get("kind") or ""),
                    "source_ref": source_ref,
                }
            )
    return _stable_json_hash(
        {
            "normalization": PROVIDER_VISIBLE_CONTEXT_LEDGER_ADAPTER_CONTRACT,
            "kind": str(spec.get("kind") or ""),
            "source_ref": str(spec.get("source_ref") or ""),
            "provider_visible_hash": str(provider_visible_hash or ""),
        }
    )


def _entries_by_key(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)]:
        key = str(entry.get("item_key") or "").strip()
        if key:
            result[key] = entry
    return result


def _entries_by_index(ledger: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for entry in [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)]:
        index = _safe_int(entry.get("entry_index"))
        if index > 0:
            result[index] = entry
    return result


def _next_entry_index(ledger: dict[str, Any], *, entries_by_index: dict[int, dict[str, Any]]) -> int:
    next_index = _safe_int(dict(ledger or {}).get("next_entry_index"))
    if next_index > 0:
        return next_index
    return max([*entries_by_index.keys(), 0]) + 1


def _previous_entry_hash(ledger: dict[str, Any]) -> str:
    entries = sorted(
        [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)],
        key=lambda item: _safe_int(item.get("entry_index")),
    )
    if not entries:
        return ""
    return str(entries[-1].get("entry_hash") or "")


def _ledger_entry_confirmed(entry: dict[str, Any]) -> bool:
    status = str(dict(entry or {}).get("commit_status") or "").strip()
    if status == PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS:
        return True
    return status in _LEGACY_REPLAYABLE_COMMIT_STATUSES


def _confirmed_ledger_entries(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(dict(ledger or {}).get("entries") or [])
        if isinstance(item, dict) and _ledger_entry_confirmed(item)
    ]


def _ledger_entry_hash(entry: dict[str, Any]) -> str:
    payload = dict(entry or {})
    return _stable_json_hash(
        {
            "schema": "provider_visible_context_ledger_entry_hash_v2",
            "entry_index": _safe_int(payload.get("entry_index")),
            "item_key": str(payload.get("item_key") or ""),
            "provider": str(payload.get("provider") or ""),
            "model": str(payload.get("model") or ""),
            "adapter_contract": str(payload.get("adapter_contract") or ""),
            "context_section": str(payload.get("context_section") or ""),
            "semantic_commit_class": str(payload.get("semantic_commit_class") or ""),
            "ledger_lane": str(payload.get("ledger_lane") or ""),
            "semantic_visibility": str(payload.get("semantic_visibility") or ""),
            "validity_scope": str(payload.get("validity_scope") or ""),
            "compaction_generation": str(payload.get("compaction_generation") or ""),
            "cache_spine_hash": str(payload.get("cache_spine_hash") or ""),
            "source_ref": str(payload.get("source_ref") or ""),
            "kind": str(payload.get("kind") or ""),
            "provider_visible_message": _provider_visible_message(dict(payload.get("provider_visible_message") or {})),
            "provider_visible_hash": str(payload.get("provider_visible_hash") or ""),
            "previous_entry_hash": str(payload.get("previous_entry_hash") or ""),
        }
    )


def _structured_failure(*, scope: str, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(code or "provider_visible_context_ledger_failure"),
        "message": str(message or ""),
        "scope": str(scope or "default"),
        "severity": "p0",
        "recovery_policy": "insert_recovery_context_checkpoint_before_resuming_append_only_ledger",
        "recovery_position": "context_memory_prefix",
        "details": dict(details or {}),
        "authority": "runtime.context_management.provider_visible_context_ledger.structured_failure",
    }


def _ledger_content_hash(ledger: dict[str, Any]) -> str:
    payload = {key: value for key, value in dict(ledger or {}).items() if key not in {"ledger_hash", "ledger_id", "updated_at"}}
    return _stable_json_hash(payload)


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
