from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from api.session_summary import enrich_session_summaries
from harness.runtime.session_lifecycle import SessionRuntimeLifecycleManager
from integrations.vscode_connection import get_vscode_connection_store
from sessions import InvalidSessionId, SessionProjectBindingConflict, SessionProjectBindingMissing
from harness.runtime.session_timeline import build_session_runtime_timeline
from task_system.environments import task_environment_registry_from_backend_dir
from task_system.session_scope import assert_optional_session_scope, normalize_session_scope, request_scope_from_query

router = APIRouter()

DEFAULT_SESSION_TITLE = "New Session"


class CreateSessionRequest(BaseModel):
    title: str = DEFAULT_SESSION_TITLE
    scope: dict[str, Any] = Field(default_factory=dict)
    project_binding: dict[str, Any] = Field(default_factory=dict)


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class GenerateTitleRequest(BaseModel):
    message: str | None = None


class TruncateMessagesRequest(BaseModel):
    message_index: int = Field(..., ge=0)


class ActiveTaskEnvironmentRequest(BaseModel):
    task_environment_id: str = Field(..., min_length=3, max_length=200)
    environment_label: str = Field(default="", max_length=200)
    source: str = Field(default="conversation", max_length=80)


class SessionPermissionModeRequest(BaseModel):
    mode: str = Field(..., min_length=1, max_length=80)


class ProjectBindingRequest(BaseModel):
    workspace_root: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(default="manual", max_length=80)


@router.get("/sessions")
async def list_sessions(
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
    include_active_task: bool = Query(default=False),
) -> list[dict[str, Any]]:
    runtime = require_runtime()
    sessions = runtime.session_manager.list_sessions(
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )
    if not include_active_task:
        return sessions
    return enrich_session_summaries(sessions, runtime)


@router.post("/sessions")
async def create_session(payload: CreateSessionRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return runtime.session_manager.create_session(
            title=payload.title,
            scope=payload.scope,
            project_binding=payload.project_binding,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}")
async def get_session_summary(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    expected_scope = request_scope_from_query(
        workspace_view=workspace_view,
        task_environment_id=task_environment_id,
        project_id=project_id,
    )
    try:
        summary = runtime.session_manager.get_session_summary(session_id)
    except InvalidSessionId:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if expected_scope is not None:
        actual = normalize_session_scope(dict(summary.get("scope") or {}))
        expected = normalize_session_scope(expected_scope)
        if actual.to_dict() != expected.to_dict():
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Session scope mismatch",
                    "session_id": session_id,
                    "actual_scope": actual.to_dict(),
                    "expected_scope": expected.to_dict(),
                },
            )
    return summary


