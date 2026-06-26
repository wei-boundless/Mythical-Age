from __future__ import annotations

import json
import hashlib
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from core.project_layout import ProjectLayout
from .models import FileAccessRule, ManagedFileRepositorySpec


EXTERNAL_READONLY_REPOSITORY_PREFIX = "repo.external_readonly."
EXTERNAL_READONLY_ROOT_REF_PREFIX = "external-readonly://"
EXTERNAL_LOGICAL_PREFIX = "external"


@dataclass(frozen=True, slots=True)
class ExternalReadScope:
    scope_id: str
    source_path: str
    source_kind: str
    title: str = ""
    enabled: bool = True
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "file_management.external_read_scope"

    @property
    def repository_id(self) -> str:
        return f"{EXTERNAL_READONLY_REPOSITORY_PREFIX}{self.scope_id}"

    @property
    def root_ref(self) -> str:
        return f"{EXTERNAL_READONLY_ROOT_REF_PREFIX}{self.scope_id}"

    @property
    def logical_prefix(self) -> str:
        return f"{EXTERNAL_LOGICAL_PREFIX}/{self.scope_id}"

    def source(self) -> Path:
        return Path(self.source_path).expanduser().resolve()

    def root(self) -> Path:
        source = self.source()
        return source.parent if self.source_kind == "file" else source

    def default_logical_path(self) -> str:
        return self.source().name if self.source_kind == "file" else ""

    def to_dict(self, *, include_source_path: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["repository_id"] = self.repository_id
        payload["root_ref"] = self.root_ref
        payload["logical_prefix"] = self.logical_prefix
        if not include_source_path:
            payload.pop("source_path", None)
        return payload


class ExternalReadScopeRegistry:
    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path).resolve()

    @classmethod
    def from_base_dir(cls, base_dir: str | Path) -> "ExternalReadScopeRegistry":
        layout = ProjectLayout.from_backend_dir(base_dir)
        return cls(layout.storage_root / "file_management" / "external_read_scopes.json")

    def list_scopes(self, *, enabled_only: bool = False) -> list[ExternalReadScope]:
        payload = self._read_payload()
        scopes = [
            scope
            for item in list(payload.get("scopes") or [])
            for scope in [_scope_from_payload(item)]
            if scope is not None
        ]
        if enabled_only:
            return [scope for scope in scopes if scope.enabled]
        return scopes

    def get_scope(self, scope_id: str) -> ExternalReadScope | None:
        target = normalize_external_scope_id(scope_id)
        return next((scope for scope in self.list_scopes() if scope.scope_id == target), None)

    def upsert_scope(
        self,
        *,
        source_path: str | Path,
        scope_id: str = "",
        title: str = "",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> ExternalReadScope:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"external read scope path does not exist: {source}")
        if not source.is_file() and not source.is_dir():
            raise ValueError("external read scope path must be a file or directory")
        normalized_id = normalize_external_scope_id(scope_id or source.stem or source.name)
        if not normalized_id:
            normalized_id = _scope_id_from_path(source)
        source_kind = "file" if source.is_file() else "directory"
        now = time.time()
        new_scope = ExternalReadScope(
            scope_id=normalized_id,
            source_path=str(source),
            source_kind=source_kind,
            title=str(title or source.name or normalized_id).strip(),
            enabled=bool(enabled),
            created_at=now,
            metadata={
                "source": "user_registered_external_read_scope",
                **dict(metadata or {}),
            },
        )
        scopes = [scope for scope in self.list_scopes() if scope.scope_id != normalized_id]
        scopes.append(new_scope)
        self._write_scopes(scopes)
        return new_scope

    def remove_scope(self, scope_id: str) -> bool:
        target = normalize_external_scope_id(scope_id)
        scopes = self.list_scopes()
        remaining = [scope for scope in scopes if scope.scope_id != target]
        if len(remaining) == len(scopes):
            return False
        self._write_scopes(remaining)
        return True

    def _read_payload(self) -> dict[str, Any]:
        if not self.storage_path.exists():
            return {"scopes": []}
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"scopes": []}
        return dict(payload or {})

    def _write_scopes(self, scopes: list[ExternalReadScope]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scopes": [scope.to_dict(include_source_path=True) for scope in sorted(scopes, key=lambda item: item.scope_id)],
            "authority": "file_management.external_read_scope_registry",
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def normalize_external_scope_id(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    raw = raw.rsplit("/", 1)[-1] if "/" in raw else raw
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe[:80].strip("-")


def external_scope_repository(scope: ExternalReadScope) -> ManagedFileRepositorySpec:
    return ManagedFileRepositorySpec(
        repository_id=scope.repository_id,
        repository_kind="material_mount",
        storage_adapter="fsspec_local",
        scope_kind="external_read_scope",
        root_ref=scope.root_ref,
        title=scope.title or scope.scope_id,
        readable=True,
        searchable=True,
        writable=False,
        access_rules=(
            FileAccessRule(action="open", behavior="allow", reason="external read scope can be opened for context"),
            FileAccessRule(action="read", behavior="allow", reason="external read scope is read-only"),
            FileAccessRule(action="search", behavior="allow", reason="external read scope is searchable"),
            FileAccessRule(action="write", behavior="deny", reason="external read scope is immutable"),
            FileAccessRule(action="edit", behavior="deny", reason="external read scope is immutable"),
        ),
        metadata={
            "external_read_scope": scope.to_dict(include_source_path=False),
            "external_source_kind": scope.source_kind,
            "external_file_name": scope.source().name if scope.source_kind == "file" else "",
        },
    )


def external_scope_repositories(scopes: list[ExternalReadScope] | tuple[ExternalReadScope, ...]) -> tuple[ManagedFileRepositorySpec, ...]:
    return tuple(external_scope_repository(scope) for scope in scopes if scope.enabled)


def external_scopes_from_payload(value: Any) -> list[ExternalReadScope]:
    result: list[ExternalReadScope] = []
    for item in list(value or []):
        scope = _scope_from_payload(item)
        if scope is not None and scope.enabled:
            result.append(scope)
    return result


def external_scope_payloads_for_base_dir(base_dir: str | Path) -> list[dict[str, Any]]:
    return [scope.to_dict(include_source_path=True) for scope in ExternalReadScopeRegistry.from_base_dir(base_dir).list_scopes(enabled_only=True)]


def external_scope_by_root_ref(base_dir: str | Path, root_ref: str) -> ExternalReadScope | None:
    scope_id = str(root_ref or "").strip().removeprefix(EXTERNAL_READONLY_ROOT_REF_PREFIX)
    if not scope_id:
        return None
    return ExternalReadScopeRegistry.from_base_dir(base_dir).get_scope(scope_id)


def split_external_logical_path(path: str) -> tuple[str, str]:
    normalized = str(path or "").replace("\\", "/").strip().strip("/")
    parts = PurePosixPath(normalized).parts
    if len(parts) < 2 or parts[0] != EXTERNAL_LOGICAL_PREFIX:
        return "", ""
    scope_id = normalize_external_scope_id(parts[1])
    tail = "/".join(parts[2:])
    return scope_id, tail


def external_logical_path(scope_id: str, relative_path: str = "") -> str:
    normalized_scope = normalize_external_scope_id(scope_id)
    tail = str(relative_path or "").replace("\\", "/").strip().strip("/")
    return f"{EXTERNAL_LOGICAL_PREFIX}/{normalized_scope}{('/' + tail) if tail else ''}"


def _scope_from_payload(value: Any) -> ExternalReadScope | None:
    if not isinstance(value, dict):
        return None
    scope_id = normalize_external_scope_id(value.get("scope_id") or value.get("id") or "")
    source_path = str(value.get("source_path") or value.get("path") or "").strip()
    if not scope_id or not source_path:
        return None
    source_kind = str(value.get("source_kind") or "").strip().lower()
    if source_kind not in {"file", "directory"}:
        source = Path(source_path).expanduser()
        source_kind = "file" if source.is_file() else "directory"
    return ExternalReadScope(
        scope_id=scope_id,
        source_path=str(Path(source_path).expanduser().resolve()),
        source_kind=source_kind,
        title=str(value.get("title") or scope_id).strip(),
        enabled=bool(value.get("enabled") is not False),
        created_at=float(value.get("created_at") or 0.0),
        metadata=dict(value.get("metadata") or {}),
    )


def _scope_id_from_path(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    safe = normalize_external_scope_id(path.stem or path.name or "external")
    return f"{safe}-{digest}".strip("-")
