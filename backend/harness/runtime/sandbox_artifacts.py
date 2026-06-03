from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from artifact_system.artifact_authority import dedupe_artifact_refs

from .artifact_scope import contract_artifact_paths, normalize_logical_path


def publish_sandbox_artifact_refs(
    *,
    project_root: Path,
    sandbox_policy: dict[str, Any],
    artifact_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or "")).resolve()
    artifact_root = normalize_logical_path(str(sandbox_policy.get("artifact_root") or ""))
    publish_roots = tuple(sandbox_publish_scopes(sandbox_policy))
    verified: list[dict[str, Any]] = []
    for ref in dedupe_artifact_refs(artifact_refs):
        resolved = publish_or_resolve_artifact_ref(
            ref,
            project_root=project_root,
            sandbox_root=sandbox_root,
            artifact_root=artifact_root,
            publish_roots=publish_roots,
        )
        if resolved is None or not resolved.exists() or not resolved.is_file():
            continue
        try:
            logical_path = resolved.relative_to(project_root).as_posix()
        except ValueError:
            logical_path = str(resolved)
        verified.append(
            {
                **dict(ref),
                "path": logical_path,
                "absolute_path": str(resolved),
                "exists": True,
                "size_bytes": resolved.stat().st_size,
                "published": True,
            }
        )
    return dedupe_artifact_refs(verified)


def discover_sandbox_artifact_refs(
    *,
    sandbox_policy: dict[str, Any],
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or "")).resolve()
    if not sandbox_root.exists() or not sandbox_root.is_dir():
        return []
    refs: list[dict[str, Any]] = []
    for root in publish_scan_roots(sandbox_policy):
        scan_root = (sandbox_root / root).resolve()
        if not _is_inside(scan_root, sandbox_root) or not scan_root.exists():
            continue
        candidates = [scan_root] if scan_root.is_file() else [path for path in scan_root.rglob("*") if path.is_file()]
        for path in candidates:
            try:
                logical_path = path.resolve().relative_to(sandbox_root).as_posix()
            except ValueError:
                continue
            if not discovered_artifact_matches_contract(logical_path, contract):
                continue
            refs.append(
                {
                    "path": logical_path,
                    "kind": artifact_kind_for_path(path),
                    "source": "sandbox_closeout_discovery",
                    "absolute_path": str(path.resolve()),
                    "sandbox_path": logical_path,
                }
            )
    return dedupe_artifact_refs(refs)


def publish_scan_roots(sandbox_policy: dict[str, Any]) -> tuple[str, ...]:
    roots = [
        str(sandbox_policy.get("artifact_root") or ""),
        *[str(item or "") for item in sandbox_publish_scopes(sandbox_policy)],
    ]
    return tuple(_dedupe_strings([normalize_logical_path(root) for root in roots]))


def sandbox_publish_scopes(sandbox_policy: dict[str, Any]) -> list[str]:
    explicit = _dedupe_strings([str(item or "") for item in list(sandbox_policy.get("publish_scopes") or [])])
    if explicit:
        return explicit
    return _dedupe_strings([str(sandbox_policy.get("artifact_root") or "")])


def discovered_artifact_matches_contract(logical_path: str, contract: dict[str, Any]) -> bool:
    normalized = normalize_logical_path(logical_path)
    if not normalized:
        return False
    if _is_graph_node_contract(contract):
        return True
    explicit_paths = {normalize_logical_path(item) for item in contract_artifact_paths(contract)}
    return normalized in explicit_paths


def artifact_kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".html", ".htm"}:
        return "html_document"
    if suffix in {".md", ".markdown"}:
        return "markdown_document"
    return "file"


def publish_or_resolve_artifact_ref(
    ref: dict[str, Any],
    *,
    project_root: Path,
    sandbox_root: Path,
    artifact_root: str,
    publish_roots: tuple[str, ...] = (),
) -> Path | None:
    logical_path = normalize_logical_path(str(ref.get("path") or ref.get("published_path") or ref.get("src") or ""))
    sandbox_source = sandbox_artifact_source(ref, sandbox_root=sandbox_root)
    if sandbox_source is not None and sandbox_source.exists() and sandbox_source.is_file():
        if not logical_path or not logical_path_publish_allowed(logical_path, artifact_root, publish_roots):
            return None
        publish_target = (project_root / logical_path).resolve()
        if not _is_inside(publish_target, project_root):
            return None
        publish_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sandbox_source, publish_target)
        return publish_target
    if logical_path:
        project_candidate = (project_root / logical_path).resolve()
        if _is_inside(project_candidate, project_root) and project_candidate.exists() and project_candidate.is_file():
            return project_candidate
    return None


def sandbox_artifact_source(ref: dict[str, Any], *, sandbox_root: Path) -> Path | None:
    for key in ("absolute_path", "sandbox_path"):
        raw = str(ref.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (sandbox_root / raw).resolve()
        if _is_inside(resolved, sandbox_root):
            return resolved
    return None


def logical_path_publish_allowed(logical_path: str, artifact_root: str, publish_roots: tuple[str, ...]) -> bool:
    normalized = normalize_logical_path(logical_path)
    if not normalized:
        return False
    if logical_path_within_artifact_root(normalized, artifact_root):
        return True
    for root in publish_roots:
        clean_root = normalize_logical_path(root)
        if clean_root and (normalized == clean_root or normalized.startswith(f"{clean_root}/")):
            return True
    return False


def logical_path_within_artifact_root(logical_path: str, artifact_root: str) -> bool:
    root = normalize_logical_path(artifact_root)
    path = normalize_logical_path(logical_path)
    if not root or not path:
        return False
    return path == root or path.startswith(f"{root}/")


def _is_graph_node_contract(contract: dict[str, Any]) -> bool:
    if str(dict(contract or {}).get("contract_source") or "") == "graph_node_work_order":
        return True
    origin = dict(dict(contract or {}).get("origin") or {})
    return str(origin.get("origin_kind") or "") == "graph_node_assigned"


def _dedupe_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_logical_path(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
