from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from prompt_composition import build_runtime_payload_message_spec
from context_system.segments.policy import CONTEXT_APPEND, DYNAMIC_TAIL
from runtime.context_management.tool_transcript import TOOL_TRANSCRIPT_DELTA_KIND

from .dynamic_context import DynamicContextProjection
from .dynamic_context.evidence_acquisition_horizon import build_evidence_acquisition_horizon


@dataclass(frozen=True, slots=True)
class ContextMessageProducerRequest:
    invocation_kind: str
    source_ref_prefix: str
    dynamic_context: DynamicContextProjection
    payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    task_state_replay_entries: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ContextMessageProjection:
    message_specs: tuple[dict[str, Any], ...] = ()
    dynamic_payload: dict[str, Any] = field(default_factory=dict)
    volatile_payload: dict[str, Any] = field(default_factory=dict)
    inherited_start_context_payload: dict[str, Any] = field(default_factory=dict)
    current_request_payload: dict[str, Any] = field(default_factory=dict)
    session_history_payload: dict[str, Any] = field(default_factory=dict)
    attachment_context_payload: dict[str, Any] = field(default_factory=dict)
    turn_state_attention_context_payload: dict[str, Any] = field(default_factory=dict)
    active_execution_lease_payload: dict[str, Any] = field(default_factory=dict)
    evidence_index_cursor_payload: dict[str, Any] = field(default_factory=dict)
    evidence_acquisition_horizon_payload: dict[str, Any] = field(default_factory=dict)
    editor_context_payload: dict[str, Any] = field(default_factory=dict)
    tool_observation_context_payload: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class ContextMessageProducer(Protocol):
    producer_id: str

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        ...


@dataclass(slots=True)
class ContextMessageProducerRegistry:
    producers: dict[str, ContextMessageProducer] = field(default_factory=dict)

    def register(self, producer: ContextMessageProducer) -> None:
        producer_id = str(getattr(producer, "producer_id", "") or "").strip()
        if not producer_id:
            raise ValueError("context message producer requires producer_id")
        self.producers[producer_id] = producer

    def collect(
        self,
        request: ContextMessageProducerRequest,
        *,
        producer_order: tuple[str, ...],
    ) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        producer_counts: dict[str, int] = {}
        missing = [producer_id for producer_id in producer_order if producer_id not in self.producers]
        if missing:
            raise ValueError(f"context message producer(s) not registered: {', '.join(missing)}")
        for producer_index, producer_id in enumerate(producer_order, start=1):
            producer = self.producers.get(producer_id)
            produced = tuple(dict(item) for item in tuple(producer.collect(request) or ()) if isinstance(item, dict))
            produced = tuple(
                _annotate_context_message_producer_spec(
                    item,
                    producer_id=producer_id,
                    producer_index=producer_index,
                    item_index=item_index,
                )
                for item_index, item in enumerate(produced, start=1)
            )
            if produced:
                specs.extend(produced)
            producer_counts[producer_id] = len(produced)
        return tuple(specs), {
            "producer_order": list(producer_order),
            "producer_counts": producer_counts,
            "message_spec_count": len(specs),
            "producer_identity_all_specs_annotated": all(
                bool(str(dict(spec.get("metadata") or {}).get("context_message_producer_id") or "").strip())
                for spec in specs
            ),
            "authority": "harness.runtime.context_message_producers.registry",
        }


def build_context_message_projection(
    *,
    invocation_kind: str,
    source_ref_prefix: str,
    dynamic_context: DynamicContextProjection,
    dynamic_payload: dict[str, Any] | None = None,
    volatile_payload: dict[str, Any] | None = None,
    inherited_start_context_payload: dict[str, Any] | None = None,
    read_evidence_prompt_payload: dict[str, Any] | None = None,
    task_state_replay_entries: tuple[dict[str, Any], ...] = (),
    registry: ContextMessageProducerRegistry | None = None,
    producer_order: tuple[str, ...] | None = None,
) -> ContextMessageProjection:
    normalized = _normalize_context_message_payloads(
        invocation_kind=invocation_kind,
        dynamic_payload=dict(dynamic_payload or {}),
        volatile_payload=dict(volatile_payload or {}),
        inherited_start_context_payload=dict(inherited_start_context_payload or {}),
    )
    payloads = {
        "attachment_context": normalized.attachment_context_payload,
        "turn_state_attention": normalized.turn_state_attention_context_payload,
        "active_execution_lease": normalized.active_execution_lease_payload,
        "evidence_index_cursor": normalized.evidence_index_cursor_payload,
        "evidence_acquisition_horizon": normalized.evidence_acquisition_horizon_payload,
        "read_evidence_context": dict(read_evidence_prompt_payload or {}),
        "editor_context": normalized.editor_context_payload,
        "tool_observation_context": normalized.tool_observation_context_payload,
        "session_history": normalized.session_history_payload,
    }
    request = ContextMessageProducerRequest(
        invocation_kind=str(invocation_kind or ""),
        source_ref_prefix=str(source_ref_prefix or ""),
        dynamic_context=dynamic_context,
        payloads=payloads,
        task_state_replay_entries=tuple(dict(item) for item in tuple(task_state_replay_entries or ()) if isinstance(item, dict)),
    )
    producer_registry = registry or build_default_context_message_producer_registry()
    order = tuple(producer_order) if producer_order is not None else _producer_order_for_invocation(invocation_kind)
    message_specs, registry_diagnostics = producer_registry.collect(request, producer_order=order)
    return ContextMessageProjection(
        message_specs=message_specs,
        dynamic_payload=normalized.dynamic_payload,
        volatile_payload=normalized.volatile_payload,
        inherited_start_context_payload=normalized.inherited_start_context_payload,
        current_request_payload=normalized.current_request_payload,
        session_history_payload=normalized.session_history_payload,
        attachment_context_payload=normalized.attachment_context_payload,
        turn_state_attention_context_payload=normalized.turn_state_attention_context_payload,
        active_execution_lease_payload=normalized.active_execution_lease_payload,
        evidence_index_cursor_payload=normalized.evidence_index_cursor_payload,
        evidence_acquisition_horizon_payload=normalized.evidence_acquisition_horizon_payload,
        editor_context_payload=normalized.editor_context_payload,
        tool_observation_context_payload=normalized.tool_observation_context_payload,
        diagnostics={
            **registry_diagnostics,
            "invocation_kind": str(invocation_kind or ""),
            "source_ref_prefix": str(source_ref_prefix or ""),
            "authority": "harness.runtime.context_message_producers.projection",
        },
    )


