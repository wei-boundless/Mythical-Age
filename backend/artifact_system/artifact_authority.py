from __future__ import annotations

from pathlib import Path
from typing import Any


class ArtifactAuthority:
    """Authoritative task artifact projection.

    This service normalizes runtime artifact candidates, merges repository
    records, and resolves file existence. It does not schedule graph work or
    decide task completion.
    """

    def __init__(self, *, workspace_root: str | Path, artifact_repository: Any | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.artifact_repository = artifact_repository

    def task_artifact_view(
        self,
        *,
        task_run_id: str,
        candidate_refs: list[Any] | tuple[Any, ...] = (),
        repository_id: str = "",
        collection_id: str = "",
        status: str = "",
        limit: int = 500,
    ) -> dict[str, Any]:
        repository_records = self._repository_records(
            task_run_id=task_run_id,
            repository_id=repository_id,
            collection_id=collection_id,
            status=status,
            limit=limit,
        )
        refs = self._candidate_refs(candidate_refs, repository_records=repository_records)
        artifacts = self.resolve_existing_artifacts(refs)
        return {
            "task_run_id": task_run_id,
            "artifact_count": len(artifacts),
            "artifact_refs": artifacts,
            "created_files": [item["path"] for item in artifacts],
            "repository_record_count": len(repository_records),
            "authority": "artifact_system.artifact_authority",
        }

    def resolve_existing_artifacts(self, refs: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in refs:
            payload = normalize_artifact_ref(ref)
            logical_path = _logical_artifact_path(payload)
            absolute_path = str(payload.get("absolute_path") or "").strip()
            if not logical_path and not absolute_path:
                continue
            resolved = self._resolve_preferred_path(logical_path=logical_path, absolute_path=absolute_path)
            if resolved is None or not resolved.exists() or not resolved.is_file():
                continue
            rel = resolved.relative_to(self.workspace_root).as_posix()
            key = logical_path or rel
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    **payload,
                    "path": rel,
                    "absolute_path": str(resolved),
                    "exists": True,
                    "size_bytes": resolved.stat().st_size,
                }
            )
        return result

    def _repository_records(
        self,
        *,
        task_run_id: str,
        repository_id: str,
        collection_id: str,
        status: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        service = self.artifact_repository
        if service is None or not hasattr(service, "overview"):
            return []
        try:
            overview = service.overview(
                task_run_id=task_run_id,
                repository_id=repository_id,
                collection_id=collection_id,
                status=status,
                limit=limit,
            )
        except Exception:
            return []
        return [dict(item) for item in list(dict(overview or {}).get("artifacts") or []) if isinstance(item, dict)]

    def _candidate_refs(self, candidate_refs: Any, *, repository_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        refs = [normalize_artifact_ref(item) for item in list(candidate_refs or [])]
        refs.extend(_artifact_ref_from_repository_record(record) for record in repository_records)
        return dedupe_artifact_refs(refs)

    def _resolve_preferred_path(self, *, logical_path: str, absolute_path: str) -> Path | None:
        if logical_path:
            candidate = (self.workspace_root / logical_path.lstrip("/")).resolve()
            if _inside(candidate, self.workspace_root) and candidate.exists() and candidate.is_file():
                return candidate
        if absolute_path:
            candidate = Path(absolute_path)
            resolved = candidate.resolve() if candidate.is_absolute() else (self.workspace_root / absolute_path).resolve()
            if _inside(resolved, self.workspace_root):
                return resolved
        if logical_path:
            fallback = (self.workspace_root / logical_path.lstrip("/")).resolve()
            if _inside(fallback, self.workspace_root):
                return fallback
        return None


def artifact_refs_from_event_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    observation = dict(dict(payload or {}).get("observation") or {})
    source = dict(observation.get("payload") or payload or {})
    envelope = dict(source.get("result_envelope") or {})
    structured = dict(source.get("structured_payload") or envelope.get("structured_payload") or {})
    return dedupe_artifact_refs(
        [
            *[normalize_artifact_ref(item) for item in list(source.get("artifact_refs") or [])],
            *[normalize_artifact_ref(item) for item in list(envelope.get("artifact_refs") or [])],
            *[normalize_artifact_ref(item) for item in list(structured.get("artifact_refs") or [])],
        ]
    )


def artifact_refs_from_events(events: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in list(events or []):
        refs.extend(artifact_refs_from_event_payload(_event_payload(event)))
    return dedupe_artifact_refs(refs)


def normalize_artifact_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
    else:
        payload = {"path": str(value or "")}
    ref_value = str(payload.get("artifact_ref") or "").strip()
    path = _logical_artifact_path(payload)
    if not path and ref_value:
        path = ref_value.removeprefix("artifact:").strip()
    if path:
        payload["path"] = path
    if ref_value:
        payload["artifact_ref"] = ref_value
    return {key: item for key, item in payload.items() if item not in ("", None, [], {})}


def dedupe_artifact_refs(refs: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for ref in refs:
        payload = normalize_artifact_ref(ref)
        key = _logical_artifact_path(payload) or str(payload.get("absolute_path") or "") or repr(sorted(payload.items()))
        if not key:
            continue
        if key in index_by_key:
            current = dict(result[index_by_key[key]])
            for field, value in payload.items():
                if field not in current or current[field] in ("", None, [], {}):
                    current[field] = value
                elif field.startswith("repository_") or field in {"content_hash", "collection_id"}:
                    current[field] = value
            result[index_by_key[key]] = current
            continue
        index_by_key[key] = len(result)
        result.append(payload)
    return result


def _artifact_ref_from_repository_record(record: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = str(record.get("artifact_ref") or "").strip()
    path = str(record.get("path") or artifact_ref.removeprefix("artifact:")).strip()
    return {
        "path": path,
        "artifact_ref": artifact_ref,
        "repository_id": str(record.get("repository_id") or ""),
        "logical_repository_id": str(record.get("logical_repository_id") or ""),
        "collection_id": str(record.get("collection_id") or ""),
        "repository_status": str(record.get("status") or ""),
        "content_hash": str(record.get("content_hash") or ""),
        "source": "artifact_repository",
    }


def _logical_artifact_path(payload: dict[str, Any]) -> str:
    return str(
        payload.get("path")
        or payload.get("published_path")
        or payload.get("src")
        or payload.get("artifact_path")
        or ""
    ).replace("\\", "/").strip().strip("/")


def _event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "payload"):
        payload = getattr(event, "payload", None)
    elif isinstance(event, dict):
        payload = event.get("payload")
    else:
        payload = None
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
