from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from memory_system import MemoryHeader
from project_layout import ProjectLayout
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


class WorkingMemoryFinalizeRequest(BaseModel):
    actor_id: str = Field(default="memory_governance_ui", max_length=160)
    terminal_reason: str = Field(default="completed", max_length=120)
    policy: dict[str, Any] = Field(default_factory=dict)


class WorkingMemoryPromoteTaskDurableRequest(BaseModel):
    title: str = Field(default="", max_length=160)
    canonical_statement: str = Field(default="", max_length=1600)
    summary: str = Field(default="", max_length=1000)
    namespace_id: str = Field(default="", max_length=180)
    task_family: str = Field(default="", max_length=120)
    domain_id: str = Field(default="", max_length=160)
    task_id: str = Field(default="", max_length=160)
    graph_id: str = Field(default="", max_length=160)
    project_id: str = Field(default="", max_length=160)
    artifact_namespace: str = Field(default="", max_length=180)
    memory_type: str = Field(default="project", max_length=40)
    memory_class: str = Field(default="work", max_length=40)
    retrieval_hints: list[str] = Field(default_factory=list, max_length=8)
    confidence: str = Field(default="medium", max_length=40)
    actor_id: str = Field(default="memory_governance_ui", max_length=160)
    reason: str = Field(default="", max_length=600)


class WorkingMemoryGovernRequest(BaseModel):
    actor_id: str = Field(default="memory_governance_ui", max_length=160)
    reason: str = Field(default="", max_length=600)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskDurableGlobalCandidateRequest(BaseModel):
    actor_id: str = Field(default="memory_governance_ui", max_length=160)
    reason: str = Field(default="", max_length=600)


class TaskDurablePromoteGlobalRequest(BaseModel):
    title: str = Field(default="", max_length=160)
    canonical_statement: str = Field(default="", max_length=1600)
    summary: str = Field(default="", max_length=1000)
    global_kind: str = Field(default="", max_length=80)
    memory_type: str = Field(default="project", max_length=40)
    memory_class: str = Field(default="work", max_length=40)
    confidence: str = Field(default="medium", max_length=40)
    actor_id: str = Field(default="memory_governance_ui", max_length=160)
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

    headers = runtime.memory_facade.scan_durable_memory_headers(limit=limit)
    session_inspect = None
    if session_id:
        session_inspect = _inspect_session_memory(runtime, session_id, query=query)

    return {
        "session_id": session_id or "",
        "query": query,
        "durable_memory": _durable_overview(headers, runtime.memory_facade.describe_durable_extraction_runtime()),
        "session_memory": session_inspect,
        "working_memory": _working_memory_overview(runtime, query=query, limit=limit),
        "task_durable_memory": _task_durable_memory_overview(runtime, query=query, limit=limit),
    }


