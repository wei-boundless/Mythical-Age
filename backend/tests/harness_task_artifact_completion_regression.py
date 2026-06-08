from __future__ import annotations

from tests.support.harness_runtime_facade_support import *

def test_required_artifact_completion_requires_existing_file() -> None:
    from harness.loop.task_executor import _verify_completion

    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    contract = {"required_artifacts": [{"artifact_kind": "html_game", "user_visible_name": "游戏"}]}
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }

    missing = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id="taskrun:test:missing",
        contract=contract,
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/artifacts/game.html"}],
    )

    real_path = project_root / "storage/task_environments/development/sandbox/artifacts/game.html"
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text("<!doctype html><title>game</title>", encoding="utf-8")
    present = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id="taskrun:test:present",
        contract=contract,
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/artifacts/game.html"}],
    )

    assert missing["ok"] is False
    assert missing["missing"] == ["required_artifacts"]
    assert present["ok"] is True
    assert present["verified_artifacts"][0]["exists"] is True

def test_sandbox_artifact_is_published_before_completion() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:publish"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_file = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/game.html"
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.write_text("<!doctype html><canvas></canvas>", encoding="utf-8")
    published_file = project_root / "storage/task_environments/development/sandbox/artifacts/game.html"

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game"}]},
        artifact_refs=[
            {
                "path": "storage/task_environments/development/sandbox/artifacts/game.html",
                "absolute_path": str(sandbox_file),
                "sandbox_path": "storage/task_environments/development/sandbox/artifacts/game.html",
            }
        ],
    )

    assert verdict["ok"] is True
    assert published_file.exists()
    assert published_file.read_text(encoding="utf-8") == "<!doctype html><canvas></canvas>"
    assert verdict["verified_artifacts"][0]["path"] == "storage/task_environments/development/sandbox/artifacts/game.html"

def test_sandbox_artifact_publish_overwrites_stale_workspace_file() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:publish-overwrite-stale"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    logical_path = "storage/task_environments/development/sandbox/artifacts/stale-game.html"
    published_file = project_root / logical_path
    published_file.parent.mkdir(parents=True, exist_ok=True)
    published_file.write_text("<!doctype html><title>stale</title>", encoding="utf-8")
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_file = Path(str(policy["sandbox_root"])) / logical_path
    sandbox_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_file.write_text("<!doctype html><title>fresh</title><canvas></canvas>", encoding="utf-8")

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game"}]},
        artifact_refs=[{"path": logical_path, "absolute_path": str(sandbox_file), "sandbox_path": logical_path}],
    )

    assert verdict["ok"] is True
    assert published_file.read_text(encoding="utf-8") == "<!doctype html><title>fresh</title><canvas></canvas>"
    assert verdict["verified_artifacts"][0]["size_bytes"] == published_file.stat().st_size

def test_completion_discovers_sandbox_artifacts_not_returned_by_tool_refs() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    task_run_id = "taskrun:test:discover-sandbox-artifacts"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_asset = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/assets/player.png"
    sandbox_asset.parent.mkdir(parents=True, exist_ok=True)
    sandbox_asset.write_bytes(b"\x89PNG\r\n\x1a\nsandbox-player")
    unrelated = sandbox_asset.parent / "scratch.txt"
    unrelated.write_text("scratch", encoding="utf-8")
    published_asset = project_root / "storage/task_environments/development/sandbox/artifacts/assets/player.png"
    unrelated_published = project_root / "storage/task_environments/development/sandbox/artifacts/assets/scratch.txt"

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "image_file", "path": "storage/task_environments/development/sandbox/artifacts/assets/player.png"}]},
        artifact_refs=[],
    )

    assert verdict["ok"] is True
    assert published_asset.exists()
    assert published_asset.read_bytes() == b"\x89PNG\r\n\x1a\nsandbox-player"
    assert any(item["path"].endswith("assets/player.png") for item in verdict["verified_artifacts"])
    assert not unrelated_published.exists()
    assert not any(item["path"].endswith("scratch.txt") for item in verdict["verified_artifacts"])