def build_default_context_message_producer_registry() -> ContextMessageProducerRegistry:
    registry = ContextMessageProducerRegistry()
    for producer in (
        _AttachmentContextProducer(),
        _TurnStateAttentionContextProducer(),
        _ActiveExecutionLeaseProducer(),
        _EvidenceIndexCursorProducer(),
        _EvidenceAcquisitionHorizonProducer(),
        _ReadEvidenceContextProducer(),
        _EditorContextProducer(),
        _ToolObservationContextProducer(),
        _SessionHistoryContextProducer(),
        _TaskStateReplayContextProducer(),
    ):
        registry.register(producer)
    return registry


@dataclass(frozen=True, slots=True)
class _NormalizedContextPayloads:
    dynamic_payload: dict[str, Any] = field(default_factory=dict)
    volatile_payload: dict[str, Any] = field(default_factory=dict)
    inherited_start_context_payload: dict[str, Any] = field(default_factory=dict)
    current_request_payload: dict[str, Any] = field(default_factory=dict)
    session_history_payload: dict[str, Any] = field(default_factory=dict)
    attachment_context_payload: dict[str, Any] = field(default_factory=dict)
    turn_state_attention_context_payload: dict[str, Any] = field(default_factory=dict)
    active_execution_lease_payload: dict[str, Any] = field(default_factory=dict)
    evidence_index_cursor_payload: dict[str, Any] = field(default_factory=dict)
    evidence_acquisition_horizon_payload: dict[str, Any] = field(default_factory=dict)
    editor_context_payload: dict[str, Any] = field(default_factory=dict)
    tool_observation_context_payload: dict[str, Any] = field(default_factory=dict)


def _normalize_context_message_payloads(
    *,
    invocation_kind: str,
    dynamic_payload: dict[str, Any],
    volatile_payload: dict[str, Any],
    inherited_start_context_payload: dict[str, Any],
) -> _NormalizedContextPayloads:
    invocation = str(invocation_kind or "").strip()
    if invocation == "single_agent_turn":
        evidence_index_cursor_payload, dynamic_payload = _extract_evidence_index_cursor_payload(dynamic_payload)
        evidence_acquisition_horizon_payload, dynamic_payload = _extract_evidence_acquisition_horizon_payload(dynamic_payload)
        dynamic_payload.pop("file_evidence_scope", None)
        for derived_evidence_key in ("file_evidence_decisions", "read_resource_state", "evidence_confidence"):
            dynamic_payload.pop(derived_evidence_key, None)
        session_history_payload, current_request_payload = _split_volatile_request_payload(volatile_payload)
        attachment_context_payload, current_request_payload = _extract_attachment_context_payload(current_request_payload)
        turn_state_attention_context_payload, current_request_payload = _extract_turn_state_attention_context_payload(current_request_payload)
        active_execution_lease_payload, current_request_payload = _extract_active_execution_lease_payload(current_request_payload)
        editor_context_payload, current_request_payload = _extract_editor_context_payload(current_request_payload)
        return _NormalizedContextPayloads(
            dynamic_payload=_drop_empty_payload(dynamic_payload),
            current_request_payload=current_request_payload,
            session_history_payload=session_history_payload,
            attachment_context_payload=attachment_context_payload,
            turn_state_attention_context_payload=turn_state_attention_context_payload,
            active_execution_lease_payload=active_execution_lease_payload,
            evidence_index_cursor_payload=evidence_index_cursor_payload,
            evidence_acquisition_horizon_payload=evidence_acquisition_horizon_payload,
            editor_context_payload=editor_context_payload,
        )
    if invocation == "task_execution":
        attachment_context_payload, inherited_start_context_payload = _extract_attachment_context_payload(inherited_start_context_payload)
        turn_state_attention_context_payload, volatile_payload = _extract_turn_state_attention_context_payload(volatile_payload)
        active_execution_lease_payload, volatile_payload = _extract_active_execution_lease_payload(volatile_payload)
        evidence_index_cursor_payload, volatile_payload = _extract_evidence_index_cursor_payload(volatile_payload)
        evidence_acquisition_horizon_payload, volatile_payload = _extract_evidence_acquisition_horizon_payload(volatile_payload)
        editor_context_payload, volatile_payload = _extract_editor_context_payload(volatile_payload)
        return _NormalizedContextPayloads(
            dynamic_payload=_drop_empty_payload(dynamic_payload),
            volatile_payload=volatile_payload,
            inherited_start_context_payload=inherited_start_context_payload,
            attachment_context_payload=attachment_context_payload,
            turn_state_attention_context_payload=turn_state_attention_context_payload,
            active_execution_lease_payload=active_execution_lease_payload,
            evidence_index_cursor_payload=evidence_index_cursor_payload,
            evidence_acquisition_horizon_payload=evidence_acquisition_horizon_payload,
            editor_context_payload=editor_context_payload,
        )
    if invocation == "tool_observation_followup":
        session_history_payload, current_request_payload = _split_volatile_request_payload(volatile_payload)
        attachment_context_payload, current_request_payload = _extract_attachment_context_payload(current_request_payload)
        turn_state_attention_context_payload, current_request_payload = _extract_turn_state_attention_context_payload(current_request_payload)
        active_execution_lease_payload, current_request_payload = _extract_active_execution_lease_payload(current_request_payload)
        editor_context_payload, current_request_payload = _extract_editor_context_payload(current_request_payload)
        tool_observation_context_payload, current_request_payload = _extract_tool_observation_context_payload(current_request_payload)
        return _NormalizedContextPayloads(
            dynamic_payload=_drop_empty_payload(dynamic_payload),
            current_request_payload=current_request_payload,
            session_history_payload=session_history_payload,
            attachment_context_payload=attachment_context_payload,
            turn_state_attention_context_payload=turn_state_attention_context_payload,
            active_execution_lease_payload=active_execution_lease_payload,
            editor_context_payload=editor_context_payload,
            tool_observation_context_payload=tool_observation_context_payload,
        )
    return _NormalizedContextPayloads(
        dynamic_payload=_drop_empty_payload(dynamic_payload),
        volatile_payload=_drop_empty_payload(volatile_payload),
        inherited_start_context_payload=_drop_empty_payload(inherited_start_context_payload),
    )


