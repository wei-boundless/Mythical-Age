from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PERSISTED_OUTPUT_TAG = "<persisted-output>"
DEFAULT_PREVIEW_SIZE_BYTES = 2000
DEFAULT_FIELD_SIZE_LIMIT_BYTES = 6000
DEFAULT_PAYLOAD_BUDGET_BYTES = 24000
TOOL_RESULTS_SUBDIR = "tool_results"
RUNTIME_CONTEXT_NAMESPACE = "runtime_context"
DEFAULT_REHYDRATION_SIZE_BYTES = 120_000
MAX_REHYDRATION_SIZE_BYTES = 500_000
_BUDGETED_FIELD_TOKENS = (
    ".answer",
    ".answer_candidate",
    ".canonical_answer",
    ".content",
    ".raw_content",
    ".clean_text",
    ".diagnostics",
    ".html",
    ".markdown",
    ".summary",
    ".text",
    ".visible_text",
    ".web_payload",
)


@dataclass(frozen=True, slots=True)
class ContentReplacement:
    replacement_id: str
    path: str
    json_path: str
    original_size_bytes: int
    preview_size_bytes: int
    has_more: bool
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "replacement_id": self.replacement_id,
            "path": self.path,
            "json_path": self.json_path,
            "original_size_bytes": self.original_size_bytes,
            "preview_size_bytes": self.preview_size_bytes,
            "has_more": self.has_more,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