@router.get("/memory/working/overview")
async def get_working_memory_overview(
    task_run_id: str = "",
    graph_id: str = "",
    owner_node_id: str = "",
    node_run_id: str = "",
    writer_agent_id: str = "",
    status: str = "",
    kind: str = "",
    query: str = "",
    limit: int = Query(default=160, ge=1, le=500),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    filters = {
        "task_run_id": task_run_id,
        "graph_id": graph_id,
        "owner_node_id": owner_node_id,
        "node_run_id": node_run_id,
        "writer_agent_id": writer_agent_id,
        "status": status,
        "kind": kind,
    }
    return _working_memory_overview(runtime, query=query, limit=limit, filters=filters)


@router.get("/memory/working/items/{work_memory_id}")
async def get_working_memory_item(work_memory_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    safe_id = work_memory_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid working memory id")
    item = runtime.memory_facade.get_working_memory_item(safe_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Working memory item not found")
    item_payload = item.to_dict()
    task_run_id = str(item_payload.get("task_run_id") or "")
    return {
        "item": _working_memory_item_payload(item_payload),
        "read_logs": [
            _working_memory_read_log_payload(log.to_dict())
            for log in runtime.memory_facade.list_working_memory_read_logs(task_run_id, limit=200)
            if safe_id in set(log.selected_item_ids) or safe_id in set(log.excluded_item_ids)
        ],
        "temporal_edges": [
            _working_memory_temporal_edge_payload(edge.to_dict())
            for edge in runtime.memory_facade.list_working_memory_temporal_edges(task_run_id)
            if edge.source_item_id == safe_id or edge.target_item_id == safe_id
        ],
        "handoff_transactions": [
            _working_memory_handoff_payload(transaction.to_dict())
            for transaction in runtime.memory_facade.list_working_memory_handoff_transactions(task_run_id)
            if safe_id in set(transaction.candidate_work_memory_ids)
            or safe_id in set(transaction.adopted_work_memory_ids)
            or safe_id in set(transaction.rejected_work_memory_ids)
        ],
    }


@router.post("/memory/working/runs/{task_run_id}/finalize")
async def finalize_working_memory_task_run(task_run_id: str, payload: WorkingMemoryFinalizeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    safe_id = task_run_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid task run id")
    result = runtime.memory_facade.finalize_working_memory_task_run(
        safe_id,
        actor_id=payload.actor_id,
        terminal_reason=payload.terminal_reason,
        policy=dict(payload.policy or {}),
    )
    return {
        "ok": True,
        "result": result.to_dict(),
    }


@router.get("/memory/task-durable/overview")
async def get_task_durable_memory_overview(
    namespace_id: str = "",
    task_family: str = "",
    domain_id: str = "",
    task_id: str = "",
    graph_id: str = "",
    project_id: str = "",
    artifact_namespace: str = "",
    kind: str = "",
    memory_semantics: str = "",
    status: str = "",
    query: str = "",
    limit: int = Query(default=160, ge=1, le=500),
) -> dict[str, Any]:
    runtime = require_runtime()
    filters = {
        "namespace_id": namespace_id,
        "task_family": task_family,
        "domain_id": domain_id,
        "task_id": task_id,
        "graph_id": graph_id,
        "project_id": project_id,
        "artifact_namespace": artifact_namespace,
        "kind": kind,
        "memory_semantics": memory_semantics,
        "status": status,
    }
    return _task_durable_memory_overview(runtime, query=query, limit=limit, filters=filters)


@router.get("/memory/task-durable/namespaces")
async def list_task_durable_memory_namespaces() -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None
    namespaces = runtime.memory_facade.list_task_durable_memory_namespaces()
    return {
        "namespaces": [_task_durable_namespace_payload(namespace.to_dict()) for namespace in namespaces],
    }


@router.get("/memory/task-durable/items/{task_memory_id}")
async def get_task_durable_memory_item(task_memory_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None
    safe_id = task_memory_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid task durable memory id")
    item = runtime.memory_facade.get_task_durable_memory_item(safe_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Task durable memory item not found")
    return {"item": _task_durable_item_payload(item.to_dict())}


@router.post("/memory/task-durable/items/{task_memory_id}/promote-global-candidate")
async def mark_task_durable_global_candidate(
    task_memory_id: str,
    payload: TaskDurableGlobalCandidateRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None
    safe_id = task_memory_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid task durable memory id")
    try:
        result = runtime.memory_facade.mark_task_durable_item_global_candidate(
            safe_id,
            actor_id=payload.actor_id,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True,
        "action": "mark_global_candidate",
        "task_memory": _task_durable_item_payload(result["task_memory"].to_dict()),
    }


@router.post("/memory/task-durable/items/{task_memory_id}/promote-global")
async def promote_task_durable_to_global(
    task_memory_id: str,
    payload: TaskDurablePromoteGlobalRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None
    safe_id = task_memory_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid task durable memory id")
    try:
        result = runtime.memory_facade.promote_task_durable_item_to_global_durable(
            safe_id,
            title=payload.title,
            canonical_statement=payload.canonical_statement,
            summary=payload.summary,
            global_kind=payload.global_kind,
            memory_type=payload.memory_type,
            memory_class=payload.memory_class,
            confidence=payload.confidence,
            actor_id=payload.actor_id,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if hasattr(runtime, "refresh_indexes_for_path"):
        runtime.refresh_indexes_for_path("durable_memory/notes")
    return {
        "ok": True,
        "action": "promote_to_global_durable",
        "filename": result["filename"],
        "header": _header_payload(result["header"]) if result.get("header") else None,
        "task_memory": _task_durable_item_payload(result["task_memory"].to_dict()),
    }


@router.post("/memory/working/items/{work_memory_id}/promote-task-durable")
async def promote_working_memory_item_to_task_durable(
    work_memory_id: str,
    payload: WorkingMemoryPromoteTaskDurableRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    safe_id = work_memory_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid working memory id")
    try:
        result = runtime.memory_facade.promote_working_memory_item_to_task_durable(
            safe_id,
            title=payload.title,
            canonical_statement=payload.canonical_statement,
            summary=payload.summary,
            namespace_id=payload.namespace_id,
            task_family=payload.task_family,
            domain_id=payload.domain_id,
            task_id=payload.task_id,
            graph_id=payload.graph_id,
            project_id=payload.project_id,
            artifact_namespace=payload.artifact_namespace,
            memory_type=payload.memory_type,
            memory_class=payload.memory_class,
            retrieval_hints=list(payload.retrieval_hints),
            confidence=payload.confidence,
            actor_id=payload.actor_id,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "action": "promote_to_task_durable",
        "work_memory_id": safe_id,
        "task_memory": _task_durable_item_payload(result["task_memory"].to_dict()),
        "item": _working_memory_item_payload(result["item"].to_dict()),
    }


@router.post("/memory/working/items/{work_memory_id}/accept")
async def accept_working_memory_item(work_memory_id: str, payload: WorkingMemoryGovernRequest) -> dict[str, Any]:
    return _govern_working_memory_item(
        work_memory_id,
        action="accept",
        payload=payload,
    )


@router.post("/memory/working/items/{work_memory_id}/discard")
async def discard_working_memory_item(work_memory_id: str, payload: WorkingMemoryGovernRequest) -> dict[str, Any]:
    return _govern_working_memory_item(
        work_memory_id,
        action="discard",
        payload=payload,
    )


@router.post("/memory/working/items/{work_memory_id}/conflict")
async def mark_working_memory_item_conflict(work_memory_id: str, payload: WorkingMemoryGovernRequest) -> dict[str, Any]:
    return _govern_working_memory_item(
        work_memory_id,
        action="conflict",
        payload=payload,
    )


@router.post("/memory/durable")
async def create_durable_memory_note(payload: DurableMemoryCreateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    result = runtime.memory_facade.create_durable_memory_note(
        title=payload.title,
        canonical_statement=payload.canonical_statement,
        summary=payload.summary,
        memory_type=payload.memory_type,
        memory_class=payload.memory_class,
        retrieval_hints=list(payload.retrieval_hints),
        confidence=payload.confidence,
        source_kind=payload.source_kind,
        source_message_excerpt=payload.source_message_excerpt,
    )
    runtime.refresh_indexes_for_path("durable_memory/notes")
    return {
        "ok": True,
        "action": "create",
        "filename": result["filename"],
        "header": _header_payload(result["header"]) if result.get("header") else None,
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
    assert runtime.memory_facade is not None

    result = runtime.memory_facade.delete_durable_memory_note(
        filename=filename,
        reason=payload.reason if payload else "",
    )
    runtime.refresh_indexes_for_path("durable_memory/notes")
    return {
        "ok": True,
        "action": "delete",
        "filename": result["filename"],
        "deleted_at": result["deleted_at"],
        "trash_path": result["trash_path"],
        "header": None,
    }


@router.post("/memory/durable/merge")
async def merge_durable_memory_notes(payload: DurableMemoryMergeRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    result = runtime.memory_facade.merge_durable_memory_notes(
        filenames=list(payload.filenames),
        title=payload.title,
        canonical_statement=payload.canonical_statement,
        summary=payload.summary,
        reason=payload.reason,
    )
    runtime.refresh_indexes_for_path("durable_memory/notes")
    return {
        "ok": True,
        "action": "merge",
        "filename": result["filename"],
        "merged": list(result["merged"]),
        "header": _header_payload(result["header"]) if result.get("header") else None,
    }


@router.post("/memory/recall-preview")
async def recall_memory_preview(payload: RecallPreviewRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    query = payload.query.strip()
    intent = analyze_memory_intent(query)
    session_summary = ""
    context_result = None

    if payload.session_id:
        history_payload = runtime.session_manager.get_history(payload.session_id)
        session_summary = str(history_payload.get("compressed_context", "") or "")
        context_result = _inspect_session_memory(runtime, payload.session_id, query=query, limit=payload.limit)

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
        "context_result": context_result,
    }


@router.get("/memory/session/{session_id}/files")
async def get_session_memory_files(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None

    safe_session_id = _safe_session_id(session_id)
    session_dir = ProjectLayout.from_backend_dir(runtime.base_dir).session_memory_dir / safe_session_id
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

    loaded = runtime.memory_facade.load_durable_memory_note(safe_name)
    return {
        "header": _header_payload(loaded["header"]) if loaded.get("header") else None,
        "content_preview": _compact_text(str(loaded.get("content") or ""), 2600),
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
    result = runtime.memory_facade.build_memory_context_package_result(
        session_id=session_id,
        query=query.strip() or None,
        memory_intent=intent,
        note_limit=limit,
    )
    payload = result.to_dict()
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


def _working_memory_overview(
    runtime: Any,
    *,
    query: str = "",
    limit: int = 160,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert runtime.memory_facade is not None
    normalized_filters = dict(filters or {})
    normalized_limit = _safe_int(limit, 160)
    items = [
        item.to_dict()
        for item in runtime.memory_facade.query_working_memory_items(
            limit=normalized_limit,
            **normalized_filters,
        )
    ]
    normalized_query = query.strip().lower()
    if normalized_query:
        items = [
            item
            for item in items
            if normalized_query
            in " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("kind") or ""),
                    str(item.get("memory_semantics") or ""),
                    str(item.get("status") or ""),
                    str(item.get("owner_node_id") or ""),
                    str(item.get("writer_agent_id") or ""),
                    json.dumps(item.get("payload") or {}, ensure_ascii=False),
                    " ".join(str(part) for part in list(item.get("tags") or [])),
                ]
            ).lower()
        ]
    read_logs = [log.to_dict() for log in runtime.memory_facade.list_working_memory_read_logs(normalized_filters.get("task_run_id", ""), limit=400)]
    temporal_edges = [edge.to_dict() for edge in runtime.memory_facade.list_working_memory_temporal_edges(normalized_filters.get("task_run_id", ""))]
    handoff_transactions = [tx.to_dict() for tx in runtime.memory_facade.list_working_memory_handoff_transactions(normalized_filters.get("task_run_id", ""))]

    by_status = Counter(str(item.get("status") or "") for item in items)
    by_kind = Counter(str(item.get("kind") or "") for item in items)
    by_owner_node = Counter(str(item.get("owner_node_id") or "") for item in items)
    by_writer_agent = Counter(str(item.get("writer_agent_id") or "") for item in items)

    conflict_items = [item for item in items if str(item.get("status") or "") == "conflicted" or str(item.get("memory_semantics") or "") == "conflict"]
    promotion_candidates = [
        item
        for item in items
        if str(item.get("promotion_state") or "") not in {"", "not_applicable", "rejected"}
    ]
    archived_items = [item for item in items if str(item.get("status") or "") in {"archived", "promoted", "discarded"}]
    active_runs = sorted({str(item.get("task_run_id") or "") for item in items if str(item.get("task_run_id") or "").strip()})

    return {
        "query": query,
        "filters": normalized_filters,
        "total": len(items),
        "active_run_ids": active_runs,
        "by_status": dict(by_status),
        "by_kind": dict(by_kind),
        "by_owner_node": dict(by_owner_node),
        "by_writer_agent": dict(by_writer_agent),
        "items": [_working_memory_item_payload(item) for item in items],
        "conflict_items": [_working_memory_item_payload(item) for item in conflict_items],
        "promotion_candidates": [_working_memory_item_payload(item) for item in promotion_candidates],
        "archived_items": [_working_memory_item_payload(item) for item in archived_items],
        "read_logs": [_working_memory_read_log_payload(log) for log in read_logs],
        "temporal_edges": [_working_memory_temporal_edge_payload(edge) for edge in temporal_edges],
        "handoff_transactions": [_working_memory_handoff_payload(tx) for tx in handoff_transactions],
    }


def _working_memory_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload["summary"] = _compact_text(str(item.get("summary") or ""), 420)
    payload["title"] = _compact_text(str(item.get("title") or ""), 180)
    payload["payload_preview"] = _compact_text(json.dumps(item.get("payload") or {}, ensure_ascii=False), 800)
    payload["tags"] = list(item.get("tags") or [])
    payload["artifact_refs"] = list(item.get("artifact_refs") or [])
    payload["contract_refs"] = list(item.get("contract_refs") or [])
    payload["source_event_refs"] = list(item.get("source_event_refs") or [])
    payload["source_message_refs"] = list(item.get("source_message_refs") or [])
    payload["temporal_refs"] = list(item.get("temporal_refs") or [])
    payload["conflict_refs"] = list(item.get("conflict_refs") or [])
    return payload


def _task_durable_memory_overview(
    runtime: Any,
    *,
    query: str = "",
    limit: int = 160,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert runtime.memory_facade is not None
    normalized_filters = dict(filters or {})
    items = [
        item.to_dict()
        for item in runtime.memory_facade.query_task_durable_memory_items(
            limit=_safe_int(limit, 160),
            **normalized_filters,
        )
    ]
    normalized_query = query.strip().lower()
    if normalized_query:
        items = [
            item
            for item in items
            if normalized_query
            in " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("canonical_statement") or ""),
                    str(item.get("kind") or ""),
                    str(item.get("memory_semantics") or ""),
                    str(item.get("namespace_id") or ""),
                    str(item.get("task_id") or ""),
                    str(item.get("graph_id") or ""),
                    str(item.get("project_id") or ""),
                    " ".join(str(part) for part in list(item.get("retrieval_hints") or [])),
                ]
            ).lower()
        ]
    namespaces = [namespace.to_dict() for namespace in runtime.memory_facade.list_task_durable_memory_namespaces()]
    by_status = Counter(str(item.get("status") or "") for item in items)
    by_namespace = Counter(str(item.get("namespace_id") or "") for item in items)
    by_kind = Counter(str(item.get("kind") or "") for item in items)
    global_candidates = [
        item
        for item in items
        if bool(item.get("eligible_for_global_promotion"))
        or str(item.get("global_promotion_state") or "") not in {"", "not_applicable"}
    ]
    return {
        "query": query,
        "filters": normalized_filters,
        "total": len(items),
        "namespace_count": len(namespaces),
        "by_status": dict(by_status),
        "by_namespace": dict(by_namespace),
        "by_kind": dict(by_kind),
        "namespaces": [_task_durable_namespace_payload(namespace) for namespace in namespaces],
        "items": [_task_durable_item_payload(item) for item in items],
        "global_promotion_candidates": [_task_durable_item_payload(item) for item in global_candidates],
    }


def _task_durable_namespace_payload(namespace: dict[str, Any]) -> dict[str, Any]:
    return {
        "namespace_id": str(namespace.get("namespace_id") or ""),
        "task_family": str(namespace.get("task_family") or ""),
        "domain_id": str(namespace.get("domain_id") or ""),
        "task_id": str(namespace.get("task_id") or ""),
        "graph_id": str(namespace.get("graph_id") or ""),
        "project_id": str(namespace.get("project_id") or ""),
        "artifact_namespace": str(namespace.get("artifact_namespace") or ""),
        "item_count": int(namespace.get("item_count") or 0),
        "updated_at": str(namespace.get("updated_at") or ""),
    }


def _task_durable_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload["summary"] = _compact_text(str(item.get("summary") or ""), 520)
    payload["canonical_statement"] = _compact_text(str(item.get("canonical_statement") or ""), 700)
    payload["payload_preview"] = _compact_text(json.dumps(item.get("payload") or {}, ensure_ascii=False), 900)
    payload["source_work_memory_ids"] = list(item.get("source_work_memory_ids") or [])
    payload["source_artifact_refs"] = list(item.get("source_artifact_refs") or [])
    payload["retrieval_hints"] = list(item.get("retrieval_hints") or [])
    return payload


def _govern_working_memory_item(
    work_memory_id: str,
    *,
    action: str,
    payload: WorkingMemoryGovernRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    safe_id = work_memory_id.strip()
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid working memory id")
    metadata = {
        **dict(payload.metadata or {}),
        "governance_reason": payload.reason,
        "governance_action": action,
    }
    try:
        if action == "accept":
            item = runtime.memory_facade.accept_working_memory_item(
                safe_id,
                actor_id=payload.actor_id,
                metadata=metadata,
            )
        elif action == "discard":
            item = runtime.memory_facade.discard_working_memory_item(
                safe_id,
                actor_id=payload.actor_id,
                metadata=metadata,
            )
        elif action == "conflict":
            item = runtime.memory_facade.mark_working_memory_conflict(
                safe_id,
                actor_id=payload.actor_id,
                metadata=metadata,
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid working memory governance action")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True,
        "action": action,
        "work_memory_id": safe_id,
        "item": _working_memory_item_payload(item.to_dict()),
    }


def _working_memory_read_log_payload(log: dict[str, Any]) -> dict[str, Any]:
    return {
        "read_log_id": str(log.get("read_log_id") or ""),
        "task_run_id": str(log.get("task_run_id") or ""),
        "graph_id": str(log.get("graph_id") or ""),
        "owner_node_id": str(log.get("owner_node_id") or ""),
        "node_run_id": str(log.get("node_run_id") or ""),
        "run_attempt_id": str(log.get("run_attempt_id") or ""),
        "reader_agent_id": str(log.get("reader_agent_id") or ""),
        "request": dict(log.get("request") or {}),
        "selected_item_ids": list(log.get("selected_item_ids") or []),
        "excluded_item_ids": list(log.get("excluded_item_ids") or []),
        "token_estimate": int(log.get("token_estimate") or 0),
        "denied_reason": str(log.get("denied_reason") or ""),
        "created_at": str(log.get("created_at") or ""),
        "authority": str(log.get("authority") or ""),
    }


def _working_memory_temporal_edge_payload(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "task_run_id": str(edge.get("task_run_id") or ""),
        "graph_id": str(edge.get("graph_id") or ""),
        "source_item_id": str(edge.get("source_item_id") or ""),
        "target_item_id": str(edge.get("target_item_id") or ""),
        "relation": str(edge.get("relation") or ""),
        "confidence": float(edge.get("confidence") or 0.0),
        "source_node_id": str(edge.get("source_node_id") or ""),
        "created_at": str(edge.get("created_at") or ""),
        "metadata": dict(edge.get("metadata") or {}),
        "authority": str(edge.get("authority") or ""),
    }


def _working_memory_handoff_payload(transaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "transaction_id": str(transaction.get("transaction_id") or ""),
        "task_run_id": str(transaction.get("task_run_id") or ""),
        "graph_id": str(transaction.get("graph_id") or ""),
        "edge_id": str(transaction.get("edge_id") or ""),
        "source_node_run_id": str(transaction.get("source_node_run_id") or ""),
        "target_node_run_id": str(transaction.get("target_node_run_id") or ""),
        "handoff_id": str(transaction.get("handoff_id") or ""),
        "source_message_hash": str(transaction.get("source_message_hash") or ""),
        "idempotency_key": str(transaction.get("idempotency_key") or ""),
        "candidate_work_memory_ids": list(transaction.get("candidate_work_memory_ids") or []),
        "adopted_work_memory_ids": list(transaction.get("adopted_work_memory_ids") or []),
        "rejected_work_memory_ids": list(transaction.get("rejected_work_memory_ids") or []),
        "ephemeral_context_refs": list(transaction.get("ephemeral_context_refs") or []),
        "transaction_status": str(transaction.get("transaction_status") or ""),
        "created_at": str(transaction.get("created_at") or ""),
        "committed_at": str(transaction.get("committed_at") or ""),
        "metadata": dict(transaction.get("metadata") or {}),
        "authority": str(transaction.get("authority") or ""),
    }


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


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
    assert runtime.memory_facade is not None
    result = runtime.memory_facade.set_durable_memory_note_status(
        filename=filename,
        status=status,
        eligible_for_injection=eligible_for_injection,
        reason=reason,
        action=action,
    )
    runtime.refresh_indexes_for_path("durable_memory/notes")
    return {
        "ok": True,
        "action": action,
        "filename": result["filename"],
        "header": _header_payload(result["header"]) if result.get("header") else None,
    }