def _producer_order_for_invocation(invocation_kind: str) -> tuple[str, ...]:
    invocation = str(invocation_kind or "").strip()
    if invocation == "task_execution":
        return (
            "attachment_context",
            "turn_state_attention_context",
            "active_execution_lease",
            "evidence_index_cursor",
            "evidence_acquisition_horizon",
            "read_evidence_context",
            "editor_context",
            "task_state_replay_context",
        )
    if invocation == "tool_observation_followup":
        return (
            "attachment_context",
            "turn_state_attention_context",
            "active_execution_lease",
            "editor_context",
            "tool_observation_context",
            "read_evidence_context",
            "session_history",
        )
    return (
        "attachment_context",
        "turn_state_attention_context",
        "active_execution_lease",
        "evidence_index_cursor",
        "evidence_acquisition_horizon",
        "editor_context",
        "read_evidence_context",
        "session_history",
    )


class _AttachmentContextProducer:
    producer_id = "attachment_context"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("attachment_context") or {})
        attachment_context_index = payload.get("attachment_context_index")
        if not attachment_context_index:
            return ()
        return (
            build_runtime_payload_message_spec(
                role="system",
                title="Attachment context index",
                payload={"attachment_context_index": attachment_context_index},
                kind="attachment_context_index",
                source_ref=f"{request.source_ref_prefix}:attachment_context_index",
                cache_scope="session",
                cache_role="session_stable",
                compression_role="ref_only",
                metadata={
                    **_dynamic_context_segment_metadata(request.dynamic_context, source="attachment_context_index"),
                    "content_source": "harness.runtime.dynamic_context.attachment_context_index",
                    "runtime_fragment_role": "attachment_context_index",
                    "cache_impact": "provider_visible_context_prefix_attachment_index_snapshot",
                },
            ),
        )


class _EvidenceIndexCursorProducer:
    producer_id = "evidence_index_cursor"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("evidence_index_cursor") or {})
        evidence_index_cursor = payload.get("evidence_index_cursor")
        if not evidence_index_cursor:
            return ()
        return (
            build_runtime_payload_message_spec(
                role="system",
                title="Evidence index cursor",
                payload=_drop_empty_payload(
                    {
                        "evidence_index_cursor": evidence_index_cursor,
                    }
                ),
                kind="evidence_index_cursor",
                source_ref=f"{request.source_ref_prefix}:evidence_index_cursor",
                cache_scope="session",
                cache_role="session_stable",
                compression_role="ref_only",
                metadata={
                    **_dynamic_context_segment_metadata(request.dynamic_context, source="evidence_index_cursor"),
                    "content_source": "harness.runtime.dynamic_context.evidence_index_cursor",
                    "runtime_fragment_role": "evidence_index_cursor",
                    "cache_impact": "provider_visible_context_prefix_evidence_cursor_snapshot",
                },
            ),
        )


