from __future__ import annotations

import ast
import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
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
        tree, parse_error = _parse_python(self._files, file_path)
        if parse_error:
            return _tool_result(parse_error, ok=False, kind="python_code_outline", path=self._files.relative_path(file_path))
        symbols = _collect_symbols(tree, path=self._files.relative_path(file_path))
        limit = max(1, min(int(max_symbols or 80), 300))
        payload = {
            "kind": "python_code_outline",
            "path": self._files.relative_path(file_path),
            "symbol_count": len(symbols),
            "symbols": [asdict(symbol) | {"qualname": symbol.qualname} for symbol in symbols[:limit]],
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
            tree, parse_error = _parse_python(self._files, file_path)
            if parse_error:
                continue
            for symbol in _collect_symbols(tree, path=self._files.relative_path(file_path)):
                haystack = f"{symbol.name} {symbol.qualname} {symbol.kind}".lower()
                if normalized in haystack:
                    matches.append(symbol)
                    if len(matches) >= limit:
                        return _symbol_search_result(query, matches, truncated=True)
        return _symbol_search_result(query, matches, truncated=False)

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


def _collect_symbols(tree: ast.AST | None, *, path: str) -> list[PythonSymbol]:
    if tree is None:
        return []
    symbols: list[PythonSymbol] = []
    for node in getattr(tree, "body", []):
        _collect_node(node, path=path, parent="", symbols=symbols, top_level=True)
    return symbols


def _collect_node(node: ast.AST, *, path: str, parent: str, symbols: list[PythonSymbol], top_level: bool) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if isinstance(node, ast.AsyncFunctionDef):
            kind = "async_method" if parent else "async_function"
        else:
            kind = "method" if parent else "function"
        symbols.append(_symbol(node.name, kind, path=path, parent=parent, node=node))
        return
    if isinstance(node, ast.ClassDef):
        symbols.append(_symbol(node.name, "class", path=path, parent=parent, node=node))
        class_parent = f"{parent}.{node.name}" if parent else node.name
        for child in node.body:
            _collect_node(child, path=path, parent=class_parent, symbols=symbols, top_level=False)
        return
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        module = getattr(node, "module", "") or ""
        for alias in node.names:
            imported = f"{module}.{alias.name}" if module and isinstance(node, ast.ImportFrom) else alias.name
            symbols.append(_symbol(alias.asname or imported, "import", path=path, parent=parent, node=node))
        return
    if top_level and isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = list(getattr(node, "targets", [])) if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            for name in _target_names(target):
                symbols.append(_symbol(name, "variable", path=path, parent=parent, node=node))


def _symbol(name: str, kind: str, *, path: str, parent: str, node: ast.AST) -> PythonSymbol:
    return PythonSymbol(
        name=str(name or ""),
        kind=kind,
        path=path,
        lineno=int(getattr(node, "lineno", 0) or 0),
        col_offset=int(getattr(node, "col_offset", 0) or 0),
        end_lineno=int(getattr(node, "end_lineno", getattr(node, "lineno", 0)) or 0),
        parent=parent,
    )


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_target_names(item))
        return names
    return []


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
