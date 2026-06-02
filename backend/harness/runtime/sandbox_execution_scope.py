from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .artifact_scope import (
    CanonicalArtifactContract,
    canonicalize_task_contract_artifacts,
    contract_artifact_paths,
    normalize_logical_path,
    runtime_artifact_scope_from_environment,
)


DEFAULT_SANDBOX_SIDE_EFFECT_OPERATIONS = (
    "op.write_file",
    "op.edit_file",
    "op.shell",
    "op.python_repl",
    "op.browser_control",
    "op.image_generate",
)


@dataclass(frozen=True, slots=True)
class SandboxExecutionScope:
    artifact_root: str
    publish_roots: tuple[str, ...]
    scratch_roots: tuple[str, ...]
    task_write_roots: tuple[str, ...]
    write_roots: tuple[str, ...]
    materialized_roots: tuple[str, ...]
    canonical_output_paths: tuple[str, ...]
    canonical_contract: dict[str, Any]
    normalizations: tuple[dict[str, Any], ...] = ()
    authority: str = "harness.runtime.sandbox_execution_scope"

    def to_policy_payload(self) -> dict[str, Any]:
        return {
            "artifact_root": self.artifact_root,
            "publish_scopes": list(self.publish_roots),
            "scratch_scopes": list(self.scratch_roots),
            "task_write_scopes": list(self.task_write_roots),
            "write_scopes": list(self.write_roots),
            "materialized_roots": list(self.materialized_roots),
            "canonical_output_paths": list(self.canonical_output_paths),
            "scope_authority": self.authority,
        }

    def to_model_visible_payload(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "authority": self.authority,
                "artifact_root": self.artifact_root,
                "write_roots": list(self.write_roots),
                "publish_roots": list(self.publish_roots),
                "scratch_roots": list(self.scratch_roots),
                "canonical_output_paths": list(self.canonical_output_paths),
                "rule": (
                    "Write publishable deliverables to canonical_output_paths when provided; "
                    "otherwise write them under artifact_root. Temporary work may use scratch_roots, "
                    "but scratch files are not delivery artifacts."
                ),
            }
        )

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "artifact_root": self.artifact_root,
            "publish_roots": list(self.publish_roots),
            "scratch_roots": list(self.scratch_roots),
            "task_write_roots": list(self.task_write_roots),
            "write_roots": list(self.write_roots),
            "materialized_roots": list(self.materialized_roots),
            "canonical_output_paths": list(self.canonical_output_paths),
            "normalizations": [dict(item) for item in self.normalizations],
            "authority": self.authority,
        }


def compile_sandbox_execution_scope(
    *,
    environment_payload: dict[str, Any] | None,
    contract: dict[str, Any] | None = None,
    safety_envelope: dict[str, Any] | None = None,
    artifact_root: str = "",
) -> SandboxExecutionScope:
    environment = dict(environment_payload or {})
    storage = dict(environment.get("storage_space") or {})
    artifact_scope = runtime_artifact_scope_from_environment(environment)
    root = normalize_logical_path(artifact_root) or artifact_scope.artifact_root
    canonical = canonicalize_task_contract_artifacts(
        contract,
        environment_payload=environment,
        artifact_root=root,
    )
    policy = dict(safety_envelope or {})
    publish_roots = _dedupe(
        [
            root,
            *_normalize_paths(policy.get("publish_targets")),
            *_normalize_paths(policy.get("default_publish_targets")),
        ]
    )
    scratch_roots = tuple(_scratch_roots_from_environment(environment))
    task_write_roots = tuple(
        _dedupe(
            [
                *_normalize_paths(policy.get("write_roots")),
                *_normalize_paths(policy.get("default_write_roots")),
                *_contract_write_roots(canonical.contract),
            ]
        )
    )
    write_roots = tuple(_dedupe([*publish_roots, *scratch_roots, *task_write_roots]))
    materialized_roots = tuple(
        _dedupe(
            [
                *_normalize_paths(policy.get("materialized_roots")),
                *_contract_materialized_roots(canonical.contract),
                *publish_roots,
            ]
        )
    )
    canonical_output_paths = tuple(
        _dedupe([*_contract_artifact_paths(canonical.contract), *_normalize_paths(policy.get("canonical_output_paths"))])
    )
    return SandboxExecutionScope(
        artifact_root=root,
        publish_roots=tuple(publish_roots),
        scratch_roots=scratch_roots,
        task_write_roots=task_write_roots,
        write_roots=write_roots,
        materialized_roots=materialized_roots,
        canonical_output_paths=canonical_output_paths,
        canonical_contract=dict(canonical.contract),
        normalizations=tuple(dict(item) for item in canonical.normalizations),
    )


