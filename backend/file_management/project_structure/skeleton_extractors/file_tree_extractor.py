from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from capability_system.tools.workspace_file_service import WorkspaceFileService

from ..repository import content_hash, utc_now_iso
from ..skeleton_models import SkeletonFactRecord
from ..skeleton_refs import REPO_STABLE_REF, file_ref, folder_ref, normalize_rel_path, skeleton_fact_id


EXTRACTOR_ID = "file_management.project_structure.skeleton.file_tree"
EXTRACTOR_VERSION = "v1"


def extract_file_tree_facts(
    *,
    file_service: WorkspaceFileService,
    build_id: str,
    generation: int,
    scope_roots: Iterable[str] = (),
) -> tuple[SkeletonFactRecord, ...]:
    roots = file_service.safe_roots(tuple(scope_roots), fallback_to_workspace=True)
    facts: list[SkeletonFactRecord] = [
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=REPO_STABLE_REF,
            predicate="declares_node",
            object_literal="repo",
            qualifiers={
                "node_kind": "repo",
                "display_name": file_service.workspace_root.name,
                "layer_kind": "repository",
                "hierarchy_path": "repo",
                "path": "",
            },
        )
    ]
    seen_nodes: set[str] = {REPO_STABLE_REF}
    seen_edges: set[tuple[str, str, str]] = set()
    for root in roots:
        _walk_root(
            file_service=file_service,
            build_id=build_id,
            generation=generation,
            root=root,
            facts=facts,
            seen_nodes=seen_nodes,
            seen_edges=seen_edges,
        )
    return tuple(facts)


def _walk_root(
    *,
    file_service: WorkspaceFileService,
    build_id: str,
    generation: int,
    root: Path,
    facts: list[SkeletonFactRecord],
    seen_nodes: set[str],
    seen_edges: set[tuple[str, str, str]],
) -> None:
    if root.is_file():
        _record_file(
            file_service=file_service,
            build_id=build_id,
            generation=generation,
            path=root,
            facts=facts,
            seen_nodes=seen_nodes,
            seen_edges=seen_edges,
        )
        return
    _record_folder(
        file_service=file_service,
        build_id=build_id,
        generation=generation,
        path=root,
        facts=facts,
        seen_nodes=seen_nodes,
        seen_edges=seen_edges,
    )
    for item in sorted(root.rglob("*"), key=lambda candidate: file_service.relative_path(candidate).lower()):
        if file_service.is_excluded(item, include_default_search_excludes=True):
            continue
        if item.is_dir():
            _record_folder(
                file_service=file_service,
                build_id=build_id,
                generation=generation,
                path=item,
                facts=facts,
                seen_nodes=seen_nodes,
                seen_edges=seen_edges,
            )
        elif item.is_file():
            _record_file(
                file_service=file_service,
                build_id=build_id,
                generation=generation,
                path=item,
                facts=facts,
                seen_nodes=seen_nodes,
                seen_edges=seen_edges,
            )


def _record_folder(
    *,
    file_service: WorkspaceFileService,
    build_id: str,
    generation: int,
    path: Path,
    facts: list[SkeletonFactRecord],
    seen_nodes: set[str],
    seen_edges: set[tuple[str, str, str]],
) -> None:
    rel = normalize_rel_path(file_service.relative_path(path))
    stable_ref = folder_ref(rel)
    parent_ref = _parent_ref(rel)
    if stable_ref not in seen_nodes:
        seen_nodes.add(stable_ref)
        facts.append(
            _fact(
                build_id=build_id,
                generation=generation,
                subject_ref=stable_ref,
                predicate="declares_node",
                object_literal="folder",
                qualifiers={
                    "node_kind": "folder",
                    "display_name": path.name or rel or ".",
                    "path": rel,
                    "layer_kind": "folder",
                    "hierarchy_path": f"repo/{rel}" if rel else "repo/.",
                    "parent_ref": parent_ref,
                },
            )
        )
    _record_edge(
        build_id=build_id,
        generation=generation,
        facts=facts,
        seen_edges=seen_edges,
        subject_ref=parent_ref,
        predicate="contains",
        object_ref=stable_ref,
        qualifiers={"edge_kind": "contains_folder"},
    )


def _record_file(
    *,
    file_service: WorkspaceFileService,
    build_id: str,
    generation: int,
    path: Path,
    facts: list[SkeletonFactRecord],
    seen_nodes: set[str],
    seen_edges: set[tuple[str, str, str]],
) -> None:
    rel = normalize_rel_path(file_service.relative_path(path))
    stable_ref = file_ref(rel)
    parent_ref = _parent_ref(rel)
    if stable_ref not in seen_nodes:
        seen_nodes.add(stable_ref)
        stat = path.stat()
        file_hash = _file_hash(path)
        facts.append(
            _fact(
                build_id=build_id,
                generation=generation,
                subject_ref=stable_ref,
                predicate="declares_node",
                object_literal="file",
                qualifiers={
                    "node_kind": "file",
                    "display_name": path.name,
                    "path": rel,
                    "layer_kind": "file",
                    "hierarchy_path": f"repo/{rel}",
                    "parent_ref": parent_ref,
                    "file_hash": file_hash,
                    "payload": {
                        "suffix": path.suffix.lower(),
                        "size_bytes": stat.st_size,
                    },
                },
            )
        )
    _record_edge(
        build_id=build_id,
        generation=generation,
        facts=facts,
        seen_edges=seen_edges,
        subject_ref=parent_ref,
        predicate="contains",
        object_ref=stable_ref,
        qualifiers={"edge_kind": "contains_file"},
    )


def _parent_ref(rel_path: str) -> str:
    rel = normalize_rel_path(rel_path)
    if not rel:
        return REPO_STABLE_REF
    parent = normalize_rel_path(Path(rel).parent.as_posix())
    if parent in {"", "."}:
        return REPO_STABLE_REF
    return folder_ref(parent)


def _record_edge(
    *,
    build_id: str,
    generation: int,
    facts: list[SkeletonFactRecord],
    seen_edges: set[tuple[str, str, str]],
    subject_ref: str,
    predicate: str,
    object_ref: str,
    qualifiers: dict[str, object] | None = None,
) -> None:
    key = (subject_ref, predicate, object_ref)
    if key in seen_edges:
        return
    seen_edges.add(key)
    facts.append(
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=subject_ref,
            predicate=predicate,
            object_ref=object_ref,
            qualifiers=dict(qualifiers or {}),
        )
    )


def _fact(
    *,
    build_id: str,
    generation: int,
    subject_ref: str,
    predicate: str,
    object_ref: str = "",
    object_literal: str = "",
    qualifiers: dict[str, object] | None = None,
) -> SkeletonFactRecord:
    payload = dict(qualifiers or {})
    return SkeletonFactRecord(
        fact_id=skeleton_fact_id(build_id, generation, "file_tree", subject_ref, predicate, object_ref, object_literal, payload),
        build_id=build_id,
        generation=generation,
        source_kind="file_tree",
        subject_ref=subject_ref,
        predicate=predicate,
        object_ref=object_ref,
        object_literal=object_literal,
        qualifiers=payload,
        source_snapshot_ref=content_hash({"subject": subject_ref, "predicate": predicate, "object": object_ref, "literal": object_literal, "q": payload}),
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        content_hash=content_hash({"subject": subject_ref, "predicate": predicate, "object": object_ref, "literal": object_literal, "q": payload}),
        confidence="exact",
        created_at=utc_now_iso(),
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
