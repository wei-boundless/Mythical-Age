from __future__ import annotations

from pathlib import Path
from typing import Iterable

from capability_system.capabilities.code_intelligence.python_ast_indexer import (
    ClassCard,
    FileModuleAstIndex,
    FunctionEndpointCard,
    build_python_file_module_ast_index,
)
from capability_system.tools.workspace_file_service import WorkspaceFileService

from ..repository import content_hash, utc_now_iso
from ..skeleton_models import SkeletonFactRecord
from ..skeleton_refs import file_ref, normalize_rel_path, py_module_ref, py_symbol_ref, skeleton_fact_id


EXTRACTOR_ID = "file_management.project_structure.skeleton.deep_ast.python"
EXTRACTOR_VERSION = "v1"


def extract_python_deep_ast_facts(
    *,
    file_service: WorkspaceFileService,
    build_id: str,
    generation: int,
    scope_roots: Iterable[str] = (),
) -> tuple[SkeletonFactRecord, ...]:
    facts: list[SkeletonFactRecord] = []
    for path in _python_files(file_service, scope_roots):
        rel = normalize_rel_path(file_service.relative_path(path))
        source = file_service.read_text(path)
        try:
            ast_index = build_python_file_module_ast_index(file_ref=rel, source=source)
        except SyntaxError as exc:
            facts.append(
                _fact(
                    build_id=build_id,
                    generation=generation,
                    subject_ref=file_ref(rel),
                    predicate="ast_parse_failed",
                    object_literal=str(exc),
                    qualifiers={"path": rel, "error_type": type(exc).__name__},
                    confidence="unresolved",
                )
            )
            continue
        facts.extend(_facts_from_index(build_id=build_id, generation=generation, path=rel, ast_index=ast_index))
    return tuple(facts)


def _python_files(file_service: WorkspaceFileService, scope_roots: Iterable[str]) -> tuple[Path, ...]:
    roots = file_service.safe_roots(tuple(scope_roots), fallback_to_workspace=True)
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix == ".py" and not file_service.is_excluded(root, include_default_search_excludes=True):
                files.append(root)
            continue
        for path in root.rglob("*.py"):
            if path.is_file() and not file_service.is_excluded(path, include_default_search_excludes=True):
                files.append(path)
    return tuple(sorted(dict.fromkeys(files), key=lambda item: file_service.relative_path(item).lower()))


def _facts_from_index(
    *,
    build_id: str,
    generation: int,
    path: str,
    ast_index: FileModuleAstIndex,
) -> tuple[SkeletonFactRecord, ...]:
    file_stable_ref = file_ref(path)
    module_ref = py_module_ref(path)
    facts: list[SkeletonFactRecord] = [
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=module_ref,
            predicate="declares_node",
            object_literal="py_module",
            qualifiers={
                "node_kind": "py_module",
                "display_name": Path(path).name,
                "path": path,
                "layer_kind": "module",
                "hierarchy_path": f"repo/{path}#module",
                "parent_ref": file_stable_ref,
                "anchor_ref": ast_index.module_anchor.anchor_id if ast_index.module_anchor is not None else "",
                "file_hash": ast_index.file_hash,
                "payload": {
                    "line_count": ast_index.line_count,
                    "exports": list(ast_index.exports),
                    "limitations": list(ast_index.limitations),
                },
            },
            anchor_refs=(ast_index.module_anchor.anchor_id,) if ast_index.module_anchor is not None else (),
        ),
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=file_stable_ref,
            predicate="defines",
            object_ref=module_ref,
            qualifiers={"edge_kind": "defines_module"},
        ),
    ]
    class_refs: dict[str, str] = {}
    for item in ast_index.classes:
        symbol_ref = py_symbol_ref(path, kind="class", qualname=item.anchor.qualname, anchor_id=item.anchor.anchor_id)
        class_refs[item.anchor.anchor_id] = symbol_ref
        facts.extend(_class_facts(build_id=build_id, generation=generation, path=path, module_ref=module_ref, item=item, symbol_ref=symbol_ref))
    for item in ast_index.functions:
        parent_ref = class_refs.get(item.anchor.parent_anchor_id, module_ref)
        facts.extend(
            _function_facts(
                build_id=build_id,
                generation=generation,
                path=path,
                module_ref=module_ref,
                parent_ref=parent_ref,
                item=item,
            )
        )
    for item in ast_index.imports:
        imported = item.imported_name or item.module
        facts.append(
            _fact(
                build_id=build_id,
                generation=generation,
                subject_ref=module_ref,
                predicate="imports_text",
                object_literal=imported,
                qualifiers={
                    "edge_kind": "imports_text",
                    "module": item.module,
                    "imported_name": item.imported_name,
                    "local_name": item.local_name,
                    "level": item.level,
                    "path": path,
                    "anchor_ref": item.anchor.anchor_id,
                },
                anchor_refs=(item.anchor.anchor_id,),
                confidence="unresolved",
            )
        )
    for item in ast_index.call_sites:
        caller_ref = ""
        if item.scope_anchor_id:
            caller_ref = _symbol_ref_by_anchor(path, ast_index, item.scope_anchor_id)
        facts.append(
            _fact(
                build_id=build_id,
                generation=generation,
                subject_ref=caller_ref or module_ref,
                predicate="calls_text",
                object_literal=item.callee_text,
                qualifiers={
                    "edge_kind": "calls_text",
                    "caller_qualname": item.caller_qualname,
                    "receiver_text": item.receiver_text,
                    "function_text": item.function_text,
                    "path": path,
                    "anchor_ref": item.anchor.anchor_id,
                    "args_text": list(item.args_text),
                    "kwargs_text": dict(item.kwargs_text),
                },
                anchor_refs=(item.anchor.anchor_id,),
                confidence="unresolved",
            )
        )
    return tuple(facts)