class _EvidenceAcquisitionHorizonProducer:
    producer_id = "evidence_acquisition_horizon"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        existing_payload = dict(request.payloads.get("evidence_acquisition_horizon") or {})
        generated_payload = build_evidence_acquisition_horizon(
            evidence_index_cursor_payload=dict(request.payloads.get("evidence_index_cursor") or {}),
            read_evidence_prompt_payload=dict(request.payloads.get("read_evidence_context") or {}),
            editor_context_payload=dict(request.payloads.get("editor_context") or {}),
        )
        horizon = dict(generated_payload.get("evidence_acquisition_horizon") or existing_payload.get("evidence_acquisition_horizon") or {})
        if not horizon:
            return ()
        return (
            build_runtime_payload_message_spec(
                role="system",
                title="Evidence acquisition horizon",
                payload={"evidence_acquisition_horizon": horizon},
                kind="evidence_acquisition_horizon",
                source_ref=f"{request.source_ref_prefix}:evidence_acquisition_horizon:{_short_hash(str(horizon.get('horizon_id') or _stable_json_hash(horizon)), prefix_chars=16)}",
                cache_scope="none",
                cache_role="volatile",
                compression_role="ref_only",
                metadata={
                    **_optional_dynamic_context_segment_metadata(request.dynamic_context, source="evidence_acquisition_horizon"),
                    "content_source": "harness.runtime.dynamic_context.evidence_acquisition_horizon",
                    "runtime_fragment_role": "evidence_acquisition_horizon",
                    "cache_impact": "current_dynamic_tail_only",
                    "context_cache_section": DYNAMIC_TAIL,
                    "context_capability_group": "evidence_context",
                    "context_capability_slot": "evidence_acquisition_horizon",
                    "context_capability_member": "contract",
                    "context_semantic_slot": "evidence_acquisition_horizon",
                    "context_semantic_slot_rank": 36,
                    "context_prefix_cache_scope": "none",
                    "context_prefix_cache_role": "volatile",
                    "context_prefix_tier": "volatile",
                    "context_commit_policy": "never_commit",
                    "context_replay_policy": "current_dynamic_tail_only",
                    "context_identity_policy": "current_invocation_only",
                    "semantic_commit_class": "current_evidence_acquisition_boundary",
                    "stability_rule": (
                        "Evidence acquisition horizon is a current invocation read-before-judgment boundary; "
                        "it is rebuilt from evidence refs/ranges/freshness and must not be sealed into history."
                    ),
                },
            ),
        )


class _ReadEvidenceContextProducer:
    producer_id = "read_evidence_context"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("read_evidence_context") or {})
        refs = [_drop_empty_payload(dict(item)) for item in list(payload.get("read_evidence_refs") or []) if isinstance(item, dict)]
        refs = [item for item in refs if item]
        if not refs:
            return ()
        projection_policy = _read_evidence_context_projection_policy(payload.get("projection_policy"))
        specs: list[dict[str, Any]] = []
        for index, evidence_ref in enumerate(refs, start=1):
            source_ref = _read_evidence_context_source_ref(
                evidence_ref,
                source_ref_prefix=request.source_ref_prefix,
                fallback_index=index,
            )
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title=f"Read evidence context {index}",
                    payload=_drop_empty_payload(
                        {
                            "read_evidence_ref": evidence_ref,
                            "projection_policy": projection_policy,
                        }
                    ),
                    kind="read_evidence_context",
                    source_ref=source_ref,
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        **_optional_dynamic_context_segment_metadata(request.dynamic_context, source="read_evidence_context"),
                        "content_source": "harness.runtime.dynamic_context.read_evidence_projector",
                        "runtime_fragment_role": "read_evidence_ref",
                        "cache_impact": "append_only_provider_visible_context_prefix",
                        "stability_rule": (
                            "read evidence refs already visible to the model are historical context; "
                            "new refs append as separate context messages and previous refs must not be rewritten"
                        ),
                        "append_only_context_package": "read_evidence_context",
                        "append_only_context_stream": "read_evidence",
                        "append_only_stream_index": index,
                    },
                )
            )
        return tuple(specs)


class _TurnStateAttentionContextProducer:
    producer_id = "turn_state_attention_context"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("turn_state_attention") or {})
        specs: list[dict[str, Any]] = []
        for descriptor in (
            {
                "key": "task_goal_context",
                "title": "current work goal resource context",
                "content_source": "harness.runtime.dynamic_context.turn_state_attention_context.task_goal_context",
                "runtime_fragment_role": "turn_goal_resource_context",
                "semantic_slot": "task_goal_context",
                "semantic_rank": 21,
            },
            {
                "key": "task_plan_context",
                "title": "current work plan cursor context",
                "content_source": "harness.runtime.dynamic_context.turn_state_attention_context.task_plan_context",
                "runtime_fragment_role": "turn_plan_cursor_context",
                "semantic_slot": "task_plan_context",
                "semantic_rank": 22,
            },
            {
                "key": "task_todo_context",
                "title": "current work todo cursor context",
                "content_source": "harness.runtime.dynamic_context.turn_state_attention_context.task_todo_context",
                "runtime_fragment_role": "turn_todo_cursor_context",
                "semantic_slot": "task_todo_context",
                "semantic_rank": 23,
            },
        ):
            key = str(descriptor["key"])
            context_payload = payload.get(key)
            if not context_payload:
                continue
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title=str(descriptor["title"]).title(),
                    payload={key: context_payload},
                    kind=key,
                    source_ref=f"{request.source_ref_prefix}:{key}",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="ref_only",
                    metadata={
                        **_dynamic_context_segment_metadata(request.dynamic_context, source=key),
                        **_current_append_fact_metadata(
                            kind=key,
                            payload={key: context_payload},
                            semantic_slot=str(descriptor["semantic_slot"]),
                            semantic_rank=int(descriptor["semantic_rank"]),
                            origin_ref=_task_state_fact_origin_ref(kind=key, payload=context_payload),
                            package="task_state_context",
                            stream=key,
                            semantic_commit_class="current_task_state_fact",
                        ),
                        "content_source": str(descriptor["content_source"]),
                        "runtime_fragment_role": str(descriptor["runtime_fragment_role"]),
                        "context_capability_group": "task_state_context",
                        "context_capability_slot": str(descriptor["semantic_slot"]),
                        "context_capability_member": "content",
                        "stability_rule": (
                            "Task goal, plan, and todo context are current task facts. "
                            "They enter current append with a content-versioned item key; unchanged facts are not re-appended, "
                            "and changed facts become the next sealed provider-visible task-state version after provider success."
                        ),
                    },
                )
            )
        return tuple(specs)


