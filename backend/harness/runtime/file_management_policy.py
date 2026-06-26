from __future__ import annotations

from typing import Any


def compile_tool_file_management_policy(
    environment_payload: dict[str, Any] | None,
    *,
    storage_space: dict[str, Any] | None = None,
    artifact_root: str = "",
    sandbox_policy: dict[str, Any] | None = None,
    external_read_scopes: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    environment = dict(environment_payload or {})
    file_management = dict(environment.get("file_management") or {})
    constraints = dict(file_management.get("constraints") or {})
    profile_id = _first_profile_ref(file_management)
    if not profile_id:
        return {}
    if profile_id == "file_profile.general_workspace":
        return {}
    if profile_id == "file_profile.base_workspace" and _sandbox_overlay_active(sandbox_policy):
        return {}
    repositories = _repository_map_for_constraints(constraints)
    if not repositories:
        repositories = _repository_map_for_profile(profile_id)
    repositories = _repository_map_for_runtime_boundary(
        profile_id,
        repositories,
        sandbox_policy=sandbox_policy,
    )
    payload = {
        "enabled": True,
        "profile_id": profile_id,
        "profile_refs": list(_string_tuple(file_management.get("file_profile_refs"))),
        "repositories": repositories,
        "default_repository_id": _default_repository_id(repositories),
        "repository_requirements": {
            kind: {}
            for kind in _string_tuple(file_management.get("required_repository_kinds"))
        },
        "task_file_requirements": dict(file_management.get("task_file_requirements") or {}),
        "agent_allowed_file_actions": _agent_allowed_file_actions(constraints),
        "canonical_write_policy": str(file_management.get("canonical_write_policy") or ""),
        "artifact_projection_policy": str(file_management.get("artifact_projection_policy") or ""),
        "memory_projection_policy": str(file_management.get("memory_projection_policy") or ""),
        "constraints": constraints,
        "storage_space": dict(storage_space or environment.get("storage_space") or {}),
        "external_read_scopes": [dict(item) for item in list(external_read_scopes or []) if isinstance(item, dict)],
        "artifact_root": str(artifact_root or ""),
        "authority": "harness.runtime.file_management_policy",
    }
    return _drop_empty(payload)


def _repository_map_for_constraints(constraints: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for action, key in (
        ("read", "default_read_repository"),
        ("search", "default_search_repository"),
        ("write", "default_write_repository"),
        ("edit", "default_edit_repository"),
        ("open", "default_open_repository"),
        ("commit", "default_commit_repository"),
    ):
        value = str(constraints.get(key) or "").strip()
        if value:
            result[action] = value
    return result


def _repository_map_for_profile(profile_id: str) -> dict[str, str]:
    profile = str(profile_id or "").strip()
    if profile == "file_profile.base_workspace":
        return {
            "read": "repo.base.project_workspace",
            "search": "repo.base.project_workspace",
        }
    if profile == "file_profile.managed_project_workspace":
        return {
            "read": "repo.managed_project.sandbox_workspace",
            "search": "repo.managed_project.sandbox_workspace",
            "write": "repo.managed_project.sandbox_workspace",
            "edit": "repo.managed_project.sandbox_workspace",
        }
    if profile == "file_profile.writing_manuscript":
        return {
            "read": "repo.writing.official_work",
            "search": "repo.writing.official_work",
            "write": "repo.writing.draft_workspace",
            "edit": "repo.writing.draft_workspace",
        }
    return {}


def _repository_map_for_runtime_boundary(
    profile_id: str,
    repositories: dict[str, str],
    *,
    sandbox_policy: dict[str, Any] | None,
) -> dict[str, str]:
    if profile_id != "file_profile.managed_project_workspace":
        return dict(repositories)
    if _sandbox_overlay_active(sandbox_policy):
        return dict(repositories)
    normalized = dict(repositories)
    for action in ("read", "search"):
        if normalized.get(action) == "repo.managed_project.sandbox_workspace":
            normalized[action] = "repo.managed_project.project_workspace"
    for action in ("write", "edit"):
        if normalized.get(action) == "repo.managed_project.sandbox_workspace":
            normalized[action] = "repo.managed_project.artifacts"
    return normalized


def _default_repository_id(repositories: dict[str, str]) -> str:
    for key in ("read", "search", "write", "edit"):
        value = str(repositories.get(key) or "").strip()
        if value:
            return value
    return ""


def _agent_allowed_file_actions(constraints: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for key, value in sorted(constraints.items()):
        key_text = str(key or "")
        if not key_text.endswith(("_read", "_search", "_write", "_edit", "_open")):
            continue
        if str(value or "").strip() in {"allowed", "allow"}:
            actions.append(key_text.rsplit("_", 1)[-1])
    return sorted(set(actions))


def _sandbox_overlay_active(sandbox_policy: dict[str, Any] | None) -> bool:
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return False
    if not str(policy.get("sandbox_root") or "").strip():
        return False
    mode = str(policy.get("mode") or policy.get("sandbox_mode") or "").strip()
    return mode in {"workspace_overlay", "local_overlay", ""}


def _first_profile_ref(file_management: dict[str, Any]) -> str:
    explicit = str(file_management.get("profile_id") or "").strip()
    if explicit:
        return explicit
    for item in _string_tuple(file_management.get("file_profile_refs")):
        return item
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.replace(",", "\n").splitlines() if item.strip())
    return tuple(str(item or "").strip() for item in list(value or []) if str(item or "").strip())


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
