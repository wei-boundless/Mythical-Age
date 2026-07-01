from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal, Type

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.tools.workspace_file_service import WorkspaceFileService
from capability_system.tools.workspace_search_service import WorkspaceSearchService


class SearchFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        description="文件名或路径关键词，例如 OpenClaw、计划书、task_understanding.py；只用于未知路径的路径定位",
    )
    roots: list[str] = Field(
        default_factory=list,
        description="可选目录 roots；只放目录，不放文件路径",
    )
    max_results: int = Field(default=20, ge=1, le=100, description="最大返回条数")


class SearchTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        description="要用 rg-like 方式搜索的文本、短语、错误信息、配置键或代码概念",
    )
    roots: list[str] = Field(
        default_factory=list,
        description="可选目录 roots；只放目录，不放文件路径；已知具体文件放 paths",
    )
    paths: list[str] = Field(
        default_factory=list,
        description="可选具体文件路径；只能放文件，目录必须放 roots；单文件也写成 paths=[\"...\"]",
    )
    glob: str = Field(default="", description="可选文件范围过滤 glob，例如 **/*.md 或 backend/**/*.py；它过滤搜索文件，不是内容 query")
    max_results: int = Field(default=20, ge=1, le=100, description="最大返回条数")
    output_mode: Literal["content", "files_with_matches", "count"] = Field(default="content", description="输出模式：content、files_with_matches 或 count")
    context: int = Field(default=0, ge=0, le=20, description="推荐读取窗口时每个命中行前后包含的上下文行数")
    case_sensitive: bool = Field(default=False, description="是否区分大小写搜索")
    head_limit: int = Field(default=0, ge=0, le=100, description="分页返回条数；0 表示使用 max_results")
    offset: int = Field(default=0, ge=0, description="分页偏移，跳过前 N 条匹配")


def _format_no_results(query: str, *, search_boundary: dict[str, Any] | None = None) -> str:
    boundary = dict(search_boundary or {})
    status = _search_status_label([], search_meta=boundary)
    lines = [
        f"搜索状态：{status}",
        f"query: {query}",
        "没有找到匹配项。",
    ]
    if boundary:
        lines.append(f"已搜索 roots：{', '.join(list(boundary.get('searched_roots') or [])) or '<none>'}")
        backend = str(boundary.get("backend") or "").strip()
        strategy = str(boundary.get("text_search_strategy") or "").strip()
        if backend or strategy:
            lines.append(f"检索层：{backend or 'unknown'}{(' / ' + strategy) if strategy else ''}")
    if boundary.get("omitted_workspace_root"):
        lines.append(
            "注意：本次使用默认搜索根，未搜索项目根目录 '.'。如果你已经知道文件路径，请直接使用 read_file/path_exists；如果要搜索根目录文件，请传 roots=[\".\"]."
        )
    if status == "no_match_incomplete":
        lines.append("无命中结果不完整；不要据此判断项目中不存在。请收窄/扩大 roots、调整 glob，或换更具体关键词。")
    return "\n".join(lines)


class SearchFilesTool(BaseTool):
    name: str = "search_files"
    description: str = (
        "Find workspace file paths by filename/path keywords when the exact path is unknown. "
        "Returns safe project-relative paths for read_file or other file tools."
    )
    args_schema: Type[BaseModel] = SearchFilesInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        query: str,
        roots: list[str] | None = None,
        max_results: int = 20,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Search failed: query is required."
        limit = max(1, min(int(max_results or 20), 100))
        service = WorkspaceSearchService(self._files.root_dir, file_service=self._files)
        result = service.search_paths(
            query=normalized_query,
            roots=list(roots or []),
            limit=limit,
        )
        search_meta = dict(result.get("search_meta") or {})
        if str(search_meta.get("status") or "") == "error":
            return f"Search failed: {search_meta.get('error') or 'search failed'}"
        matches = [
            str(item.get("path") or "")
            for item in list(result.get("matches") or [])
            if isinstance(item, dict) and str(item.get("path") or "")
        ]
        if not matches:
            text = _format_no_results(
                normalized_query,
                search_boundary=search_meta,
            )
            if search_meta.get("truncated"):
                text = f"{text}\n搜索已按交互式预算提前返回，结果可能未穷尽；可缩小 roots 或使用 glob_paths 精确匹配。"
            return text
        suffix = "\n搜索已按交互式预算提前返回，结果可能未穷尽；可缩小 roots 或使用 glob_paths 精确匹配。" if search_meta.get("truncated") else ""
        return "\n".join(f"[{index}] {path}" for index, path in enumerate(matches, start=1)) + suffix

    async def _arun(
        self,
        query: str,
        roots: list[str] | None = None,
        max_results: int = 20,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, roots, max_results, None)


