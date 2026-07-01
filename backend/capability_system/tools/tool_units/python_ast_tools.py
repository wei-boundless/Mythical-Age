from __future__ import annotations

import ast
import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Type

from capability_system.capabilities.code_intelligence import FileModuleAstIndex, build_python_file_module_ast_index
from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.tools.workspace_file_service import WorkspaceFileService


class PythonAstToolResult(dict):
    def __str__(self) -> str:
        return str(self.get("text") or "")


@dataclass(frozen=True, slots=True)
class PythonSymbol:
    name: str
    kind: str
    path: str
    lineno: int
    col_offset: int
    end_lineno: int
    parent: str = ""

    @property
    def qualname(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name


class PythonCodeOutlineInput(BaseModel):
    path: str = Field(..., description="Python file path relative to the project root")
    max_symbols: int = Field(default=80, ge=1, le=300, description="Maximum symbols returned")


class PythonParseCheckInput(BaseModel):
    path: str = Field(..., description="Python file path relative to the project root")


class PythonSymbolSearchInput(BaseModel):
    query: str = Field(..., description="Symbol name or partial name to search for")
    roots: list[str] = Field(default_factory=list, description="Optional workspace roots to scan")
    max_results: int = Field(default=40, ge=1, le=200, description="Maximum matching symbols returned")


class PythonCodeOutlineTool(BaseTool):
    name: str = "python_code_outline"
    description: str = (
        "Use Python's official ast standard library to summarize a Python file's classes, functions, "
        "methods, imports, and top-level assignments without reading the whole file."
    )
    args_schema: Type[BaseModel] = PythonCodeOutlineInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, path: str, max_symbols: int = 80, run_manager: CallbackManagerForToolRun | None = None) -> dict[str, Any]:
        _ = run_manager
        file_path, error = _resolve_python_file(self._files, path)
        if error:
            return _tool_result(error, ok=False, kind="python_code_outline")
        index, parse_error = _build_python_index(self._files, file_path)
        if parse_error:
            return _tool_result(parse_error, ok=False, kind="python_code_outline", path=self._files.relative_path(file_path))
        assert index is not None
        symbols = _symbols_from_index(index, include_local_assignments=False)
        limit = max(1, min(int(max_symbols or 80), 300))
        payload = {
            "kind": "python_code_outline",
            "path": self._files.relative_path(file_path),
            "source_authority": "capability_system.capabilities.code_intelligence.python_ast_indexer",
            "symbol_count": len(symbols),
            "symbols": [asdict(symbol) | {"qualname": symbol.qualname} for symbol in symbols[:limit]],
            "file_module_ast_index": index.to_dict(),
            "truncated": len(symbols) > limit,
        }
        return _tool_result(_format_outline(payload), ok=True, kind="python_code_outline", path=payload["path"], payload=payload)

    async def _arun(self, path: str, max_symbols: int = 80, run_manager: AsyncCallbackManagerForToolRun | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._run, path, max_symbols, None)


class PythonParseCheckTool(BaseTool):
    name: str = "python_parse_check"
    description: str = "Use Python's official ast standard library to verify that a Python file parses successfully."
    args_schema: Type[BaseModel] = PythonParseCheckInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, path: str, run_manager: CallbackManagerForToolRun | None = None) -> dict[str, Any]:
        _ = run_manager
        file_path, error = _resolve_python_file(self._files, path)
        if error:
            return _tool_result(error, ok=False, kind="python_parse_check")
        _tree, parse_error = _parse_python(self._files, file_path)
        rel = self._files.relative_path(file_path)
        if parse_error:
            return _tool_result(parse_error, ok=False, kind="python_parse_check", path=rel)
        payload = {"kind": "python_parse_check", "path": rel, "valid": True}
        return _tool_result(f"OK: Python syntax is valid for {rel}", ok=True, kind="python_parse_check", path=rel, payload=payload)

    async def _arun(self, path: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._run, path, None)