class ToolResultStore:
    def __init__(self, root_dir: Path, *, run_id: str = "", namespace: str = RUNTIME_CONTEXT_NAMESPACE) -> None:
        _ = namespace
        safe_run = _safe_path_part(run_id or "default")
        self.base_dir = Path(root_dir) / TOOL_RESULTS_SUBDIR / safe_run

    def apply_budget(
        self,
        payload: dict[str, Any],
        *,
        field_limit_bytes: int = DEFAULT_FIELD_SIZE_LIMIT_BYTES,
        preview_size_bytes: int = DEFAULT_PREVIEW_SIZE_BYTES,
        payload_budget_bytes: int = DEFAULT_PAYLOAD_BUDGET_BYTES,
        replacement_metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], tuple[ContentReplacement, ...]]:
        cloned = _json_clone(payload)
        replacements: list[ContentReplacement] = []
        field_limit = max(1, int(field_limit_bytes or DEFAULT_FIELD_SIZE_LIMIT_BYTES))
        preview_limit = max(1, int(preview_size_bytes or DEFAULT_PREVIEW_SIZE_BYTES))
        payload_budget = max(1, int(payload_budget_bytes or DEFAULT_PAYLOAD_BUDGET_BYTES))
        while True:
            payload_size = _json_bytes(cloned)
            candidates = sorted(
                (
                    (_text_bytes(value), json_path, value)
                    for json_path, value in _walk_budgeted_strings(cloned)
                    if (
                        (_text_bytes(value) > field_limit or payload_size > payload_budget)
                        and _replacement_can_shrink(value, preview_size_bytes=preview_limit)
                    )
                ),
                reverse=True,
            )
            if not candidates:
                break
            _size, json_path, value = candidates[0]
            replacement = self._persist(
                content=value,
                json_path=json_path,
                preview_size_bytes=preview_limit,
                metadata=replacement_metadata,
            )
            _set_json_path(cloned, json_path, replacement_text(value, replacement, preview_size_bytes=preview_limit))
            replacements.append(replacement)
        return cloned, tuple(replacements)

    def resolve(self, replacement_id_or_path: str) -> str:
        target = str(replacement_id_or_path or "").strip()
        if not target:
            raise ValueError("replacement id or path is required")
        path = self._resolve_path(target)
        return path.read_bytes().decode("utf-8", errors="replace")

    @staticmethod
    def prune_task_runs(root_dir: Path, task_run_ids: set[str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        targets = {str(item).strip() for item in task_run_ids if str(item).strip()}
        base_dir = Path(root_dir) / TOOL_RESULTS_SUBDIR
        deleted: list[str] = []
        deleted_paths: list[str] = []
        for task_run_id in sorted(targets):
            path = base_dir / _safe_path_part(task_run_id)
            if not path.exists():
                continue
            try:
                shutil.rmtree(path)
            except OSError:
                continue
            deleted.append(task_run_id)
            deleted_paths.append(str(path))
        return {
            "authority": "runtime.tool_result_store.prune_task_runs",
            "root_dir": str(Path(root_dir)),
            "requested_task_run_ids": sorted(targets),
            "deleted_task_run_ids": deleted,
            "deleted_paths": deleted_paths,
            "deleted_count": len(deleted),
        }

    def _persist(
        self,
        *,
        content: str,
        json_path: str,
        preview_size_bytes: int,
        metadata: dict[str, Any] | None = None,
    ) -> ContentReplacement:
        encoded = content.encode("utf-8", errors="replace")
        digest = hashlib.sha1((json_path + "\n" + content[:4096]).encode("utf-8", errors="replace")).hexdigest()[:16]
        path = self.base_dir / f"{_safe_path_part(json_path)}-{digest}.txt"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        clean_metadata = _json_clone(dict(metadata or {})) if isinstance(metadata, dict) and metadata else {}
        if clean_metadata:
            _metadata_path(path).write_text(
                json.dumps(clean_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str),
                encoding="utf-8",
            )
        return ContentReplacement(
            replacement_id=f"tool_result:{digest}",
            path=str(path),
            json_path=json_path,
            original_size_bytes=len(encoded),
            preview_size_bytes=min(len(encoded), max(1, int(preview_size_bytes or DEFAULT_PREVIEW_SIZE_BYTES))),
            has_more=len(encoded) > max(1, int(preview_size_bytes or DEFAULT_PREVIEW_SIZE_BYTES)),
            metadata=clean_metadata or None,
        )

    def _resolve_path(self, target: str) -> Path:
        if target.startswith("tool_result:"):
            digest = target.split(":", 1)[1]
            matches = sorted(self.base_dir.glob(f"*-{digest}.txt"))
            if not matches:
                raise FileNotFoundError(target)
            return matches[0]
        path = Path(target)
        if not path.is_absolute():
            path = self.base_dir / target
        resolved = path.resolve()
        base = self.base_dir.resolve()
        if base not in [resolved, *resolved.parents]:
            raise ValueError("replacement path is outside tool result store")
        return resolved


def read_persisted_tool_result(
    *,
    root_dir: Path,
    replacement_id: str = "",
    path: str = "",
    task_run_id: str = "",
    max_bytes: int = DEFAULT_REHYDRATION_SIZE_BYTES,
    start_byte: int = 0,
    trusted_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """Read a runtime-persisted tool result without exposing arbitrary file IO."""

    try:
        target = _resolve_persisted_tool_result_path(
            root_dir=Path(root_dir),
            replacement_id=replacement_id,
            path=path,
            task_run_id=task_run_id,
            trusted_roots=trusted_roots,
        )
        start = max(0, int(start_byte or 0))
        limit = max(1, min(int(max_bytes or DEFAULT_REHYDRATION_SIZE_BYTES), MAX_REHYDRATION_SIZE_BYTES))
        total = target.stat().st_size
        with target.open("rb") as handle:
            handle.seek(start)
            chunk = handle.read(limit)
        content = chunk.decode("utf-8", errors="replace")
        replacement_ref = _normalize_replacement_id(replacement_id) or _replacement_id_from_path(target)
        returned = len(chunk)
        return {
            "ok": True,
            "status": "ok",
            "authority": "runtime.tool_result_rehydration",
            "replacement_id": replacement_ref,
            "path": str(target),
            "content": content,
            "start_byte": start,
            "returned_bytes": returned,
            "total_bytes": total,
            "truncated": start + returned < total,
            "metadata": _read_replacement_metadata(target),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "authority": "runtime.tool_result_rehydration",
            "replacement_id": str(replacement_id or "").strip(),
            "path": str(path or "").strip(),
            "error": str(exc),
        }


def _resolve_persisted_tool_result_path(
    *,
    root_dir: Path,
    replacement_id: str,
    path: str,
    task_run_id: str,
    trusted_roots: Iterable[Path],
) -> Path:
    roots = _trusted_roots(root_dir=root_dir, trusted_roots=trusted_roots)
    normalized_id = _normalize_replacement_id(replacement_id)
    if path:
        target = _resolve_supplied_result_path(path, roots=roots)
        if normalized_id and _replacement_id_from_path(target) != normalized_id:
            raise ValueError("replacement_id does not match persisted result path")
        if not target.exists():
            raise FileNotFoundError(str(target))
        if not target.is_file():
            raise IsADirectoryError(str(target))
        return target
    if not normalized_id:
        raise ValueError("replacement_id or path is required")
    matches = _find_replacement_matches(normalized_id, task_run_id=task_run_id, roots=roots)
    if not matches:
        raise FileNotFoundError(normalized_id)
    if len(matches) > 1:
        raise ValueError("replacement_id is ambiguous; retry with the path from the rehydration plan")
    return matches[0]


def _resolve_supplied_result_path(path: str, *, roots: tuple[Path, ...]) -> Path:
    raw = Path(str(path or "").strip())
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        for root in roots:
            candidates.append(root / raw)
            candidates.append(root / TOOL_RESULTS_SUBDIR / raw)
    for candidate in candidates:
        resolved = candidate.resolve()
        if _is_trusted_tool_result_path(resolved, roots=roots):
            return resolved
    raise ValueError("persisted tool result path is outside trusted runtime context storage")


def _find_replacement_matches(replacement_id: str, *, task_run_id: str, roots: tuple[Path, ...]) -> list[Path]:
    digest = replacement_id.split(":", 1)[1]
    run_part = _safe_path_part(task_run_id) if str(task_run_id or "").strip() else ""
    patterns = []
    if run_part:
        patterns.append(f"{run_part}/*-{digest}.txt")
        patterns.append(f"**/{run_part}/*-{digest}.txt")
    patterns.append(f"**/*-{digest}.txt")
    matches: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for pattern in patterns:
            for match in root.glob(pattern):
                resolved = match.resolve()
                if resolved in seen or not _is_trusted_tool_result_path(resolved, roots=roots):
                    continue
                if resolved.is_file():
                    seen.add(resolved)
                    matches.append(resolved)
    return sorted(matches)


def _trusted_roots(*, root_dir: Path, trusted_roots: Iterable[Path]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in (root_dir, *tuple(trusted_roots or ())):
        try:
            root = Path(value).resolve()
        except Exception:
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _is_trusted_tool_result_path(path: Path, *, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    if not any(root == resolved or root in resolved.parents for root in roots):
        return False
    parts = tuple(part.lower() for part in resolved.parts)
    for index in range(0, len(parts)):
        if parts[index] == TOOL_RESULTS_SUBDIR:
            return True
    if any(root.name == TOOL_RESULTS_SUBDIR and (root == resolved or root in resolved.parents) for root in roots):
        return True
    return False


def _normalize_replacement_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith("tool_result:"):
        raise ValueError("replacement_id must start with tool_result:")
    digest = text.split(":", 1)[1].strip()
    if not digest or any(char not in "0123456789abcdefABCDEF" for char in digest):
        raise ValueError("replacement_id digest must be hexadecimal")
    return f"tool_result:{digest.lower()}"


def _replacement_id_from_path(path: Path) -> str:
    stem = Path(path).stem
    digest = stem.rsplit("-", 1)[-1].strip().lower()
    if not digest or any(char not in "0123456789abcdef" for char in digest):
        return ""
    return f"tool_result:{digest}"


def _metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.metadata.json")


def _read_replacement_metadata(path: Path) -> dict[str, Any]:
    metadata_path = _metadata_path(path)
    if not metadata_path.exists() or not metadata_path.is_file():
        return {}
    try:
        parsed = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def replacement_text(content: str, replacement: ContentReplacement, *, preview_size_bytes: int) -> str:
    more = "\n[Full output persisted; read the referenced file if more evidence is required.]" if replacement.has_more else ""
    return (
        f"{PERSISTED_OUTPUT_TAG}\n"
        f"Path: {replacement.path}\n"
        f"Original bytes: {replacement.original_size_bytes}\n"
        f"Preview bytes: {replacement.preview_size_bytes}\n"
        f"Preview:\n{_preview_bytes(content, preview_size_bytes)}{more}"
    ).strip()


def _walk_budgeted_strings(value: Any, prefix: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_budgeted_strings(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_budgeted_strings(child, f"{prefix}[{index}]")
    elif isinstance(value, str) and any(token in prefix.lower() for token in _BUDGETED_FIELD_TOKENS):
        yield prefix, value


def _set_json_path(root: Any, json_path: str, value: str) -> None:
    target = root
    parts = _parse_json_path(json_path)
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def _parse_json_path(path: str) -> list[Any]:
    text = path[2:] if path.startswith("$.") else path
    parts: list[Any] = []
    token = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == ".":
            if token:
                parts.append(token)
                token = ""
            index += 1
        elif char == "[":
            if token:
                parts.append(token)
                token = ""
            end = text.index("]", index)
            parts.append(int(text[index + 1 : end]))
            index = end + 1
        else:
            token += char
            index += 1
    if token:
        parts.append(token)
    return parts


def _preview_bytes(content: str, limit: int) -> str:
    return content.encode("utf-8", errors="replace")[: max(1, int(limit or DEFAULT_PREVIEW_SIZE_BYTES))].decode(
        "utf-8",
        errors="ignore",
    ).strip()


def _json_clone(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8", errors="replace"))


def _text_bytes(value: str) -> int:
    return len(value.encode("utf-8", errors="replace"))


def _replacement_can_shrink(value: str, *, preview_size_bytes: int) -> bool:
    # A persisted reference includes path metadata and a preview. Replacing short
    # fields such as titles, URLs, or stop reasons makes the payload larger and
    # less readable, so only externalize fields that can actually shrink.
    if str(value or "").lstrip().startswith(PERSISTED_OUTPUT_TAG):
        return False
    return _text_bytes(value) > max(1, int(preview_size_bytes or DEFAULT_PREVIEW_SIZE_BYTES)) + 512


def _safe_path_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or ""))
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")[:120] or "payload"


__all__ = [
    "ContentReplacement",
    "DEFAULT_FIELD_SIZE_LIMIT_BYTES",
    "DEFAULT_PAYLOAD_BUDGET_BYTES",
    "DEFAULT_PREVIEW_SIZE_BYTES",
    "DEFAULT_REHYDRATION_SIZE_BYTES",
    "MAX_REHYDRATION_SIZE_BYTES",
    "PERSISTED_OUTPUT_TAG",
    "RUNTIME_CONTEXT_NAMESPACE",
    "ToolResultStore",
    "read_persisted_tool_result",
    "replacement_text",
]
