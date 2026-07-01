from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout
from runtime.model_gateway.lightweight_chat_model import provider_message_payloads

from context_system.segments.policy import (
    CONTEXT_APPEND,
    CURRENT_CONTROL_TAIL_KINDS,
    DYNAMIC_TAIL,
    DEFAULT_PROVIDER_ADAPTER_CONTRACT,
    context_append_order_key,
    context_segment_policy_for_spec,
    context_segment_policy_is_provider_visible_sealable,
    context_segment_policy_metadata,
)
from .context_candidates import ContextCommitCandidate


PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION = 2
PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT = DEFAULT_PROVIDER_ADAPTER_CONTRACT
PROVIDER_VISIBLE_APPEND_CONFIRMED_STATUS = "confirmed_provider_visible"
PROVIDER_VISIBLE_CONTEXT_PREFIX = "provider_visible_context_prefix"


def assemble_provider_visible_append_specs(
    items: list[tuple[int, dict[str, Any]]],
    *,
    storage_root: Path | None,
    scope: str,
    inherited_scope: str = "",
    inherited_anchor: dict[str, Any] | None = None,
    compaction_generation: str = "",
    provider: str = "",
    model: str = "",
    adapter_contract: str = PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
) -> list[tuple[int, dict[str, Any]]]:
    """Return current provider-visible append candidates.

    The provider-visible ledger records and de-duplicates append candidates,
    but it is not allowed to replay confirmed provider messages. Replay is owned
    only by the physical prefix frame ledger.

    """

    normalized_scope = str(scope or "default").strip() or "default"
    normalized_inherited_scope = str(inherited_scope or "").strip()
    normalized_generation = _normalize_compaction_generation(compaction_generation)
    normalized_adapter = str(adapter_contract or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT).strip()
    inherited_entries, _inherited_recovery_events = _inherited_ledger_entries_for_anchor(
        storage_root=storage_root,
        scope=normalized_inherited_scope,
        anchor=dict(inherited_anchor or {}),
        compaction_generation=normalized_generation,
        adapter_contract=normalized_adapter,
    )
    ledger = load_provider_visible_append_ledger(storage_root=storage_root, scope=normalized_scope)
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

    all_existing_entries = _active_confirmed_ledger_entries(ledger)
    existing_entries = _ledger_entries_for_compaction_generation(
        all_existing_entries,
        compaction_generation=normalized_generation,
    )
    inherited_entries_by_key = _entries_by_key({"entries": inherited_entries})
    entries_by_key = _entries_by_key({"entries": existing_entries})
    entries_by_fact_slot = _entries_by_fact_slot({"entries": existing_entries})
    inherited_entries_by_fact_slot = _entries_by_fact_slot({"entries": inherited_entries})
    changed = bool(failure)
    filtered_candidates: list[dict[str, Any]] = []
    current_append_specs: list[tuple[int, dict[str, Any]]] = []

    for original_order, raw_spec in sorted(list(items or []), key=context_append_order_key):
        spec = dict(raw_spec or {})
        policy = context_segment_policy_for_spec(spec)
        provider_message = _provider_visible_message_from_spec(spec)
        if not provider_message:
            continue
        provider_hash = _stable_json_hash(provider_message)
        fact_identity = _fact_identity_from_spec(spec)
        fact_slot_key = str(fact_identity.get("fact_slot_key") or "").strip()
        fact_content_hash = str(fact_identity.get("fact_content_hash") or "").strip()
        fact_change_class = str(fact_identity.get("fact_change_class") or "").strip()
        if fact_slot_key:
            existing_fact = dict(entries_by_fact_slot.get(fact_slot_key) or {})
            inherited_fact = dict(inherited_entries_by_fact_slot.get(fact_slot_key) or {})
            matched_fact = existing_fact or inherited_fact
            matched_fact_content_hash = str(matched_fact.get("fact_content_hash") or "").strip()
            if matched_fact and fact_content_hash and matched_fact_content_hash == fact_content_hash:
                filtered_candidates.append(
                    _filtered_fact_candidate(
                        spec,
                        fact_identity=fact_identity,
                        reason="same_fact_slot_same_content_hash_already_visible",
                        matched_entry=matched_fact,
                    )
                )
                continue
            if matched_fact and fact_change_class in {"no_change", "minor_refresh", "freshness_only"}:
                filtered_candidates.append(
                    _filtered_fact_candidate(
                        spec,
                        fact_identity=fact_identity,
                        reason=f"fact_change_class_{fact_change_class}_does_not_require_reinjection",
                        matched_entry=matched_fact,
                    )
                )
                continue
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
                filtered_candidates.append(
                    _filtered_fact_candidate(
                        spec,
                        fact_identity=fact_identity,
                        reason="same_provider_visible_item_inherited_from_parent_scope",
                        matched_entry=inherited_existing,
                    )
                )
                continue
        current_append_specs.append(
            (
                int(original_order or 0),
                _current_append_spec_from_candidate(
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
    if filtered_candidates:
        ledger["last_filtered_fact_candidates"] = filtered_candidates[-50:]
        changed = True
    if changed:
        save_provider_visible_append_ledger(storage_root=storage_root, scope=normalized_scope, ledger=ledger)

    return [*current_append_specs]


def provider_visible_append_candidate_spec(
    spec: dict[str, Any],
    *,
    storage_root: Path | None,
    scope: str,
    provider: str = "",
    model: str = "",
    adapter_contract: str = PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
) -> dict[str, Any]:
    """Return a provider-visible append candidate without injecting replay messages.

    This is for append-only callers that already hold the immutable provider
    prefix in memory. The ledger may confirm this candidate after provider
    success, but it must not inject or reorder replay entries into the
    caller's current message sequence.
    """

    payload = dict(spec or {})
    normalized_scope = str(scope or "default").strip() or "default"
    normalized_adapter = str(adapter_contract or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT).strip()
    policy = context_segment_policy_for_spec(payload)
    if not _provider_visible_append_candidate_allowed(payload, policy=policy):
        return payload
    provider_message = _provider_visible_message_from_spec(payload)
    if not provider_message:
        return payload
    provider_hash = _stable_json_hash(provider_message)
    item_key = _provider_visible_item_key(payload, provider_visible_hash=provider_hash, policy=policy)
    return _current_append_spec_from_candidate(
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


def _provider_visible_append_candidate_allowed(payload: dict[str, Any], *, policy: Any) -> bool:
    metadata = dict(dict(payload or {}).get("metadata") or {})
    if not context_segment_policy_is_provider_visible_sealable(policy):
        return False
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


def confirm_provider_visible_append_entries(
    candidates: list[ContextCommitCandidate] | tuple[ContextCommitCandidate, ...],
    *,
    default_storage_root: Path | str | None = None,
    default_scope: str = "",
    provider: str = "",
    model: str = "",
    request_id: str = "",
    turn_id: str = "",
    response_ref: str = "",
    provider_payload_prefix_hash: str = "",
    provider_payload_messages_hash: str = "",
    physical_cache_spine_message_subtotal_hash: str = "",
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
        raise TypeError("confirm_provider_visible_append_entries requires ContextCommitCandidate items")
    normalized_turn_id = str(turn_id or "").strip()

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
        ledger = load_provider_visible_append_ledger(storage_root=storage_root, scope=scope)
        failure = _ledger_failure(
            ledger,
            scope=scope,
            adapter_contract=str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
        )
        if failure:
            failures.append(failure)
            continue
        ledger = _ledger_for_append(
            ledger,
            scope=scope,
            provider=provider,
            model=model,
            adapter_contract=str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
        )
        active_entries = _active_confirmed_ledger_entries(ledger)
        entries_by_key = _entries_by_key({"entries": active_entries})
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
                        "turn_id": normalized_turn_id,
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
                        "turn_id": normalized_turn_id,
                    },
                )
                ledger = _record_recovery_event(ledger, failure)
                failures.append(failure)
                changed = True
                group_failed = True
                continue
            candidate_adapter = str(ref.adapter_contract or ledger.get("adapter_contract") or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT)
            ledger_adapter = str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT)
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
                        "turn_id": normalized_turn_id,
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
                            "turn_id": normalized_turn_id,
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
                    "confirmed_turn_id": str(existing.get("confirmed_turn_id") or ""),
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
                previous_entry_hash=_previous_entry_hash({"entries": active_entries}),
                provider=str(provider or ref.provider or ""),
                model=str(model or ref.model or ""),
                adapter_contract=candidate_adapter,
                confirmed_by_request_id=str(request_id or ""),
                confirmed_turn_id=normalized_turn_id,
                confirmed_response_ref=str(response_ref or ""),
                semantic_visibility=str(ref.semantic_visibility or ""),
                validity_scope=str(ref.validity_scope or ""),
                compaction_generation=str(ref.compaction_generation or ""),
                cache_spine_hash=str(ref.cache_spine_hash or ""),
                provider_tool_protocol=dict(ref.provider_tool_protocol or {}),
                fact_slot_key=str(ref.fact_slot_key or ""),
                fact_content_hash=str(ref.fact_content_hash or ""),
                fact_change_class=str(ref.fact_change_class or ""),
                fact_supersession_policy=str(ref.fact_supersession_policy or ""),
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
            active_entries = _filter_superseded_fact_entries([*active_entries, entry])
            confirmation = {
                "scope": scope,
                "entry_index": next_index,
                "item_key": item_key,
                "status": PROVIDER_VISIBLE_APPEND_CONFIRMED_STATUS,
                "already_confirmed": False,
                "confirmed_turn_id": normalized_turn_id,
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
                turn_id=normalized_turn_id,
                response_ref=response_ref,
                provider_payload_prefix_hash=provider_payload_prefix_hash,
                provider_payload_messages_hash=provider_payload_messages_hash,
                physical_cache_spine_message_subtotal_hash=physical_cache_spine_message_subtotal_hash,
                transport_contract_hash=transport_contract_hash,
                request_message_count=request_message_count,
                request_entry_indexes=[
                    _safe_int(item.get("entry_index"))
                    for item in group_confirmations
                    if _safe_int(item.get("entry_index")) > 0
                ],
                active_entries=active_entries,
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
                adapter_contract=str(ledger.get("adapter_contract") or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
            )
            save_provider_visible_append_ledger(storage_root=storage_root, scope=scope, ledger=ledger)

    return {
        "status": "ok" if not failures else "recovery_required",
        "confirmed_count": confirmed_count,
        "confirmation_count": len(confirmations),
        "changed_group_count": changed_groups,
        "anchor_update_count": anchor_update_count,
        "confirmations": confirmations,
        "provider_success_anchors": anchors,
        "failures": failures,
        "authority": "runtime.context_management.provider_visible_append_ledger.confirm",
    }


def latest_provider_visible_append_success_anchor(*, storage_root: Path | str | None, scope: str) -> dict[str, Any]:
    ledger = load_provider_visible_append_ledger(
        storage_root=Path(storage_root) if storage_root else None,
        scope=scope,
    )
    return _active_provider_success_anchor(ledger)


def truncate_provider_visible_append_ledger_after_session_cutoff(
    *,
    storage_root: Path | str | None,
    scope: str,
    kept_turn_ids: set[str] | list[str] | tuple[str, ...],
    cutoff_created_before: float,
    reason: str = "session_history_truncated",
) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    kept = {str(item or "").strip() for item in list(kept_turn_ids or []) if str(item or "").strip()}
    cutoff_ts = float(cutoff_created_before or time.time())
    root = Path(storage_root) if storage_root else None
    ledger = load_provider_visible_append_ledger(storage_root=root, scope=normalized_scope)
    active_entries = _active_confirmed_ledger_entries(ledger)
    if not active_entries:
        return {
            "authority": "runtime.context_management.provider_visible_append_ledger.branch_cursor",
            "scope": normalized_scope,
            "deactivated_count": 0,
            "active_count": 0,
            "reason": "provider_visible_append_ledger_empty",
        }

    target_position = -1
    for index, entry in enumerate(active_entries):
        confirmed_turn_id = str(entry.get("confirmed_turn_id") or "").strip()
        if confirmed_turn_id and confirmed_turn_id in kept:
            target_position = index

    payload = dict(ledger or {})
    target_entries = active_entries[: target_position + 1] if target_position >= 0 else []
    deactivated_entries = active_entries[target_position + 1 :] if target_position >= 0 else active_entries
    target_anchor = _provider_success_anchor_for_terminal_entries(
        payload,
        entries=target_entries,
        scope=normalized_scope,
        reason=str(reason or "session_history_truncated"),
    )
    payload = _set_active_provider_visible_cursor(payload, anchor=target_anchor, active_entries=target_entries)
    payload["last_truncate_cutoff"] = {
        "reason": str(reason or "session_history_truncated"),
        "cutoff_created_before": cutoff_ts,
        "kept_turn_ids": sorted(kept),
        "active_entry_indexes": [
            _safe_int(item.get("entry_index"))
            for item in target_entries
            if _safe_int(item.get("entry_index")) > 0
        ],
        "deactivated_entry_indexes": [
            _safe_int(item.get("entry_index"))
            for item in deactivated_entries
            if _safe_int(item.get("entry_index")) > 0
        ],
        "deactivated_turn_ids": sorted(
            {
                str(item.get("confirmed_turn_id") or "").strip()
                for item in deactivated_entries
                if str(item.get("confirmed_turn_id") or "").strip()
            }
        ),
        "target_anchor_id": str(target_anchor.get("anchor_id") or ""),
        "target_terminal_entry_index": _safe_int(target_anchor.get("terminal_entry_index")),
        "target_terminal_entry_hash": str(target_anchor.get("terminal_entry_hash") or ""),
        "cursor_policy": "preserve_immutable_entries_switch_active_branch_head",
        "authority": "runtime.context_management.provider_visible_append_ledger.branch_cursor",
    }
    payload = _finalize_ledger(
        payload,
        scope=normalized_scope,
        provider=str(payload.get("provider") or ""),
        model=str(payload.get("model") or ""),
        adapter_contract=str(payload.get("adapter_contract") or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
    )
    save_provider_visible_append_ledger(storage_root=root, scope=normalized_scope, ledger=payload)
    return {
        "authority": "runtime.context_management.provider_visible_append_ledger.branch_cursor",
        "scope": normalized_scope,
        "deactivated_count": len(deactivated_entries),
        "active_count": len(target_entries),
        "active_success_anchor_id": str(payload.get("active_success_anchor_id") or ""),
        "active_terminal_entry_index": _safe_int(payload.get("active_terminal_entry_index")),
        "active_terminal_entry_hash": str(payload.get("active_terminal_entry_hash") or ""),
        "deactivated_entry_indexes": [
            _safe_int(item.get("entry_index"))
            for item in deactivated_entries
            if _safe_int(item.get("entry_index")) > 0
        ],
        "reason": str(reason or "session_history_truncated"),
    }


def load_provider_visible_append_ledger(*, storage_root: Path | None, scope: str) -> dict[str, Any]:
    normalized_scope = str(scope or "default").strip() or "default"
    path = provider_visible_append_ledger_path(storage_root=storage_root, scope=normalized_scope)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "authority": "runtime.context_management.provider_visible_append_ledger.load",
            "ledger_schema_revision": PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION,
            "adapter_contract": PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
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
            "authority": "runtime.context_management.provider_visible_append_ledger.load",
            "ledger_schema_revision": PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION,
            "adapter_contract": PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
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


def save_provider_visible_append_ledger(*, storage_root: Path | None, scope: str, ledger: dict[str, Any]) -> None:
    path = provider_visible_append_ledger_path(storage_root=storage_root, scope=scope)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_stable(dict(ledger or {})), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def provider_visible_append_ledger_path(*, storage_root: Path | None, scope: str) -> Path | None:
    if storage_root is None:
        return None
    try:
        runtime_state_dir = ProjectLayout.from_runtime_root(Path(storage_root)).runtime_state_dir.resolve()
    except Exception:
        runtime_state_dir = Path(storage_root).resolve()
    safe_scope = safe_provider_visible_append_ledger_filename(scope)
    if not safe_scope:
        return None
    return runtime_state_dir / "provider_visible_append_ledger" / f"{safe_scope}.json"


def safe_provider_visible_append_ledger_filename(value: str) -> str:
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
    payload.setdefault("ledger_schema_revision", PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION)
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
        "authority": "runtime.context_management.provider_visible_append_ledger",
        "ledger_schema_revision": PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION,
        "adapter_contract": str(adapter_contract or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
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
    ledger_schema_revision = _safe_int(ledger.get("ledger_schema_revision"))
    if ledger_schema_revision != PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION:
        return _structured_failure(
            scope=scope,
            code="ledger_schema_revision_mismatch",
            message="provider-visible context ledger schema revision does not match",
            details={
                "ledger_schema_revision": ledger_schema_revision,
                "expected_ledger_schema_revision": PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION,
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
    turn_id: str,
    response_ref: str,
    provider_payload_prefix_hash: str,
    provider_payload_messages_hash: str,
    physical_cache_spine_message_subtotal_hash: str,
    transport_contract_hash: str,
    request_message_count: int,
    request_entry_indexes: list[int] | tuple[int, ...],
    active_entries: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        return dict(ledger or {}), {}
    normalized_turn_id = str(turn_id or "").strip()
    payload = dict(ledger or {})
    selected_entries = (
        [dict(item) for item in list(active_entries or []) if isinstance(item, dict)]
        if active_entries is not None
        else _active_confirmed_ledger_entries(payload)
    )
    entries = sorted(
        selected_entries,
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
        "turn_id": normalized_turn_id,
        "response_ref": str(response_ref or ""),
        "entry_count": len(entry_indexes),
        "terminal_entry_index": entry_indexes[-1],
        "terminal_entry_hash": str(last_entry.get("entry_hash") or ""),
        "provider_payload_messages_hash": str(provider_payload_messages_hash or ""),
    }
    anchor = {
        "anchor_id": "provider-success-anchor:" + _stable_json_hash(anchor_seed).split(":", 1)[-1][:16],
        "request_id": normalized_request_id,
        "turn_id": normalized_turn_id,
        "response_ref": str(response_ref or ""),
        "scope": str(scope or "default"),
        "provider": str(provider or payload.get("provider") or ""),
        "model": str(model or payload.get("model") or ""),
        "confirmed_ledger_entry_range": [entry_indexes[0], entry_indexes[-1]],
        "confirmed_ledger_entry_indexes": entry_indexes,
        "confirmed_ledger_entry_count": len(entry_indexes),
        "request_confirmed_entry_indexes": request_indexes,
        "terminal_entry_index": entry_indexes[-1],
        "terminal_entry_hash": str(last_entry.get("entry_hash") or ""),
        "terminal_cumulative_prefix_hash": str(last_entry.get("cumulative_prefix_hash") or ""),
        "compaction_generation": _normalize_compaction_generation(last_entry.get("compaction_generation")),
        "provider_payload_prefix_hash": str(provider_payload_prefix_hash or ""),
        "provider_payload_messages_hash": str(provider_payload_messages_hash or ""),
        "physical_cache_spine_message_subtotal_hash": str(physical_cache_spine_message_subtotal_hash or ""),
        "transport_contract_hash": str(transport_contract_hash or ""),
        "request_message_count": _safe_int(request_message_count),
        "created_at": time.time(),
        "authority": "runtime.context_management.provider_visible_append_ledger.provider_success_anchor",
    }
    existing = [
        dict(item)
        for item in list(payload.get("provider_success_anchors") or [])
        if isinstance(item, dict)
        and str(item.get("anchor_id") or "") != str(anchor.get("anchor_id") or "")
    ]
    payload["provider_success_anchors"] = [*existing, anchor][-32:]
    payload = _set_active_provider_visible_cursor(payload, anchor=anchor, active_entries=entries)
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
    payload["authority"] = "runtime.context_management.provider_visible_append_ledger"
    payload["ledger_schema_revision"] = PROVIDER_VISIBLE_APPEND_LEDGER_SCHEMA_REVISION
    payload["adapter_contract"] = str(adapter_contract or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT)
    payload["scope"] = str(scope or payload.get("scope") or "default")
    payload["provider"] = str(provider or payload.get("provider") or "")
    payload["model"] = str(model or payload.get("model") or "")
    payload["entries"] = [dict(item) for item in list(payload.get("entries") or []) if isinstance(item, dict)]
    active_entries = _active_confirmed_ledger_entries(payload)
    payload["items"] = {
        str(entry.get("item_key") or ""): _safe_int(entry.get("entry_index"))
        for entry in active_entries
        if str(entry.get("item_key") or "").strip()
    }
    payload["entry_index"] = max([_safe_int(entry.get("entry_index")) for entry in payload["entries"]] or [0])
    payload["next_entry_index"] = max(_safe_int(payload.get("next_entry_index")), int(payload["entry_index"]) + 1)
    active_anchor = _active_provider_success_anchor(payload)
    if not active_anchor and active_entries:
        active_anchor = _provider_success_anchor_for_terminal_entries(
            payload,
            entries=active_entries,
            scope=str(scope or payload.get("scope") or "default"),
            reason="finalize_legacy_provider_visible_cursor",
        )
    payload = _set_active_provider_visible_cursor(
        payload,
        anchor=active_anchor,
        active_entries=active_entries,
    )
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
    confirmed_turn_id: str = "",
    confirmed_response_ref: str = "",
    semantic_visibility: str = "",
    validity_scope: str = "",
    compaction_generation: str = "",
    cache_spine_hash: str = "",
    provider_tool_protocol: dict[str, Any] | None = None,
    fact_slot_key: str = "",
    fact_content_hash: str = "",
    fact_change_class: str = "",
    fact_supersession_policy: str = "",
) -> dict[str, Any]:
    payload = {
        "entry_index": int(entry_index or 0),
        "item_key": str(item_key or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "adapter_contract": str(adapter_contract or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
        "context_section": "context_memory_prefix",
        "ledger_lane": PROVIDER_VISIBLE_CONTEXT_PREFIX,
        "semantic_visibility": str(semantic_visibility or "active"),
        "validity_scope": str(validity_scope or ""),
        "compaction_generation": str(compaction_generation or ""),
        "cache_spine_hash": str(cache_spine_hash or ""),
        "semantic_commit_class": str(semantic_commit_class or ""),
        "source_ref": str(source_ref or ""),
        "kind": str(kind or ""),
        "provider_tool_protocol": dict(provider_tool_protocol or {}),
        "fact_slot_key": str(fact_slot_key or ""),
        "fact_content_hash": str(fact_content_hash or ""),
        "fact_change_class": str(fact_change_class or ""),
        "fact_supersession_policy": str(fact_supersession_policy or ""),
        "provider_visible_message": _provider_visible_message(provider_visible_message),
        "provider_visible_hash": str(provider_visible_hash or ""),
        "previous_entry_hash": str(previous_entry_hash or ""),
        "commit_status": PROVIDER_VISIBLE_APPEND_CONFIRMED_STATUS,
        "confirmed_at": time.time(),
        "confirmed_by_request_id": str(confirmed_by_request_id or ""),
        "confirmed_turn_id": str(confirmed_turn_id or ""),
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
    ledger = load_provider_visible_append_ledger(storage_root=storage_root, scope=normalized_scope)
    failure = _ledger_failure(ledger, scope=normalized_scope, adapter_contract=adapter_contract)
    if failure:
        return [], [failure]
    entries = _active_confirmed_ledger_entries(ledger, anchor=normalized_anchor)
    entries = _ledger_entries_for_compaction_generation(
        entries,
        compaction_generation=_normalize_compaction_generation(compaction_generation),
    )
    if not entries:
        return [], [
            _structured_failure(
                scope=normalized_scope,
                code="fork_inherited_provider_visible_append_anchor_empty",
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


def _current_append_spec_from_candidate(
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
    source_policy_section = str(getattr(policy, "section", "") or CONTEXT_APPEND)
    policy_section = CONTEXT_APPEND
    fixed_context_package = "context_memory_append"
    semantic_commit_class = str(
        dict(payload.get("metadata") or {}).get("semantic_commit_class")
        or getattr(policy, "semantic_commit_class", "")
        or ""
    )
    metadata = {
        **dict(payload.get("metadata") or {}),
        **context_segment_policy_metadata(policy),
        "context_cache_section": policy_section,
        "provider_visible_append_source_context_section": source_policy_section,
        "fixed_context_package": fixed_context_package,
        "provider_visible_append_ledger_scope": str(scope or ""),
        "provider_visible_append_ledger_storage_root": storage_root_text,
        "provider_visible_append_commit_stage": "provider_success_required",
        "provider_visible_append_item_key": str(item_key or ""),
        "provider_visible_append_ledger_authority": "runtime.context_management.provider_visible_append_ledger",
        "provider_visible_hash": str(provider_visible_hash or ""),
        "provider_visible_payload_form": "provider_chat_completion_message",
        "provider_visible_payload_authority": "runtime.context_management.provider_visible_append_ledger.current_append",
        "provider_visible_append_candidate_message": _provider_visible_message(provider_visible_message),
        "provider_visible_append_candidate_kind": str(payload.get("kind") or ""),
        "provider_visible_append_candidate_source_ref": str(payload.get("source_ref") or ""),
        "provider_visible_append_candidate_semantic_commit_class": semantic_commit_class,
        "provider_visible_append_candidate_provider": str(provider or ""),
        "provider_visible_append_candidate_model": str(model or ""),
        "provider_adapter_contract": str(adapter_contract or PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT),
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
    }
    fact_identity = _fact_identity_from_spec(payload)
    if fact_identity.get("fact_slot_key"):
        metadata["provider_visible_append_fact_slot_key"] = str(fact_identity.get("fact_slot_key") or "")
        metadata["provider_visible_append_fact_content_hash"] = str(fact_identity.get("fact_content_hash") or "")
        metadata["provider_visible_append_fact_change_class"] = str(fact_identity.get("fact_change_class") or "")
        metadata["provider_visible_append_fact_supersession_policy"] = str(
            fact_identity.get("fact_supersession_policy") or ""
        )
    payload["cache_scope"] = str(getattr(policy, "prefix_cache_scope", "") or payload.get("cache_scope") or "session")
    payload["cache_role"] = str(getattr(policy, "prefix_cache_role", "") or payload.get("cache_role") or "session_stable")
    payload["prefix_tier"] = str(getattr(policy, "prefix_tier", "") or payload.get("prefix_tier") or "session")
    payload["role"] = str(provider_visible_message.get("role") or payload.get("role") or "system")
    payload["content"] = str(provider_visible_message.get("content") if provider_visible_message.get("content") is not None else "")
    payload["model_message"] = _provider_visible_message(provider_visible_message)
    payload["metadata"] = metadata
    return payload


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
    prefix_identity = dict(spec.get("prefix_identity") or metadata.get("prefix_identity") or {})
    explicit = str(
        metadata.get("provider_visible_append_item_key")
        or metadata.get("append_only_context_item_key")
        or ""
    ).strip()
    if explicit:
        return explicit
    identity_policy = str(getattr(policy, "identity_policy", "") or "").strip()
    semantic_slot = str(
        metadata.get("context_semantic_slot")
        or metadata.get("semantic_slot")
        or getattr(policy, "semantic_slot", "")
        or spec.get("kind")
        or ""
    ).strip()
    origin_authority = str(
        metadata.get("context_origin_authority")
        or metadata.get("prefix_origin_authority")
        or metadata.get("origin_authority")
        or prefix_identity.get("origin_authority")
        or metadata.get("context_semantic_source")
        or metadata.get("semantic_source")
        or spec.get("source_ref")
        or spec.get("kind")
        or ""
    ).strip()
    origin_ref = str(
        metadata.get("context_origin_ref")
        or metadata.get("prefix_origin_ref")
        or metadata.get("origin_ref")
        or metadata.get("stable_origin_ref")
        or prefix_identity.get("origin_ref")
        or prefix_identity.get("logical_segment_ref")
        or metadata.get("logical_segment_ref")
        or spec.get("logical_segment_ref")
        or metadata.get("provider_visible_append_candidate_source_ref")
        or spec.get("source_ref")
        or ""
    ).strip()
    if origin_ref:
        return _stable_json_hash(
            {
                "schema": "provider_visible_context_item_identity",
                "normalization": PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
                "identity_policy": identity_policy or "origin_ref_stable",
                "kind": str(spec.get("kind") or ""),
                "semantic_slot": semantic_slot,
                "origin_authority": origin_authority,
                "origin_ref": origin_ref,
            }
        )
    return _stable_json_hash(
        {
            "schema": "provider_visible_context_item_identity",
            "normalization": PROVIDER_VISIBLE_APPEND_LEDGER_ADAPTER_CONTRACT,
            "identity_policy": "missing_origin_ref_diagnostic",
            "kind": str(spec.get("kind") or ""),
            "semantic_slot": semantic_slot,
            "origin_authority": origin_authority,
        }
    )


def _entries_by_key(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)]:
        key = str(entry.get("item_key") or "").strip()
        if key:
            result[key] = entry
    return result


def _entries_by_fact_slot(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in sorted(
        [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)],
        key=lambda item: _safe_int(item.get("entry_index")),
    ):
        key = str(entry.get("fact_slot_key") or "").strip()
        if key:
            result[key] = entry
    return result


def _fact_identity_from_spec(spec: dict[str, Any]) -> dict[str, str]:
    metadata = dict(dict(spec or {}).get("metadata") or {})
    fact_slot_key = str(metadata.get("fact_slot_key") or metadata.get("provider_visible_append_fact_slot_key") or "").strip()
    fact_content_hash = str(
        metadata.get("fact_content_hash")
        or metadata.get("provider_visible_append_fact_content_hash")
        or metadata.get("append_only_content_hash")
        or ""
    ).strip()
    return {
        "fact_slot_key": fact_slot_key,
        "fact_content_hash": fact_content_hash,
        "fact_change_class": str(metadata.get("fact_change_class") or "").strip(),
        "fact_supersession_policy": str(metadata.get("fact_supersession_policy") or "").strip(),
    }


def _filtered_fact_candidate(
    spec: dict[str, Any],
    *,
    fact_identity: dict[str, str],
    reason: str,
    matched_entry: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(dict(spec or {}).get("metadata") or {})
    return {
        "reason": str(reason or ""),
        "kind": str(dict(spec or {}).get("kind") or metadata.get("kind") or ""),
        "source_ref": str(dict(spec or {}).get("source_ref") or metadata.get("source_ref") or ""),
        "semantic_slot": str(metadata.get("context_semantic_slot") or metadata.get("semantic_slot") or ""),
        "fact_slot_key": str(fact_identity.get("fact_slot_key") or ""),
        "fact_content_hash": str(fact_identity.get("fact_content_hash") or ""),
        "fact_change_class": str(fact_identity.get("fact_change_class") or ""),
        "matched_entry_index": _safe_int(dict(matched_entry or {}).get("entry_index")),
        "matched_fact_content_hash": str(dict(matched_entry or {}).get("fact_content_hash") or ""),
        "authority": "runtime.context_management.provider_visible_append_ledger.fact_filter",
    }


def _entries_by_index(ledger: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for entry in [dict(item) for item in list(dict(ledger or {}).get("entries") or []) if isinstance(item, dict)]:
        index = _safe_int(entry.get("entry_index"))
        if index > 0:
            result[index] = entry
    return result


def _next_entry_index(ledger: dict[str, Any], *, entries_by_index: dict[int, dict[str, Any]]) -> int:
    next_index = _safe_int(dict(ledger or {}).get("next_entry_index"))
    return max(next_index, max([*entries_by_index.keys(), 0]) + 1)


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
    return status == PROVIDER_VISIBLE_APPEND_CONFIRMED_STATUS


def _confirmed_ledger_entries(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(dict(ledger or {}).get("entries") or [])
        if isinstance(item, dict) and _ledger_entry_confirmed(item)
    ]


def _active_provider_success_anchor(ledger: dict[str, Any]) -> dict[str, Any]:
    payload = dict(ledger or {})
    active = payload.get("active_provider_success_anchor")
    if isinstance(active, dict) and active:
        return dict(active)
    return {}


def _active_confirmed_ledger_entries(
    ledger: dict[str, Any],
    *,
    anchor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = dict(ledger or {})
    entries = _confirmed_ledger_entries(ledger)
    if not entries:
        return []
    explicit_anchor = anchor is not None
    selected_anchor = dict(anchor or {}) if explicit_anchor else _active_provider_success_anchor(ledger)
    terminal_hash = str(
        selected_anchor.get("terminal_entry_hash")
        or (payload.get("active_terminal_entry_hash") if not explicit_anchor else "")
        or ""
    ).strip()
    if terminal_hash:
        lineage = _entry_lineage_for_terminal_hash(entries, terminal_hash)
        return _filter_superseded_fact_entries(lineage)
    terminal_index = _safe_int(
        selected_anchor.get("terminal_entry_index")
        or (payload.get("active_terminal_entry_index") if not explicit_anchor else 0)
    )
    if terminal_index > 0:
        return _filter_superseded_fact_entries([
            dict(item)
            for item in sorted(entries, key=lambda value: _safe_int(value.get("entry_index")))
            if 0 < _safe_int(item.get("entry_index")) <= terminal_index
        ])
    if explicit_anchor or _has_explicit_active_provider_visible_cursor(payload):
        return []
    return _filter_superseded_fact_entries(sorted(entries, key=lambda value: _safe_int(value.get("entry_index"))))


def _has_explicit_active_provider_visible_cursor(ledger: dict[str, Any]) -> bool:
    payload = dict(ledger or {})
    return any(
        key in payload
        for key in (
            "active_provider_success_anchor",
            "active_success_anchor_id",
            "active_terminal_entry_index",
            "active_terminal_entry_hash",
        )
    )


def _entry_lineage_for_terminal_hash(entries: list[dict[str, Any]], terminal_hash: str) -> list[dict[str, Any]]:
    by_hash = {
        str(item.get("entry_hash") or "").strip(): dict(item)
        for item in list(entries or [])
        if str(item.get("entry_hash") or "").strip()
    }
    current_hash = str(terminal_hash or "").strip()
    lineage: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current_hash:
        if current_hash in seen:
            return []
        seen.add(current_hash)
        entry = dict(by_hash.get(current_hash) or {})
        if not entry:
            return []
        lineage.append(entry)
        current_hash = str(entry.get("previous_entry_hash") or "").strip()
    return list(reversed(lineage))


def _filter_superseded_fact_entries(entries: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    ordered = [dict(item) for item in list(entries or []) if isinstance(item, dict)]
    latest_index_by_fact_slot: dict[str, int] = {}
    for entry in sorted(ordered, key=lambda value: _safe_int(value.get("entry_index"))):
        fact_slot_key = str(entry.get("fact_slot_key") or "").strip()
        supersession_policy = str(entry.get("fact_supersession_policy") or "").strip()
        if not fact_slot_key or supersession_policy != "same_fact_slot_latest_content_hash_supersedes_prior":
            continue
        entry_index = _safe_int(entry.get("entry_index"))
        if entry_index > 0:
            latest_index_by_fact_slot[fact_slot_key] = entry_index
    if not latest_index_by_fact_slot:
        return ordered
    result: list[dict[str, Any]] = []
    for entry in sorted(ordered, key=lambda value: _safe_int(value.get("entry_index"))):
        fact_slot_key = str(entry.get("fact_slot_key") or "").strip()
        supersession_policy = str(entry.get("fact_supersession_policy") or "").strip()
        if (
            fact_slot_key
            and supersession_policy == "same_fact_slot_latest_content_hash_supersedes_prior"
            and _safe_int(entry.get("entry_index")) != latest_index_by_fact_slot.get(fact_slot_key)
        ):
            continue
        result.append(entry)
    return result


def _provider_success_anchor_for_terminal_entries(
    ledger: dict[str, Any],
    *,
    entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    scope: str,
    reason: str,
) -> dict[str, Any]:
    active_entries = [dict(item) for item in list(entries or []) if isinstance(item, dict)]
    if not active_entries:
        return {}
    terminal = dict(active_entries[-1])
    terminal_hash = str(terminal.get("entry_hash") or "").strip()
    terminal_index = _safe_int(terminal.get("entry_index"))
    anchors = [
        dict(item)
        for item in list(dict(ledger or {}).get("provider_success_anchors") or [])
        if isinstance(item, dict)
    ]
    for anchor in reversed(anchors):
        if terminal_hash and str(anchor.get("terminal_entry_hash") or "").strip() == terminal_hash:
            return anchor
        if terminal_index > 0 and _safe_int(anchor.get("terminal_entry_index")) == terminal_index:
            return anchor
    entry_indexes = [
        _safe_int(item.get("entry_index"))
        for item in active_entries
        if _safe_int(item.get("entry_index")) > 0
    ]
    anchor_seed = {
        "scope": str(scope or "default"),
        "terminal_entry_index": terminal_index,
        "terminal_entry_hash": terminal_hash,
        "terminal_cumulative_prefix_hash": str(terminal.get("cumulative_prefix_hash") or ""),
        "entry_indexes": entry_indexes,
        "reason": str(reason or ""),
    }
    return {
        "anchor_id": "provider-branch-anchor:" + _stable_json_hash(anchor_seed).split(":", 1)[-1][:16],
        "request_id": str(terminal.get("confirmed_by_request_id") or ""),
        "turn_id": str(terminal.get("confirmed_turn_id") or ""),
        "response_ref": str(terminal.get("confirmed_response_ref") or ""),
        "scope": str(scope or "default"),
        "provider": str(terminal.get("provider") or dict(ledger or {}).get("provider") or ""),
        "model": str(terminal.get("model") or dict(ledger or {}).get("model") or ""),
        "confirmed_ledger_entry_range": [entry_indexes[0], entry_indexes[-1]] if entry_indexes else [0, 0],
        "confirmed_ledger_entry_indexes": entry_indexes,
        "confirmed_ledger_entry_count": len(entry_indexes),
        "request_confirmed_entry_indexes": [],
        "terminal_entry_index": terminal_index,
        "terminal_entry_hash": terminal_hash,
        "terminal_cumulative_prefix_hash": str(terminal.get("cumulative_prefix_hash") or ""),
        "compaction_generation": _normalize_compaction_generation(terminal.get("compaction_generation")),
        "provider_payload_prefix_hash": "",
        "provider_payload_messages_hash": "",
        "physical_cache_spine_message_subtotal_hash": "",
        "transport_contract_hash": "",
        "request_message_count": 0,
        "created_at": time.time(),
        "reason": str(reason or ""),
        "authority": "runtime.context_management.provider_visible_append_ledger.branch_anchor",
    }


def _set_active_provider_visible_cursor(
    ledger: dict[str, Any],
    *,
    anchor: dict[str, Any],
    active_entries: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    payload = dict(ledger or {})
    active_anchor = dict(anchor or {})
    entry_indexes = [
        _safe_int(item.get("entry_index"))
        for item in list(active_entries or [])
        if isinstance(item, dict) and _safe_int(item.get("entry_index")) > 0
    ]
    if active_anchor:
        payload["active_provider_success_anchor"] = active_anchor
        payload["active_success_anchor_id"] = str(active_anchor.get("anchor_id") or "")
        payload["active_terminal_entry_index"] = _safe_int(active_anchor.get("terminal_entry_index"))
        payload["active_terminal_entry_hash"] = str(active_anchor.get("terminal_entry_hash") or "")
    else:
        payload["active_provider_success_anchor"] = {}
        payload["active_success_anchor_id"] = ""
        payload["active_terminal_entry_index"] = 0
        payload["active_terminal_entry_hash"] = ""
    payload["active_ledger_entry_indexes"] = entry_indexes
    payload["active_ledger_entry_count"] = len(entry_indexes)
    payload["branch_cursor_policy"] = "immutable_entries_active_head"
    return payload


def _ledger_entry_hash(entry: dict[str, Any]) -> str:
    payload = dict(entry or {})
    return _stable_json_hash(
        {
            "schema": "provider_visible_append_ledger_entry_hash",
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
            "provider_tool_protocol": dict(payload.get("provider_tool_protocol") or {}),
            "provider_visible_message": _provider_visible_message(dict(payload.get("provider_visible_message") or {})),
            "provider_visible_hash": str(payload.get("provider_visible_hash") or ""),
            "previous_entry_hash": str(payload.get("previous_entry_hash") or ""),
        }
    )


def _structured_failure(*, scope: str, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(code or "provider_visible_append_ledger_failure"),
        "message": str(message or ""),
        "scope": str(scope or "default"),
        "severity": "p0",
        "recovery_policy": "insert_recovery_context_checkpoint_before_resuming_append_only_ledger",
        "recovery_position": "context_memory_prefix",
        "details": dict(details or {}),
        "authority": "runtime.context_management.provider_visible_append_ledger.structured_failure",
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