class _ActiveExecutionLeaseProducer:
    producer_id = "active_execution_lease"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("active_execution_lease") or {})
        active_execution_lease = payload.get("active_execution_lease")
        if not active_execution_lease:
            return ()
        lease = dict(active_execution_lease or {}) if isinstance(active_execution_lease, dict) else {}
        if str(lease.get("lease_state") or "").strip() not in {"active", "recoverable", "suspended"}:
            return ()
        return (
            build_runtime_payload_message_spec(
                role="system",
                title="Active execution lease",
                payload={"active_execution_lease": lease},
                kind="active_execution_lease",
                source_ref=f"{request.source_ref_prefix}:active_execution_lease:{_short_hash(str(lease.get('lease_id') or _stable_json_hash(lease)), prefix_chars=16)}",
                cache_scope="none",
                cache_role="volatile",
                compression_role="ref_only",
                metadata={
                    **_optional_dynamic_context_segment_metadata(request.dynamic_context, source="active_execution_lease"),
                    "content_source": "harness.runtime.dynamic_context.active_execution_lease",
                    "runtime_fragment_role": "active_execution_lease",
                    "cache_impact": "current_dynamic_tail_only",
                    "context_cache_section": DYNAMIC_TAIL,
                    "context_capability_group": "turn_state_control",
                    "context_capability_slot": "active_execution_lease",
                    "context_capability_member": "control",
                    "context_semantic_slot": "active_execution_lease",
                    "context_semantic_slot_rank": 24,
                    "context_prefix_cache_scope": "none",
                    "context_prefix_cache_role": "volatile",
                    "context_prefix_tier": "volatile",
                    "context_commit_policy": "never_commit",
                    "context_replay_policy": "current_dynamic_tail_only",
                    "context_identity_policy": "current_invocation_only",
                    "semantic_commit_class": "current_active_execution_lease",
                    "stability_rule": (
                        "Active execution lease is a short-lived current work boundary. "
                        "Completed, canceled, released, or superseded leases must not be injected."
                    ),
                },
            ),
        )


class _EditorContextProducer:
    producer_id = "editor_context"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("editor_context") or {})
        specs: list[dict[str, Any]] = []
        editor_context_index = payload.get("editor_context_index")
        if editor_context_index:
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title="Editor context index",
                    payload={"editor_context_index": editor_context_index},
                    kind="editor_context_index",
                    source_ref=f"{request.source_ref_prefix}:editor_context_index",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        **_dynamic_context_segment_metadata(request.dynamic_context, source="editor_context_index"),
                        "content_source": "harness.runtime.dynamic_context.editor_context_index",
                        "runtime_fragment_role": "editor_context_index",
                        "cache_impact": "provider_visible_context_prefix_editor_context_index_snapshot",
                    },
                )
            )
        editor_evidence_delta = payload.get("current_editor_evidence_delta")
        if editor_evidence_delta:
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title="Current editor evidence",
                    payload={"current_editor_evidence_delta": editor_evidence_delta},
                    kind="current_editor_evidence_delta",
                    source_ref=f"{request.source_ref_prefix}:current_editor_evidence_delta",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="preserve",
                    metadata={
                        **_dynamic_context_segment_metadata(request.dynamic_context, source="editor_exact_evidence_delta"),
                        **_current_append_fact_metadata(
                            kind="current_editor_evidence_delta",
                            payload={"current_editor_evidence_delta": editor_evidence_delta},
                            semantic_slot="current_editor_evidence_delta",
                            semantic_rank=41,
                            origin_ref=_editor_evidence_delta_origin_ref(editor_evidence_delta),
                            package="evidence_context",
                            stream="current_editor_evidence_delta",
                            semantic_commit_class="current_exact_evidence_fact",
                        ),
                        "content_source": "harness.runtime.dynamic_context.current_editor_evidence_delta",
                        "runtime_fragment_role": "current_editor_evidence_delta",
                        "stability_rule": (
                            "Editor exact evidence is a current evidence fact, not a dynamic control route. "
                            "The fact slot is based on path/event/range; unchanged visible text is not re-appended, "
                            "and changed text supersedes the previous content version after provider success."
                        ),
                    },
                )
            )
        return tuple(specs)


class _ToolObservationContextProducer:
    producer_id = "tool_observation_context"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = dict(request.payloads.get("tool_observation_context") or {})
        observations_payload = (
            dict(payload.get("observations") or {})
            if isinstance(payload.get("observations"), dict)
            else {}
        )
        observations = [
            _drop_empty_payload(dict(item))
            for item in list(observations_payload.get("latest_observations") or [])
            if isinstance(item, dict)
        ]
        observations = [item for item in observations if item]
        specs: list[dict[str, Any]] = []
        for index, observation in enumerate(observations, start=1):
            observation_ref = _tool_observation_entry_ref(observation, fallback_index=index)
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title=f"Current request tool result {observation_ref}",
                    payload={TOOL_TRANSCRIPT_DELTA_KIND: observation},
                    kind=TOOL_TRANSCRIPT_DELTA_KIND,
                    source_ref=f"{request.source_ref_prefix}:tool_transcript:{observation_ref}",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="ref_only",
                    metadata={
                        **_dynamic_context_segment_metadata(request.dynamic_context, source="current_request"),
                        "source_route": "observation_followup_projector",
                        "canonical_kind": TOOL_TRANSCRIPT_DELTA_KIND,
                        "semantic_title": "Current request tool result",
                        "volatility_reason": (
                            "this tool transcript entry is newly appended for the current follow-up; "
                            "later follow-ups must reuse it unchanged and append later tool results after it"
                        ),
                        "cache_impact": "append_only_provider_visible_context_prefix",
                        "stability_rule": (
                            "tool transcript deltas are emitted as append-only context entries; existing "
                            "entries must not be rewritten when later tool results arrive"
                        ),
                        "content_source": "harness.runtime.dynamic_context.tool_transcript_delta",
                        "runtime_fragment_role": "tool_transcript_delta",
                        "append_only_context_package": "tool_transcript",
                        "append_only_context_stream": "tool_transcript",
                        "append_only_event_offset": _safe_int(observation.get("event_offset")),
                        "append_only_created_at": _safe_float(observation.get("created_at")),
                        "append_only_stream_index": index,
                        "tool_observation_ref": observation_ref,
                    },
                )
            )
        return tuple(specs)