class PythonSymbolSearchTool(BaseTool):
    name: str = "python_symbol_search"
    description: str = (
        "Use Python's official ast standard library to search Python classes, functions, methods, imports, "
        "and top-level assignments across workspace Python files."
    )
    args_schema: Type[BaseModel] = PythonSymbolSearchInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        query: str,
        roots: list[str] | None = None,
        max_results: int = 40,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        _ = run_manager
        normalized = str(query or "").strip().lower()
        if not normalized:
            return _tool_result("Python symbol search failed: query is required.", ok=False, kind="python_symbol_search")
        limit = max(1, min(int(max_results or 40), 200))
        matches: list[PythonSymbol] = []
        for file_path in _iter_python_files(self._files, roots):
            index, parse_error = _build_python_index(self._files, file_path)
            if parse_error:
                continue
            assert index is not None
            for symbol in _symbols_from_index(index, include_local_assignments=False):
                if _symbol_matches(normalized, symbol):
                    matches.append(symbol)
        ranked = sorted(matches, key=lambda symbol: _symbol_match_key(normalized, symbol))
        return _symbol_search_result(query, ranked[:limit], truncated=len(ranked) > limit)

    async def _arun(
        self,
        query: str,
        roots: list[str] | None = None,
        max_results: int = 40,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._run, query, roots, max_results, None)


def _resolve_python_file(files: WorkspaceFileService, path: str) -> tuple[Path | None, str]:
    try:
        file_path = files.resolve(path, require_path=True)
    except ValueError as exc:
        return None, f"Python AST failed: {exc}"
    if not file_path.exists():
        return None, "Python AST failed: file does not exist."
    if file_path.is_dir():
        return None, "Python AST failed: path is a directory."
    if file_path.suffix.lower() != ".py":
        return None, "Python AST failed: supported files must use the .py suffix."
    return file_path, ""


def _parse_python(files: WorkspaceFileService, file_path: Path) -> tuple[ast.AST | None, str]:
    try:
        source = files.read_text(file_path)
        return ast.parse(source, filename=files.relative_path(file_path), type_comments=True), ""
    except SyntaxError as exc:
        location = f"{exc.filename}:{exc.lineno}:{exc.offset}" if exc.lineno else str(exc.filename or files.relative_path(file_path))
        return None, f"Python syntax error at {location}: {exc.msg}"
    except Exception as exc:
        return None, f"Python AST failed: {exc}"


def _build_python_index(files: WorkspaceFileService, file_path: Path) -> tuple[FileModuleAstIndex | None, str]:
    rel = files.relative_path(file_path)
    try:
        source = files.read_text(file_path)
        return build_python_file_module_ast_index(file_ref=rel, source=source), ""
    except SyntaxError as exc:
        location = f"{exc.filename}:{exc.lineno}:{exc.offset}" if exc.lineno else str(exc.filename or rel)
        return None, f"Python syntax error at {location}: {exc.msg}"
    except Exception as exc:
        return None, f"Python AST failed: {exc}"


def _symbols_from_index(index: FileModuleAstIndex, *, include_local_assignments: bool) -> list[PythonSymbol]:
    path = str(index.file_ref or "")
    symbols: list[PythonSymbol] = []
    for item in index.classes:
        symbols.append(_symbol_from_anchor(item.anchor.name, "class", path=path, anchor=item.anchor))
    for item in index.functions:
        symbols.append(_symbol_from_anchor(item.anchor.name, item.kind, path=path, anchor=item.anchor))
    for item in index.imports:
        symbols.append(_symbol_from_anchor(_import_symbol_name(item), "import", path=path, anchor=item.anchor))
    for item in index.assignments:
        if not include_local_assignments and item.scope_anchor_id:
            continue
        for target in item.target_texts:
            symbols.append(_symbol_from_anchor(target, "variable", path=path, anchor=item.anchor))
    return sorted(symbols, key=lambda item: (item.path, item.lineno, item.col_offset, item.kind, item.qualname))


def _symbol_from_anchor(name: str, kind: str, *, path: str, anchor: Any) -> PythonSymbol:
    qualname = str(getattr(anchor, "qualname", "") or name or "")
    parent = qualname.rsplit(".", 1)[0] if "." in qualname else ""
    return PythonSymbol(
        name=str(name or ""),
        kind=str(kind or "symbol"),
        path=path,
        lineno=int(getattr(anchor, "start_line", 0) or 0),
        col_offset=int(getattr(anchor, "start_col", 0) or 0),
        end_lineno=int(getattr(anchor, "end_line", getattr(anchor, "start_line", 0)) or 0),
        parent=parent,
    )


