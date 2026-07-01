from __future__ import annotations

from pathlib import Path
from typing import Any

from .repository import stable_project_structure_id


REPO_STABLE_REF = "repo://workspace"


def normalize_rel_path(value: str | Path) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    return raw.strip("/")


def folder_ref(path: str | Path) -> str:
    rel = normalize_rel_path(path)
    return f"folder://{rel}" if rel else "folder://."


def file_ref(path: str | Path) -> str:
    return f"file://{normalize_rel_path(path)}"


def py_module_ref(path: str | Path) -> str:
    return f"pyast://{normalize_rel_path(path)}#module"


def py_symbol_ref(path: str | Path, *, kind: str, qualname: str, anchor_id: str = "") -> str:
    rel = normalize_rel_path(path)
    name = str(qualname or "").strip()
    if name:
        return f"pyast://{rel}#{kind}:{name}"
    return f"pyast://{rel}#{kind}:{str(anchor_id or '').strip()}"


def skeleton_node_id(build_id: str, generation: int, stable_ref: str) -> str:
    return stable_project_structure_id("pnsnode", build_id, int(generation or 0), stable_ref)


def skeleton_edge_id(build_id: str, generation: int, edge_kind: str, src_ref: str, dst_ref: str, evidence_key: str = "") -> str:
    return stable_project_structure_id("pnsedge", build_id, int(generation or 0), edge_kind, src_ref, dst_ref, evidence_key)


def skeleton_fact_id(
    build_id: str,
    generation: int,
    source_kind: str,
    subject_ref: str,
    predicate: str,
    object_ref: str = "",
    object_literal: str = "",
    qualifiers: dict[str, Any] | None = None,
) -> str:
    return stable_project_structure_id(
        "pnsfact",
        build_id,
        int(generation or 0),
        source_kind,
        subject_ref,
        predicate,
        object_ref,
        object_literal,
        qualifiers or {},
    )