class _SessionHistoryContextProducer:
    producer_id = "session_history"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        payload = _drop_empty_payload(dict(request.payloads.get("session_history") or {}))
        if not payload:
            return ()
        metadata = _dynamic_context_segment_metadata(request.dynamic_context, source="session_history")
        pinned_facts_payload = _session_history_pinned_facts_context_payload(payload)
        recent_work_outcome_payload = _recent_work_outcome_context_payload(payload)
        specs: list[dict[str, Any]] = []
        if pinned_facts_payload:
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title="Recent session pinned facts",
                    payload=pinned_facts_payload,
                    kind="session_pinned_facts_context",
                    source_ref=f"{request.source_ref_prefix}_session_history:pinned_facts_context",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="summarize",
                    metadata={
                        **metadata,
                        "cache_impact": "context_append_then_sealed_prefix",
                        "stability_rule": "pinned facts are rememberable context; changes append as new context rather than living in the dynamic tail",
                        "session_history_component": "pinned_facts_context",
                        "append_only_context_package": "historical_context",
                        "append_only_context_stream": "session_pinned_facts",
                    },
                )
            )
        if recent_work_outcome_payload:
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title="Recent work outcome",
                    payload=recent_work_outcome_payload,
                    kind="recent_work_outcome",
                    source_ref=f"{request.source_ref_prefix}_session_history:recent_work_outcome",
                    cache_scope="none",
                    cache_role="volatile",
                    compression_role="summarize",
                    metadata={
                        **metadata,
                        **_current_append_fact_metadata(
                            kind="recent_work_outcome",
                            payload=recent_work_outcome_payload,
                            semantic_slot="recovery_or_recent_work_facts",
                            semantic_rank=10,
                            origin_ref=_recent_work_outcome_origin_ref(recent_work_outcome_payload),
                            package="recent_work_outcome",
                            stream="recent_work_outcome",
                            semantic_commit_class="recent_work_outcome_fact",
                        ),
                        "stability_rule": (
                            "Recent work outcome is a read-only work fact. It belongs in current append, "
                            "not in the never-replay control tail; runtime recovery instructions remain separate."
                        ),
                        "session_history_component": "recent_work_outcome",
                    },
                )
            )
        return tuple(specs)


class _TaskStateReplayContextProducer:
    producer_id = "task_state_replay_context"

    def collect(self, request: ContextMessageProducerRequest) -> tuple[dict[str, Any], ...]:
        specs: list[dict[str, Any]] = []
        for index, raw_entry in enumerate(tuple(request.task_state_replay_entries or ()), start=1):
            entry = _drop_empty_payload(dict(raw_entry or {}))
            if not entry:
                continue
            entry_ref = _task_state_replay_entry_ref(entry, fallback_index=index)
            specs.append(
                build_runtime_payload_message_spec(
                    role="system",
                    title=f"Task execution replayed state evidence {entry_ref}",
                    payload={"task_state_replay_entry": entry},
                    kind="task_state_replay_entry",
                    source_ref=f"task_state_replay:{entry_ref}",
                    cache_scope="session",
                    cache_role="session_stable",
                    compression_role="preserve",
                    metadata={
                        "cache_impact": "append_only_provider_visible_context_prefix",
                        "stability_rule": "replay entries are append-only historical evidence; current invocation deltas remain in volatile task state",
                        "dynamic_context_report_ref": "task_state_replay_entries",
                        "projection_strategy": "bounded_task_state_replay_entry",
                        "task_state_replay_entry_index": index,
                        "task_state_replay_entry_ref": entry_ref,
                        "content_source": "runtime.dynamic_context.task_state_replay_entry",
                        "runtime_fragment_role": "append_only_task_state_evidence",
                    },
                )
            )
        return tuple(specs)


def _split_volatile_request_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    source = dict(payload or {})
    history_payload = dict(source.get("history") or {}) if isinstance(source.get("history"), dict) else {}
    current_request = dict(source)
    current_request.pop("history", None)
    session_history = dict(history_payload)
    return _drop_empty_payload(session_history), _drop_empty_payload(current_request)


def _extract_editor_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    editor_payload = _drop_empty_payload(
        {
            "editor_context_index": current.pop("editor_context_index", None),
            "current_editor_evidence_delta": current.pop("current_editor_evidence_delta", None),
        }
    )
    return editor_payload, _drop_empty_payload(current)


def _extract_attachment_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    attachment_payload = _drop_empty_payload(
        {
            "attachment_context_index": current.pop("attachment_context_index", None),
        }
    )
    return attachment_payload, _drop_empty_payload(current)


def _extract_turn_state_attention_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    task_mode_payload = _drop_empty_payload(
        {
            "task_goal_context": current.pop("task_goal_context", None),
            "task_plan_context": current.pop("task_plan_context", None),
            "task_todo_context": current.pop("task_todo_context", None),
        }
    )
    return task_mode_payload, _drop_empty_payload(current)


def _extract_active_execution_lease_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    lease_payload = _drop_empty_payload(
        {
            "active_execution_lease": current.pop("active_execution_lease", None),
        }
    )
    return lease_payload, _drop_empty_payload(current)


