from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from token_accounting import count_text_tokens

from .contracts import MemoryContextCandidate
from .working_memory_models import (
    WorkingMemoryHandoffTransaction,
    WorkingMemoryItem,
    WorkingMemoryPolicyProfile,
    WorkingMemoryQuery,
    WorkingMemoryReadLog,
    WorkingMemoryTemporalEdge,
)
from .working_memory_store import WorkingMemoryStore


class WorkingMemoryPolicyDenied(ValueError):
    def __init__(self, denied_reason: str) -> None:
        super().__init__(denied_reason)
        self.denied_reason = denied_reason


class WorkingMemoryService:
    def __init__(self, root_dir: str | Path) -> None:
        self.store = WorkingMemoryStore(root_dir)

    def create_item(self, **payload: Any) -> WorkingMemoryItem:
        data = dict(payload)
        task_run_id = _required(data, "task_run_id")
        owner_node_id = str(data.get("owner_node_id") or "").strip()
        node_run_id = str(data.get("node_run_id") or "").strip()
        kind = str(data.get("kind") or "intermediate_result").strip()
        summary = str(data.get("summary") or "").strip()
        title = str(data.get("title") or summary[:80] or kind).strip()
        idempotency_key = str(data.get("idempotency_key") or "").strip()
        if not idempotency_key:
            idempotency_key = _stable_id(
                "wmidem",
                task_run_id,
                owner_node_id,
                node_run_id,
                str(data.get("run_attempt_id") or ""),
                kind,
                summary,
                str(data.get("source_message_hash") or ""),
            )
        item = WorkingMemoryItem(
            work_memory_id=str(data.get("work_memory_id") or _stable_id("wm", task_run_id, owner_node_id, node_run_id, idempotency_key)),
            task_run_id=task_run_id,
            task_id=str(data.get("task_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            owner_node_id=owner_node_id,
            owner_node_role=str(data.get("owner_node_role") or ""),
            node_run_id=node_run_id,
            run_attempt_id=str(data.get("run_attempt_id") or ""),
            stage_id=str(data.get("stage_id") or ""),
            writer_agent_id=str(data.get("writer_agent_id") or ""),
            last_writer_agent_id=str(data.get("last_writer_agent_id") or data.get("writer_agent_id") or ""),
            scope=str(data.get("scope") or "node_scope"),  # type: ignore[arg-type]
            kind=kind,
            memory_semantics=str(data.get("memory_semantics") or _default_semantics(kind)),  # type: ignore[arg-type]
            title=title,
            payload=dict(data.get("payload") or {}),
            summary=summary,
            status=str(data.get("status") or "draft"),  # type: ignore[arg-type]
            visibility=str(data.get("visibility") or "private_to_node"),  # type: ignore[arg-type]
            read_policy=dict(data.get("read_policy") or {}),
            write_policy=dict(data.get("write_policy") or {}),
            version=int(data.get("version") or 1),
            parent_item_id=str(data.get("parent_item_id") or ""),
            source_event_refs=tuple(_strings(data.get("source_event_refs"))),
            source_message_refs=tuple(_strings(data.get("source_message_refs"))),
            artifact_refs=tuple(_strings(data.get("artifact_refs"))),
            contract_refs=tuple(_strings(data.get("contract_refs"))),
            reader_policy=dict(data.get("reader_policy") or {}),
            tags=tuple(_strings(data.get("tags"))),
            temporal_refs=tuple(_strings(data.get("temporal_refs"))),
            conflict_refs=tuple(_strings(data.get("conflict_refs"))),
            adopted_from_handoff_id=str(data.get("adopted_from_handoff_id") or data.get("handoff_id") or ""),
            idempotency_key=idempotency_key,
            source_message_hash=str(data.get("source_message_hash") or ""),
            expires_at=str(data.get("expires_at") or ""),
            promotion_state=str(data.get("promotion_state") or "not_applicable"),  # type: ignore[arg-type]
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "candidate_only"),  # type: ignore[arg-type]
        )
        return self.store.upsert_item(item)

    def get_item(self, work_memory_id: str) -> WorkingMemoryItem | None:
        return self.store.get_item(work_memory_id)

    def query_items(self, **filters: Any) -> tuple[WorkingMemoryItem, ...]:
        return self.store.query_items(WorkingMemoryQuery(**filters))

    def context_candidates(
        self,
        *,
        task_run_id: str = "",
        task_id: str = "",
        graph_id: str = "",
        owner_node_id: str = "",
        node_run_id: str = "",
        run_attempt_id: str = "",
        requested_kinds: list[str] | tuple[str, ...] = (),
        requested_semantics: list[str] | tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[MemoryContextCandidate, ...]:
        if not task_run_id:
            return ()
        items = self.query_items(
            task_run_id=task_run_id,
            task_id=task_id,
            graph_id=graph_id,
            owner_node_id=owner_node_id,
            node_run_id=node_run_id,
            run_attempt_id=run_attempt_id,
            limit=max(1, min(int(limit or 20), 100)),
        )
        kind_filter = set(_strings(requested_kinds))
        semantics_filter = set(_strings(requested_semantics))
        candidates: list[MemoryContextCandidate] = []
        for item in items:
            if kind_filter and item.kind not in kind_filter:
                continue
            if semantics_filter and item.memory_semantics not in semantics_filter:
                continue
            if item.status in {"discarded", "superseded", "archived", "promoted"}:
                continue
            preview = _render_candidate_preview(item)
            if not preview:
                continue
            candidates.append(
                MemoryContextCandidate(
                    candidate_id=f"memory-context:{task_run_id}:working:{item.work_memory_id}",
                    memory_layer="working",
                    source="working_memory.store",
                    content_ref=item.work_memory_id,
                    rendered_preview=preview,
                    relevance=_working_relevance(item.status),
                    confidence=_working_confidence(item),
                    staleness="task_run_scoped",
                    owner_task_id=item.task_id,
                    token_estimate=max(1, count_text_tokens(preview)),
                    budget_class="required" if item.status == "accepted" else "preferred",
                    can_override_current_turn=False,
                    requires_verification_before_use=item.status != "accepted",
                    authority="candidate_only",
                    metadata={
                        "task_run_id": item.task_run_id,
                        "graph_id": item.graph_id,
                        "owner_node_id": item.owner_node_id,
                        "node_run_id": item.node_run_id,
                        "run_attempt_id": item.run_attempt_id,
                        "stage_id": item.stage_id,
                        "kind": item.kind,
                        "memory_semantics": item.memory_semantics,
                        "status": item.status,
                        "visibility": item.visibility,
                        "writer_agent_id": item.writer_agent_id,
                    },
                )
            )
        return tuple(candidates)

    def select_for_node(
        self,
        *,
        task_run_id: str,
        graph_id: str = "",
        owner_node_id: str = "",
        node_run_id: str = "",
        run_attempt_id: str = "",
        reader_agent_id: str = "",
        node_role: str = "",
        memory_read_policy: dict[str, Any] | None = None,
        dynamic_read_policy: dict[str, Any] | None = None,
        request: dict[str, Any] | None = None,
        token_budget: int = 0,
        read_count_so_far: int = 0,
    ) -> dict[str, Any]:
        task_run = str(task_run_id or "").strip()
        if not task_run:
            raise ValueError("WorkingMemoryService.select_for_node requires task_run_id")
        read_policy = dict(memory_read_policy or {})
        dynamic_policy = dict(dynamic_read_policy or {})
        read_request = dict(request or {})
        denied_reason = _read_denied_reason(
            read_policy=read_policy,
            dynamic_policy=dynamic_policy,
            read_request=read_request,
            read_count_so_far=read_count_so_far,
        )
        if denied_reason:
            log = self.record_read(
                task_run_id=task_run,
                graph_id=graph_id,
                owner_node_id=owner_node_id,
                node_run_id=node_run_id,
                run_attempt_id=run_attempt_id,
                reader_agent_id=reader_agent_id,
                selected_item_ids=(),
                excluded_item_ids=(),
                request={**read_request, "node_role": node_role},
                denied_reason=denied_reason,
            )
            return _selection_payload((), (), log, denied_reason=denied_reason)

        items = self.query_items(
            task_run_id=task_run,
            graph_id=graph_id,
            limit=max(200, int(read_request.get("candidate_pool_limit") or read_policy.get("candidate_pool_limit") or 200)),
        )
        selected: list[WorkingMemoryItem] = []
        excluded: list[WorkingMemoryItem] = []
        token_used = 0
        max_initial_items = max(1, int(read_request.get("max_items") or read_policy.get("max_items") or 200))
        explicit_requested_kinds = read_request.get("requested_kinds") or read_request.get("requested_kind")
        requested_kinds = set(_strings(explicit_requested_kinds or read_policy.get("readable_kinds")))
        requested_semantics = set(_strings(read_request.get("requested_semantics") or read_request.get("requested_semantic") or read_policy.get("readable_semantics")))
        repository_read_edges = _normalized_repository_read_edges(read_request.get("repository_read_edges") or read_policy.get("repository_read_edges"))
        if repository_read_edges and not explicit_requested_kinds:
            requested_kinds = set()
        readable_scopes = _effective_readable_scopes(read_request=read_request, read_policy=read_policy)
        readable_visibilities = _effective_readable_visibilities(read_request=read_request, read_policy=read_policy)
        required_stage_ids = set(_strings(read_request.get("required_stage_ids")))
        for item in items:
            if item.status != "accepted":
                excluded.append(item)
                continue
            if readable_visibilities and item.visibility not in readable_visibilities:
                excluded.append(item)
                continue
            if item.visibility == "private_to_agent" and item.writer_agent_id != reader_agent_id:
                excluded.append(item)
                continue
            if item.visibility == "private_to_node" and item.owner_node_id != owner_node_id:
                excluded.append(item)
                continue
            if item.visibility == "handoff_only" and not _handoff_visibility_allowed(
                item=item,
                owner_node_id=owner_node_id,
                read_request=read_request,
                read_policy=read_policy,
            ):
                excluded.append(item)
                continue
            if item.visibility in {"coordinator_only", "human_review_only"} and node_role not in {"coordinator", "human_gate"}:
                excluded.append(item)
                continue
            if readable_scopes and item.scope not in readable_scopes:
                excluded.append(item)
                continue
            if requested_kinds and item.kind not in requested_kinds:
                excluded.append(item)
                continue
            if requested_semantics and item.memory_semantics not in requested_semantics:
                excluded.append(item)
                continue
            if required_stage_ids and item.stage_id not in required_stage_ids:
                excluded.append(item)
                continue
            if repository_read_edges and not _item_matches_any_repository_edge(item, repository_read_edges):
                excluded.append(item)
                continue
            item_tokens = count_text_tokens(item.summary or item.title or str(item.payload)[:500])
            if token_budget and token_used + item_tokens > token_budget:
                excluded.append(item)
                continue
            if len(selected) >= max_initial_items:
                excluded.append(item)
                continue
            token_used += item_tokens
            selected.append(item)
        selected_with_temporal = self._expand_temporal_neighbors(
            selected,
            items=items,
            read_request=read_request,
            dynamic_policy=dynamic_policy,
            token_budget=max(0, int(token_budget or 0) - token_used),
        )
        selected_ids = tuple(item.work_memory_id for item in selected_with_temporal)
        excluded_ids = tuple(item.work_memory_id for item in excluded if item.work_memory_id not in selected_ids)
        log = self.record_read(
            task_run_id=task_run,
            graph_id=graph_id,
            owner_node_id=owner_node_id,
            node_run_id=node_run_id,
            run_attempt_id=run_attempt_id,
            reader_agent_id=reader_agent_id,
            selected_item_ids=selected_ids,
            excluded_item_ids=excluded_ids,
            request={**read_request, "node_role": node_role},
        )
        return _selection_payload(selected_with_temporal, tuple(excluded), log)

    def resolve_handoff_into_working_memory(
        self,
        *,
        task_run_id: str,
        graph_id: str = "",
        edge_id: str = "",
        source_node_run_id: str = "",
        target_node_run_id: str = "",
        handoff_id: str = "",
        source_message_hash: str = "",
        working_memory_refs: list[str] | tuple[str, ...] = (),
        summary: str = "",
        ephemeral_context_refs: list[str] | tuple[str, ...] = (),
        idempotency_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkingMemoryHandoffTransaction:
        refs = tuple(_strings(working_memory_refs))
        transaction = self.create_handoff_transaction(
            task_run_id=task_run_id,
            graph_id=graph_id,
            edge_id=edge_id,
            source_node_run_id=source_node_run_id,
            target_node_run_id=target_node_run_id,
            handoff_id=handoff_id,
            source_message_hash=source_message_hash,
            idempotency_key=idempotency_key,
            candidate_work_memory_ids=refs,
            ephemeral_context_refs=tuple(_strings(ephemeral_context_refs)),
            metadata={**dict(metadata or {}), "summary": summary},
        )
        if transaction.transaction_status == "committed":
            return transaction
        return self.commit_handoff_transaction(
            transaction.transaction_id,
            adopted_work_memory_ids=refs,
            ephemeral_context_refs=tuple(_strings(ephemeral_context_refs)) or (() if refs else (summary,)),
        )

    def accept_item(self, work_memory_id: str, *, actor_id: str = "", metadata: dict[str, Any] | None = None) -> WorkingMemoryItem:
        return self.store.set_item_status(
            work_memory_id,
            status="accepted",
            authority="coordinator_adopted" if actor_id else "runloop_adopted",
            actor_id=actor_id,
            metadata=metadata,
        )

    def discard_item(self, work_memory_id: str, *, actor_id: str = "", metadata: dict[str, Any] | None = None) -> WorkingMemoryItem:
        return self.store.set_item_status(
            work_memory_id,
            status="discarded",
            actor_id=actor_id,
            metadata=metadata,
        )

    def mark_conflict(self, work_memory_id: str, *, actor_id: str = "", metadata: dict[str, Any] | None = None) -> WorkingMemoryItem:
        return self.store.set_item_status(
            work_memory_id,
            status="conflicted",
            actor_id=actor_id,
            metadata=metadata,
        )

    def update_lifecycle(
        self,
        work_memory_id: str,
        *,
        status: str | None = None,
        promotion_state: str | None = None,
        authority: str = "",
        actor_id: str = "",
        metadata: dict[str, Any] | None = None,
        event_type: str = "lifecycle_updated",
    ) -> WorkingMemoryItem:
        return self.store.update_item_lifecycle(
            work_memory_id,
            status=status,
            promotion_state=promotion_state,
            authority=authority,
            actor_id=actor_id,
            metadata=metadata,
            event_type=event_type,
        )

    def record_read(
        self,
        *,
        task_run_id: str,
        selected_item_ids: list[str] | tuple[str, ...],
        excluded_item_ids: list[str] | tuple[str, ...] = (),
        graph_id: str = "",
        owner_node_id: str = "",
        node_run_id: str = "",
        run_attempt_id: str = "",
        reader_agent_id: str = "",
        request: dict[str, Any] | None = None,
        denied_reason: str = "",
    ) -> WorkingMemoryReadLog:
        selected = tuple(_strings(selected_item_ids))
        token_estimate = 0
        for item_id in selected:
            item = self.store.get_item(item_id)
            if item is not None:
                token_estimate += count_text_tokens(item.summary or item.title or item.kind)
        log = WorkingMemoryReadLog(
            read_log_id=_stable_id("wmread", task_run_id, node_run_id, reader_agent_id, ",".join(selected), denied_reason),
            task_run_id=task_run_id,
            graph_id=graph_id,
            owner_node_id=owner_node_id,
            node_run_id=node_run_id,
            run_attempt_id=run_attempt_id,
            reader_agent_id=reader_agent_id,
            request=dict(request or {}),
            selected_item_ids=selected,
            excluded_item_ids=tuple(_strings(excluded_item_ids)),
            token_estimate=token_estimate,
            denied_reason=denied_reason,
        )
        return self.store.append_read_log(log)

    def list_read_logs(self, task_run_id: str = "", *, limit: int = 200) -> tuple[WorkingMemoryReadLog, ...]:
        return self.store.list_read_logs(task_run_id, limit=limit)

    def create_temporal_edge(self, **payload: Any) -> WorkingMemoryTemporalEdge:
        task_run_id = _required(payload, "task_run_id")
        source_item_id = str(payload.get("source_item_id") or "").strip()
        target_item_id = str(payload.get("target_item_id") or "").strip()
        relation = str(payload.get("relation") or "depends_on").strip()
        edge = WorkingMemoryTemporalEdge(
            edge_id=str(payload.get("edge_id") or _stable_id("wmtedge", task_run_id, source_item_id, target_item_id, relation)),
            task_run_id=task_run_id,
            graph_id=str(payload.get("graph_id") or ""),
            source_item_id=source_item_id,
            target_item_id=target_item_id,
            relation=relation,
            confidence=float(payload.get("confidence") or 0.0),
            source_node_id=str(payload.get("source_node_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )
        return self.store.add_temporal_edge(edge)

    def list_temporal_edges(self, task_run_id: str = "") -> tuple[WorkingMemoryTemporalEdge, ...]:
        return self.store.list_temporal_edges(task_run_id)

    def create_handoff_transaction(self, **payload: Any) -> WorkingMemoryHandoffTransaction:
        task_run_id = _required(payload, "task_run_id")
        handoff_id = str(payload.get("handoff_id") or "").strip()
        source_message_hash = str(payload.get("source_message_hash") or "").strip()
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            idempotency_key = _stable_id("wmhid", task_run_id, handoff_id, source_message_hash)
        transaction = WorkingMemoryHandoffTransaction(
            transaction_id=str(payload.get("transaction_id") or _stable_id("wmh", task_run_id, idempotency_key)),
            task_run_id=task_run_id,
            graph_id=str(payload.get("graph_id") or ""),
            edge_id=str(payload.get("edge_id") or ""),
            source_node_run_id=str(payload.get("source_node_run_id") or ""),
            target_node_run_id=str(payload.get("target_node_run_id") or ""),
            handoff_id=handoff_id,
            source_message_hash=source_message_hash,
            idempotency_key=idempotency_key,
            candidate_work_memory_ids=tuple(_strings(payload.get("candidate_work_memory_ids"))),
            adopted_work_memory_ids=tuple(_strings(payload.get("adopted_work_memory_ids"))),
            rejected_work_memory_ids=tuple(_strings(payload.get("rejected_work_memory_ids"))),
            ephemeral_context_refs=tuple(_strings(payload.get("ephemeral_context_refs"))),
            transaction_status=str(payload.get("transaction_status") or "pending"),  # type: ignore[arg-type]
            metadata=dict(payload.get("metadata") or {}),
        )
        return self.store.upsert_handoff_transaction(transaction)

    def commit_handoff_transaction(
        self,
        transaction_id: str,
        *,
        adopted_work_memory_ids: list[str] | tuple[str, ...] = (),
        rejected_work_memory_ids: list[str] | tuple[str, ...] = (),
        ephemeral_context_refs: list[str] | tuple[str, ...] = (),
    ) -> WorkingMemoryHandoffTransaction:
        return self.store.update_handoff_transaction_status(
            transaction_id,
            transaction_status="committed",
            adopted_work_memory_ids=tuple(_strings(adopted_work_memory_ids)),
            rejected_work_memory_ids=tuple(_strings(rejected_work_memory_ids)),
            ephemeral_context_refs=tuple(_strings(ephemeral_context_refs)),
        )

    def list_handoff_transactions(self, task_run_id: str = "") -> tuple[WorkingMemoryHandoffTransaction, ...]:
        return self.store.list_handoff_transactions(task_run_id)

    def save_policy_profile(self, **payload: Any) -> WorkingMemoryPolicyProfile:
        profile = WorkingMemoryPolicyProfile(
            profile_id=_required(payload, "profile_id"),
            allowed_kinds=tuple(_strings(payload.get("allowed_kinds"))),
            allowed_semantics=tuple(_strings(payload.get("allowed_semantics"))),  # type: ignore[arg-type]
            readable_scopes_by_node_role=dict(payload.get("readable_scopes_by_node_role") or {}),
            writable_kinds_by_node_role=dict(payload.get("writable_kinds_by_node_role") or {}),
            default_visibility_by_kind=dict(payload.get("default_visibility_by_kind") or {}),
            default_status_by_semantics=dict(payload.get("default_status_by_semantics") or {}),
            promotion_rules=dict(payload.get("promotion_rules") or {}),
            retention_rules=dict(payload.get("retention_rules") or {}),
            conflict_rules=dict(payload.get("conflict_rules") or {}),
            dynamic_read_rules=dict(payload.get("dynamic_read_rules") or {}),
            temporal_rules=dict(payload.get("temporal_rules") or {}),
            retry_memory_rules=dict(payload.get("retry_memory_rules") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )
        return self.store.upsert_policy_profile(profile)

    def get_policy_profile(self, profile_id: str) -> WorkingMemoryPolicyProfile | None:
        return self.store.get_policy_profile(profile_id)

    def _expand_temporal_neighbors(
        self,
        selected: list[WorkingMemoryItem],
        *,
        items: tuple[WorkingMemoryItem, ...],
        read_request: dict[str, Any],
        dynamic_policy: dict[str, Any],
        token_budget: int,
    ) -> tuple[WorkingMemoryItem, ...]:
        if not bool(read_request.get("include_temporal_neighbors")):
            return tuple(selected)
        if not bool(dynamic_policy.get("allow_temporal_expansion")):
            return tuple(selected)
        max_neighbors = max(0, int(dynamic_policy.get("max_temporal_neighbors") or dynamic_policy.get("max_temporal_expansion_count") or 0))
        if max_neighbors <= 0:
            return tuple(selected)
        base_count = len(selected)
        selected_ids = {item.work_memory_id for item in selected}
        by_id = {item.work_memory_id: item for item in items}
        edges = self.list_temporal_edges(selected[0].task_run_id if selected else "")
        for edge in edges:
            if len(selected) >= base_count + max_neighbors:
                break
            neighbor_id = ""
            if edge.source_item_id in selected_ids:
                neighbor_id = edge.target_item_id
            elif edge.target_item_id in selected_ids:
                neighbor_id = edge.source_item_id
            neighbor = by_id.get(neighbor_id)
            if neighbor is None or neighbor.work_memory_id in selected_ids or neighbor.status != "accepted":
                continue
            item_tokens = count_text_tokens(neighbor.summary or neighbor.title or str(neighbor.payload)[:500])
            if token_budget and item_tokens > token_budget:
                continue
            token_budget = max(0, token_budget - item_tokens)
            selected.append(neighbor)
            selected_ids.add(neighbor.work_memory_id)
        return tuple(selected)


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"WorkingMemoryService requires {key}")
    return value


def _default_semantics(kind: str) -> str:
    if kind in {"failure_reflection", "retry_guidance", "rejected_attempt_summary"}:
        return "reflection"
    if kind in {"evaluator_feedback", "review_note"}:
        return "evaluation"
    if kind in {"conflict_flag", "continuity_conflict"}:
        return "conflict"
    if kind in {"decision_record"}:
        return "decision"
    if kind in {"handoff_context"}:
        return "handoff_note"
    if kind in {"timeline_event_draft"}:
        return "temporal_event"
    if "draft" in kind:
        return "draft_artifact"
    return "working_fact"


def _render_candidate_preview(item: WorkingMemoryItem) -> str:
    lines = []
    title = item.title or item.kind
    if title:
        lines.append(f"### {title}")
    lines.append(
        " / ".join(
            part
            for part in (
                f"kind={item.kind}",
                f"semantics={item.memory_semantics}",
                f"status={item.status}",
                f"node={item.owner_node_id}",
                f"node_run={item.node_run_id}",
            )
            if part
        )
    )
    if item.summary:
        lines.append(item.summary)
    elif item.payload:
        lines.append(str(item.payload)[:500])
    return "\n".join(line for line in lines if line).strip()


def _working_relevance(status: str) -> float:
    if status == "accepted":
        return 0.9
    if status == "proposed":
        return 0.72
    if status == "conflicted":
        return 0.45
    return 0.6


def _working_confidence(item: WorkingMemoryItem) -> float:
    if item.status == "accepted":
        return 0.82
    if item.status == "conflicted":
        return 0.35
    if item.status == "proposed":
        return 0.62
    return 0.5


def _read_denied_reason(
    *,
    read_policy: dict[str, Any],
    dynamic_policy: dict[str, Any],
    read_request: dict[str, Any],
    read_count_so_far: int,
) -> str:
    if read_request.get("dynamic") or read_request.get("dynamic_read"):
        if not bool(dynamic_policy.get("allow_dynamic_read")):
            return "dynamic_read_not_allowed"
        max_reads = int(dynamic_policy.get("max_dynamic_reads_per_node_run") or 0)
        if max_reads and read_count_so_far >= max_reads:
            return "dynamic_read_limit_exceeded"
    readable_scopes = set(_strings(read_policy.get("readable_scopes")))
    requested_scopes = set(_strings(read_request.get("acceptable_scopes")))
    if readable_scopes and requested_scopes and not requested_scopes.issubset(readable_scopes):
        return "requested_scope_outside_policy"
    readable_kinds = set(_strings(read_policy.get("readable_kinds")))
    requested_kinds = set(_strings(read_request.get("requested_kinds") or read_request.get("requested_kind")))
    if readable_kinds and requested_kinds and not requested_kinds.issubset(readable_kinds):
        return "requested_kind_outside_policy"
    readable_semantics = set(_strings(read_policy.get("readable_semantics")))
    requested_semantics = set(_strings(read_request.get("requested_semantics") or read_request.get("requested_semantic")))
    if readable_semantics and requested_semantics and not requested_semantics.issubset(readable_semantics):
        return "requested_semantics_outside_policy"
    if bool(read_request.get("include_temporal_neighbors")) and not bool(dynamic_policy.get("allow_temporal_expansion")):
        return "temporal_expansion_not_allowed"
    if bool(read_request.get("include_temporal_neighbors")):
        max_neighbors = int(dynamic_policy.get("max_temporal_neighbors") or dynamic_policy.get("max_temporal_expansion_count") or 0)
        if max_neighbors <= 0:
            return "temporal_expansion_limit_missing"
    return ""


def _selection_payload(
    selected_items: tuple[WorkingMemoryItem, ...] | list[WorkingMemoryItem],
    excluded_items: tuple[WorkingMemoryItem, ...] | list[WorkingMemoryItem],
    read_log: WorkingMemoryReadLog,
    *,
    denied_reason: str = "",
) -> dict[str, Any]:
    selected_tuple = tuple(selected_items)
    excluded_tuple = tuple(excluded_items)
    required = tuple(item for item in selected_tuple if item.status == "accepted")
    preferred = tuple(item for item in selected_tuple if item.status != "accepted")
    repository_read_edges = _normalized_repository_read_edges(dict(read_log.request or {}).get("repository_read_edges"))
    missing_repository_edges = _missing_repository_read_edges(required, repository_read_edges)
    return {
        "required_items": required,
        "preferred_items": preferred,
        "optional_refs": tuple(item.work_memory_id for item in preferred),
        "excluded_items": excluded_tuple,
        "read_log": read_log,
        "read_log_id": read_log.read_log_id,
        "denied_reason": denied_reason,
        "diagnostics": {
            "selected_count": len(selected_tuple),
            "excluded_count": len(excluded_tuple),
            "token_estimate": read_log.token_estimate,
            "denied_reason": denied_reason,
            "selected_refs": [item.work_memory_id for item in selected_tuple if item.work_memory_id],
            "excluded_refs": [item.work_memory_id for item in excluded_tuple if item.work_memory_id],
            "missing_repository_read_edges": missing_repository_edges,
            "selected_repository_records": [
                preview
                for item in selected_tuple
                for preview in [_formal_memory_preview(item)]
                if preview
            ],
            "selected_item_previews": [
                {
                    "work_memory_id": item.work_memory_id,
                    "owner_node_id": item.owner_node_id,
                    "scope": item.scope,
                    "visibility": item.visibility,
                    "kind": item.kind,
                    "summary": item.summary,
                    "formal_memory": _formal_memory_preview(item),
                }
                for item in selected_tuple[:12]
            ],
        },
    }


def _effective_readable_scopes(*, read_request: dict[str, Any], read_policy: dict[str, Any]) -> set[str]:
    requested = set(_strings(read_request.get("acceptable_scopes")))
    if requested:
        return requested
    policy_scopes = set(_strings(read_policy.get("readable_scopes")))
    if policy_scopes:
        return policy_scopes
    return {"node_scope"}


def _effective_readable_visibilities(*, read_request: dict[str, Any], read_policy: dict[str, Any]) -> set[str]:
    requested = set(_strings(read_request.get("readable_visibilities")))
    if requested:
        return requested
    policy_visibilities = set(_strings(read_policy.get("readable_visibilities")))
    if policy_visibilities:
        return policy_visibilities
    return {"private_to_node", "shared_in_graph"}


def _handoff_visibility_allowed(
    *,
    item: WorkingMemoryItem,
    owner_node_id: str,
    read_request: dict[str, Any],
    read_policy: dict[str, Any],
) -> bool:
    if item.owner_node_id == owner_node_id:
        return True
    allowed_handoff = bool(
        read_request.get("allow_handoff_visibility")
        or read_policy.get("allow_handoff_visibility")
    )
    if not allowed_handoff:
        return False
    authorized_sources = {
        *set(_strings(read_request.get("authorized_source_node_ids"))),
        *set(_strings(read_policy.get("authorized_source_node_ids"))),
        *set(_strings(read_request.get("readable_owner_node_ids"))),
        *set(_strings(read_policy.get("readable_owner_node_ids"))),
    }
    if not authorized_sources:
        return True
    return item.owner_node_id in authorized_sources


def _normalized_repository_read_edges(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    edges: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        selector = dict(raw.get("selector") or {})
        record_kinds = _strings(raw.get("record_keys") or raw.get("record_kinds") or selector.get("record_kinds"))
        repository = str(raw.get("repository") or raw.get("repository_id") or selector.get("repository") or "").strip()
        collection = str(raw.get("collection") or raw.get("collection_id") or selector.get("collection") or "").strip()
        edge = {
            "edge_id": str(raw.get("edge_id") or "").strip(),
            "repository": repository,
            "collection": collection,
            "record_kinds": tuple(record_kinds),
            "status_filter": tuple(_strings(selector.get("status_filter") or raw.get("status_filter"))),
            "selector": selector,
            "version_selector": str(raw.get("version_selector") or selector.get("version_selector") or "").strip(),
            "on_missing": str(raw.get("on_missing") or selector.get("on_missing") or "").strip(),
        }
        if edge["edge_id"] or repository or collection or edge["record_kinds"]:
            edges.append(edge)
    return tuple(edges)


def _item_matches_any_repository_edge(item: WorkingMemoryItem, edges: tuple[dict[str, Any], ...]) -> bool:
    formal = _formal_memory_payload(item)
    if not formal:
        return False
    return any(_item_matches_repository_edge(item, formal, edge) for edge in edges)


def _item_matches_repository_edge(item: WorkingMemoryItem, formal: dict[str, Any], edge: dict[str, Any]) -> bool:
    repository = str(edge.get("repository") or "").strip()
    collection = str(edge.get("collection") or "").strip()
    record_kinds = {str(kind).strip() for kind in tuple(edge.get("record_kinds") or ()) if str(kind).strip()}
    if repository and repository != str(formal.get("repository_id") or formal.get("repository") or "").strip():
        return False
    if collection and collection != str(formal.get("collection_id") or formal.get("collection") or "").strip():
        return False
    item_kind = str(formal.get("record_kind") or item.kind or "").strip()
    formal_kinds = {str(kind).strip() for kind in list(formal.get("record_kinds") or []) if str(kind).strip()}
    if item_kind:
        formal_kinds.add(item_kind)
    if record_kinds and not formal_kinds.intersection(record_kinds):
        return False
    status_filter = {str(status).strip() for status in tuple(edge.get("status_filter") or ()) if str(status).strip()}
    if "committed" in status_filter:
        commit_state = str(formal.get("commit_state") or formal.get("status") or "").strip()
        if commit_state and commit_state != "committed":
            return False
    return True


def _formal_memory_payload(item: WorkingMemoryItem) -> dict[str, Any]:
    metadata = dict(getattr(item, "metadata", {}) or {})
    formal = dict(metadata.get("formal_memory") or metadata.get("memory_record") or {})
    if not formal:
        repository = str(metadata.get("repository") or metadata.get("repository_id") or "").strip()
        collection = str(metadata.get("collection") or metadata.get("collection_id") or "").strip()
        record_kind = str(metadata.get("record_kind") or "").strip()
        if repository or collection or record_kind:
            formal = {
                "repository_id": repository,
                "collection_id": collection,
                "record_kind": record_kind or item.kind,
            }
    return formal


def _formal_memory_preview(item: WorkingMemoryItem) -> dict[str, Any]:
    formal = _formal_memory_payload(item)
    if not formal:
        return {}
    return {
        "work_memory_id": item.work_memory_id,
        "repository_id": str(formal.get("repository_id") or formal.get("repository") or ""),
        "collection_id": str(formal.get("collection_id") or formal.get("collection") or ""),
        "record_kind": str(formal.get("record_kind") or item.kind or ""),
        "record_kinds": [str(kind) for kind in list(formal.get("record_kinds") or []) if str(kind)],
        "commit_state": str(formal.get("commit_state") or formal.get("status") or ""),
        "source_edge_id": str(formal.get("source_edge_id") or ""),
        "version_selector": str(formal.get("version_selector") or ""),
    }


def _missing_repository_read_edges(
    selected_items: tuple[WorkingMemoryItem, ...],
    repository_edges: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for edge in repository_edges:
        if str(edge.get("on_missing") or "") not in {"block", "required", "fail_closed"}:
            continue
        if any(_item_matches_repository_edge(item, _formal_memory_payload(item), edge) for item in selected_items):
            continue
        missing.append(
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "repository": str(edge.get("repository") or ""),
                "collection": str(edge.get("collection") or ""),
                "record_kinds": [str(kind) for kind in tuple(edge.get("record_kinds") or ()) if str(kind)],
                "on_missing": str(edge.get("on_missing") or ""),
            }
        )
    return missing


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values.strip()] if values.strip() else []
    return [str(item).strip() for item in list(values or []) if str(item).strip()]
