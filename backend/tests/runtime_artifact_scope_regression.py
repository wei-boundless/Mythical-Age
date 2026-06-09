from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from harness.loop.task_executor import _task_sandbox_policy, _verify_completion
from harness.runtime.artifact_scope import canonicalize_task_contract_artifacts
from harness.runtime.file_management_policy import compile_tool_file_management_policy
from harness.runtime.sandbox_execution_scope import compile_sandbox_execution_scope
from runtime.shared.safety import build_task_safety_validators


class _EmptyStateIndex:
    def get_task_run(self, task_run_id: str):
        del task_run_id
        return None


def _runtime_host(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        backend_dir=Path(__file__).resolve().parents[1],
        root_dir=tmp_path,
        state_index=_EmptyStateIndex(),
    )


def test_task_executor_uses_storage_artifact_root_for_policy_and_completion(tmp_path: Path) -> None:
    artifact_root = "storage/task_environments/coding/vibe-workspace/artifacts"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {
                "environment_storage_root": "storage/task_environments/coding/vibe-workspace",
                "artifact_root": artifact_root,
            },
            "artifact_policy": {"artifact_root": "runtime_output"},
            "sandbox_policy": {},
        }
    }
    runtime_host = _runtime_host(tmp_path)
    task_run_id = "taskrun:artifact-scope-regression"
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime_host, task_run_id=task_run_id)
    canonical_path = f"{artifact_root}/demo/index.html"
    sandbox_file = Path(str(policy["sandbox_root"])) / canonical_path
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.write_text("<!doctype html><title>ok</title>", encoding="utf-8")

    verdict = _verify_completion(
        runtime_host=runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_document", "path": "artifacts/demo/index.html"}]},
        artifact_refs=[],
    )

    assert policy["artifact_root"] == artifact_root
    assert policy["write_scopes"][0] == artifact_root
    assert policy["publish_scopes"] == [artifact_root]
    assert "runtime_output" not in policy["write_scopes"]
    assert verdict["ok"] is True
    assert verdict["verified_artifacts"][0]["path"] == canonical_path


def test_canonical_artifact_contract_does_not_keep_executable_requested_path() -> None:
    artifact_root = "storage/task_environments/coding/vibe-workspace/artifacts"
    normalized = canonicalize_task_contract_artifacts(
        {"required_artifacts": [{"artifact_kind": "html_document", "path": "artifacts/demo/index.html"}]},
        artifact_root=artifact_root,
    )

    assert normalized.contract["required_artifacts"] == [
        {"artifact_kind": "html_document", "path": f"{artifact_root}/demo/index.html"}
    ]
    assert "requested_path" not in normalized.contract["required_artifacts"][0]
    assert normalized.normalizations[0]["requested_path"] == "artifacts/demo/index.html"


def test_canonical_artifact_contract_rejects_absolute_drive_paths() -> None:
    normalized = canonicalize_task_contract_artifacts(
        {"required_artifacts": [{"artifact_kind": "html_document", "path": "C:/tmp/escape.html"}]},
        artifact_root="storage/task_environments/coding/vibe-workspace/artifacts",
    )

    assert normalized.contract["required_artifacts"] == [{"artifact_kind": "html_document"}]
    assert normalized.normalizations[0]["status"] == "invalid_path_removed"
    assert normalized.normalizations[0]["requested_path"] == "C:/tmp/escape.html"


def test_sandbox_execution_scope_allows_declared_scratch_without_publishing_it() -> None:
    artifact_root = "storage/task_environments/coding/vibe-workspace/artifacts"
    scope = compile_sandbox_execution_scope(
        environment_payload={
            "storage_space": {
                "environment_storage_root": "storage/task_environments/coding/vibe-workspace",
                "runtime_state_root": "storage/task_environments/coding/vibe-workspace/runtime_state",
                "artifact_root": artifact_root,
                "cache_root": "storage/task_environments/coding/vibe-workspace/cache",
            },
            "sandbox_policy": {"enabled": True, "write_policy": "sandbox_or_task_granted"},
            "file_management": {"constraints": {"sandbox_workspace_write": "allowed"}},
        },
        contract={"required_artifacts": [{"artifact_kind": "html_document", "path": "game.html"}]},
    )

    assert f"{artifact_root}/game.html" in scope.canonical_output_paths
    assert ".tmp" in scope.write_roots
    assert ".tmp" in scope.scratch_roots
    assert ".tmp" not in scope.publish_roots


