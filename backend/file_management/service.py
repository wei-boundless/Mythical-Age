from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from code_environment.workspace_tree import _is_excluded_relative_path
from core.project_layout import ProjectLayout
from runtime.file_changes import FileChangeTracker
from runtime.file_change_signals import publish_file_change_record

from .access_table import build_file_access_table
from .api_models import ManagedFileTarget
from .external_read_scopes import (
    EXTERNAL_READONLY_REPOSITORY_PREFIX,
    ExternalReadScope,
    ExternalReadScopeRegistry,
    external_logical_path,
    external_scope_payloads_for_base_dir,
    external_scope_repositories,
)
from .gateway import FileGateway, FileGatewayApprovalRequired, FileGatewayRequestContext
from .models import FileAccessRule, ManagedFileRepositorySpec, normalize_logical_path, stable_content_hash
from .resolver import ResolvedFileEnvironment, resolve_file_environment

MANAGED_PROJECT_PROFILE_ID = "file_profile.managed_project_workspace"
GRAPH_INSTANCE_PROFILE_ID = "file_profile.graph_task_instance"
GRAPH_INSTANCE_REPOSITORY_ID = "repo.graph_task_instance.instance"

SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
NON_TEXT_SUFFIXES = (
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".webp",
    ".zip",
)


@dataclass(frozen=True, slots=True)
class ManagedFileServiceContext:
    session_id: str = ""
    task_run_id: str = ""
    agent_run_id: str = ""
    tool_call_id: str = ""
    actor_id: str = "agent_ui"


class ManagedFileConflict(RuntimeError):
    pass