def _extract_tool_observation_context_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    observations_payload = (
        dict(current.get("observations") or {}) if isinstance(current.get("observations"), dict) else {}
    )
    latest_observations = [
        _drop_empty_payload(dict(item))
        for item in list(observations_payload.get("latest_observations") or [])
        if isinstance(item, dict)
    ]
    latest_observations = [item for item in latest_observations if item]
    if not latest_observations:
        return {}, _drop_empty_payload(current)

    remaining_observations = dict(observations_payload)
    remaining_observations.pop("latest_observations", None)
    if set(remaining_observations) <= {"authority"}:
        remaining_observations = {}
    if remaining_observations:
        current["observations"] = _drop_empty_payload(remaining_observations)
    else:
        current.pop("observations", None)
    return {
        "observations": {
            "latest_observations": latest_observations,
        }
    }, _drop_empty_payload(current)


def _extract_evidence_index_cursor_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    evidence_payload = _drop_empty_payload(
        {
            "evidence_index_cursor": current.pop("evidence_index_cursor", None),
        }
    )
    return evidence_payload, _drop_empty_payload(current)


def _extract_evidence_acquisition_horizon_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    current = dict(payload or {})
    horizon_payload = _drop_empty_payload(
        {
            "evidence_acquisition_horizon": current.pop("evidence_acquisition_horizon", None),
        }
    )
    return horizon_payload, _drop_empty_payload(current)


def _read_evidence_context_projection_policy(value: Any) -> dict[str, Any]:
    policy = dict(value or {}) if isinstance(value, dict) else {}
    return _drop_empty_payload(
        {
            "historical_read_evidence": policy.get("historical_read_evidence"),
            "rehydration": policy.get("rehydration"),
        }
    )


def _read_evidence_context_source_ref(
    evidence_ref: dict[str, Any],
    *,
    source_ref_prefix: str,
    fallback_index: int,
) -> str:
    payload = dict(evidence_ref or {})
    stable_ref = str(
        payload.get("artifact_ref")
        or payload.get("exact_artifact_ref")
        or payload.get("evidence_ref")
        or payload.get("observation_ref")
        or payload.get("tool_call_id")
        or ""
    ).strip()
    if stable_ref:
        return f"{source_ref_prefix}:read_evidence_context:{_short_hash(stable_ref, prefix_chars=16)}"
    seed = {
        "path": str(payload.get("path") or ""),
        "start_line": payload.get("start_line"),
        "end_line": payload.get("end_line"),
        "content_sha256": str(payload.get("content_sha256") or ""),
    }
    digest = _stable_json_hash(seed).removeprefix("sha256:")[:16]
    return f"{source_ref_prefix}:read_evidence_context:{digest or fallback_index}"