def test_managed_project_workspace_write_scope_is_not_limited_to_artifacts() -> None:
    artifact_root = "storage/task_environments/coding/vibe-workspace/artifacts"
    scope = compile_sandbox_execution_scope(
        environment_payload={
            "storage_space": {
                "environment_storage_root": "storage/task_environments/coding/vibe-workspace",
                "runtime_state_root": "storage/task_environments/coding/vibe-workspace/runtime_state",
                "artifact_root": artifact_root,
                "cache_root": "storage/task_environments/coding/vibe-workspace/cache",
            },
            "sandbox_policy": {"enabled": True, "write_policy": "sandbox_or_task_granted"},
            "file_management": {
                "file_profile_refs": ["file_profile.managed_project_workspace"],
                "constraints": {"sandbox_workspace_write": "allowed"},
            },
        },
        contract={},
    )

    assert "." in scope.workspace_write_roots
    assert "." in scope.write_roots
    assert scope.publish_roots == (artifact_root,)


def test_managed_project_file_policy_uses_artifacts_when_sandbox_is_absent() -> None:
    policy = compile_tool_file_management_policy(
        {
            "file_management": {
                "file_profile_refs": ["file_profile.managed_project_workspace"],
                "constraints": {
                    "project_workspace_read": "allowed",
                    "project_workspace_search": "allowed",
                    "project_workspace_write": "task_granted",
                    "project_workspace_edit": "task_granted",
                    "sandbox_workspace_read": "allowed",
                    "sandbox_workspace_search": "allowed",
                    "sandbox_workspace_write": "allowed",
                    "sandbox_workspace_edit": "allowed",
                    "artifact_repository_read": "allowed",
                    "artifact_repository_search": "allowed",
                    "artifact_repository_write": "allowed",
                    "artifact_repository_edit": "allowed",
                    "default_read_repository": "repo.managed_project.sandbox_workspace",
                    "default_search_repository": "repo.managed_project.sandbox_workspace",
                    "default_write_repository": "repo.managed_project.sandbox_workspace",
                    "default_edit_repository": "repo.managed_project.sandbox_workspace",
                },
            }
        },
        sandbox_policy={"enabled": False},
    )

    assert policy["repositories"]["read"] == "repo.managed_project.project_workspace"
    assert policy["repositories"]["search"] == "repo.managed_project.project_workspace"
    assert policy["repositories"]["write"] == "repo.managed_project.artifacts"
    assert policy["repositories"]["edit"] == "repo.managed_project.artifacts"
    assert set(policy["agent_allowed_file_actions"]) == {"read", "search", "write", "edit"}


def test_safety_gate_allows_any_write_inside_sandbox_root(tmp_path: Path) -> None:
    sandbox_root = tmp_path / "sandbox"
    workspace_root = Path(__file__).resolve().parents[2]
    outside_root = workspace_root.parent / "outside-sandbox-root"
    sandbox_root.mkdir()
    validators = build_task_safety_validators(
        root_dir=workspace_root,
        safety_envelope={
            "write_mode": "bounded_create",
            "write_roots": ["storage/task_environments/coding/vibe-workspace/artifacts"],
            "canonical_output_paths": ["storage/task_environments/coding/vibe-workspace/artifacts/game.html"],
        },
        sandbox_policy={"enabled": True, "sandbox_root": str(sandbox_root)},
    )

    assert validators["filesystem_path"]({"operation_id": "op.write_file", "args": {"path": "game.html"}}) is True
    assert validators["filesystem_path"]({"operation_id": "op.write_file", "args": {"path": "docs/game.html"}}) is True

    assert validators["filesystem_path"]({"operation_id": "op.write_file", "args": {"path": str(outside_root / "game.html")}}) == (
        False,
        "path traversal detected",
    )