@router.put("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    payload: RenameSessionRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return runtime.session_manager.rename_session(session_id, payload.title)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    missing_session = False
    try:
        assert_optional_session_scope(
            runtime.session_manager,
            session_id,
            request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
        )
    except ValueError as exc:
        if str(exc) != "Unknown session_id":
            raise
        missing_session = True
    try:
        cleanup = await SessionRuntimeLifecycleManager(runtime).detach_session_runtime(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not missing_session:
        runtime.session_manager.delete_session(session_id)
    return {"ok": True, "cleanup": cleanup, "session_missing_before_delete": missing_session}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return {
        "messages": runtime.session_manager.load_session(session_id),
        "latest_prompt_manifest_summary": _latest_prompt_manifest_summary(runtime, session_id),
    }


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return runtime.session_manager.get_history(session_id)


@router.get("/sessions/{session_id}/conversation-state")
async def get_session_conversation_state(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return runtime.session_manager.get_conversation_state(session_id)


@router.put("/sessions/{session_id}/active-task-environment")
async def set_session_active_task_environment(
    session_id: str,
    payload: ActiveTaskEnvironmentRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    try:
        task_environment_registry_from_backend_dir(runtime.base_dir).require(payload.task_environment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown task environment: {payload.task_environment_id}") from exc
    return runtime.session_manager.set_active_task_environment(
        session_id,
        {
            "task_environment_id": payload.task_environment_id,
            "environment_label": payload.environment_label or payload.task_environment_id,
            "source": payload.source or "conversation",
        },
    )


@router.put("/sessions/{session_id}/permission-mode")
async def set_session_permission_mode(
    session_id: str,
    payload: SessionPermissionModeRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return runtime.session_manager.set_permission_mode(session_id, payload.mode)


@router.get("/sessions/{session_id}/project-binding")
async def get_session_project_binding(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    return {"project_binding": runtime.session_manager.get_project_binding(session_id)}


@router.put("/sessions/{session_id}/project-binding")
async def bind_session_project(
    session_id: str,
    payload: ProjectBindingRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    try:
        binding = runtime.session_manager.bind_project(
            session_id,
            workspace_root=payload.workspace_root,
            source=payload.source or "manual",
        )
    except SessionProjectBindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project_binding": binding}


@router.post("/sessions/{session_id}/project-binding/select-directory")
async def select_session_project_directory(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    try:
        selected_root = await asyncio.to_thread(_select_project_directory_with_windows_dialog)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not selected_root:
        raise HTTPException(status_code=409, detail="project directory selection cancelled")
    try:
        binding = runtime.session_manager.bind_project(
            session_id,
            workspace_root=selected_root,
            source="frontend.directory_picker",
        )
    except SessionProjectBindingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project_binding": binding, "selected_path": selected_root}


@router.post("/sessions/{session_id}/project-binding/open-vscode")
async def open_session_project_in_vscode(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    try:
        binding = runtime.session_manager.require_project_binding(session_id)
    except SessionProjectBindingMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    workspace_root = str(binding.get("workspace_root") or "").strip()
    connection_store = get_vscode_connection_store()
    current_status = connection_store.status(session_id, session_manager=runtime.session_manager)
    if current_status.connected and not current_status.stale and _same_resolved_path(current_status.workspace_root, workspace_root):
        return {
            "ok": True,
            "project_binding": binding,
            "command": [],
            "window_mode": "existing_project_connection",
            "connection_reused": True,
            "connection_status": current_status.to_dict(),
            "session_id": session_id,
        }
    executable = shutil.which("code")
    if not executable:
        raise HTTPException(status_code=503, detail="VS Code CLI `code` was not found on PATH")
    extension_installation = _ensure_vscode_connection_extension_installed()
    if not extension_installation:
        raise HTTPException(
            status_code=503,
            detail="VS Code connection extension is not built; run `npm run compile` in extensions/vscode",
        )
    connection_store.register_launch_intent(session_id=session_id, workspace_root=workspace_root)
    command = [executable, "--new-window", workspace_root]
    env = {
        **os.environ,
        "LANGCHAIN_AGENT_SESSION_ID": session_id,
        "LANGCHAIN_AGENT_WORKSPACE_ROOT": workspace_root,
    }
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        subprocess.Popen(
            command,
            creationflags=creationflags,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to open VS Code: {exc}") from exc
    return {
        "ok": True,
        "project_binding": binding,
        "command": command,
        "window_mode": "new_window",
        "extension_installation": extension_installation,
        "session_id": session_id,
    }


def _select_project_directory_with_windows_dialog() -> str:
    if not sys.platform.startswith("win"):
        raise RuntimeError("Native project directory selection is only available on Windows.")
    try:
        selected = _select_project_directory_with_tkinter()
    except Exception as tk_error:
        try:
            return _select_project_directory_with_powershell()
        except RuntimeError as ps_error:
            raise RuntimeError(f"{ps_error}; tkinter selection failed: {tk_error}") from ps_error
    return selected


def _same_resolved_path(left: object, right: object) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    try:
        return Path(left_text).expanduser().resolve() == Path(right_text).expanduser().resolve()
    except Exception:
        return left_text.casefold() == right_text.casefold()


def _select_project_directory_with_tkinter() -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(
            parent=root,
            title="选择要绑定到当前会话的项目目录",
            mustexist=True,
        )
        return str(selected or "").strip()
    finally:
        root.destroy()


def _select_project_directory_with_powershell() -> str:
    command = [
        "powershell",
        "-NoProfile",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "$ErrorActionPreference = 'Stop';"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$dialog.Description = '选择要绑定到当前会话的项目目录';"
            "$dialog.ShowNewFolderButton = $false;"
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {"
            "  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
            "  Write-Output $dialog.SelectedPath;"
            "}"
        ),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Project directory selection failed.").strip()
        raise RuntimeError(detail)
    return (completed.stdout or "").strip()


def _ensure_vscode_connection_extension_installed() -> dict[str, Any]:
    extension_dir = Path(__file__).resolve().parents[2] / "extensions" / "vscode"
    package_path = extension_dir / "package.json"
    main_path = extension_dir / "out" / "extension.js"
    if not package_path.exists() or not main_path.exists():
        return {}
    package = json.loads(package_path.read_text(encoding="utf-8"))
    publisher = str(package.get("publisher") or "local").strip() or "local"
    name = str(package.get("name") or "langchain-agent-vscode").strip() or "langchain-agent-vscode"
    version = str(package.get("version") or "0.0.0").strip() or "0.0.0"
    extension_id = f"{publisher}.{name}"
    install_root = Path(os.environ.get("VSCODE_EXTENSIONS") or Path.home() / ".vscode" / "extensions").resolve()
    install_dir = (install_root / f"{extension_id}-{version}").resolve()
    if install_root not in install_dir.parents:
        raise RuntimeError("invalid VS Code extension install path")
    install_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package_path, install_dir / "package.json")
    target_out = install_dir / "out"
    if target_out.exists():
        shutil.rmtree(target_out)
    shutil.copytree(extension_dir / "out", target_out)
    return {
        "extension_id": extension_id,
        "version": version,
        "install_dir": str(install_dir),
        "source_dir": str(extension_dir),
        "authority": "api.sessions.vscode_connection_extension_installation",
    }


@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    history = runtime.session_manager.get_history(session_id)
    return build_session_runtime_timeline(
        session_id=session_id,
        history=history,
        runtime_host=runtime.harness_runtime.single_agent_runtime_host,
    )


@router.post("/sessions/{session_id}/messages/truncate")
async def truncate_session_messages(
    session_id: str,
    payload: TruncateMessagesRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    try:
        record = runtime.session_manager.truncate_messages_from(session_id, payload.message_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        ledger = runtime.harness_runtime.single_agent_runtime_host.prompt_accounting_ledger
        reset = getattr(ledger, "reset_prompt_cache_baseline", None)
        if callable(reset):
            reset(
                request_id=f"pcachebaseline-reset:session-truncate:{session_id}:{payload.message_index}",
                session_id=session_id,
                reason="session_history_truncated",
                reset_ref=f"session:{session_id}:message_index:{payload.message_index}",
                diagnostics={"message_index": payload.message_index},
            )
    except Exception:
        pass
    try:
        await runtime.memory_facade.arun_memory_maintenance_after_commit(
            session_id=session_id,
            messages=list(record.get("messages", []) or []),
            durable_lane_enabled=False,
        )
    except Exception:
        pass
    return record


@router.post("/sessions/{session_id}/generate-title")
async def generate_title(
    session_id: str,
    payload: GenerateTitleRequest,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, str]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )
    if payload.message:
        seed = payload.message
    else:
        messages = runtime.session_manager.load_session(session_id)
        first_user = next((item["content"] for item in messages if item.get("role") == "user"), "")
        seed = first_user
    title = await runtime.harness_runtime.generate_title(seed or DEFAULT_SESSION_TITLE)
    runtime.session_manager.set_title(session_id, title)
    return {"session_id": session_id, "title": title}


def _latest_prompt_manifest_summary(runtime: Any, session_id: str) -> dict[str, Any]:
    ledger = runtime.harness_runtime.single_agent_runtime_host.prompt_accounting_ledger
    maps = ledger.list_segment_maps(session_id=session_id)
    latest = maps[-1] if maps else {}
    return {
        "authority": "api.sessions.latest_prompt_manifest_summary",
        "available": bool(latest),
        "request_id": str(latest.get("request_id") or ""),
        "task_run_id": str(latest.get("task_run_id") or ""),
        "segment_count": len(list(latest.get("segments") or [])),
        "predicted_prompt_tokens": int(latest.get("predicted_prompt_tokens") or 0),
        "metadata": dict(latest.get("metadata") or {}),
    }