def _tool_observation_entry_ref(observation: dict[str, Any], *, fallback_index: int) -> str:
    explicit = str(
        observation.get("observation_id")
        or observation.get("observation_ref")
        or observation.get("tool_result_ref")
        or ""
    ).strip()
    if explicit:
        return explicit
    digest = hashlib.sha256(
        json.dumps(_json_stable(observation), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:12]
    return f"observation:{digest or fallback_index}"


def _current_append_fact_metadata(
    *,
    kind: str,
    payload: dict[str, Any],
    semantic_slot: str,
    semantic_rank: int,
    origin_ref: str = "",
    package: str = "",
    stream: str = "",
    semantic_commit_class: str = "",
) -> dict[str, Any]:
    normalized_kind = str(kind or "").strip()
    normalized_slot = str(semantic_slot or normalized_kind or "context_memory_append").strip()
    content_hash = _stable_json_hash(payload)
    stable_origin_ref = str(origin_ref or "").strip() or f"{normalized_kind}:{content_hash}"
    fact_slot_key = _stable_json_hash(
        {
            "schema": "semantic_fact_slot",
            "kind": normalized_kind,
            "semantic_slot": normalized_slot,
            "origin_ref": stable_origin_ref,
        }
    )
    item_key = _stable_json_hash(
        {
            "schema": "current_append_fact_context_item",
            "kind": normalized_kind,
            "semantic_slot": normalized_slot,
            "origin_ref": stable_origin_ref,
            "content_hash": content_hash,
        }
    )
    return {
        "cache_impact": "context_append_then_sealed_prefix",
        "context_cache_section": CONTEXT_APPEND,
        "context_prefix_cache_scope": "none",
        "context_prefix_cache_role": "volatile",
        "context_prefix_tier": "volatile",
        "context_semantic_slot": normalized_slot,
        "context_semantic_slot_rank": int(semantic_rank or 0),
        "context_commit_policy": "append_then_seal",
        "context_replay_policy": "current_append_commit_on_provider_success_then_next_physical_prefix_frame",
        "context_identity_policy": "origin_ref_stable",
        "context_origin_authority": "harness.runtime.context_message_producers.current_append_fact",
        "context_origin_ref": stable_origin_ref,
        "append_only_context_package": str(package or normalized_slot or normalized_kind),
        "append_only_context_stream": str(stream or normalized_slot or normalized_kind),
        "append_only_context_item_key": item_key,
        "append_only_content_hash": content_hash,
        "fact_slot_key": fact_slot_key,
        "fact_content_hash": content_hash,
        "fact_change_class": "content_version_candidate",
        "fact_supersession_policy": "same_fact_slot_latest_content_hash_supersedes_prior",
        "semantic_commit_class": str(semantic_commit_class or "context_memory_append"),
        "provider_visible_after_validity": "replay_after_provider_success_via_physical_prefix_frame",
    }


def _task_state_fact_origin_ref(*, kind: str, payload: dict[str, Any]) -> str:
    normalized_kind = str(kind or "").strip()
    data = dict(payload or {})
    if normalized_kind == "task_goal_context":
        active_goal = dict(data.get("active_goal") or {}) if isinstance(data.get("active_goal"), dict) else {}
        return str(active_goal.get("goal_ref") or active_goal.get("goal_sha256") or "").strip()
    if normalized_kind == "task_plan_context":
        baseline = dict(data.get("task_plan_baseline") or {}) if isinstance(data.get("task_plan_baseline"), dict) else {}
        return str(baseline.get("plan_baseline_ref") or baseline.get("plan_sha256") or "").strip()
    if normalized_kind == "task_todo_context":
        baseline = dict(data.get("task_todo_baseline") or {}) if isinstance(data.get("task_todo_baseline"), dict) else {}
        delta = dict(data.get("task_todo_delta") or {}) if isinstance(data.get("task_todo_delta"), dict) else {}
        baseline_ref = str(baseline.get("todo_baseline_ref") or baseline.get("todo_sha256") or "").strip()
        cursor_hash = str(delta.get("cursor_hash") or "").strip()
        return ":".join(item for item in (baseline_ref, cursor_hash) if item)
    return ""


def _editor_evidence_delta_origin_ref(payload: Any) -> str:
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    anchors: list[dict[str, Any]] = []
    for item in list(data.get("events") or [])[:8]:
        if not isinstance(item, dict):
            continue
        anchors.append(
            _drop_empty_payload(
                {
                    "event": str(item.get("event") or ""),
                    "path": str(item.get("path") or "").replace("\\", "/"),
                    "range": dict(item.get("range") or {}) if isinstance(item.get("range"), dict) else {},
                    "source": str(item.get("source") or ""),
                }
            )
        )
    anchors = [item for item in anchors if item]
    if not anchors:
        return ""
    return "editor_evidence_delta:" + _stable_json_hash({"anchors": anchors}).removeprefix("sha256:")[:16]


def _recent_work_outcome_origin_ref(payload: dict[str, Any]) -> str:
    data = dict(dict(payload or {}).get("recent_work_outcome") or {})
    task_run_id = str(data.get("task_run_id") or "").strip()
    status = str(data.get("status") or "").strip()
    content_hash = _stable_json_hash(payload).removeprefix("sha256:")[:16]
    return ":".join(item for item in ("recent_work_outcome", task_run_id, status, content_hash) if item)


def _recent_work_outcome_context_payload(clean_payload: dict[str, Any]) -> dict[str, Any]:
    session_context = dict(clean_payload.get("session_context") or {}) if isinstance(clean_payload.get("session_context"), dict) else {}
    recent_work_outcome = (
        dict(session_context.get("recent_work_outcome") or {})
        if isinstance(session_context.get("recent_work_outcome"), dict)
        else {}
    )
    return _drop_empty_payload(
        {
            "recent_work_outcome": recent_work_outcome,
        }
    )


def _session_history_pinned_facts_context_payload(clean_payload: dict[str, Any]) -> dict[str, Any]:
    pinned_facts = [
        _drop_empty_payload(dict(item))
        for item in list(clean_payload.get("pinned_facts") or [])
        if isinstance(item, dict)
    ]
    pinned_facts = [item for item in pinned_facts if item]
    return _drop_empty_payload(
        {
            "pinned_facts": pinned_facts,
        }
    )


def _task_state_replay_entry_ref(entry: dict[str, Any], *, fallback_index: int) -> str:
    explicit_ref = str(entry.get("observation_ref") or entry.get("entry_ref") or "").strip()
    if explicit_ref:
        return explicit_ref
    digest = hashlib.sha256(
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="ignore")
    ).hexdigest()[:12]
    return f"entry:{digest or fallback_index}"


def _dynamic_context_segment_metadata(
    projection: DynamicContextProjection,
    *,
    source: str,
) -> dict[str, Any]:
    source_text = str(source or "")
    for report in projection.section_reports:
        if str(report.source or "") == source_text:
            return {
                "dynamic_context_report_ref": report.section_id,
                "volatility_reason": report.volatility_reason,
                "projection_strategy": report.projection_strategy,
                "cache_impact": report.cache_impact,
            }
    raise ValueError(f"dynamic context section report missing for source: {source_text}")


def _optional_dynamic_context_segment_metadata(
    projection: DynamicContextProjection,
    *,
    source: str,
) -> dict[str, Any]:
    try:
        return _dynamic_context_segment_metadata(projection, source=source)
    except ValueError:
        return {}


def _annotate_context_message_producer_spec(
    spec: dict[str, Any],
    *,
    producer_id: str,
    producer_index: int,
    item_index: int,
) -> dict[str, Any]:
    payload = dict(spec or {})
    metadata = {
        **dict(payload.get("metadata") or {}),
        "context_message_producer_id": str(producer_id or "").strip(),
        "context_message_producer_authority": "harness.runtime.context_message_producers.registry",
        "context_message_producer_order": int(producer_index or 0),
        "context_message_producer_item_index": int(item_index or 0),
    }
    metadata.setdefault(
        "context_candidate_source_route",
        str(metadata.get("source_route") or metadata.get("content_source") or producer_id or "").strip(),
    )
    payload["metadata"] = metadata
    return payload


def _drop_empty_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _short_hash(value: str, *, prefix_chars: int = 10) -> str:
    digest = hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()
    return digest[: max(4, int(prefix_chars or 10))]


def _stable_json_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="ignore")
    ).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
