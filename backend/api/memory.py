from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from artifact_system import ArtifactRepositoryService
from memory_system import MemoryHeader
from memory_system.governance_service import DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS
from memory_system.layout import durable_memory_namespace_id_for_task_environment
from memory_system.runtime_services import MemoryRuntimeServices
from project_layout import ProjectLayout
from request_intent.memory_intent import analyze_memory_intent
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

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


class DurableMemoryGovernanceTickRequest(BaseModel):
    reason: str = Field(default="", max_length=600)
    force: bool = False
    namespace_id: str = Field(default="", max_length=200)
    task_environment_id: str = Field(default="", max_length=200)
    min_interval_seconds: int = Field(
        default=DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS,
        ge=0,
        le=7 * 24 * 60 * 60,
    )


class DurableMemoryMergeRequest(BaseModel):
    filenames: list[str] = Field(..., min_length=2, max_length=8)
    title: str = Field(..., min_length=1, max_length=160)
    canonical_statement: str = Field(..., min_length=1, max_length=1600)
    summary: str = Field(default="", max_length=1000)
    reason: str = Field(default="", max_length=600)


def _layout_from_runtime(runtime: Any) -> ProjectLayout:
    assert runtime.base_dir is not None
    return ProjectLayout.from_backend_dir(runtime.base_dir)


def _memory_runtime_services(runtime: Any) -> MemoryRuntimeServices:
    layout = _layout_from_runtime(runtime)
    facade_services = getattr(getattr(runtime, "memory_facade", None), "runtime_services", None)
    if isinstance(facade_services, MemoryRuntimeServices):
        return facade_services
    return MemoryRuntimeServices(layout.storage_root)


def _formal_memory_service(runtime: Any):
    return _memory_runtime_services(runtime).formal_memory


def _artifact_repository_service(runtime: Any) -> ArtifactRepositoryService:
    layout = _layout_from_runtime(runtime)
    return ArtifactRepositoryService(layout.storage_root / "artifact_repository")


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

    headers = runtime.memory_facade.governance_service.scan_durable_memory_headers(limit=limit)
    session_inspect = None
    if session_id:
        session_inspect = _inspect_session_memory(runtime, session_id, query=query)

    return {
        "session_id": session_id or "",
        "query": query,
        "durable_memory": _durable_overview(headers, _durable_maintenance_runtime(runtime.memory_facade)),
        "session_memory": session_inspect,
    }