def canonicalize_contract_for_scope(
    *,
    environment_payload: dict[str, Any] | None,
    contract: dict[str, Any] | None,
    artifact_root: str = "",
) -> CanonicalArtifactContract:
    root = normalize_logical_path(artifact_root) or runtime_artifact_scope_from_environment(environment_payload).artifact_root
    return canonicalize_task_contract_artifacts(contract, environment_payload=environment_payload, artifact_root=root)


def task_safety_envelope_from_assembly(runtime_assembly: dict[str, Any] | None) -> dict[str, Any]:
    assembly = dict(runtime_assembly or {})
    for candidate in (
        assembly.get("safety_envelope"),
        dict(assembly.get("task_execution_assembly") or {}).get("safety_envelope"),
        dict(assembly.get("task_spec") or {}).get("safety_envelope"),
        dict(assembly.get("operation_requirement") or {}).get("safety_envelope"),
    ):
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def _scratch_roots_from_environment(environment: dict[str, Any]) -> list[str]:
    storage = dict(environment.get("storage_space") or {})
    roots: list[str] = []
    environment_storage_root = normalize_logical_path(storage.get("environment_storage_root"))
    if environment_storage_root:
        roots.append(f"{environment_storage_root}/tmp")
    for key in ("runtime_state_root", "cache_root"):
        root = normalize_logical_path(storage.get(key))
        if root:
            roots.append(root)
    if _sandbox_workspace_write_allowed(environment):
        roots.append(".tmp")
    return _dedupe(roots)


def _sandbox_workspace_write_allowed(environment: dict[str, Any]) -> bool:
    file_management = dict(environment.get("file_management") or {})
    constraints = dict(file_management.get("constraints") or {})
    if str(constraints.get("sandbox_workspace_write") or "").strip() == "allowed":
        return True
    sandbox = dict(environment.get("sandbox_policy") or {})
    write_policy = str(sandbox.get("write_policy") or "").strip()
    return bool(sandbox.get("enabled") is True and "sandbox" in write_policy)


def _contract_write_roots(contract: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for path in contract_artifact_paths(contract):
        normalized = normalize_logical_path(path)
        if not normalized:
            continue
        parent = _parent_or_self(normalized)
        if parent:
            roots.append(parent)
    return _dedupe(roots)


def _contract_materialized_roots(contract: dict[str, Any]) -> list[str]:
    roots: list[str] = []
    for path in contract_artifact_paths(contract):
        parent = _parent_or_self(path)
        if parent:
            roots.append(parent)
    return _dedupe(roots)


def _contract_artifact_paths(contract: dict[str, Any]) -> list[str]:
    return _dedupe(contract_artifact_paths(contract))


def _normalize_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value or []) if isinstance(value, (list, tuple, set)) else []
    return _dedupe([normalize_logical_path(item) for item in values])


def _parent_or_self(path: str) -> str:
    normalized = normalize_logical_path(path)
    if not normalized:
        return ""
    parent = PurePosixPath(normalized).parent.as_posix().strip(".").strip("/")
    return parent or normalized


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_logical_path(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