def _class_facts(
    *,
    build_id: str,
    generation: int,
    path: str,
    module_ref: str,
    item: ClassCard,
    symbol_ref: str,
) -> tuple[SkeletonFactRecord, ...]:
    return (
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=symbol_ref,
            predicate="declares_node",
            object_literal="py_class",
            qualifiers={
                "node_kind": "py_class",
                "display_name": item.anchor.qualname or item.anchor.name,
                "path": path,
                "layer_kind": "class",
                "hierarchy_path": f"repo/{path}#class:{item.anchor.qualname}",
                "parent_ref": module_ref,
                "anchor_ref": item.anchor.anchor_id,
                "payload": {
                    "name": item.anchor.name,
                    "qualname": item.anchor.qualname,
                    "bases": list(item.bases),
                    "decorators": list(item.decorators),
                    "docstring": item.docstring[:400],
                    "start_line": item.anchor.start_line,
                    "end_line": item.anchor.end_line,
                },
            },
            anchor_refs=(item.anchor.anchor_id,),
        ),
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=module_ref,
            predicate="defines",
            object_ref=symbol_ref,
            qualifiers={"edge_kind": "defines_class", "path": path, "anchor_ref": item.anchor.anchor_id},
            anchor_refs=(item.anchor.anchor_id,),
        ),
    )


def _function_facts(
    *,
    build_id: str,
    generation: int,
    path: str,
    module_ref: str,
    parent_ref: str,
    item: FunctionEndpointCard,
) -> tuple[SkeletonFactRecord, ...]:
    kind = "py_method" if item.kind in {"method", "async_method"} else "py_function"
    symbol_ref = py_symbol_ref(path, kind=kind, qualname=item.anchor.qualname, anchor_id=item.anchor.anchor_id)
    edge_kind = "defines_method" if kind == "py_method" else "defines_function"
    return (
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=symbol_ref,
            predicate="declares_node",
            object_literal=kind,
            qualifiers={
                "node_kind": kind,
                "display_name": item.anchor.qualname or item.anchor.name,
                "path": path,
                "layer_kind": "function" if kind == "py_function" else "method",
                "hierarchy_path": f"repo/{path}#{kind}:{item.anchor.qualname}",
                "parent_ref": parent_ref or module_ref,
                "anchor_ref": item.anchor.anchor_id,
                "payload": {
                    "name": item.anchor.name,
                    "qualname": item.anchor.qualname,
                    "signature": item.signature,
                    "parameters": [parameter.to_dict() for parameter in item.parameters],
                    "decorators": list(item.decorators),
                    "returns_annotation": item.returns_annotation,
                    "docstring": item.docstring[:400],
                    "start_line": item.anchor.start_line,
                    "end_line": item.anchor.end_line,
                    "call_site_anchor_ids": list(item.call_site_anchor_ids),
                    "return_anchor_ids": list(item.return_anchor_ids),
                    "assignment_anchor_ids": list(item.assignment_anchor_ids),
                },
            },
            anchor_refs=(item.anchor.anchor_id,),
        ),
        _fact(
            build_id=build_id,
            generation=generation,
            subject_ref=parent_ref or module_ref,
            predicate="defines",
            object_ref=symbol_ref,
            qualifiers={"edge_kind": edge_kind, "path": path, "anchor_ref": item.anchor.anchor_id},
            anchor_refs=(item.anchor.anchor_id,),
        ),
    )


def _symbol_ref_by_anchor(path: str, ast_index: FileModuleAstIndex, anchor_id: str) -> str:
    for item in ast_index.classes:
        if item.anchor.anchor_id == anchor_id:
            return py_symbol_ref(path, kind="class", qualname=item.anchor.qualname, anchor_id=anchor_id)
    for item in ast_index.functions:
        if item.anchor.anchor_id == anchor_id:
            kind = "py_method" if item.kind in {"method", "async_method"} else "py_function"
            return py_symbol_ref(path, kind=kind, qualname=item.anchor.qualname, anchor_id=anchor_id)
    if ast_index.module_anchor is not None and ast_index.module_anchor.anchor_id == anchor_id:
        return py_module_ref(path)
    return ""


def _fact(
    *,
    build_id: str,
    generation: int,
    subject_ref: str,
    predicate: str,
    object_ref: str = "",
    object_literal: str = "",
    qualifiers: dict[str, object] | None = None,
    anchor_refs: tuple[str, ...] = (),
    confidence: str = "exact",
) -> SkeletonFactRecord:
    payload = dict(qualifiers or {})
    digest = content_hash({"subject": subject_ref, "predicate": predicate, "object": object_ref, "literal": object_literal, "q": payload})
    return SkeletonFactRecord(
        fact_id=skeleton_fact_id(build_id, generation, "deep_ast", subject_ref, predicate, object_ref, object_literal, payload),
        build_id=build_id,
        generation=generation,
        source_kind="deep_ast",
        subject_ref=subject_ref,
        predicate=predicate,
        object_ref=object_ref,
        object_literal=object_literal,
        qualifiers=payload,
        anchor_refs=anchor_refs,
        source_snapshot_ref=digest,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        content_hash=digest,
        confidence=confidence,  # type: ignore[arg-type]
        created_at=utc_now_iso(),
    )
