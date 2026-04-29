from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from memory.manifest_scan import MemoryHeader, load_memory_header, scan_memory_headers
from memory_system import MemoryGovernance
from structured_memory.frontmatter import format_frontmatter, parse_frontmatter
from structured_memory.models import DEFAULT_DURABLE_SCHEMA_VERSION, MemoryNote, utc_now_iso
from understanding.memory_intent import analyze_memory_intent

router = APIRouter()


class RecallPreviewRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = None
    limit: int = Field(default=5, ge=1, le=20)


class DurableMemoryCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    canonical_statement: str = Field(..., min_length=1, max_length=1200)
    summary: str = Field(default="", max_length=800)
    memory_type: str = Field(default="project", max_length=40)
    memory_class: str = Field(default="work", max_length=40)
    retrieval_hints: list[str] = Field(default_factory=list, max_length=8)
    confidence: str = Field(default="medium", max_length=40)
    source_kind: str = Field(default="manual", max_length=80)
    source_message_excerpt: str = Field(default="", max_length=1200)


class DurableMemoryGovernRequest(BaseModel):
    reason: str = Field(default="", max_length=600)


class DurableMemoryMergeRequest(BaseModel):
    filenames: list[str] = Field(..., min_length=2, max_length=8)
    title: str = Field(..., min_length=1, max_length=160)
    canonical_statement: str = Field(..., min_length=1, max_length=1600)
    summary: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=600)


SESSION_MEMORY_FILE_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    ("summary", "模型摘要", "summary.md", "模型通常读取的精简状态视图"),
    ("agent_view", "Agent 工作视图", "views/agent_view.md", "当前工作记忆的主视图"),
    ("debug_view", "调试视图", "views/debug_view.md", "排查问题时使用的完整状态视图"),
    ("compaction_view", "压缩恢复视图", "views/compaction_view.md", "上下文压缩后用于恢复任务的材料"),
    ("process_state", "权威状态 JSON", "process_state.json", "状态记忆的结构化源文件"),
    ("state_mirror", "状态镜像 JSON", "state.json", "兼容迁移期的状态镜像"),
    ("flow_snapshots", "流程快照 JSON", "flow_snapshots.json", "任务切换和流程演进记录"),
)


