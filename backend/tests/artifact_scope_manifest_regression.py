from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.artifact_scope_manifest import build_artifact_scope_manifest
from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.sandbox_execution_scope import compile_sandbox_execution_scope


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _environment() -> dict[str, object]:
    return {
        "environment_id": "env.general.workspace",
        "storage_space": {
            "environment_storage_root": "storage/task_environments/development/sandbox",
            "runtime_state_root": "storage/task_environments/development/sandbox/runtime_state",
            "artifact_root": "storage/task_environments/development/sandbox/artifacts",
            "cache_root": "storage/task_environments/development/sandbox/cache",
        },
        "sandbox_policy": {"enabled": True, "write_policy": "sandbox_or_task_granted"},
    }


def _contract() -> dict[str, object]:
    return {
        "task_run_goal": "Validate artifact scope manifest",
        "completion_criteria": ["manifest attached"],
        "required_artifacts": [{"artifact_kind": "html_document", "path": "demo/index.html"}],
    }


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    text = str(content or "")
    assert text.startswith(title + "\n")
    return json.loads(text.split("\n", 1)[1])


def _message_payload_with_title(packet, title: str) -> dict[str, object]:
    for message in packet.model_messages:
        content = str(dict(message).get("content") or "")
        if content.startswith(title + "\n"):
            return _payload_after_title(content, title)
    raise AssertionError(f"missing model message title: {title}")


def test_artifact_scope_manifest_renders_legacy_model_visible_payload() -> None:
    scope = compile_sandbox_execution_scope(
        environment_payload=_environment(),
        contract=_contract(),
    )
    manifest = build_artifact_scope_manifest(
        invocation_kind="task_execution",
        sandbox_execution_scope=scope,
        source_ref="task_execution_artifact_write_scope",
    )

    assert manifest.source_ref == "task_execution_artifact_write_scope"
    assert manifest.scope_hash.startswith("sha256:")
    assert manifest.artifact_root == "storage/task_environments/development/sandbox/artifacts"
    assert "storage/task_environments/development/sandbox/artifacts/demo/index.html" in manifest.canonical_output_paths
    assert manifest.to_model_visible_payload() == {"artifact_execution_scope": scope.to_model_visible_payload()}


def test_task_execution_packet_attaches_artifact_scope_manifest_without_prompt_drift() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:artifact-scope-manifest",
        task_run={"task_run_id": "taskrun:artifact-scope-manifest", "diagnostics": {"executor_status": "running"}},
        contract=_contract(),
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": _environment(),
        },
    )

    packet = result.packet
    artifact_payload = _message_payload_with_title(packet, "Task execution artifact write scope")
    artifact_segment = next(
        segment
        for segment in list(packet.segment_plan.get("segments") or [])
        if dict(segment).get("kind") == "artifact_scope_stable"
    )
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert artifact_payload == {"artifact_execution_scope": packet.artifact_scope_manifest["model_visible_scope"]}
    assert artifact_segment["source_ref"] == packet.artifact_scope_manifest["source_ref"]
    assert prompt_manifest["artifact_scope_manifest"] == packet.artifact_scope_manifest
    assert packet.diagnostics["artifact_scope_manifest"] == packet.artifact_scope_manifest
    assert "storage/task_environments/development/sandbox/artifacts/demo/index.html" in packet.artifact_scope_manifest["canonical_output_paths"]


def test_single_agent_turn_does_not_attach_task_artifact_scope_manifest() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:artifact-scope-single",
        turn_id="turn:artifact-scope-single",
        agent_invocation_id="aginvoke:artifact-scope-single",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": _environment(),
        },
    )

    packet = result.packet
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert packet.artifact_scope_manifest == {}
    assert "artifact_scope_manifest" not in prompt_manifest
    assert "artifact_scope_manifest" not in packet.diagnostics