class ManagedFileService:
    authority = "file_management.service"

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.layout = ProjectLayout.from_backend_dir(runtime.base_dir)

    def list_profiles(self) -> dict[str, Any]:
        from .registry import default_file_environment_registry

        registry = default_file_environment_registry()
        return {
            "profiles": [profile.to_dict() for profile in registry.list_profiles()],
            "authority": "file_management.service.profiles",
        }

    def list_repositories(self, *, session_id: str = "") -> dict[str, Any]:
        profiles = self.list_profiles()["profiles"]
        project_target = self.project_target_for_session(session_id=session_id)
        graph_repository = _graph_instance_repository_spec("preview").to_dict()
        external_scopes = self._external_scope_registry().list_scopes(enabled_only=True)
        external_repositories = [repo.to_dict() for repo in external_scope_repositories(external_scopes)]
        return {
            "profiles": profiles,
            "project_target": project_target,
            "dynamic_repositories": [graph_repository, *external_repositories],
            "external_read_scopes": [scope.to_dict(include_source_path=True) for scope in external_scopes],
            "authority": "file_management.service.repositories",
        }

    def list_external_read_scopes(self) -> dict[str, Any]:
        scopes = self._external_scope_registry().list_scopes()
        return {
            "scopes": [scope.to_dict(include_source_path=True) for scope in scopes],
            "authority": "file_management.service.external_read_scopes",
        }

    def upsert_external_read_scope(
        self,
        *,
        source_path: str,
        scope_id: str = "",
        title: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        scope = self.register_external_read_scope(
            source_path=source_path,
            scope_id=scope_id,
            title=title,
            enabled=enabled,
        )
        return {
            "ok": True,
            "scope": scope.to_dict(include_source_path=True),
            "target": self.external_read_target(scope).model_dump(),
            "logical_path": external_logical_path(scope.scope_id, scope.default_logical_path()),
            "authority": "file_management.service.external_read_scope_upsert",
        }

    def register_external_read_scope(
        self,
        *,
        source_path: str,
        scope_id: str = "",
        title: str = "",
        enabled: bool = True,
    ) -> ExternalReadScope:
        try:
            return self._external_scope_registry().upsert_scope(
                source_path=source_path,
                scope_id=scope_id,
                title=title,
                enabled=enabled,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def delete_external_read_scope(self, scope_id: str) -> dict[str, Any]:
        removed = self._external_scope_registry().remove_scope(scope_id)
        if not removed:
            raise HTTPException(status_code=404, detail="external read scope not found")
        return {
            "ok": True,
            "scope_id": str(scope_id or "").strip(),
            "authority": "file_management.service.external_read_scope_delete",
        }

    def external_read_target(self, scope: ExternalReadScope) -> ManagedFileTarget:
        return ManagedFileTarget(
            repository_id=scope.repository_id,
            repository_kind="material_mount",
            scope_kind="external_read_scope",
            scope_id=scope.scope_id,
            logical_path=scope.default_logical_path() or ".",
            workspace_root=str(self.layout.project_root.resolve()),
            profile_id=MANAGED_PROJECT_PROFILE_ID,
        )

    def project_target_for_session(self, *, session_id: str = "", logical_path: str = "AGENTS.md") -> dict[str, Any]:
        root = self._project_root(session_id=session_id)
        return {
            "repository_id": "repo.managed_project.project_workspace",
            "repository_kind": "project_workspace",
            "scope_kind": "project_scoped",
            "scope_id": session_id or root.name,
            "logical_path": logical_path,
            "workspace_root": str(root),
            "profile_id": MANAGED_PROJECT_PROFILE_ID,
        }

    def read(self, target: ManagedFileTarget, *, context: ManagedFileServiceContext | None = None) -> dict[str, Any]:
        resolved = self._resolved(target, context=context)
        self._guard_text_target(resolved=resolved, action="read")
        try:
            result = resolved.gateway.read_text(
                resolved.repository_id,
                resolved.logical_path,
                resolved.gateway_context,
                operation_id="op.read_file",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="File is not a supported text file") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self._guard_text_bytes(Path(result.physical_path))
        return {
            "target": resolved.target_payload(result.logical_path),
            "path": result.logical_path,
            "content": result.content,
            "content_sha256": _sha256_text(result.content),
            "managed_file_ref": result.managed_file_ref.to_dict(),
            "repository": resolved.repository.to_dict(),
            "root_binding": dict(result.metadata.get("root_binding") or {}),
            "authority": "file_management.service.read",
        }

    def write(
        self,
        target: ManagedFileTarget,
        *,
        content: str,
        expected_sha256: str = "",
        source: str = "agent_ui",
        reason: str = "user_save",
        force: bool = False,
        context: ManagedFileServiceContext | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolved(target, context=context)
        self._guard_text_target(resolved=resolved, action="write")
        before = self._read_before(resolved)
        self._assert_expected_hash(before_content=before, expected_sha256=expected_sha256, force=force)
        try:
            result = resolved.gateway.write_text(
                resolved.repository_id,
                resolved.logical_path,
                content,
                resolved.gateway_context,
                operation_id="op.write_file",
                approval_fingerprint=self._approval_fingerprint(
                    resolved=resolved,
                    source=source,
                    reason=reason,
                    expected_sha256=expected_sha256,
                ),
            )
        except FileGatewayApprovalRequired as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self._write_payload(
            resolved=resolved,
            result=result,
            source=source,
            reason=reason,
            action="write",
        )

    def edit(
        self,
        target: ManagedFileTarget,
        *,
        old_text: str,
        new_text: str,
        expected_sha256: str = "",
        source: str = "agent_ui",
        reason: str = "user_edit",
        force: bool = False,
        context: ManagedFileServiceContext | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolved(target, context=context)
        self._guard_text_target(resolved=resolved, action="edit")
        before = self._read_before(resolved)
        self._assert_expected_hash(before_content=before, expected_sha256=expected_sha256, force=force)
        try:
            result = resolved.gateway.edit_text(
                resolved.repository_id,
                resolved.logical_path,
                old_text,
                new_text,
                resolved.gateway_context,
                operation_id="op.edit_file",
                approval_fingerprint=self._approval_fingerprint(
                    resolved=resolved,
                    source=source,
                    reason=reason,
                    expected_sha256=expected_sha256,
                ),
            )
        except FileGatewayApprovalRequired as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self._write_payload(
            resolved=resolved,
            result=result,
            source=source,
            reason=reason,
            action="edit",
        )

    def _write_payload(self, *, resolved: "_ResolvedManagedFile", result: Any, source: str, reason: str, action: str) -> dict[str, Any]:
        receipt = result.receipt.to_dict() if result.receipt is not None else {}
        record = self._record_change(resolved=resolved, result=result, receipt=receipt, source=source, reason=reason, action=action)
        self._refresh_indexes(resolved.logical_path)
        return {
            "ok": True,
            "target": resolved.target_payload(result.logical_path),
            "path": result.logical_path,
            "content_sha256": _sha256_text(result.content),
            "managed_file_ref": result.managed_file_ref.to_dict(),
            "receipt": receipt,
            "file_change_record": record,
            "repository": resolved.repository.to_dict(),
            "root_binding": dict(result.metadata.get("root_binding") or {}),
            "authority": f"file_management.service.{action}",
        }

    def _resolved(self, target: ManagedFileTarget, *, context: ManagedFileServiceContext | None) -> "_ResolvedManagedFile":
        ctx = context or ManagedFileServiceContext()
        logical_path = normalize_logical_path(target.logical_path)
        profile_id = str(target.profile_id or "").strip() or _default_profile_for_repository(target.repository_id)
        external_scopes = external_scope_payloads_for_base_dir(self.runtime.base_dir)
        if str(target.repository_id or "").strip() == GRAPH_INSTANCE_REPOSITORY_ID:
            environment = _graph_instance_environment(str(target.scope_id or "").strip())
        else:
            try:
                environment = resolve_file_environment(profile_id, external_read_scopes=external_scopes)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        repository_id = str(target.repository_id or "").strip()
        repository = environment.repository(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"unknown file repository: {repository_id}")
        if target.repository_kind and target.repository_kind != repository.repository_kind:
            raise HTTPException(status_code=409, detail="repository_kind does not match repository_id")
        access_table = build_file_access_table(environment)
        project_root = self._project_root(session_id=ctx.session_id, target=target)
        gateway = FileGateway.for_roots(
            environment=environment,
            access_table=access_table,
            project_root=project_root,
            managed_storage_root=self.layout.project_root / ".managed-files",
            runtime_output_root=self.layout.storage_root / "runtime_state" / "file_management",
            external_read_scopes=external_scopes,
        )
        return _ResolvedManagedFile(
            gateway=gateway,
            gateway_context=FileGatewayRequestContext(
                task_run_id=ctx.task_run_id or ctx.session_id,
                agent_run_id=ctx.agent_run_id or ctx.actor_id,
                tool_call_id=ctx.tool_call_id,
                actor_id=ctx.actor_id,
                metadata={
                    "session_id": ctx.session_id,
                    "source": ctx.actor_id,
                    "file_management_api": True,
                },
            ),
            environment=environment,
            repository=repository,
            repository_id=repository_id,
            logical_path=logical_path,
            target=target,
            project_root=project_root,
            context=ctx,
        )

    def _project_root(self, *, session_id: str = "", target: ManagedFileTarget | None = None) -> Path:
        explicit_root = str(getattr(target, "workspace_root", "") or "").strip()
        if str(getattr(target, "repository_id", "") or "").strip().startswith(EXTERNAL_READONLY_REPOSITORY_PREFIX):
            explicit_root = ""
        if explicit_root:
            root = Path(explicit_root).expanduser().resolve()
            if not root.is_dir():
                raise HTTPException(status_code=404, detail="workspace_root not found")
            return root
        target_session_id = str(session_id or "").strip()
        session_manager = getattr(self.runtime, "session_manager", None)
        if target_session_id and session_manager is not None:
            binding = session_manager.get_project_binding(target_session_id)
            workspace_root = str(dict(binding or {}).get("workspace_root") or "").strip()
            if workspace_root:
                root = Path(workspace_root).expanduser().resolve()
                if not root.is_dir():
                    raise HTTPException(status_code=404, detail="Session project binding root not found")
                return root
        return self.layout.project_root.resolve()

    def _read_before(self, resolved: "_ResolvedManagedFile") -> str | None:
        try:
            payload = resolved.gateway.read_text(
                resolved.repository_id,
                resolved.logical_path,
                resolved.gateway_context,
                operation_id="op.read_file",
            )
            return payload.content
        except FileNotFoundError:
            return None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="File is not a supported text file") from exc

    def _assert_expected_hash(self, *, before_content: str | None, expected_sha256: str, force: bool) -> None:
        expected = _normalize_sha256(expected_sha256)
        if force or not expected:
            return
        current = _sha256_text(before_content or "") if before_content is not None else ""
        if current != expected:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "managed_file_conflict",
                    "message": "File changed since it was loaded.",
                    "expected_sha256": expected,
                    "current_sha256": current,
                },
            )

    def _guard_text_target(self, *, resolved: "_ResolvedManagedFile", action: str) -> None:
        path = resolved.logical_path.replace("\\", "/").strip("/")
        if _is_excluded_relative_path(path):
            raise HTTPException(status_code=400, detail="Path is excluded from editable workspace files")
        name = Path(path).name.lower()
        if name in SENSITIVE_FILE_NAMES or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
            raise HTTPException(status_code=400, detail="Sensitive file is not editable through file management UI")
        if name.endswith(NON_TEXT_SUFFIXES):
            raise HTTPException(status_code=415, detail="File is not a supported text file")
        if resolved.repository.repository_kind == "git_worktree_view" and action in {"write", "edit"}:
            raise HTTPException(status_code=400, detail="git worktree view is read-only")

    def _guard_text_bytes(self, physical_path: Path) -> None:
        try:
            data = physical_path.read_bytes()[:4096]
        except OSError:
            return
        if b"\x00" in data:
            raise HTTPException(status_code=415, detail="File is not a supported text file")

    def _record_change(self, *, resolved: "_ResolvedManagedFile", result: Any, receipt: dict[str, Any], source: str, reason: str, action: str) -> dict[str, Any]:
        root = _root_from_result(result) or resolved.project_root
        try:
            record = FileChangeTracker(self.runtime.base_dir).record_text_change(
                session_id=resolved.context.session_id,
                task_run_id=resolved.context.task_run_id,
                agent_run_id=resolved.context.agent_run_id or resolved.context.actor_id,
                tool_call_id=resolved.context.tool_call_id,
                tool_name="file_management_ui",
                operation_id=f"op.{action}_file",
                workspace_root=root,
                logical_path=result.logical_path,
                absolute_path=result.physical_path,
                before_content=result.before_content,
                after_content=result.content,
                metadata={
                    "source": str(source or "agent_ui"),
                    "reason": str(reason or ""),
                    "actor": "human" if str(source or "") == "agent_ui" else "system",
                    "repository_id": result.repository_id,
                    "repository_kind": result.repository_kind,
                    "scope_kind": resolved.target.scope_kind or resolved.repository.scope_kind,
                    "scope_id": resolved.target.scope_id or resolved.context.session_id,
                    "session_id": resolved.context.session_id,
                    "file_operation_receipt_id": str(receipt.get("receipt_id") or ""),
                    "authority": "file_management.service.change_metadata",
                },
            )
            publish_file_change_record(
                self.runtime,
                record,
                action=action,
                source="file_management.service",
            )
            return record
        except Exception as exc:
            return {"status": "error", "error": str(exc), "authority": "file_management.service.change_record_error"}

    def _approval_fingerprint(self, *, resolved: "_ResolvedManagedFile", source: str, reason: str, expected_sha256: str) -> str:
        payload = "|".join(
            (
                str(source or "agent_ui"),
                str(reason or "user_save"),
                resolved.repository_id,
                resolved.logical_path,
                _normalize_sha256(expected_sha256),
                resolved.context.session_id,
                str(time.time_ns()),
            )
        )
        return f"human-file-edit:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"

    def _refresh_indexes(self, logical_path: str) -> None:
        refresh = getattr(self.runtime, "refresh_indexes_for_path", None)
        if callable(refresh):
            try:
                refresh(logical_path)
            except Exception:
                return

    def _external_scope_registry(self) -> ExternalReadScopeRegistry:
        return ExternalReadScopeRegistry.from_base_dir(self.runtime.base_dir)


@dataclass(frozen=True, slots=True)
class _ResolvedManagedFile:
    gateway: FileGateway
    gateway_context: FileGatewayRequestContext
    environment: ResolvedFileEnvironment
    repository: ManagedFileRepositorySpec
    repository_id: str
    logical_path: str
    target: ManagedFileTarget
    project_root: Path
    context: ManagedFileServiceContext

    def target_payload(self, logical_path: str) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "repository_kind": self.repository.repository_kind,
            "scope_kind": self.target.scope_kind or self.repository.scope_kind,
            "scope_id": self.target.scope_id or self.context.session_id,
            "logical_path": logical_path,
            "workspace_root": self.target.workspace_root or str(self.project_root),
            "profile_id": self.target.profile_id or self.environment.profile_id,
        }