def _import_symbol_name(item: Any) -> str:
    imported_name = str(getattr(item, "imported_name", "") or "")
    local_name = str(getattr(item, "local_name", "") or "")
    module = str(getattr(item, "module", "") or "")
    if module:
        imported_leaf = imported_name.rsplit(".", 1)[-1]
        return imported_name if local_name == imported_leaf else local_name or imported_name
    imported_root = imported_name.split(".", 1)[0]
    return imported_name if local_name == imported_root else local_name or imported_name


def _symbol_matches(normalized_query: str, symbol: PythonSymbol) -> bool:
    haystack = f"{symbol.name} {symbol.qualname} {symbol.kind}".lower()
    return bool(normalized_query and normalized_query in haystack)


def _symbol_match_key(normalized_query: str, symbol: PythonSymbol) -> tuple[int, str, int, int, str]:
    compact_query = _compact_identifier(normalized_query)
    compact_name = _compact_identifier(symbol.name)
    compact_qualname = _compact_identifier(symbol.qualname)
    rank = 8
    if compact_query and compact_query == compact_name:
        rank = 0
    elif compact_query and compact_query == compact_qualname:
        rank = 1
    elif normalized_query and normalized_query == symbol.name.lower():
        rank = 2
    elif normalized_query and normalized_query == symbol.qualname.lower():
        rank = 3
    elif compact_query and compact_name.startswith(compact_query):
        rank = 4
    elif compact_query and compact_qualname.endswith(compact_query):
        rank = 5
    elif compact_query and compact_query in compact_name:
        rank = 6
    elif compact_query and compact_query in compact_qualname:
        rank = 7
    return (rank, symbol.path, symbol.lineno, symbol.col_offset, symbol.qualname)


def _compact_identifier(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _iter_python_files(files: WorkspaceFileService, roots: list[str] | None) -> list[Path]:
    safe_roots = files.safe_roots(roots, defaults=("backend", "scripts", "tests"), fallback_to_workspace=True)
    results: list[Path] = []
    seen: set[Path] = set()
    for root in safe_roots:
        candidates = [root] if root.is_file() else root.rglob("*.py")
        for candidate in candidates:
            path = candidate.resolve()
            if path in seen or not path.is_file() or path.suffix.lower() != ".py":
                continue
            if files.is_excluded(path, include_default_search_excludes=True):
                continue
            seen.add(path)
            results.append(path)
            if len(results) >= 2000:
                return results
    return results


def _format_outline(payload: dict[str, Any]) -> str:
    lines = [
        f"Python outline: {payload['path']}",
        f"symbols: {payload['symbol_count']}" + (" (truncated)" if payload.get("truncated") else ""),
    ]
    for item in payload["symbols"]:
        indent = "  " if item.get("parent") else ""
        lines.append(f"{indent}- {item['kind']} {item['qualname']} @ {item['path']}:{item['lineno']}")
    return "\n".join(lines)


def _symbol_search_result(query: str, matches: list[PythonSymbol], *, truncated: bool) -> dict[str, Any]:
    payload = {
        "kind": "python_symbol_search",
        "query": query,
        "source_authority": "capability_system.capabilities.code_intelligence.python_ast_indexer",
        "result_count": len(matches),
        "symbols": [asdict(symbol) | {"qualname": symbol.qualname} for symbol in matches],
        "truncated": truncated,
    }
    if not matches:
        return _tool_result(f"No Python symbols found for: {query}", ok=True, kind="python_symbol_search", payload=payload)
    lines = [f"Python symbol search: {query}", f"results: {len(matches)}" + (" (truncated)" if truncated else "")]
    for symbol in matches:
        lines.append(f"- {symbol.kind} {symbol.qualname} @ {symbol.path}:{symbol.lineno}")
    return _tool_result("\n".join(lines), ok=True, kind="python_symbol_search", payload=payload)


def _tool_result(text: str, *, ok: bool, kind: str, path: str = "", payload: dict[str, Any] | None = None) -> PythonAstToolResult:
    body = dict(payload or {"kind": kind})
    body.setdefault("kind", kind)
    body.setdefault("ok", ok)
    if path:
        body.setdefault("path", path)
    return PythonAstToolResult({
        "text": str(text or ""),
        "structured_payload": {
            "tool_result": body,
        },
    })
