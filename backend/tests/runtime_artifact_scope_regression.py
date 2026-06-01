from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from harness.loop.task_executor import _task_sandbox_policy, _verify_completion
from harness.runtime.artifact_scope import canonicalize_task_contract_artifacts


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
    artifact_root = "storage/task_environments/development/sandbox/artifacts"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {
                "environment_storage_root": "storage/task_environments/development/sandbox",
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
    artifact_root = "storage/task_environments/development/sandbox/artifacts"
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
        artifact_root="storage/task_environments/development/sandbox/artifacts",
    )

    assert normalized.contract["required_artifacts"] == [{"artifact_kind": "html_document"}]
    assert normalized.normalizations[0]["status"] == "invalid_path_removed"
    assert normalized.normalizations[0]["requested_path"] == "C:/tmp/escape.html"
