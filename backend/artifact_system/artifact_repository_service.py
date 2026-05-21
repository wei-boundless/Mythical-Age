from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_repository_models import ArtifactRecord, ArtifactRepository
from .artifact_repository_store import ArtifactRepositoryStore, build_artifact_id, content_hash, file_content_hash


class ArtifactRepositoryService:
    def __init__(self, root_dir: str | Path, *, workspace_root: str | Path | None = None) -> None:
        self.store = ArtifactRepositoryStore(root_dir)
        self.workspace_root = Path(workspace_root).resolve() if workspace_root is not None else _infer_workspace_root(Path(root_dir))

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
        output_contract_id: str = "",
        producer_node_id: str = "",
        artifact_kind: str = "file",
        content_type: str = "",
        materialization_id: str = "",
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
                node_id=producer_node_id,
                title=f"{repository_id}:{producer_node_id}" if producer_node_id else repository_id,
                lifecycle_policy=dict(lifecycle_policy or {}),
            )
        )
        refs = [str(item).strip() for item in list(artifact_refs or []) if str(item).strip()]
        files = [str(item).strip() for item in list(created_files or []) if str(item).strip()]
        materialization_ref = str(materialization_id or node_run_id or f"{task_run_id}:{stage_id}").strip()
        records: list[ArtifactRecord] = []
        for index, artifact_ref in enumerate(refs):
            path = artifact_ref.removeprefix("artifact:")
            artifact_path = self._resolve_artifact_path(
                artifact_ref=artifact_ref,
                created_file=files[index] if index < len(files) else "",
                artifact_root=artifact_root,
            )
            created_file = files[index] if index < len(files) else (artifact_path.name if artifact_path else path)
            record = ArtifactRecord(
                artifact_id=build_artifact_id(
                    scope["effective_repository_id"],
                    collection_id,
                    output_contract_id,
                    artifact_ref,
                    materialization_ref,
                ),
                artifact_ref=artifact_ref,
                path=path,
                repository_id=scope["effective_repository_id"],
                collection_id=collection_id,
                output_contract_id=output_contract_id,
                artifact_kind=artifact_kind or "file",
                producer_node_id=producer_node_id,
                content_type=content_type or _content_type_for_path(path),
                materialization_id=materialization_ref,
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
                content_hash=self._artifact_content_hash(artifact_ref=artifact_ref, artifact_path=artifact_path),
                metadata={
                    **dict(metadata or {}),
                    "artifact_root": artifact_root,
                    "created_file": created_file,
                    "content_hash_source": "file" if artifact_path and artifact_path.exists() else "artifact_ref",
                },
            )
            records.append(self.store.upsert_artifact(record))
        return {
            "task_run_id": task_run_id,
            "repository_id": repository_id,
            "effective_repository_id": scope["effective_repository_id"],
            "collection_id": collection_id,
            "output_contract_id": output_contract_id,
            "producer_node_id": producer_node_id,
            "materialization_id": materialization_ref,
            "artifact_count": len(records),
            "artifacts": [item.to_dict() for item in records],
            "authority": "artifact_repository.service",
        }

    def latest_refs_by_contract(
        self,
        *,
        output_contract_id: str,
        task_run_id: str = "",
        repository_id: str = "",
        collection_id: str = "",
        status: str = "accepted",
        limit: int = 20,
    ) -> list[str]:
        records = self.store.list_artifacts(
            task_run_id=task_run_id,
            repository_id=repository_id,
            collection_id=collection_id,
            status=status,
            output_contract_id=output_contract_id,
            limit=limit,
        )
        return _dedupe_refs(record.artifact_ref for record in records)

    def overview(
        self,
        *,
        task_run_id: str = "",
        repository_id: str = "",
        collection_id: str = "",
        status: str = "",
        graph_id: str = "",
        stage_id: str = "",
        node_run_id: str = "",
        task_ref: str = "",
        output_contract_id: str = "",
        producer_node_id: str = "",
        artifact_kind: str = "",
        limit: int = 500,
    ) -> dict[str, Any]:
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
                graph_id=graph_id,
                stage_id=stage_id,
                node_run_id=node_run_id,
                task_ref=task_ref,
                output_contract_id=output_contract_id,
                producer_node_id=producer_node_id,
                artifact_kind=artifact_kind,
                limit=limit,
            )
        ]
        return {
            "task_run_id": task_run_id,
            "repository_id": repository_id,
            "collection_id": collection_id,
            "status": status,
            "graph_id": graph_id,
            "stage_id": stage_id,
            "node_run_id": node_run_id,
            "task_ref": task_ref,
            "output_contract_id": output_contract_id,
            "producer_node_id": producer_node_id,
            "artifact_kind": artifact_kind,
            "repository_count": len(repositories),
            "artifact_count": len(artifacts),
            "repositories": repositories,
            "artifacts": artifacts,
            "authority": "artifact_repository.management_overview",
        }

    def _artifact_content_hash(self, *, artifact_ref: str, artifact_path: Path | None) -> str:
        if artifact_path is not None and artifact_path.exists() and artifact_path.is_file():
            return file_content_hash(artifact_path)
        return content_hash(artifact_ref)

    def _resolve_artifact_path(self, *, artifact_ref: str, created_file: str, artifact_root: str) -> Path | None:
        candidates: list[str] = []
        ref_path = str(artifact_ref or "").removeprefix("artifact:").strip()
        if ref_path:
            candidates.append(ref_path)
        clean_created_file = str(created_file or "").strip()
        if clean_created_file:
            candidates.append(clean_created_file)
        clean_root = str(artifact_root or "").strip()
        if clean_root and clean_created_file:
            root_part = clean_root.rstrip("/\\")
            file_part = clean_created_file.lstrip("/\\")
            candidates.append(f"{root_part}/{file_part}")
        for candidate in candidates:
            resolved = _resolve_inside_workspace(self.workspace_root, candidate)
            if resolved is not None and resolved.exists():
                return resolved
        return _resolve_inside_workspace(self.workspace_root, ref_path or clean_created_file)


def _safe_scope_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip()) or "scope"


def _infer_workspace_root(root_dir: Path) -> Path:
    root = Path(root_dir).resolve()
    if root.name == "artifact_repository" and root.parent.name == "storage" and root.parent.parent.exists():
        return root.parent.parent.resolve()
    if root.name == "artifact_repository" and root.parent.exists():
        return root.parent.resolve()
    return root.resolve()


def _resolve_inside_workspace(workspace_root: Path, value: str) -> Path | None:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return None
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / raw.lstrip("/")).resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError:
        return None
    return resolved


def _content_type_for_path(path: str) -> str:
    suffix = Path(str(path or "")).suffix.lower()
    return {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".json": "application/json",
        ".html": "text/html",
        ".htm": "text/html",
        ".css": "text/css",
        ".js": "text/javascript",
        ".ts": "text/typescript",
        ".tsx": "text/typescript",
        ".py": "text/x-python",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream" if suffix else "")


def _dedupe_refs(refs: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in list(refs or []):
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
