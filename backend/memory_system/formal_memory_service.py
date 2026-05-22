from __future__ import annotations

from pathlib import Path
from typing import Any

from .formal_memory_content import (
    formal_memory_content_requirement_from_payloads,
    formal_memory_content_requirement_satisfied,
    formal_memory_content_state,
    formal_memory_content_warnings,
)
from .formal_memory_models import (
    FormalMemoryCollection,
    FormalMemoryRecordVersion,
    FormalMemoryRepository,
    FormalMemoryTransaction,
)
from .formal_memory_store import FormalMemoryStore


class FormalMemoryService:
    def __init__(self, root_dir: str | Path) -> None:
        self.store = FormalMemoryStore(root_dir)
        self._scope_policies_by_logical_repository: dict[str, dict[str, Any]] = {}

    def sync_graph_spec(self, *, graph_id: str = "", graph_spec: dict[str, Any] | None = None, task_run_id: str = "") -> dict[str, Any]:
        return self.sync_graph_spec_for_scope(
            graph_id=graph_id,
            graph_spec=graph_spec,
            task_run_id=task_run_id,
            runtime_scope={},
        )

    def sync_graph_spec_for_scope(
        self,
        *,
        graph_id: str = "",
        graph_spec: dict[str, Any] | None = None,
        task_run_id: str = "",
        runtime_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        graph = dict(graph_spec or {})
        repositories: list[FormalMemoryRepository] = []
        collections: list[FormalMemoryCollection] = []
        scope_context = dict(runtime_scope or {})
        for node in _memory_repository_nodes_from_graph(graph):
            metadata = dict(node.get("metadata") or {})
            repo_config = dict(metadata.get("memory_repository") or {})
            node_id = str(node.get("node_id") or node.get("id") or "").strip()
            repository_id = str(repo_config.get("repository_id") or metadata.get("repository_id") or node_id).strip()
            if not repository_id:
                continue
            lifecycle_policy = _repository_lifecycle_policy(node=node, repo_config=repo_config)
            scope = self.resolve_repository_scope(
                logical_repository_id=repository_id,
                task_run_id=task_run_id,
                lifecycle_policy=lifecycle_policy,
                runtime_scope=scope_context,
            )
            self._scope_policies_by_logical_repository[repository_id] = dict(scope)
            repository = self.store.upsert_repository(
                FormalMemoryRepository(
                    repository_id=scope["effective_repository_id"],
                    logical_repository_id=repository_id,
                    effective_repository_id=scope["effective_repository_id"],
                    task_run_id=scope["task_run_id"],
                    scope_kind=scope["scope_kind"],
                    scope_id=scope["scope_id"],
                    graph_id=str(graph_id or graph.get("graph_ref") or graph.get("graph_id") or ""),
                    node_id=node_id,
                    title=str(repo_config.get("title") or node.get("title") or node.get("label") or repository_id),
                    repository_kind=str(repo_config.get("repository_kind") or "formal_memory"),
                    lifecycle_policy=lifecycle_policy,
                )
            )
            repositories.append(repository)
            raw_collections = repo_config.get("collections") if isinstance(repo_config.get("collections"), list) else metadata.get("collections")
            if not isinstance(raw_collections, list) or not raw_collections:
                raw_collections = [{"collection_id": "default", "title": "default"}]
            for index, raw_collection in enumerate(raw_collections):
                if isinstance(raw_collection, str):
                    collection_payload = {"collection_id": raw_collection, "title": raw_collection}
                elif isinstance(raw_collection, dict):
                    collection_payload = dict(raw_collection)
                else:
                    continue
                collection_id = str(
                    collection_payload.get("collection_id")
                    or collection_payload.get("id")
                    or collection_payload.get("name")
                    or ("default" if index == 0 else f"collection_{index + 1}")
                ).strip()
                if not collection_id:
                    continue
                collection = self.store.upsert_collection(
                    FormalMemoryCollection(
                        repository_id=scope["effective_repository_id"],
                        collection_id=collection_id,
                        logical_repository_id=repository_id,
                        effective_repository_id=scope["effective_repository_id"],
                        task_run_id=scope["task_run_id"],
                        scope_kind=scope["scope_kind"],
                        scope_id=scope["scope_id"],
                        title=str(collection_payload.get("title") or collection_payload.get("label") or collection_id),
                        schema_id=str(collection_payload.get("schema_id") or collection_payload.get("schema_ref") or repo_config.get("schema_id") or "schema.formal_memory_record"),
                        record_kinds=tuple(_strings(collection_payload.get("record_kinds") or collection_payload.get("kinds"))),
                        key_strategy=str(collection_payload.get("key_strategy") or "stable_key"),
                        default_version_selector=str(collection_payload.get("default_version_selector") or "latest_committed_before_clock"),
                        retention_policy={
                            **dict(collection_payload.get("retention_policy") or {}),
                            **(
                                {"content_requirement": dict(collection_payload.get("content_requirement") or {})}
                                if isinstance(collection_payload.get("content_requirement"), dict)
                                else {}
                            ),
                            **(
                                {"snapshot_budget": dict(collection_payload.get("snapshot_budget") or {})}
                                if isinstance(collection_payload.get("snapshot_budget"), dict)
                                else {}
                            ),
                        },
                    )
                )
                collections.append(collection)
        return {
            "repository_count": len(repositories),
            "collection_count": len(collections),
            "task_run_id": task_run_id,
            "repositories": [item.to_dict() for item in repositories],
            "collections": [item.to_dict() for item in collections],
        }

    def resolve_repository_scope(
        self,
        *,
        logical_repository_id: str,
        task_run_id: str = "",
        lifecycle_policy: dict[str, Any] | None = None,
        runtime_scope: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        logical_id = str(logical_repository_id or "").strip()
        policy = dict(lifecycle_policy or self._scope_policies_by_logical_repository.get(logical_id) or {})
        scope_context = dict(runtime_scope or {})
        scope_kind = str(
            policy.get("scope_kind")
            or policy.get("scope")
            or policy.get("lifecycle_scope")
            or "run_scoped"
        ).strip() or "run_scoped"
        if scope_kind not in {"run_scoped", "project_scoped", "durable"}:
            scope_kind = "run_scoped"
        requested_scope_id = str(
            policy.get("scope_id")
            or policy.get("project_id")
            or scope_context.get("scope_id")
            or scope_context.get("project_id")
            or ""
        ).strip()
        if scope_kind == "run_scoped":
            scope_id = task_run_id or requested_scope_id or "unbound_run"
            effective_repository_id = f"run:{_safe_scope_id(scope_id)}:{logical_id}"
        elif scope_kind == "project_scoped":
            scope_id = requested_scope_id or "default_project"
            effective_repository_id = f"project:{_safe_scope_id(scope_id)}:{logical_id}"
        else:
            scope_id = requested_scope_id or "global"
            effective_repository_id = logical_id
        return {
            "logical_repository_id": logical_id,
            "effective_repository_id": effective_repository_id,
            "task_run_id": task_run_id if scope_kind == "run_scoped" else "",
            "scope_kind": scope_kind,
            "scope_id": scope_id,
        }

    def write_candidate_from_edge(
        self,
        *,
        edge: dict[str, Any],
        candidate: dict[str, Any],
        task_run_id: str = "",
        graph_id: str = "",
        node_run_id: str = "",
        source_node_id: str = "",
        source_clock: str = "",
        source_clock_seq: int = 0,
        artifact_refs: list[str] | tuple[str, ...] = (),
        runtime_scope: dict[str, Any] | None = None,
    ) -> tuple[FormalMemoryRecordVersion, FormalMemoryTransaction]:
        logical_repository_id = str(edge.get("repository") or edge.get("repository_id") or "").strip()
        scope = self.resolve_repository_scope(
            logical_repository_id=logical_repository_id,
            task_run_id=task_run_id,
            lifecycle_policy=dict(edge.get("resource_lifecycle_policy") or edge.get("lifecycle_policy") or {}),
            runtime_scope=dict(runtime_scope or {}),
        )
        repository_id = scope["effective_repository_id"]
        collection_id = str(edge.get("collection") or edge.get("collection_id") or "").strip()
        selector = dict(edge.get("selector") or {})
        record_kind = str(
            candidate.get("record_kind")
            or selector.get("record_kind")
            or edge.get("record_kind")
            or _first(edge.get("record_kinds"))
            or candidate.get("kind")
            or "formal_memory_record"
        ).strip()
        record_key = str(
            candidate.get("record_key")
            or selector.get("record_key")
            or edge.get("record_key")
            or record_kind
        ).strip()
        candidate_artifact_refs = _strings(candidate.get("artifact_refs") or artifact_refs)
        payload = dict(candidate.get("payload") or {})
        canonical_text = str(
            candidate.get("canonical_text")
            or payload.get("canonical_text")
            or payload.get("text")
            or payload.get("content")
            or ""
        ).strip()
        summary = str(candidate.get("summary") or canonical_text or candidate.get("title") or "").strip()
        content_requirement = self._content_requirement(
            repository_id=repository_id,
            collection_id=collection_id,
            edge=edge,
            candidate=candidate,
        )
        if not formal_memory_content_requirement_satisfied(
            canonical_text=canonical_text,
            summary=summary,
            artifact_refs=candidate_artifact_refs,
            requirement=content_requirement,
        ):
            raise ValueError(
                "formal memory candidate does not satisfy content requirement: "
                f"repository={repository_id}, collection={collection_id}, record_key={record_key}, "
                f"content_state={formal_memory_content_state(canonical_text=canonical_text, artifact_refs=candidate_artifact_refs)}, "
                f"requirement={content_requirement}"
            )
        idempotency_key = str(
            candidate.get("idempotency_key")
            or f"{task_run_id}:{node_run_id}:{edge.get('edge_id')}:{repository_id}:{collection_id}:{record_key}"
        )
        return self.store.write_candidate(
            repository_id=repository_id,
            collection_id=collection_id,
            record_key=record_key,
            logical_repository_id=logical_repository_id,
            task_run_id=scope["task_run_id"],
            scope_kind=scope["scope_kind"],
            scope_id=scope["scope_id"],
            record_kind=record_kind,
            payload=payload,
            canonical_text=canonical_text,
            summary=summary,
            artifact_refs=candidate_artifact_refs,
            source_node_id=source_node_id,
            source_edge_id=str(edge.get("edge_id") or ""),
            source_node_run_id=node_run_id,
            source_clock=source_clock,
            source_clock_seq=int(source_clock_seq or 0),
            idempotency_key=idempotency_key,
        )

    def commit_from_edge(
        self,
        *,
        edge: dict[str, Any],
        candidate_version_id: str,
        node_run_id: str = "",
        source_clock: str = "",
        source_clock_seq: int = 0,
        verdict: str = "",
        required_verdict: str = "",
        reject_reason: str = "",
    ) -> tuple[FormalMemoryRecordVersion, FormalMemoryTransaction]:
        required = str(required_verdict or edge.get("required_verdict") or "").strip()
        reject = bool(required and verdict and verdict != required)
        current = self.store.get_version(candidate_version_id)
        if current is None:
            raise KeyError(f"Unknown formal memory candidate version: {candidate_version_id}")
        content_requirement = self._content_requirement(
            repository_id=current.repository_id,
            collection_id=current.collection_id,
            edge=edge,
            candidate={"payload": dict(current.payload)},
        )
        if not formal_memory_content_requirement_satisfied(
            canonical_text=current.canonical_text,
            summary=current.summary,
            artifact_refs=list(current.artifact_refs),
            requirement=content_requirement,
        ):
            raise ValueError(
                "formal memory candidate cannot be committed because content requirement is not satisfied: "
                f"repository={current.repository_id}, collection={current.collection_id}, record_key={current.record_key}, "
                f"content_state={formal_memory_content_state(canonical_text=current.canonical_text, artifact_refs=list(current.artifact_refs))}, "
                f"requirement={content_requirement}"
            )
        commit_visibility_policy = dict(edge.get("commit_visibility_policy") or edge.get("visibility_policy") or {})
        visible_after_clock, visible_after_clock_seq = _visible_after_clock(
            source_clock=source_clock,
            source_clock_seq=int(source_clock_seq or 0),
            visible_after=str(commit_visibility_policy.get("visible_after") or "next_clock"),
        )
        return self.store.commit_version(
            candidate_version_id=candidate_version_id,
            edge_id=str(edge.get("edge_id") or ""),
            node_run_id=node_run_id,
            source_clock=source_clock,
            source_clock_seq=int(source_clock_seq or 0),
            visible_after_clock=visible_after_clock,
            visible_after_clock_seq=visible_after_clock_seq,
            idempotency_key=f"{node_run_id}:{edge.get('edge_id')}:{candidate_version_id}:commit",
            reject=reject,
            reject_reason=reject_reason,
        )

    def select_for_node(
        self,
        *,
        read_edges: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        task_run_id: str = "",
        node_run_id: str = "",
        clock: str = "",
        clock_seq: int = 0,
        limit: int = 50,
        runtime_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_run_id = task_run_id or _task_run_id_from_node_run_id(node_run_id)
        scope_context = dict(runtime_scope or {})
        records: list[dict[str, Any]] = []
        read_logs: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        for raw_edge in read_edges:
            edge = dict(raw_edge or {})
            selector = dict(edge.get("selector") or {})
            logical_repository_id = str(edge.get("repository") or edge.get("repository_id") or selector.get("repository") or "").strip()
            scope = self.resolve_repository_scope(
                logical_repository_id=logical_repository_id,
                task_run_id=task_run_id,
                lifecycle_policy=dict(edge.get("resource_lifecycle_policy") or edge.get("lifecycle_policy") or {}),
                runtime_scope=scope_context,
            )
            repository_id = scope["effective_repository_id"]
            collection_id = str(edge.get("collection") or edge.get("collection_id") or selector.get("collection") or "").strip()
            if not logical_repository_id or not collection_id:
                missing.append({"edge_id": str(edge.get("edge_id") or ""), "reason": "missing_repository_or_collection"})
                continue
            versions, read_log = self.store.select_versions(
                repository_id=repository_id,
                collection_id=collection_id,
                logical_repository_id=logical_repository_id,
                task_run_id=scope["task_run_id"],
                scope_kind=scope["scope_kind"],
                scope_id=scope["scope_id"],
                selector=selector,
                version_selector=edge.get("version_selector") or selector.get("version_selector") or "",
                clock=clock,
                clock_seq=int(clock_seq or 0),
                edge_id=str(edge.get("edge_id") or ""),
                node_run_id=node_run_id,
                limit=limit,
            )
            read_logs.append(read_log.to_dict())
            content_requirement = self._content_requirement(
                repository_id=repository_id,
                collection_id=collection_id,
                edge=edge,
            )
            usable_versions: list[FormalMemoryRecordVersion] = []
            rejected_versions: list[dict[str, Any]] = []
            for version in versions:
                if formal_memory_content_requirement_satisfied(
                    canonical_text=version.canonical_text,
                    summary=version.summary,
                    artifact_refs=list(version.artifact_refs),
                    requirement=content_requirement,
                ):
                    usable_versions.append(version)
                    continue
                rejected_versions.append(
                    {
                        "version_id": version.version_id,
                        "record_id": version.record_id,
                        "record_key": version.record_key,
                        "content_state": formal_memory_content_state(
                            canonical_text=version.canonical_text,
                            artifact_refs=list(version.artifact_refs),
                        ),
                        "reason": "content_requirement_not_satisfied",
                    }
                )
            required_missing = str(edge.get("on_missing") or selector.get("on_missing") or "") in {"block", "required", "fail_closed"}
            if not usable_versions and required_missing:
                missing.append(
                    {
                        "edge_id": str(edge.get("edge_id") or ""),
                        "repository": repository_id,
                        "logical_repository_id": logical_repository_id,
                        "collection": collection_id,
                        "selector": selector,
                        "on_missing": str(edge.get("on_missing") or selector.get("on_missing") or ""),
                        "content_requirement": content_requirement,
                        "rejected_versions": rejected_versions,
                        "reason": "no_versions_selected" if not versions else "content_requirement_not_satisfied",
                    }
                )
            for version in usable_versions:
                records.append(
                    _record_payload(
                        version=version,
                        edge=edge,
                        read_log_id=read_log.read_log_id,
                        content_requirement=content_requirement,
                    )
                )
        return {
            "required_records": records,
            "read_logs": read_logs,
            "read_log_ids": [item["read_log_id"] for item in read_logs if item.get("read_log_id")],
            "missing_required_records": missing,
            "diagnostics": {
                "formal_memory_record_count": len(records),
                "formal_memory_read_edge_count": len(list(read_edges or [])),
                "missing_required_records": missing,
            },
            "authority": "formal_memory.service",
        }

    def get_version(self, version_id: str) -> FormalMemoryRecordVersion | None:
        return self.store.get_version(version_id)

    def _content_requirement(
        self,
        *,
        repository_id: str,
        collection_id: str,
        edge: dict[str, Any] | None = None,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        edge_payload = dict(edge or {})
        candidate_payload = dict(candidate or {})
        collection = self.store.get_collection(repository_id, collection_id)
        retention_policy = dict(getattr(collection, "retention_policy", {}) or {})
        return formal_memory_content_requirement_from_payloads(
            edge=edge_payload,
            candidate=candidate_payload,
            collection_requirement=dict(retention_policy.get("content_requirement") or {}),
        )

    def overview(self, *, task_run_id: str = "", repository_id: str = "", collection_id: str = "", limit: int = 500) -> dict[str, Any]:
        repositories = [item.to_dict() for item in self.store.list_repositories()]
        if task_run_id:
            repositories = [item for item in repositories if str(item.get("task_run_id") or "") == task_run_id]
        if repository_id:
            repositories = [
                item for item in repositories
                if repository_id in {str(item.get("repository_id") or ""), str(item.get("logical_repository_id") or "")}
            ]
        collections = [item.to_dict() for item in self.store.list_collections()]
        if task_run_id:
            collections = [item for item in collections if str(item.get("task_run_id") or "") == task_run_id]
        if repository_id:
            collections = [
                item for item in collections
                if repository_id in {str(item.get("repository_id") or ""), str(item.get("logical_repository_id") or "")}
            ]
        if collection_id:
            collections = [item for item in collections if str(item.get("collection_id") or "") == collection_id]
        records = [
            item.to_dict()
            for item in self.store.list_records(
                task_run_id=task_run_id,
                repository_id=repository_id,
                collection_id=collection_id,
                limit=limit,
            )
        ]
        versions = [
            item.to_dict()
            for item in self.store.list_versions(
                task_run_id=task_run_id,
                repository_id=repository_id,
                collection_id=collection_id,
                limit=limit,
            )
        ]
        read_logs = list(self.store.list_read_logs(task_run_id=task_run_id, repository_id=repository_id, limit=limit))
        return {
            "task_run_id": task_run_id,
            "repository_id": repository_id,
            "collection_id": collection_id,
            "repository_count": len(repositories),
            "collection_count": len(collections),
            "record_count": len(records),
            "version_count": len(versions),
            "read_log_count": len(read_logs),
            "repositories": repositories,
            "collections": collections,
            "records": records,
            "versions": versions,
            "read_logs": read_logs,
            "authority": "formal_memory.management_overview",
        }


def _record_payload(
    *,
    version: FormalMemoryRecordVersion,
    edge: dict[str, Any],
    read_log_id: str,
    content_requirement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_refs = list(version.artifact_refs)
    requirement = dict(content_requirement or {})
    return {
        "record_id": version.record_id,
        "version_id": version.version_id,
        "repository_id": version.repository_id,
        "collection_id": version.collection_id,
        "record_key": version.record_key,
        "record_kind": version.record_kind,
        "version": version.version,
        "status": version.status,
        "payload": dict(version.payload),
        "canonical_text": version.canonical_text,
        "summary": version.summary,
        "artifact_refs": artifact_refs,
        "content_state": formal_memory_content_state(canonical_text=version.canonical_text, artifact_refs=artifact_refs),
        "content_requirement": requirement,
        "content_warnings": formal_memory_content_warnings(
            canonical_text=version.canonical_text,
            artifact_refs=artifact_refs,
            requirement=requirement,
        ),
        "source_node_id": version.source_node_id,
        "source_edge_id": version.source_edge_id,
        "source_node_run_id": version.source_node_run_id,
        "source_clock": version.source_clock,
        "source_clock_seq": version.source_clock_seq,
        "visible_after_clock": version.visible_after_clock,
        "visible_after_clock_seq": version.visible_after_clock_seq,
        "content_hash": version.content_hash,
        "read_edge_id": str(edge.get("edge_id") or ""),
        "read_log_id": read_log_id,
        "model_visible_label": str(edge.get("model_visible_label") or version.record_key),
        "usage_instruction": str(edge.get("usage_instruction") or ""),
        "authority": "formal_memory.resolved_record",
    }

def _memory_repository_nodes_from_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes_by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    raw_nodes = [
        *[item for item in list(graph.get("nodes") or []) if isinstance(item, dict)],
        *[item for item in list(graph.get("resource_nodes") or []) if isinstance(item, dict)],
    ]
    for index, raw_node in enumerate(raw_nodes):
        node = dict(raw_node)
        if not _is_memory_repository_node(node):
            continue
        node_id = str(node.get("node_id") or node.get("id") or "").strip()
        node_key = node_id or f"anonymous_memory_repository_{index}"
        if node_key in nodes_by_id:
            existing = nodes_by_id[node_key]
            nodes_by_id[node_key] = {
                **existing,
                **node,
                "metadata": {
                    **dict(existing.get("metadata") or {}),
                    **dict(node.get("metadata") or {}),
                },
            }
            continue
        nodes_by_id[node_key] = node
        ordered_ids.append(node_key)
    return [nodes_by_id[node_id] for node_id in ordered_ids]


def _repository_lifecycle_policy(*, node: dict[str, Any], repo_config: dict[str, Any]) -> dict[str, Any]:
    return dict(
        node.get("resource_lifecycle_policy")
        or node.get("lifecycle_policy")
        or repo_config.get("lifecycle_policy")
        or {}
    )


def _is_memory_repository_node(node: dict[str, Any]) -> bool:
    node_type = str(node.get("node_type") or node.get("resource_type") or "").strip()
    node_id = str(node.get("node_id") or node.get("id") or "").strip()
    work_posture = str(node.get("work_posture") or node.get("role") or "").strip()
    metadata = dict(node.get("metadata") or {})
    has_repository_config = bool(metadata.get("memory_repository") or metadata.get("repository_id") or node.get("repository_id"))
    if node_type == "artifact_repository":
        return False
    return (
        node_type in {
            "memory_repository",
            "working_memory_store",
            "runtime_state_store",
            "thread_ledger",
            "progress_ledger",
            "issue_ledger",
            "memory_resource",
            "memory",
        }
        or (node_type.endswith("repository") and "artifact" not in node_type)
        or (work_posture == "resource" and node_id.startswith("memory."))
        or (has_repository_config and node_id.startswith("memory."))
    )


def _visible_after_clock(*, source_clock: str, source_clock_seq: int, visible_after: str) -> tuple[str, int]:
    mode = str(visible_after or "next_clock").strip()
    if mode in {"same_clock", "same_scope_next_node"}:
        return source_clock, int(source_clock_seq or 0)
    if mode in {"next_clock", "next_iteration"}:
        return f"clock:{int(source_clock_seq or 0) + 1}", int(source_clock_seq or 0) + 1
    if mode == "manual_release":
        return "manual_release", 2**31 - 1
    return source_clock, int(source_clock_seq or 0)


def _first(value: Any) -> str:
    values = _strings(value)
    return values[0] if values else ""


def _strings(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values.strip()] if values.strip() else []
    return [str(item).strip() for item in list(values or []) if str(item).strip()]


def _safe_scope_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip()) or "scope"


def _task_run_id_from_node_run_id(node_run_id: str) -> str:
    value = str(node_run_id or "").strip()
    if value.startswith("taskrun:") and ":" in value:
        return value.rsplit(":", 1)[0]
    return ""