def test_completion_discovery_ignores_free_text_artifact_names() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_harness_runtime()
    task_run_id = "taskrun:test:discover-structured-only"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {"artifact_root": "storage/task_environments/development/sandbox/artifacts"},
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)
    sandbox_asset = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/artifacts/assets/free-text-player.png"
    sandbox_asset.parent.mkdir(parents=True, exist_ok=True)
    sandbox_asset.write_bytes(b"\x89PNG\r\n\x1a\nfree-text-player")

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "image_file", "user_visible_name": "free-text-player.png"}]},
        artifact_refs=[],
    )

    assert verdict["ok"] is False
    assert verdict["verified_artifacts"] == []

def test_task_sandbox_workspace_root_is_project_root() -> None:
    from harness.loop.task_executor import _task_sandbox_policy

    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    policy = _task_sandbox_policy(
        {"task_environment": {"storage_space": {}, "sandbox_policy": {}}},
        runtime_host=runtime.single_agent_runtime_host,
        task_run_id="taskrun:test:workspace-root",
    )

    assert Path(str(policy["workspace_root"])).resolve() == project_root

def test_task_sandbox_grants_environment_scratch_without_publishing_it() -> None:
    from harness.loop.task_executor import _task_sandbox_policy, _verify_completion

    runtime = build_harness_runtime()
    task_run_id = "taskrun:test:scratch-scope"
    runtime_assembly = {
        "task_environment": {
            "storage_space": {
                "environment_storage_root": "storage/task_environments/development/sandbox",
                "runtime_state_root": "storage/task_environments/development/sandbox/runtime_state",
                "artifact_root": "storage/task_environments/development/sandbox/artifacts",
                "cache_root": "storage/task_environments/development/sandbox/cache",
            },
            "sandbox_policy": {},
        }
    }
    policy = _task_sandbox_policy(runtime_assembly, runtime_host=runtime.single_agent_runtime_host, task_run_id=task_run_id)

    assert "storage/task_environments/development/sandbox/tmp" in policy["write_scopes"]
    assert "storage/task_environments/development/sandbox/cache" in policy["write_scopes"]
    assert "storage/task_environments/development/sandbox/runtime_state" in policy["write_scopes"]
    assert "storage/task_environments/development/sandbox/tmp" not in policy["publish_scopes"]
    assert "." not in policy["write_scopes"]

    scratch_file = Path(str(policy["sandbox_root"])) / "storage/task_environments/development/sandbox/tmp/debug-note.html"
    scratch_file.parent.mkdir(parents=True, exist_ok=True)
    scratch_file.write_text("<!doctype html><title>scratch</title>", encoding="utf-8")

    verdict = _verify_completion(
        runtime_host=runtime.single_agent_runtime_host,
        runtime_assembly=runtime_assembly,
        task_run_id=task_run_id,
        contract={"required_artifacts": [{"artifact_kind": "html_game", "user_visible_name": "debug-note.html"}]},
        artifact_refs=[{"path": "storage/task_environments/development/sandbox/tmp/debug-note.html", "absolute_path": str(scratch_file)}],
    )

    assert verdict["ok"] is False
    assert verdict["missing"] == ["required_artifacts"]

def test_task_run_artifact_view_returns_only_existing_files() -> None:
    runtime = build_harness_runtime()
    project_root = Path(runtime.base_dir).resolve().parent
    existing = project_root / "storage/task_environments/development/sandbox/artifacts/final.html"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("<!doctype html><title>final</title>", encoding="utf-8")
    runtime.single_agent_runtime_host.state_index.upsert_agent_run_result(
        AgentRunResult(
            agent_run_result_id="agresult:test-artifacts",
            agent_run_id="agrun:test-artifacts",
            task_run_id="taskrun:test-artifacts",
            agent_id="agent:0",
            status="completed",
            artifact_refs=(
                "storage/task_environments/development/sandbox/artifacts/final.html",
                "storage/task_environments/development/sandbox/artifacts/missing.html",
            ),
        )
    )

    view = runtime.single_agent_runtime_host.get_task_run_artifacts("taskrun:test-artifacts")

    assert view["created_files"] == ["storage/task_environments/development/sandbox/artifacts/final.html"]
    assert view["artifact_refs"][0]["exists"] is True

