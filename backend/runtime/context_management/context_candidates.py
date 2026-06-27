from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .context_segment_policy import (
    CONTEXT_APPEND,
    CURRENT_CONTROL_TAIL_KINDS,
)


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    candidate_id: str
    canonical_kind: str
    semantic_slot: str
    semantic_title: str
    source_route: str
    source_ref: str
    identity: str
    payload: dict[str, Any] = field(default_factory=dict)
    content_ref: str = ""
    content_hash: str = ""
    freshness: dict[str, Any] = field(default_factory=dict)
    provider_visibility: str = "provider_visible"
    render_contract: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = dict(self.payload)
        payload["freshness"] = dict(self.freshness)
        payload["render_contract"] = dict(self.render_contract)
        return payload


@dataclass(frozen=True, slots=True)
class ContextPolicyDecision:
    section: str
    semantic_commit_class: str
    cache_policy: dict[str, Any]
    capability_group: str
    sealable: bool
    validity_scope: str
    stability_hash: str
    failure_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cache_policy"] = dict(self.cache_policy)
        payload["failure_policy"] = dict(self.failure_policy)
        return payload


@dataclass(frozen=True, slots=True)
class PhysicalContextSegment:
    physical_lane: str
    order_key: tuple[Any, ...]
    cache_spine_member: bool
    provider_visible_hash: str
    cache_spine_hash: str
    ledger_entry_ref: str
    tail_break_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["order_key"] = list(self.order_key)
        return payload


@dataclass(frozen=True, slots=True)
class ContextCommitCandidate:
    item_key: str
    provider_message: dict[str, Any]
    provider_visible_hash: str
    adapter_contract: str
    scope: str
    storage_root: str = ""
    kind: str = ""
    semantic_commit_class: str = ""
    source_ref: str = ""
    provider: str = ""
    model: str = ""
    physical_lane_before_commit: str = ""
    semantic_visibility: str = ""
    validity_scope: str = ""
    compaction_generation: str = ""
    cache_spine_hash: str = ""
    candidate_id: str = ""
    fork_anchor_delta: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.context_management.context_commit_candidate"

    @classmethod
    def from_provider_payload_segment(cls, segment: dict[str, Any]) -> "ContextCommitCandidate | None":
        payload = dict(segment or {})
        metadata = dict(payload.get("metadata") or {})
        if str(metadata.get("provider_visible_context_ledger_commit_stage") or "") != "provider_success_required":
            return None
        if not _provider_payload_segment_commit_eligible(payload, metadata=metadata):
            return None
        scope = str(metadata.get("provider_visible_context_ledger_scope") or "").strip()
        item_key = str(metadata.get("provider_visible_context_ledger_item_key") or "").strip()
        provider_hash = str(metadata.get("provider_visible_hash") or "").strip()
        provider_message = dict(metadata.get("provider_visible_context_candidate_message") or {})
        if not scope or not item_key or not provider_hash or not provider_message:
            return None
        seed = {
            "scope": scope,
            "item_key": item_key,
            "provider_visible_hash": provider_hash,
        }
        return cls(
            candidate_id="ctxcommitcand:" + _stable_hash(seed)[:16],
            item_key=item_key,
            provider_message=provider_message,
            provider_visible_hash=provider_hash,
            adapter_contract=str(metadata.get("provider_adapter_contract") or ""),
            scope=scope,
            storage_root=str(metadata.get("provider_visible_context_ledger_storage_root") or "").strip(),
            kind=str(metadata.get("provider_visible_context_candidate_kind") or "").strip(),
            semantic_commit_class=str(metadata.get("provider_visible_context_candidate_semantic_commit_class") or "").strip(),
            source_ref=str(metadata.get("provider_visible_context_candidate_source_ref") or "").strip(),
            provider=str(metadata.get("provider_visible_context_candidate_provider") or "").strip(),
            model=str(metadata.get("provider_visible_context_candidate_model") or "").strip(),
            physical_lane_before_commit=str(metadata.get("physical_prefix_lane") or "").strip(),
            semantic_visibility=str(metadata.get("semantic_visibility") or "").strip(),
            validity_scope=str(metadata.get("validity_scope") or "").strip(),
            compaction_generation=str(metadata.get("compaction_generation") or "").strip(),
            cache_spine_hash=str(metadata.get("cache_spine_hash") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_message"] = dict(self.provider_message)
        payload["fork_anchor_delta"] = dict(self.fork_anchor_delta)
        return payload


def context_candidate_from_message_spec(spec: dict[str, Any]) -> ContextCandidate:
    payload = dict(spec or {})
    metadata = dict(payload.get("metadata") or {})
    kind = str(payload.get("kind") or metadata.get("canonical_kind") or "").strip()
    source_ref = str(payload.get("source_ref") or metadata.get("source_ref") or "").strip()
    content = str(payload.get("content") or "")
    content_hash = str(metadata.get("provider_visible_hash") or metadata.get("content_hash") or "")
    if not content_hash:
        content_hash = "sha256:" + hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
    seed = {
        "kind": kind,
        "source_ref": source_ref,
        "content_hash": content_hash,
    }
    candidate_id = "ctxcand:" + _stable_hash(seed)[:16]
    title = str(metadata.get("semantic_title") or metadata.get("runtime_fragment_title") or payload.get("title") or kind)
    return ContextCandidate(
        candidate_id=candidate_id,
        canonical_kind=str(metadata.get("canonical_kind") or kind),
        semantic_slot=str(metadata.get("context_semantic_slot") or metadata.get("semantic_slot") or ""),
        semantic_title=title,
        source_route=str(metadata.get("source_route") or metadata.get("content_source") or ""),
        source_ref=source_ref,
        identity=str(metadata.get("context_identity") or metadata.get("tool_call_id") or source_ref or content_hash),
        payload={},
        content_ref=str(metadata.get("content_ref") or metadata.get("reusable_result_ref") or ""),
        content_hash=content_hash,
        freshness=dict(metadata.get("freshness") or {}),
        provider_visibility=str(metadata.get("provider_visibility") or "provider_visible"),
        render_contract={
            "role": str(payload.get("role") or ""),
            "compression_role": str(payload.get("compression_role") or ""),
        },
    )


def _provider_payload_segment_commit_eligible(payload: dict[str, Any], *, metadata: dict[str, Any]) -> bool:
    kind = str(
        metadata.get("provider_visible_context_candidate_kind")
        or payload.get("kind")
        or metadata.get("kind")
        or ""
    ).strip()
    if kind in CURRENT_CONTROL_TAIL_KINDS:
        return False

    section = str(metadata.get("context_cache_section") or metadata.get("context_policy_section") or "").strip()
    if section != CONTEXT_APPEND:
        return False

    if str(metadata.get("context_commit_policy") or "").strip() != "append_then_seal":
        return False

    if str(metadata.get("memory_commit_policy") or "").strip() == "never_commit":
        return False

    if str(metadata.get("context_replay_policy") or "").strip() == "current_dynamic_tail_only":
        return False

    if str(metadata.get("context_provider_visible_boundary") or "").strip() == "current_dynamic_tail":
        return False

    if str(metadata.get("physical_prefix_lane") or "").strip() == "never_replay_tail":
        return False

    if str(metadata.get("provider_visible_after_validity") or "").strip() == "not_replayed_after_current_request":
        return False

    semantic_commit_class = str(
        metadata.get("provider_visible_context_candidate_semantic_commit_class")
        or metadata.get("semantic_commit_class")
        or ""
    ).strip()
    if semantic_commit_class == "current_runtime_control":
        return False

    return True


def _stable_hash(value: Any) -> str:
    text = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
