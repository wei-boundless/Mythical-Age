from __future__ import annotations

from pathlib import Path
from typing import Any

from .sandbox_policy import workspace_root_for_runtime


def prepare_runtime_file_management_policy_for_turn(
    *,
    root_dir: Path,
    task_run_id: str,
    selected_recipe_payload: dict[str, Any],
    task_selection: dict[str, Any] | None,
    sandbox_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the system-owned file environment policy for this runtime turn."""

    selection = dict(task_selection or {})
    recipe_metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    explicit_policy = _merge_explicit_file_policies(recipe_metadata, selection)
    if explicit_policy.get("enabled") is False:
        return {"enabled": False, "mode": str(explicit_policy.get("mode") or "disabled")}

    sandbox = dict(sandbox_policy or {})
    workspace_root = workspace_root_for_runtime(root_dir)
    policy = _merge_file_management_policy(
        _default_policy_for_environment(
            environment_id=_resolve_environment_id(recipe_metadata=recipe_metadata, task_selection=selection),
            sandbox_enabled=bool(sandbox.get("enabled") is True),
        ),
        explicit_policy,
    )
    if not policy:
        return {}
    if policy.get("enabled") is False:
        return {"enabled": False, "mode": str(policy.get("mode") or "disabled")}
    policy["enabled"] = True
    policy.setdefault("managed_storage_root", str((workspace_root / ".managed-files").resolve()))
    policy.setdefault("runtime_output_root", str((workspace_root / ".managed-files" / "runtime").resolve()))
    policy.setdefault("task_run_id", str(task_run_id or ""))
    policy.setdefault("authority", "runtime.unit_runtime.file_management_policy")
    policy.setdefault("source", "task_environment_or_specific_task")
    if str(sandbox.get("sandbox_root") or "").strip():
        policy.setdefault("sandbox_root", str(sandbox.get("sandbox_root") or ""))
    policy.setdefault("workspace_root", str(workspace_root))
    repositories = dict(policy.get("repositories") or {})
    if repositories:
        policy["repositories"] = repositories
    return policy


def _merge_file_management_policy(base_policy: dict[str, Any], explicit_policy: dict[str, Any]) -> dict[str, Any]:
    merged = {**dict(base_policy or {}), **dict(explicit_policy or {})}
    base_repositories = dict(dict(base_policy or {}).get("repositories") or {})
    explicit_repositories = dict(dict(explicit_policy or {}).get("repositories") or {})
    if base_repositories or explicit_repositories:
        merged["repositories"] = {**base_repositories, **explicit_repositories}
    return merged


def _merge_explicit_file_policies(
    recipe_metadata: dict[str, Any],
    task_selection: dict[str, Any],
) -> dict[str, Any]:
    mode_policy = dict(recipe_metadata.get("mode_policy") or {})
    return {
        **dict(recipe_metadata.get("file_management_policy") or {}),
        **dict(recipe_metadata.get("file_management") or {}),
        **dict(mode_policy.get("file_management_policy") or {}),
        **dict(mode_policy.get("file_management") or {}),
        **dict(task_selection.get("file_management_policy") or {}),
        **dict(task_selection.get("file_management") or {}),
    }


def _resolve_environment_id(
    *,
    recipe_metadata: dict[str, Any],
    task_selection: dict[str, Any],
) -> str:
    candidates = (
        task_selection.get("task_environment_id"),
        task_selection.get("environment_id"),
        task_selection.get("environment"),
        dict(task_selection.get("task_environment") or {}).get("environment_id")
        if isinstance(task_selection.get("task_environment"), dict)
        else task_selection.get("task_environment"),
        dict(task_selection.get("task_order_projection") or {}).get("task_environment_id"),
        recipe_metadata.get("task_environment_id"),
        recipe_metadata.get("environment_id"),
        recipe_metadata.get("environment"),
        dict(recipe_metadata.get("task_environment") or {}).get("environment_id")
        if isinstance(recipe_metadata.get("task_environment"), dict)
        else recipe_metadata.get("task_environment"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return "env.vibe_coding"


def _default_policy_for_environment(*, environment_id: str, sandbox_enabled: bool) -> dict[str, Any]:
    normalized = str(environment_id or "").strip()
    if normalized in {"env.writing", "writing"}:
        return {
            "enabled": True,
            "environment_id": "env.writing",
            "profile_id": "file_profile.writing_manuscript",
            "repositories": {
                "read": "repo.writing.official_work",
                "open": "repo.writing.official_work",
                "search": "repo.writing.official_work",
                "write": "repo.writing.draft_workspace",
                "edit": "repo.writing.draft_workspace",
            },
        }
    if normalized in {"env.web_research", "web_research", "research"}:
        return {
            "enabled": True,
            "environment_id": "env.web_research",
            "profile_id": "file_profile.web_research_evidence",
            "repositories": {
                "read": "repo.research.evidence_archive",
                "search": "repo.research.evidence_archive",
                "write": "repo.research.evidence_archive",
                "edit": "repo.research.evidence_archive",
            },
        }
    write_repository = "repo.coding.sandbox_workspace" if sandbox_enabled else "repo.coding.project_workspace"
    read_repository = "repo.coding.sandbox_workspace" if sandbox_enabled else "repo.coding.project_workspace"
    return {
        "enabled": True,
        "environment_id": "env.vibe_coding",
        "profile_id": "file_profile.vibe_coding_project",
        "repositories": {
            "read": read_repository,
            "search": read_repository,
            "write": write_repository,
            "edit": write_repository,
        },
    }