class SearchTextTool(BaseTool):
    name: str = "search_text"
    description: str = (
        "Normal rg-like workspace search for content keywords, phrases, errors, config keys, and code concepts. "
        "Use roots/glob/paths to narrow scope; returned read windows are locator candidates, not exact source evidence."
    )
    args_schema: Type[BaseModel] = SearchTextInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        query: str,
        roots: list[str] | None = None,
        paths: list[str] | None = None,
        glob: str = "",
        max_results: int = 20,
        output_mode: str = "content",
        context: int = 0,
        case_sensitive: bool = False,
        head_limit: int = 0,
        offset: int = 0,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Search failed: query is required."
        limit = _search_limit(max_results=max_results, head_limit=head_limit)
        scan_limit = min(100, limit + max(0, int(offset or 0)) + 1)
        mode = _normalize_output_mode(output_mode)
        service = WorkspaceSearchService(self._files.root_dir, file_service=self._files)
        requested_paths = _nonempty_path_args(paths)
        if requested_paths:
            result = service.search_text(
                query=normalized_query,
                paths=requested_paths,
                glob=str(glob or ""),
                limit=scan_limit,
                case_sensitive=case_sensitive,
                fallback_to_workspace=False,
            )
            meta = dict(result.get("search_meta") or {})
            if str(meta.get("status") or "") == "error":
                return f"Search failed: {meta.get('error') or 'search failed'}"
            return _format_structured_search_matches(
                _slice_structured_matches(list(result.get("matches") or []), offset=offset, limit=limit),
                query=normalized_query,
                output_mode=mode,
                search_meta=meta,
            )
        roots_error = _roots_file_misuse_error(self._files, roots)
        if roots_error:
            return f"Search failed: {roots_error}"
        using_default_roots = not [str(item or "").strip() for item in list(roots or [])]
        result = service.search_text(
            query=normalized_query,
            roots=list(roots or []),
            glob=str(glob or ""),
            limit=scan_limit,
            case_sensitive=case_sensitive,
            fallback_to_workspace=using_default_roots,
        )
        meta = dict(result.get("search_meta") or {})
        if str(meta.get("status") or "") == "error":
            return f"Search failed: {meta.get('error') or meta.get('stderr') or 'search failed'}"
        return _format_structured_search_matches(
            _slice_structured_matches(list(result.get("matches") or []), offset=offset, limit=limit),
            query=normalized_query,
            output_mode=mode,
            search_meta=meta,
        )

    async def _arun(
        self,
        query: str,
        roots: list[str] | None = None,
        paths: list[str] | None = None,
        glob: str = "",
        max_results: int = 20,
        output_mode: str = "content",
        context: int = 0,
        case_sensitive: bool = False,
        head_limit: int = 0,
        offset: int = 0,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._run,
            query,
            roots,
            paths,
            glob,
            max_results,
            output_mode,
            context,
            case_sensitive,
            head_limit,
            offset,
            None,
        )


def _nonempty_path_args(paths: list[str] | str | None) -> list[str]:
    values = [paths] if isinstance(paths, str) else list(paths or [])
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def _roots_file_misuse_error(files: WorkspaceFileService, roots: list[str] | None) -> str:
    for item in _nonempty_path_args(roots):
        try:
            target = files.resolve(item, require_path=True)
        except ValueError:
            continue
        if target.exists() and target.is_file():
            rel = files.relative_path(target)
            return f"roots accepts directories only. Put file paths in paths instead, for example paths=[\"{rel}\"]."
    return ""


def _format_structured_search_matches(
    matches: list[dict[str, Any]],
    *,
    query: str,
    output_mode: str = "content",
    search_meta: dict[str, Any] | None = None,
) -> str:
    if not matches:
        return _format_no_results(query, search_boundary=search_meta)
    if output_mode == "files_with_matches":
        paths = [str(item.get("path") or "") for item in matches if str(item.get("path") or "")]
        text = "\n".join(dict.fromkeys(paths)) or _format_no_results(query, search_boundary=search_meta)
    elif output_mode == "count":
        counts: dict[str, int] = {}
        for item in matches:
            path = str(item.get("path") or "")
            if path:
                counts[path] = counts.get(path, 0) + 1
        text = "\n".join(f"{path}:{count}" for path, count in counts.items()) or _format_no_results(query, search_boundary=search_meta)
    else:
        text = "\n".join(
            f"{item['path']}:{item['line']}:{item['column']}:{item['text']}"
            for item in matches
            if item.get("path") and item.get("line") and item.get("column")
        )
    text = _prepend_search_summary(text, matches=matches, query=query, output_mode=output_mode, search_meta=search_meta)
    text = _append_read_window_notice(text, matches=matches)
    return _append_structured_search_notice(text, search_meta=search_meta)