def test_running_task_artifact_view_includes_tool_observation_refs() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    project_root = Path(runtime.base_dir).resolve().parent
    canonical_artifact = project_root / "storage/task_environments/general/workspace/artifacts/plan.md"
    canonical_artifact.parent.mkdir(parents=True, exist_ok=True)
    canonical_artifact.write_text("# canonical plan", encoding="utf-8")
    sandbox_artifact = project_root / "storage/runtime_state/sandboxes/taskrun_test_running_artifacts/storage/task_environments/general/workspace/artifacts/plan.md"
    sandbox_artifact.parent.mkdir(parents=True, exist_ok=True)
    sandbox_artifact.write_text("# sandbox plan", encoding="utf-8")
    task_run_id = "taskrun:test:running-artifacts"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-running-artifacts",
            task_id="task:running-artifacts",
            status="running",
            created_at=100.0,
            updated_at=110.0,
            execution_runtime_kind="single_agent_task",
            diagnostics={
                "artifact_refs": [
                    {
                        "path": "storage/task_environments/general/workspace/artifacts/plan.md",
                        "absolute_path": str(canonical_artifact),
                        "kind": "file",
                        "source": "write_file",
                    }
                ]
            },
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "payload": {
                    "tool_name": "write_file",
                    "result_envelope": {
                        "artifact_refs": [
                            {
                                "path": "storage/task_environments/general/workspace/artifacts/plan.md",
                                "absolute_path": str(sandbox_artifact),
                                "kind": "file",
                                "source": "write_file",
                            }
                        ],
                    },
                },
            },
        },
    )

    view = host.get_task_run_artifacts(task_run_id)
    monitor = host.get_task_run_live_monitor(task_run_id)

    assert view["created_files"] == [
        "storage/task_environments/general/workspace/artifacts/plan.md"
    ]
    assert view["artifact_refs"][0]["exists"] is True
    assert monitor is not None
    assert monitor["artifact_count"] == 1
    assert monitor["artifact_refs"][0]["source"] == "write_file"

def test_artifact_view_prefers_published_path_over_sandbox_absolute_path() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    project_root = Path(runtime.base_dir).resolve().parent
    logical_path = "storage/task_environments/general/workspace/artifacts/calculator.html"
    published_artifact = project_root / logical_path
    published_artifact.parent.mkdir(parents=True, exist_ok=True)
    published_artifact.write_text("<!doctype html><title>published</title>", encoding="utf-8")
    sandbox_artifact = (
        project_root
        / "storage/runtime_state/sandboxes/taskrun_test_calculator/storage/task_environments/general/workspace/artifacts/calculator.html"
    )
    sandbox_artifact.parent.mkdir(parents=True, exist_ok=True)
    sandbox_artifact.write_text("<!doctype html><title>sandbox</title>", encoding="utf-8")
    task_run_id = "taskrun:test:calculator-artifact-index"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-calculator-artifact-index",
            task_id="task:calculator-artifact-index",
            status="running",
            created_at=100.0,
            updated_at=110.0,
            execution_runtime_kind="single_agent_task",
        )
    )
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={
            "observation": {
                "payload": {
                    "tool_name": "write_file",
                    "result_envelope": {
                        "artifact_refs": [
                            {
                                "path": logical_path,
                                "absolute_path": str(sandbox_artifact),
                                "sandbox_path": logical_path,
                                "kind": "file",
                                "source": "write_file",
                            }
                        ],
                    },
                },
            },
        },
    )

    view = host.get_task_run_artifacts(task_run_id)

    assert view["created_files"] == [logical_path]
    assert view["artifact_refs"][0]["absolute_path"] == str(published_artifact.resolve())
    assert Path(view["artifact_refs"][0]["absolute_path"]).read_text(encoding="utf-8") == "<!doctype html><title>published</title>"
