from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


_PATH_KEYS = ("path", "output_path", "artifact_path", "target_path", "verification_path")


@dataclass(frozen=True, slots=True)
class RuntimeArtifactScope:
    artifact_root: str
    authority: str = "harness.runtime.artifact_scope"

    def to_artifact_policy(self, artifact_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = dict(artifact_policy or {})
        if self.artifact_root:
            policy["artifact_root"] = self.artifact_root
            policy["artifact_root_authority"] = self.authority
        return policy


@dataclass(frozen=True, slots=True)
class CanonicalArtifactContract:
    contract: dict[str, Any]
    normalizations: tuple[dict[str, Any], ...] = ()
    authority: str = "harness.runtime.artifact_scope.contract_normalization"


def runtime_artifact_scope_from_environment(environment_payload: dict[str, Any] | None) -> RuntimeArtifactScope:
    environment = dict(environment_payload or {})
    storage = dict(environment.get("storage_space") or {})
    return RuntimeArtifactScope(artifact_root=_normalize_logical_path(storage.get("artifact_root")))


def canonicalize_task_contract_artifacts(
    contract: dict[str, Any] | None,
    *,
    environment_payload: dict[str, Any] | None = None,
    artifact_root: str = "",
) -> CanonicalArtifactContract:
    original = dict(contract or {})
    root = _normalize_logical_path(artifact_root) or runtime_artifact_scope_from_environment(environment_payload).artifact_root
    if not root:
        return CanonicalArtifactContract(contract=original)

    result = dict(original)
    normalizations: list[dict[str, Any]] = []
    for collection in ("required_artifacts", "required_verifications"):
        normalized_items: list[Any] = []
        changed = False
        for index, raw_item in enumerate(list(original.get(collection) or [])):
            if not isinstance(raw_item, dict):
                normalized_items.append(raw_item)
                continue
            item, item_normalization = _canonicalize_artifact_item(
                dict(raw_item),
                artifact_root=root,
                collection=collection,
                index=index,
            )
            normalized_items.append(item)
            changed = changed or item != raw_item
            if item_normalization:
                normalizations.append(item_normalization)
        if changed or collection in result:
            result[collection] = normalized_items
    return CanonicalArtifactContract(contract=result, normalizations=tuple(normalizations))


def canonicalize_artifact_path(path: str, *, artifact_root: str) -> str:
    root = _normalize_logical_path(artifact_root)
    requested = _normalize_logical_path(path)
    if not root or not requested:
        return requested
    if _is_within_root(requested, root):
        return requested
    suffix = _artifact_suffix(requested)
    return _join_paths(root, suffix)


def contract_artifact_paths(contract: dict[str, Any] | None) -> list[str]:
    paths: list[str] = []
    for collection in ("required_artifacts", "required_verifications"):
        for item in list(dict(contract or {}).get(collection) or []):
            if not isinstance(item, dict):
                continue
            for key in _PATH_KEYS:
                value = _normalize_logical_path(item.get(key))
                if value:
                    paths.append(value)
                    break
    return _dedupe(paths)


def normalize_logical_path(path: Any) -> str:
    return _normalize_logical_path(path)


def _canonicalize_artifact_item(
    item: dict[str, Any],
    *,
    artifact_root: str,
    collection: str,
    index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    requested = ""
    requested_key = ""
    for key in _PATH_KEYS:
        raw_value = str(item.get(key) or "").strip()
        if not raw_value:
            continue
        requested_key = key
        requested = _normalize_logical_path(raw_value)
        if requested:
            requested_key = key
            break
        normalized = dict(item)
        for path_key in _PATH_KEYS:
            normalized.pop(path_key, None)
        return normalized, {
            "collection": collection,
            "index": index,
            "requested_path": raw_value,
            "path": "",
            "path_field": requested_key,
            "artifact_root": artifact_root,
            "status": "invalid_path_removed",
            "authority": "harness.runtime.artifact_scope.contract_normalization",
        }
    if not requested:
        return item, {}

    canonical = canonicalize_artifact_path(requested, artifact_root=artifact_root)
    normalized = dict(item)
    for key in _PATH_KEYS:
        normalized.pop(key, None)
    normalized["path"] = canonical
    if canonical == requested and requested_key == "path":
        return normalized, {}
    return normalized, {
        "collection": collection,
        "index": index,
        "requested_path": requested,
        "path": canonical,
        "path_field": requested_key,
        "artifact_root": artifact_root,
        "authority": "harness.runtime.artifact_scope.contract_normalization",
    }


def _artifact_suffix(path: str) -> str:
    parts = [part for part in PurePosixPath(path).parts if part not in {"", "."}]
    if not parts:
        return ""
    lowered = [part.lower() for part in parts]
    if lowered[0] in {"artifact", "artifacts"}:
        return "/".join(parts[1:])
    for index, part in enumerate(lowered):
        if part in {"artifact", "artifacts"} and index < len(parts) - 1:
            return "/".join(parts[index + 1 :])
    return "/".join(parts)


def _normalize_logical_path(path: Any) -> str:
    normalized = str(path or "").replace("\\", "/").strip().strip("'\"`")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.strip("/")
    if not normalized or normalized == ".":
        return ""
    if "://" in normalized or normalized.startswith(("/", "\\")):
        return ""
    if len(normalized) >= 2 and normalized[1] == ":":
        return ""
    if normalized.startswith("../") or "/../" in f"/{normalized}/":
        return ""
    return normalized


def _join_paths(root: str, suffix: str) -> str:
    clean_root = _normalize_logical_path(root)
    clean_suffix = _normalize_logical_path(suffix)
    if not clean_root:
        return clean_suffix
    if not clean_suffix:
        return clean_root
    return f"{clean_root}/{clean_suffix}"


def _is_within_root(path: str, root: str) -> bool:
    clean_path = _normalize_logical_path(path)
    clean_root = _normalize_logical_path(root)
    return bool(clean_root) and (clean_path == clean_root or clean_path.startswith(f"{clean_root}/"))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_logical_path(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