def _prepend_search_summary(
    text: str,
    *,
    matches: list[dict[str, Any]],
    query: str,
    output_mode: str,
    search_meta: dict[str, Any] | None = None,
) -> str:
    meta = dict(search_meta or {})
    header = [
        f"搜索状态：{_search_status_label(matches, search_meta=meta)}",
        "证据语义：locator-only；需要逐行判断、修改或引用时再 read_file。",
        f"query: {query}",
    ]
    backend = str(meta.get("backend") or "").strip()
    strategy = str(meta.get("text_search_strategy") or "").strip()
    roots = [str(item) for item in list(meta.get("searched_roots") or []) if str(item)]
    if backend or strategy:
        header.append(f"检索层：{backend or 'unknown'}{(' / ' + strategy) if strategy else ''}")
    if roots:
        header.append("搜索范围：" + ", ".join(roots[:8]))
    limit = _safe_int(meta.get("limit"))
    matched_count = _safe_int(meta.get("matched_count"))
    if limit or matched_count:
        header.append(f"返回：{len(matches)} 条；工具命中计数：{matched_count}; limit={limit}; output_mode={output_mode}")
    return "\n".join(header) + "\n" + str(text or "").rstrip()


def _search_status_label(matches: list[dict[str, Any]], *, search_meta: dict[str, Any] | None = None) -> str:
    meta = dict(search_meta or {})
    status = str(meta.get("status") or "").strip()
    incomplete = bool(meta.get("truncated") or meta.get("has_more")) or status in {"timeout", "error", "permission_error"}
    if matches:
        return "candidate_only_incomplete" if incomplete else "candidate_only"
    if status == "no_match" and not incomplete:
        return "no_match_complete"
    if status in {"timeout", "error", "permission_error"} or incomplete:
        return "no_match_incomplete"
    return status or "no_match_unknown"


def _append_structured_search_notice(text: str, *, search_meta: dict[str, Any] | None = None) -> str:
    meta = dict(search_meta or {})
    status = str(meta.get("status") or "").strip()
    notices: list[str] = []
    if status == "timeout":
        notices.append("搜索超时；结果不完整，不能据此判断不存在。")
    elif status in {"error", "permission_error"}:
        detail = str(meta.get("error") or meta.get("stderr") or "").strip()
        notices.append("搜索未完成：" + (detail[:240] if detail else status))
    if meta.get("has_more"):
        notices.append("搜索命中分页/预算上限；用 offset/head_limit 翻页，或收窄 roots/glob/关键词。")
    if not notices:
        return text
    return str(text or "").rstrip() + "\n" + "\n".join(notices)


def _append_read_window_notice(text: str, *, matches: list[dict[str, Any]]) -> str:
    windows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in list(matches or []):
        window = dict(dict(item or {}).get("recommended_read_window") or {})
        path = str(window.get("path") or "").strip()
        start_line = _safe_int(window.get("start_line"))
        line_count = _safe_int(window.get("line_count"))
        if not path or start_line <= 0 or line_count <= 0:
            continue
        key = (path, start_line, line_count)
        if key in seen:
            continue
        seen.add(key)
        windows.append(window)
        if len(windows) >= 3:
            break
    if not windows:
        return text
    lines = [
        f"- read_file path=\"{window['path']}\" start_line={int(window['start_line'])} line_count={int(window['line_count'])}"
        for window in windows
    ]
    return str(text or "").rstrip() + "\n候选读取窗口（可选；只有需要 exact source 时读取）：\n" + "\n".join(lines)


def _slice_structured_matches(matches: list[dict[str, Any]], *, offset: int, limit: int) -> list[dict[str, Any]]:
    start = max(0, int(offset or 0))
    return [dict(item) for item in list(matches or [])[start : start + max(1, int(limit or 1))] if isinstance(item, dict)]


def _search_limit(*, max_results: int, head_limit: int = 0) -> int:
    selected = int(head_limit or 0) or int(max_results or 20)
    return max(1, min(selected, 100))


def _normalize_output_mode(value: str) -> str:
    mode = str(value or "content").strip()
    return mode if mode in {"content", "files_with_matches", "count"} else "content"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