@router.get("/memory/formal/overview")
async def get_formal_memory_overview(
    task_run_id: str = "",
    repository_id: str = "",
    collection_id: str = "",
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    runtime = require_runtime()
    return _formal_memory_service(runtime).overview(
        task_run_id=task_run_id.strip(),
        repository_id=repository_id.strip(),
        collection_id=collection_id.strip(),
        limit=limit,
    )


@router.get("/memory/formal/repositories")
async def list_formal_memory_repositories(
    task_run_id: str = "",
    repository_id: str = "",
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    runtime = require_runtime()
    overview = _formal_memory_service(runtime).overview(
        task_run_id=task_run_id.strip(),
        repository_id=repository_id.strip(),
        limit=limit,
    )
    return {
        "task_run_id": task_run_id,
        "repository_id": repository_id,
        "repositories": overview["repositories"],
        "authority": "formal_memory.repositories_api",
    }


@router.get("/memory/formal/records")
async def list_formal_memory_records(
    task_run_id: str = "",
    repository_id: str = "",
    collection_id: str = "",
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    runtime = require_runtime()
    overview = _formal_memory_service(runtime).overview(
        task_run_id=task_run_id.strip(),
        repository_id=repository_id.strip(),
        collection_id=collection_id.strip(),
        limit=limit,
    )
    return {
        "task_run_id": task_run_id,
        "repository_id": repository_id,
        "collection_id": collection_id,
        "records": overview["records"],
        "versions": overview["versions"],
        "authority": "formal_memory.records_api",
    }


@router.get("/memory/formal/read-logs")
async def list_formal_memory_read_logs(
    task_run_id: str = "",
    repository_id: str = "",
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    runtime = require_runtime()
    overview = _formal_memory_service(runtime).overview(
        task_run_id=task_run_id.strip(),
        repository_id=repository_id.strip(),
        limit=limit,
    )
    return {
        "task_run_id": task_run_id,
        "repository_id": repository_id,
        "read_logs": overview["read_logs"],
        "authority": "formal_memory.read_logs_api",
    }


@router.get("/memory/artifacts/overview")
async def get_artifact_repository_overview(
    task_run_id: str = "",
    repository_id: str = "",
    collection_id: str = "",
    status: str = "",
    graph_id: str = "",
    graph_run_id: str = "",
    stage_id: str = "",
    node_run_id: str = "",
    task_ref: str = "",
    output_contract_id: str = "",
    producer_node_id: str = "",
    artifact_kind: str = "",
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    runtime = require_runtime()
    return _artifact_repository_service(runtime).overview(
        task_run_id=task_run_id.strip(),
        repository_id=repository_id.strip(),
        collection_id=collection_id.strip(),
        status=status.strip(),
        graph_id=graph_id.strip(),
        graph_run_id=graph_run_id.strip(),
        stage_id=stage_id.strip(),
        node_run_id=node_run_id.strip(),
        task_ref=task_ref.strip(),
        output_contract_id=output_contract_id.strip(),
        producer_node_id=producer_node_id.strip(),
        artifact_kind=artifact_kind.strip(),
        limit=limit,
    )


@router.get("/memory/artifacts/records")
async def list_artifact_repository_records(
    task_run_id: str = "",
    repository_id: str = "",
    collection_id: str = "",
    status: str = "",
    graph_id: str = "",
    graph_run_id: str = "",
    stage_id: str = "",
    node_run_id: str = "",
    task_ref: str = "",
    output_contract_id: str = "",
    producer_node_id: str = "",
    artifact_kind: str = "",
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    runtime = require_runtime()
    overview = _artifact_repository_service(runtime).overview(
        task_run_id=task_run_id.strip(),
        repository_id=repository_id.strip(),
        collection_id=collection_id.strip(),
        status=status.strip(),
        graph_id=graph_id.strip(),
        graph_run_id=graph_run_id.strip(),
        stage_id=stage_id.strip(),
        node_run_id=node_run_id.strip(),
        task_ref=task_ref.strip(),
        output_contract_id=output_contract_id.strip(),
        producer_node_id=producer_node_id.strip(),
        artifact_kind=artifact_kind.strip(),
        limit=limit,
    )
    return {
        "task_run_id": task_run_id,
        "repository_id": repository_id,
        "collection_id": collection_id,
        "status": status,
        "graph_id": graph_id,
        "graph_run_id": graph_run_id,
        "stage_id": stage_id,
        "node_run_id": node_run_id,
        "task_ref": task_ref,
        "output_contract_id": output_contract_id,
        "producer_node_id": producer_node_id,
        "artifact_kind": artifact_kind,
        "artifacts": overview["artifacts"],
        "authority": "artifact_repository.records_api",
    }


@router.post("/memory/durable")
async def create_durable_memory_note(payload: DurableMemoryCreateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.base_dir is not None
    assert runtime.memory_facade is not None

    result = runtime.memory_facade.governance_service.create_durable_memory_note(
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

    result = runtime.memory_facade.governance_service.delete_durable_memory_note(
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

    result = runtime.memory_facade.governance_service.merge_durable_memory_notes(
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


@router.get("/memory/durable/governance/runtime")
async def get_durable_memory_governance_runtime() -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None
    return runtime.memory_facade.governance_service.describe_runtime_state()


@router.post("/memory/durable/governance/tick")
async def run_durable_memory_governance_tick(payload: DurableMemoryGovernanceTickRequest) -> dict[str, Any]:
    runtime = require_runtime()
    assert runtime.memory_facade is not None

    namespace_ids: list[str] = []
    if payload.namespace_id.strip():
        namespace_ids.append(payload.namespace_id.strip())
    elif payload.task_environment_id.strip():
        namespace_ids.append(durable_memory_namespace_id_for_task_environment(payload.task_environment_id.strip()))

    result = runtime.memory_facade.run_durable_memory_governance_tick(
        namespace_ids=namespace_ids or None,
        force=payload.force,
        min_interval_seconds=payload.min_interval_seconds,
        reason=payload.reason or "manual_api",
        source="api.memory.durable_governance_tick",
    )
    ran = [dict(item or {}) for item in list(result.get("ran") or [])]
    if any(str(item.get("namespace_id") or "") == "global_common" and int(item.get("updated") or 0) > 0 for item in ran):
        runtime.retrieval_service.rebuild_durable_memory()
    return result


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

    result = runtime.memory_facade.bundle_service.recall_durable_memories(
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
async def get_session_memory_files(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(
            workspace_view=workspace_view,
            task_environment_id=task_environment_id,
            project_id=project_id,
        ),
    )
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

    loaded = runtime.memory_facade.governance_service.load_durable_memory_note(safe_name)
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
    result = runtime.memory_facade.bundle_service.build_memory_context_package_result(
        session_id=session_id,
        query=query.strip() or None,
        memory_intent=intent,
        note_limit=limit,
        memory_request_profile={
            "requested_memory_layers": ["state", "long_term"],
            "allow_long_term_memory": True,
        },
    )
    payload = result.to_dict()
    package = dict(payload.get("package") or {})
    sections = dict(package.get("model_visible_sections") or {})
    memory_view = runtime.memory_facade.bundle_service.build_memory_runtime_view(
        session_id=session_id,
        query=query.strip() or None,
        memory_intent=intent,
        note_limit=limit,
        memory_request_profile={
            "requested_memory_layers": ["state", "long_term"],
            "allow_long_term_memory": True,
        },
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
        "durable_matches": {"long_term_candidate_count": int(memory_view.diagnostics.get("long_term_candidate_count") or 0)},
        "maintenance_runtime": runtime.memory_facade.describe_memory_maintenance_runtime(),
    }


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _durable_overview(headers: list[MemoryHeader], maintenance_runtime: dict[str, object]) -> dict[str, Any]:
    by_type = Counter(header.memory_type or "project" for header in headers)
    by_class = Counter(header.memory_class or "work" for header in headers)
    return {
        "total": len(headers),
        "active": sum(1 for header in headers if header.status == "active"),
        "injectable": sum(1 for header in headers if header.eligible_for_injection),
        "by_type": dict(by_type),
        "by_class": dict(by_class),
        "headers": [_header_payload(header) for header in headers],
        "maintenance_runtime": maintenance_runtime,
    }


def _durable_maintenance_runtime(memory_facade: Any) -> dict[str, object]:
    return {
        **memory_facade.bundle_service.describe_durable_maintenance_runtime(),
        "memory_maintenance": memory_facade.describe_memory_maintenance_runtime(),
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
    assert runtime.memory_facade is not None
    result = runtime.memory_facade.governance_service.set_durable_memory_note_status(
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