@router.get("/memory/overview")
async def get_memory_overview(
    session_id: str | None = None,
    query: str = "",
    limit: int = Query(default=80, ge=1, le=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    headers = scan_memory_headers(runtime.base_dir / "durable_memory", limit=limit)
    session_inspect = None
    if session_id:
        session_inspect = _inspect_session_memory(runtime, session_id, query=query)

    return {
        "session_id": session_id or "",
        "query": query,
        "durable_memory": _durable_overview(headers, runtime.memory_facade.durable_memory.describe_extraction_runtime()),
        "session_memory": session_inspect,
    }


@router.post("/memory/durable")
async def create_durable_memory_note(payload: DurableMemoryCreateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    now = utc_now_iso()
    manager = runtime.memory_facade.memory_manager
    title = payload.title.strip()
    canonical = payload.canonical_statement.strip()
    summary = payload.summary.strip() or canonical
    slug = _unique_slug(manager, title)
    memory_type = _normalize_choice(payload.memory_type, {"user", "feedback", "project", "reference"}, "project")
    memory_class = _normalize_choice(payload.memory_class, {"work", "preference"}, "work")
    note = MemoryNote(
        slug=slug,
        title=title,
        summary=summary,
        canonical_statement=canonical,
        body=_build_note_body(canonical, payload.retrieval_hints, "Manual memory governance", payload.source_message_excerpt or canonical),
        memory_type=memory_type,  # type: ignore[arg-type]
        memory_class=memory_class,  # type: ignore[arg-type]
        tags=[memory_type, memory_class],
        retrieval_hints=[item.strip() for item in payload.retrieval_hints if item.strip()][:8],
        created_at=now,
        updated_at=now,
        created_by="memory_governance_ui",
        source_role="user",
        source_message_excerpt=payload.source_message_excerpt.strip() or canonical,
        confidence=payload.confidence.strip() or "medium",
        status="active",
        scope="project",
        stability="stable",
        source_kind=payload.source_kind.strip() or "manual",
        eligible_for_injection="true",
    )
    path = manager.save_note(note)
    runtime.refresh_indexes_for_path("durable_memory/notes")
    _append_governance_log(runtime.base_dir, "create", [path.name], reason="manual_create", created=path.name)
    header = load_memory_header(path)
    return {
        "ok": True,
        "action": "create",
        "filename": path.name,
        "header": _header_payload(header) if header else None,
    }


@router.post("/memory/durable/{filename}/disable")
async def disable_durable_memory_note(filename: str, payload: DurableMemoryGovernRequest) -> dict[str, Any]:
    return _govern_existing_note(filename, status="inactive", eligible_for_injection="false", reason=payload.reason or "Disabled from memory UI", action="disable")


@router.post("/memory/durable/{filename}/activate")
async def activate_durable_memory_note(filename: str, payload: DurableMemoryGovernRequest) -> dict[str, Any]:
    return _govern_existing_note(filename, status="active", eligible_for_injection="true", reason=payload.reason or "Activated from memory UI", action="activate")


@router.post("/memory/durable/{filename}/archive")
async def archive_durable_memory_note(filename: str, payload: DurableMemoryGovernRequest) -> dict[str, Any]:
    return _govern_existing_note(filename, status="archived", eligible_for_injection="false", reason=payload.reason or "Archived from memory UI", action="archive")


@router.delete("/memory/durable/{filename}")
async def delete_durable_memory_note(filename: str, payload: DurableMemoryGovernRequest | None = None) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    path = _safe_note_path(runtime.base_dir, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Memory note not found")

    trash_dir = runtime.base_dir / "durable_memory" / "trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    deleted_at = utc_now_iso()
    target = _unique_trash_path(trash_dir, path.name)
    path.replace(target)

    runtime.memory_facade.memory_manager.sync_index()
    runtime.refresh_indexes_for_path("durable_memory/notes")
    reason = payload.reason if payload else ""
    _append_governance_log(
        runtime.base_dir,
        "delete",
        [path.name],
        reason=reason or "Deleted from memory UI",
        created=f"durable_memory/trash/{target.name}",
    )
    return {
        "ok": True,
        "action": "delete",
        "filename": path.name,
        "deleted_at": deleted_at,
        "trash_path": f"durable_memory/trash/{target.name}",
        "header": None,
    }


@router.post("/memory/durable/merge")
async def merge_durable_memory_notes(payload: DurableMemoryMergeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    manager = runtime.memory_facade.memory_manager
    paths = [_safe_note_path(runtime.base_dir, filename) for filename in payload.filenames]
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        raise HTTPException(status_code=404, detail=f"Memory note not found: {', '.join(missing)}")

    now = utc_now_iso()
    loaded = [load_memory_header(path) for path in paths]
    hints: list[str] = []
    for header in loaded:
      if header:
        hints.extend(header.retrieval_hints)
    canonical = payload.canonical_statement.strip()
    summary = payload.summary.strip() or canonical
    slug = _unique_slug(manager, payload.title.strip())
    source_excerpt = " / ".join(header.title for header in loaded if header)[:1000]
    note = MemoryNote(
        slug=slug,
        title=payload.title.strip(),
        summary=summary,
        canonical_statement=canonical,
        body=_build_note_body(canonical, hints, payload.reason or "Merged durable memories", source_excerpt),
        memory_type=(loaded[0].memory_type if loaded[0] else "project"),  # type: ignore[arg-type]
        memory_class=(loaded[0].memory_class if loaded[0] else "work"),  # type: ignore[arg-type]
        tags=["merged", "governed"],
        retrieval_hints=_dedupe(hints + [payload.title.strip(), canonical])[:8],
        created_at=now,
        updated_at=now,
        created_by="memory_governance_ui",
        source_role="user",
        source_message_excerpt=source_excerpt,
        confidence="medium",
        status="active",
        scope="project",
        stability="stable",
        source_kind="manual_merge",
        eligible_for_injection="true",
        supersedes=", ".join(path.stem for path in paths),
    )
    new_path = manager.save_note(note)
    for path in paths:
        _update_note_frontmatter(
            path,
            {
                "status": "deprecated",
                "eligible_for_injection": "false",
                "updated_at": now,
                "invalidation_reason": payload.reason.strip() or f"Merged into {new_path.stem}",
            },
        )
    manager.sync_index()
    runtime.refresh_indexes_for_path("durable_memory/notes")
    _append_governance_log(runtime.base_dir, "merge", [path.name for path in paths], reason=payload.reason, created=new_path.name)
    header = load_memory_header(new_path)
    return {
        "ok": True,
        "action": "merge",
        "filename": new_path.name,
        "merged": [path.name for path in paths],
        "header": _header_payload(header) if header else None,
    }


@router.post("/memory/recall-preview")
async def recall_memory_preview(payload: RecallPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    query = payload.query.strip()
    intent = analyze_memory_intent(query)
    session_summary = ""
    context_preview = None

    if payload.session_id:
        history_payload = runtime.session_manager.get_history(payload.session_id)
        session_summary = str(history_payload.get("compressed_context", "") or "")
        context_preview = _inspect_session_memory(runtime, payload.session_id, query=query, limit=payload.limit)

    result = runtime.memory_facade.recall_durable_memories(
        query=query,
        memory_intent=intent,
        note_limit=payload.limit,
        session_summary=session_summary,
    )

    return {
        "query": query,
        "session_id": payload.session_id or "",
        "intent": {
            "intent": intent.intent,
            "read_mode": intent.memory_read_mode,
            "write_mode": intent.memory_write_mode,
            "explicit_read_inventory": intent.explicit_read_inventory,
            "ignore_memory": intent.ignore_memory,
            "preferred_types": list(intent.preferred_types),
            "preferred_memory_classes": list(intent.preferred_memory_classes),
        },
        "selection": result.selection.model_dump(),
        "selected_headers": [_clean_header_dict(item) for item in result.selected_headers],
        "selected_notes": [_clean_note_dict(item) for item in result.selected_notes],
        "rendered_summary": _compact_text(result.rendered_summary, 1200),
        "context_preview": context_preview,
    }


@router.get("/memory/session/{session_id}/files")
async def get_session_memory_files(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None

    safe_session_id = _safe_session_id(session_id)
    session_dir = runtime.base_dir / "session-memory" / safe_session_id
    files = [
        _session_memory_file_payload(session_dir, safe_session_id, item_id, label, relative_path, description)
        for item_id, label, relative_path, description in SESSION_MEMORY_FILE_TARGETS
    ]
    existing = [item for item in files if item["exists"]]
    return {
        "session_id": safe_session_id,
        "root": f"session-memory/{safe_session_id}",
        "present": session_dir.exists() and bool(existing),
        "existing_count": len(existing),
        "missing_count": len(files) - len(existing),
        "files": files,
    }


@router.get("/memory/durable/{filename}")
async def get_durable_memory_note(filename: str) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    safe_name = filename.strip()
    if not safe_name or "/" in safe_name or "\\" in safe_name or safe_name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid memory filename")

    path = runtime.base_dir / "durable_memory" / "notes" / safe_name
    if not path.exists() or path.suffix.lower() != ".md":
        raise HTTPException(status_code=404, detail="Memory note not found")

    header = load_memory_header(path)
    content = path.read_text(encoding="utf-8")
    return {
        "header": _header_payload(header) if header else None,
        "content_preview": _compact_text(content, 2600),
        "path": f"durable_memory/notes/{safe_name}",
    }


def _safe_session_id(session_id: str) -> str:
    safe_id = session_id.strip()
    if not safe_id or "/" in safe_id or "\\" in safe_id or ".." in safe_id:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return safe_id


def _session_memory_file_payload(
    session_dir: Path,
    session_id: str,
    item_id: str,
    label: str,
    relative_path: str,
    description: str,
) -> dict[str, Any]:
    path = session_dir / relative_path
    exists = path.exists() and path.is_file()
    stat = path.stat() if exists else None
    return {
        "id": item_id,
        "label": label,
        "description": description,
        "path": f"session-memory/{session_id}/{relative_path}",
        "kind": "json" if path.suffix.lower() == ".json" else "markdown",
        "exists": exists,
        "size": stat.st_size if stat else 0,
        "updated_at": stat.st_mtime if stat else None,
        "preview": _read_session_memory_preview(path) if exists else "",
    }


def _read_session_memory_preview(path: Path, limit: int = 12000) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            raw = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def _inspect_session_memory(runtime: Any, session_id: str, *, query: str = "", limit: int = 5) -> dict[str, Any]:
    assert runtime.memory_facade is not None
    messages = runtime.session_manager.load_session(session_id)
    intent = analyze_memory_intent(query) if query.strip() else None
    preview = runtime.memory_facade.build_memory_context_package_preview(
        session_id=session_id,
        query=query.strip() or None,
        memory_intent=intent,
        note_limit=limit,
    )
    payload = preview.to_dict()
    package = dict(payload.get("package") or {})
    sections = dict(package.get("model_visible_sections") or {})
    memory_view = runtime.memory_facade.build_memory_runtime_view(
        session_id=session_id,
        query=query.strip() or None,
        memory_intent=intent,
        note_limit=limit,
    )
    state = memory_view.state_snapshot
    rendered_sections = "\n".join(
        "\n".join(str(item) for item in list(sections.get(name, []) or []))
        for name in ("active_process_context", "hot_truth_window", "relevant_durable_context")
    ).strip()
    return {
        "present": bool(memory_view.context_candidates or memory_view.restore_candidates),
        "preview": _compact_text(rendered_sections, 900),
        "model_preview": _compact_text(rendered_sections, 900),
        "debug_preview": _compact_text(json.dumps(payload, ensure_ascii=False), 900),
        "active_goal": str(getattr(state, "active_goal", "") or ""),
        "flow_state": dict(getattr(state, "flow_state", {}) or {}),
        "task_state": dict(getattr(state, "task_state", {}) or {}),
        "context_slots": dict(getattr(state, "context_slots", {}) or {}),
        "risk": {},
        "warm_snapshots": [],
        "storage": {"memory_runtime_view": memory_view.view_id},
        "context_management": package,
        "durable_matches": {"long_term_record_count": len(memory_view.long_term_records)},
    }


def _durable_overview(headers: list[MemoryHeader], extraction_runtime: dict[str, object]) -> dict[str, Any]:
    by_type = Counter(header.memory_type for header in headers)
    by_class = Counter(header.memory_class for header in headers)
    active = [header for header in headers if header.status == "active"]
    injectable = [header for header in headers if header.eligible_for_injection and header.status == "active"]
    return {
        "total": len(headers),
        "active": len(active),
        "injectable": len(injectable),
        "by_type": dict(by_type),
        "by_class": dict(by_class),
        "headers": [_header_payload(header) for header in headers],
        "extraction_runtime": extraction_runtime,
    }


def _header_payload(header: MemoryHeader) -> dict[str, Any]:
    return {
        "note_id": header.note_id,
        "filename": header.filename,
        "memory_type": header.memory_type,
        "memory_class": header.memory_class,
        "title": header.title,
        "description": _compact_text(header.description, 360),
        "status": header.status,
        "confidence": header.confidence,
        "updated_at": header.updated_at,
        "retrieval_hints": list(header.retrieval_hints),
        "eligible_for_injection": header.eligible_for_injection,
        "canonical_statement": _compact_text(header.canonical_statement, 420),
        "summary": _compact_text(header.summary, 420),
    }


def _clean_header_dict(item: dict[str, object]) -> dict[str, Any]:
    return {
        "note_id": str(item.get("note_id") or ""),
        "filename": str(item.get("filename") or ""),
        "title": str(item.get("title") or ""),
        "description": _compact_text(str(item.get("description") or ""), 420),
        "memory_type": str(item.get("memory_type") or ""),
        "memory_class": str(item.get("memory_class") or ""),
        "status": str(item.get("status") or ""),
        "confidence": str(item.get("confidence") or ""),
        "eligible_for_injection": bool(item.get("eligible_for_injection", True)),
        "canonical_statement": _compact_text(str(item.get("canonical_statement") or ""), 420),
        "retrieval_hints": list(item.get("retrieval_hints") or []),
    }


def _clean_note_dict(item: dict[str, object]) -> dict[str, Any]:
    return {
        "note_id": str(item.get("note_id") or ""),
        "filename": str(item.get("filename") or ""),
        "title": str(item.get("title") or ""),
        "summary": _compact_text(str(item.get("summary") or ""), 520),
        "canonical_statement": _compact_text(str(item.get("canonical_statement") or ""), 520),
        "content_preview": _compact_text(str(item.get("content") or ""), 800),
        "memory_type": str(item.get("memory_type") or ""),
        "memory_class": str(item.get("memory_class") or ""),
        "confidence": str(item.get("confidence") or ""),
        "status": str(item.get("status") or ""),
        "retrieval_hints": list(item.get("retrieval_hints") or []),
        "eligible_for_injection": bool(item.get("eligible_for_injection", True)),
    }


def _compact_text(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").replace("\r\n", "\n").replace("\r", "\n").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _govern_existing_note(filename: str, *, status: str, eligible_for_injection: str, reason: str, action: str) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None
    path = _safe_note_path(runtime.base_dir, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Memory note not found")
    _update_note_frontmatter(
        path,
        {
            "status": status,
            "eligible_for_injection": eligible_for_injection,
            "updated_at": utc_now_iso(),
            "invalidation_reason": reason.strip(),
        },
    )
    runtime.memory_facade.memory_manager.sync_index()
    runtime.refresh_indexes_for_path("durable_memory/notes")
    _append_governance_log(runtime.base_dir, action, [path.name], reason=reason)
    header = load_memory_header(path)
    return {
        "ok": True,
        "action": action,
        "filename": path.name,
        "header": _header_payload(header) if header else None,
    }


def _safe_note_path(base_dir: Path, filename: str) -> Path:
    safe_name = filename.strip()
    if not safe_name or "/" in safe_name or "\\" in safe_name or safe_name.startswith(".") or not safe_name.endswith(".md"):
        raise HTTPException(status_code=400, detail="Invalid memory filename")
    return base_dir / "durable_memory" / "notes" / safe_name


def _unique_trash_path(trash_dir: Path, filename: str) -> Path:
    candidate = trash_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    timestamp = re.sub(r"[^0-9]", "", utc_now_iso())[:14] or "deleted"
    index = 2
    candidate = trash_dir / f"{stem}.{timestamp}{suffix}"
    while candidate.exists():
        candidate = trash_dir / f"{stem}.{timestamp}-{index}{suffix}"
        index += 1
    return candidate


def _update_note_frontmatter(path: Path, updates: dict[str, str]) -> None:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(raw)
    if not frontmatter:
        raise HTTPException(status_code=400, detail="Memory note has no frontmatter")
    merged = {**frontmatter, **updates}
    path.write_text(f"{format_frontmatter(merged)}\n\n{body.strip()}\n", encoding="utf-8", newline="\n")


def _unique_slug(manager: Any, title: str) -> str:
    base_slug = manager.slugify(title)
    if base_slug == "memory-note":
        digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
        base_slug = f"memory-{digest}"
    slug = base_slug
    index = 2
    while manager.note_path(slug).exists():
        slug = f"{base_slug}-{index}"
        index += 1
    return slug


def _normalize_choice(value: str, allowed: set[str], fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z_-]", "", value.strip().lower())
    return normalized if normalized in allowed else fallback


def _build_note_body(canonical: str, hints: list[str], why: str, evidence: str) -> str:
    hint_lines = "\n".join(f"- {item.strip()}" for item in hints if item.strip()) or "- 无"
    return (
        f"## Canonical Memory\n{canonical.strip()}\n\n"
        f"## Retrieval Hints\n{hint_lines}\n\n"
        f"## Why Stored\n{why.strip() or 'Manual durable memory governance'}\n\n"
        f"## Source Evidence\n{evidence.strip() or canonical.strip()}"
    )


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _append_governance_log(base_dir: Path, action: str, filenames: list[str], *, reason: str = "", created: str = "") -> None:
    mapped_action = {
        "create": "manual_create",
        "disable": "manual_disable",
        "activate": "manual_activate",
        "archive": "manual_archive",
        "delete": "manual_delete",
        "merge": "manual_merge",
    }.get(action, "manual_update")
    MemoryGovernance(base_dir).record(
        action=mapped_action,  # type: ignore[arg-type]
        commit_layer="long_term",
        target_refs=tuple(filenames),
        created_ref=created,
        reason=reason,
        actor="memory_governance_ui",
        allowed=True,
        metadata={"legacy_action": action},
    )