def _default_profile_for_repository(repository_id: str) -> str:
    repo = str(repository_id or "").strip()
    if repo.startswith("repo.writing."):
        return "file_profile.writing_manuscript"
    if repo == GRAPH_INSTANCE_REPOSITORY_ID:
        return GRAPH_INSTANCE_PROFILE_ID
    return MANAGED_PROJECT_PROFILE_ID


def _graph_instance_environment(instance_id: str) -> ResolvedFileEnvironment:
    repository = _graph_instance_repository_spec(instance_id)
    return ResolvedFileEnvironment(
        profile_id=GRAPH_INSTANCE_PROFILE_ID,
        repositories=(repository,),
        metadata={"dynamic_profile": True, "graph_task_instance_id": instance_id},
    )


def _graph_instance_repository_spec(instance_id: str) -> ManagedFileRepositorySpec:
    safe_id = _safe_scope_id(instance_id or "preview")
    return ManagedFileRepositorySpec(
        repository_id=GRAPH_INSTANCE_REPOSITORY_ID,
        repository_kind="artifact_repository",
        storage_adapter="fsspec_local",
        scope_kind="graph_task_instance",
        root_ref=f"graph-task-instance://{safe_id}",
        title="Graph task instance files",
        readable=True,
        writable=True,
        searchable=True,
        access_rules=(
            FileAccessRule(action="read", behavior="allow", reason="graph task instance files are readable"),
            FileAccessRule(action="search", behavior="allow", reason="graph task instance files are searchable"),
            FileAccessRule(action="write", behavior="ask", reason="graph task instance edit requires user action"),
            FileAccessRule(action="edit", behavior="ask", reason="graph task instance edit requires user action"),
        ),
        metadata={"dynamic_repository": True, "graph_task_instance_id": safe_id},
    )


def _safe_scope_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ":"} else "_" for ch in str(value or "").strip())
    return safe.strip("_-") or "graph_task_instance"


def _root_from_result(result: Any) -> Path | None:
    root = str(dict(dict(result.metadata or {}).get("root_binding") or {}).get("root") or "").strip()
    if not root:
        return None
    return Path(root).resolve()


def _normalize_sha256(value: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    return text


def _sha256_text(value: str) -> str:
    return stable_content_hash(str(value or ""))

