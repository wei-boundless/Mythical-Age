from __future__ import annotations

from pathlib import Path
from typing import Any

from token_accounting import count_text_tokens

from .contracts import MemoryContextCandidate
from .task_durable_memory_models import (
    TaskDurableMemoryItem,
    TaskDurableMemoryQuery,
)
from .task_durable_memory_store import (
    TaskDurableMemoryStore,
    build_namespace_id,
    stable_task_memory_id,
)
from .working_memory_models import WorkingMemoryItem


class TaskDurableMemoryService:
    def __init__(self, root_dir: str | Path) -> None:
        self.store = TaskDurableMemoryStore(root_dir)

    def create_item(self, **payload: Any) -> TaskDurableMemoryItem:
        data = dict(payload)
        namespace_id = str(data.get("namespace_id") or "").strip() or self.build_namespace_id(**data)
        if not namespace_id:
            raise ValueError("Task durable memory requires task/domain/graph/project/artifact namespace")
        title = str(data.get("title") or data.get("summary") or data.get("canonical_statement") or "").strip()
        canonical_statement = str(data.get("canonical_statement") or data.get("summary") or title).strip()
        if not canonical_statement:
            raise ValueError("Task durable memory requires canonical_statement or summary")
        item = TaskDurableMemoryItem(
            task_memory_id=str(
                data.get("task_memory_id")
                or stable_task_memory_id(
                    namespace_id,
                    title,
                    canonical_statement,
                    ",".join(_strings(data.get("source_work_memory_ids"))),
                )
            ),
            namespace_id=namespace_id,
            task_family=str(data.get("task_family") or ""),
            domain_id=str(data.get("domain_id") or ""),
            task_id=str(data.get("task_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            project_id=str(data.get("project_id") or ""),
            artifact_namespace=str(data.get("artifact_namespace") or ""),
            source_work_memory_ids=tuple(_strings(data.get("source_work_memory_ids"))),
            source_artifact_refs=tuple(_strings(data.get("source_artifact_refs"))),
            memory_type=str(data.get("memory_type") or "project"),
            memory_class=str(data.get("memory_class") or "work"),
            kind=str(data.get("kind") or "task_memory"),
            memory_semantics=str(data.get("memory_semantics") or "working_fact"),
            title=title or canonical_statement[:120],
            canonical_statement=canonical_statement,
            summary=str(data.get("summary") or canonical_statement).strip(),
            payload=dict(data.get("payload") or {}),
            retrieval_hints=tuple(_strings(data.get("retrieval_hints"))),
            status=str(data.get("status") or "active"),  # type: ignore[arg-type]
            confidence=str(data.get("confidence") or "medium"),
            stability=str(data.get("stability") or "stable"),
            eligible_for_task_injection=bool(data.get("eligible_for_task_injection", True)),
            eligible_for_global_promotion=bool(data.get("eligible_for_global_promotion", False)),
            global_promotion_state=str(data.get("global_promotion_state") or "not_applicable"),  # type: ignore[arg-type]
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_durable_memory.task_asset"),
        )
        return self.store.upsert_item(item)

    def promote_working_memory_item(self, item: WorkingMemoryItem, **payload: Any) -> TaskDurableMemoryItem:
        if item.promotion_state not in {"candidate", "needs_review", "approved"} and item.kind != "promotion_candidate":
            raise ValueError("Working memory item is not eligible for task durable promotion")

        namespace_payload = {
            "task_family": str(payload.get("task_family") or item.metadata.get("task_family") or ""),
            "domain_id": str(payload.get("domain_id") or item.metadata.get("domain_id") or ""),
            "task_id": str(payload.get("task_id") or item.task_id or ""),
            "graph_id": str(payload.get("graph_id") or item.graph_id or ""),
            "project_id": str(payload.get("project_id") or item.metadata.get("project_id") or ""),
            "artifact_namespace": str(payload.get("artifact_namespace") or item.metadata.get("artifact_namespace") or ""),
        }
        namespace_id = str(payload.get("namespace_id") or "").strip() or self.build_namespace_id(**namespace_payload)
        if not namespace_id:
            raise ValueError("Task durable promotion requires task_id, graph_id, project_id, domain_id or artifact_namespace")

        title = str(payload.get("title") or item.title or item.summary or item.work_memory_id).strip()
        canonical_statement = str(
            payload.get("canonical_statement")
            or item.summary
            or item.payload.get("canonical_statement")
            or item.payload.get("text")
            or item.payload.get("content")
            or item.work_memory_id
        ).strip()
        summary = str(payload.get("summary") or item.summary or canonical_statement).strip()
        retrieval_hints = _dedupe_strings(
            [
                *_strings(payload.get("retrieval_hints")),
                namespace_id,
                namespace_payload["task_family"],
                namespace_payload["domain_id"],
                namespace_payload["task_id"],
                namespace_payload["graph_id"],
                namespace_payload["project_id"],
                namespace_payload["artifact_namespace"],
                item.owner_node_id,
                item.writer_agent_id,
                item.kind,
                item.memory_semantics,
                *item.tags,
            ]
        )
        source_refs = {
            "work_memory_id": item.work_memory_id,
            "task_run_id": item.task_run_id,
            "task_id": item.task_id,
            "graph_id": item.graph_id,
            "owner_node_id": item.owner_node_id,
            "node_run_id": item.node_run_id,
            "writer_agent_id": item.writer_agent_id,
            "status": item.status,
            "promotion_state": item.promotion_state,
            "source_event_refs": list(item.source_event_refs),
            "source_message_refs": list(item.source_message_refs),
            "artifact_refs": list(item.artifact_refs),
            "contract_refs": list(item.contract_refs),
        }
        return self.create_item(
            namespace_id=namespace_id,
            **namespace_payload,
            source_work_memory_ids=[item.work_memory_id],
            source_artifact_refs=list(item.artifact_refs),
            memory_type=str(payload.get("memory_type") or "project"),
            memory_class=str(payload.get("memory_class") or "work"),
            kind=str(payload.get("kind") or item.kind or "task_memory"),
            memory_semantics=str(payload.get("memory_semantics") or item.memory_semantics or "working_fact"),
            title=title,
            canonical_statement=canonical_statement,
            summary=summary,
            payload={
                "source_working_memory": item.to_dict(),
                "source_refs": source_refs,
            },
            retrieval_hints=retrieval_hints[:12],
            confidence=str(payload.get("confidence") or "medium"),
            metadata={
                "actor_id": str(payload.get("actor_id") or "memory_governance_ui"),
                "promotion_reason": str(payload.get("reason") or "manual_working_memory_promotion"),
                "promotion_source": "working_memory",
                "promotion_source_refs": source_refs,
            },
        )

    def get_item(self, task_memory_id: str) -> TaskDurableMemoryItem | None:
        return self.store.get_item(task_memory_id)

    def query_items(self, **filters: Any) -> tuple[TaskDurableMemoryItem, ...]:
        return self.store.query_items(TaskDurableMemoryQuery(**filters))

    def list_namespaces(self):
        return self.store.list_namespaces()

    def context_candidates(
        self,
        *,
        namespace_id: str = "",
        task_family: str = "",
        domain_id: str = "",
        task_id: str = "",
        graph_id: str = "",
        project_id: str = "",
        artifact_namespace: str = "",
        requested_kinds: list[str] | tuple[str, ...] = (),
        requested_semantics: list[str] | tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[MemoryContextCandidate, ...]:
        query_namespace = namespace_id or self.build_namespace_id(
            task_family=task_family,
            domain_id=domain_id,
            task_id=task_id,
            graph_id=graph_id,
            project_id=project_id,
            artifact_namespace=artifact_namespace,
        )
        if not query_namespace and not any([task_family, domain_id, task_id, graph_id, project_id, artifact_namespace]):
            return ()
        items = self.query_items(
            namespace_id=query_namespace,
            task_family=task_family,
            domain_id=domain_id,
            task_id=task_id,
            graph_id=graph_id,
            project_id=project_id,
            artifact_namespace=artifact_namespace,
            status="active",
            limit=max(1, min(int(limit or 20), 100)),
        )
        kind_filter = set(_strings(requested_kinds))
        semantics_filter = set(_strings(requested_semantics))
        candidates: list[MemoryContextCandidate] = []
        for item in items:
            if not item.eligible_for_task_injection:
                continue
            if kind_filter and item.kind not in kind_filter:
                continue
            if semantics_filter and item.memory_semantics not in semantics_filter:
                continue
            preview = _render_candidate_preview(item)
            if not preview:
                continue
            candidates.append(
                MemoryContextCandidate(
                    candidate_id=f"memory-context:{item.namespace_id}:task-durable:{item.task_memory_id}",
                    memory_layer="task_durable",
                    source="task_durable_memory.store",
                    content_ref=item.task_memory_id,
                    rendered_preview=preview,
                    relevance=0.82,
                    confidence=_confidence(item.confidence),
                    staleness="task_namespace_scoped",
                    owner_task_id=item.task_id,
                    token_estimate=max(1, count_text_tokens(preview)),
                    budget_class="preferred",
                    can_override_current_turn=False,
                    requires_verification_before_use=item.global_promotion_state in {"candidate", "needs_review"},
                    authority="candidate_only",
                    metadata={
                        "namespace_id": item.namespace_id,
                        "task_family": item.task_family,
                        "domain_id": item.domain_id,
                        "task_id": item.task_id,
                        "graph_id": item.graph_id,
                        "project_id": item.project_id,
                        "artifact_namespace": item.artifact_namespace,
                        "kind": item.kind,
                        "memory_semantics": item.memory_semantics,
                        "source_authority": item.authority,
                        "source_work_memory_ids": list(item.source_work_memory_ids),
                    },
                )
            )
        return tuple(candidates)

    @staticmethod
    def build_namespace_id(**payload: Any) -> str:
        return build_namespace_id(
            task_family=str(payload.get("task_family") or ""),
            domain_id=str(payload.get("domain_id") or ""),
            task_id=str(payload.get("task_id") or ""),
            graph_id=str(payload.get("graph_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            artifact_namespace=str(payload.get("artifact_namespace") or ""),
        )


def _render_candidate_preview(item: TaskDurableMemoryItem) -> str:
    lines = []
    if item.title:
        lines.append(f"### {item.title}")
    lines.append(
        " / ".join(
            part
            for part in (
                f"namespace={item.namespace_id}",
                f"kind={item.kind}",
                f"semantics={item.memory_semantics}",
                f"task={item.task_id}",
                f"graph={item.graph_id}",
            )
            if part
        )
    )
    if item.summary:
        lines.append(item.summary)
    elif item.canonical_statement:
        lines.append(item.canonical_statement)
    return "\n".join(line for line in lines if line).strip()


def _confidence(value: str) -> float:
    normalized = str(value or "").lower()
    if normalized in {"high", "strong"}:
        return 0.86
    if normalized in {"low", "weak"}:
        return 0.42
    return 0.66


def _strings(values: Any) -> list[str]:
    return [str(item).strip() for item in list(values or []) if str(item).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
