from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_repository_models import ArtifactRecord, ArtifactRepository
from .artifact_repository_store import ArtifactRepositoryStore, build_artifact_id, content_hash


class ArtifactRepositoryService:
    def __init__(self, root_dir: str | Path) -> None:
        self.store = ArtifactRepositoryStore(root_dir)

    def resolve_repository_scope(
        self,
        *,
        logical_repository_id: str,
        task_run_id: str = "",
        lifecycle_policy: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        logical_id = str(logical_repository_id or "artifact.repository.default").strip()
        policy = dict(lifecycle_policy or {})
        scope_kind = str(policy.get("scope_kind") or policy.get("scope") or "run_scoped").strip() or "run_scoped"
        if scope_kind not in {"run_scoped", "project_scoped", "durable"}:
            scope_kind = "run_scoped"
        requested_scope_id = str(policy.get("scope_id") or policy.get("project_id") or "").strip()
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

    def record_materialization(
        self,
        *,
        task_run_id: str,
        graph_id: str = "",
        stage_id: str = "",
        node_run_id: str = "",
        task_ref: str = "",
        coordination_run_id: str = "",
        artifact_refs: list[str] | tuple[str, ...] = (),
        artifact_root: str = "",
        created_files: list[str] | tuple[str, ...] = (),
        status: str = "accepted",
        repository_id: str = "artifact.repository.default",
        collection_id: str = "default",
        lifecycle_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self.resolve_repository_scope(
            logical_repository_id=repository_id,
            task_run_id=task_run_id,
            lifecycle_policy=dict(lifecycle_policy or {}),
        )
        self.store.upsert_repository(
            ArtifactRepository(
                repository_id=scope["effective_repository_id"],
                logical_repository_id=repository_id,
                effective_repository_id=scope["effective_repository_id"],
                task_run_id=scope["task_run_id"],
                scope_kind=scope["scope_kind"],
                scope_id=scope["scope_id"],
                graph_id=graph_id,
                node_id=repository_id,
                title=repository_id,
                lifecycle_policy=dict(lifecycle_policy or {}),
            )
        )
        refs = [str(item).strip() for item in list(artifact_refs or []) if str(item).strip()]
        files = [str(item).strip() for item in list(created_files or []) if str(item).strip()]
        records: list[ArtifactRecord] = []
        for index, artifact_ref in enumerate(refs):
            path = artifact_ref.removeprefix("artifact:")
            created_file = files[index] if index < len(files) else path
            record = ArtifactRecord(
                artifact_id=build_artifact_id(scope["effective_repository_id"], collection_id, artifact_ref, node_run_id),
                artifact_ref=artifact_ref,
                path=path,
                repository_id=scope["effective_repository_id"],
                collection_id=collection_id,
                logical_repository_id=repository_id,
                effective_repository_id=scope["effective_repository_id"],
                task_run_id=scope["task_run_id"],
                scope_kind=scope["scope_kind"],
                scope_id=scope["scope_id"],
                graph_id=graph_id,
                stage_id=stage_id,
                node_run_id=node_run_id,
                task_ref=task_ref,
                coordination_run_id=coordination_run_id,
                status=status,
                content_hash=content_hash(artifact_ref),
                metadata={
                    **dict(metadata or {}),
                    "artifact_root": artifact_root,
                    "created_file": created_file,
                },
            )
            records.append(self.store.upsert_artifact(record))
        return {
            "task_run_id": task_run_id,
            "repository_id": repository_id,
            "effective_repository_id": scope["effective_repository_id"],
            "collection_id": collection_id,
            "artifact_count": len(records),
            "artifacts": [item.to_dict() for item in records],
            "authority": "artifact_repository.service",
        }

    def overview(self, *, task_run_id: str = "", repository_id: str = "", collection_id: str = "", status: str = "", limit: int = 500) -> dict[str, Any]:
        repositories = [item.to_dict() for item in self.store.list_repositories(task_run_id=task_run_id)]
        if repository_id:
            repositories = [
                item for item in repositories
                if repository_id in {str(item.get("repository_id") or ""), str(item.get("logical_repository_id") or "")}
            ]
        artifacts = [
            item.to_dict()
            for item in self.store.list_artifacts(
                task_run_id=task_run_id,
                repository_id=repository_id,
                collection_id=collection_id,
                status=status,
                limit=limit,
            )
        ]
        return {
            "task_run_id": task_run_id,
            "repository_id": repository_id,
            "collection_id": collection_id,
            "status": status,
            "repository_count": len(repositories),
            "artifact_count": len(artifacts),
            "repositories": repositories,
            "artifacts": artifacts,
            "authority": "artifact_repository.management_overview",
        }


def _safe_scope_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip()) or "scope"
