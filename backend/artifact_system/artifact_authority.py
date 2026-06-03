from __future__ import annotations

import json
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
    return artifact_refs_from_tool_result_payload(source)


def artifact_refs_from_events(events: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in list(events or []):
        refs.extend(artifact_refs_from_event_payload(_event_payload(event)))
    return dedupe_artifact_refs(refs)


def artifact_refs_from_tool_result_payload(tool_result: dict[str, Any]) -> list[dict[str, Any]]:
    item = _dict_payload(tool_result)
    envelope = _dict_payload(item.get("result_envelope") or item.get("envelope"))
    raw_text = (
        envelope.get("text")
        or item.get("text")
        or item.get("result")
        or item.get("content")
        or item.get("summary")
        or ""
    )
    parsed_text = _parse_json_object(raw_text)
    parsed_tool_result = _dict_payload(parsed_text.get("tool_result"))
    parsed_structured_payload = _dict_payload(parsed_text.get("structured_payload"))
    structured = _merge_dicts(parsed_structured_payload, envelope.get("structured_payload"), item.get("structured_payload"))
    nested_tool_result = _merge_dicts(parsed_tool_result, structured.get("tool_result"))

    refs: list[Any] = []
    for source in (item, envelope, structured, nested_tool_result, parsed_text):
        refs.extend(list(_dict_payload(source).get("artifact_refs") or []))
    refs.extend(_artifact_refs_from_image_payload(parsed_text, structured, nested_tool_result))
    return dedupe_artifact_refs([normalize_artifact_ref(ref) for ref in refs])


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


def model_visible_artifact_refs(refs: Any, *, limit: int | None = None, summary_limit: int = 240) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in dedupe_artifact_refs([normalize_artifact_ref(item) for item in list(refs or [])]):
        path = _logical_artifact_path(ref)
        if not path:
            path = str(ref.get("sandbox_path") or "").replace("\\", "/").strip().strip("/")
        absolute_path = str(ref.get("absolute_path") or "").strip()
        if not path and absolute_path and not _is_runtime_sandbox_path(absolute_path):
            path = absolute_path
        payload = _drop_empty(
            {
                "path": path,
                "artifact_ref": str(ref.get("artifact_ref") or "") if ref.get("artifact_ref") and ref.get("artifact_ref") != path else "",
                "kind": str(ref.get("kind") or ""),
                "source": str(ref.get("source") or ""),
                "title": str(ref.get("title") or ref.get("label") or ""),
                "summary": _compact_text(ref.get("summary") or "", limit=summary_limit),
                "mime_type": str(ref.get("mime_type") or ""),
                "exists": ref.get("exists") if isinstance(ref.get("exists"), bool) else None,
                "size_bytes": ref.get("size_bytes") if isinstance(ref.get("size_bytes"), int) else None,
                "published": ref.get("published") if isinstance(ref.get("published"), bool) else None,
            }
        )
        key = str(payload.get("path") or payload.get("artifact_ref") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(payload)
        if limit is not None and len(result) >= limit:
            break
    return result


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


def artifact_ref_value(ref: Any) -> str:
    payload = normalize_artifact_ref(ref)
    logical_path = _logical_artifact_path(payload)
    if logical_path:
        return logical_path
    return str(payload.get("absolute_path") or "").replace("\\", "/").strip()


def artifact_materialization_ref(ref: Any) -> str:
    payload = normalize_artifact_ref(ref)
    explicit_ref = str(payload.get("artifact_ref") or "").strip()
    if explicit_ref:
        return explicit_ref
    return artifact_ref_value(payload)


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


def _artifact_refs_from_image_payload(*sources: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for source in sources:
        payload = _dict_payload(source)
        image = _dict_payload(payload.get("image"))
        path = str(image.get("file_path") or image.get("src") or image.get("path") or "").strip()
        if not path:
            continue
        refs.append(
            _drop_empty(
                {
                    "path": path,
                    "kind": str(image.get("kind") or "image"),
                    "source": str(image.get("source") or payload.get("tool_name") or "image_generate"),
                    "mime_type": str(image.get("mime_type") or ""),
                    "summary": str(image.get("summary") or ""),
                }
            )
        )
    return refs


def _dict_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text[0] not in "{[":
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _merge_dicts(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return _drop_empty(merged)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _is_runtime_sandbox_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return "/storage/runtime_state/sandboxes/" in normalized or normalized.startswith("storage/runtime_state/sandboxes/")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
