from __future__ import annotations

import json
from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.task_contract_manifest import build_task_contract_manifest


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _contract() -> dict[str, object]:
    return {
        "contract_id": "contract:task-contract-manifest",
        "task_run_goal": "Validate task contract manifest",
        "completion_criteria": ["manifest attached"],
        "required_artifacts": [{"artifact_kind": "markdown_document", "path": "report.md"}],
    }


def _planning_protocol() -> dict[str, object]:
    return {
        "authority": "harness.runtime.planning_protocol",
        "todo_required": True,
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


def test_task_contract_manifest_renders_task_execution_model_visible_payload() -> None:
    model_visible_contract = {
        "task_run_goal": "Validate task contract manifest",
        "completion_criteria": ["manifest attached"],
        "authority": "harness.runtime.task_contract.model_visible",
    }
    manifest = build_task_contract_manifest(
        invocation_kind="task_execution",
        model_visible_contract=model_visible_contract,
        planning_protocol=_planning_protocol(),
        source_ref="contract:task-contract-manifest",
    )

    assert manifest.source_ref == "contract:task-contract-manifest"
    assert manifest.contract_hash.startswith("sha256:")
    assert manifest.planning_protocol_hash.startswith("sha256:")
    assert manifest.contract_kind == "task_contract"
    assert manifest.completion_criteria_count == 1
    assert manifest.to_model_visible_payload() == {
        "task_contract": model_visible_contract,
        "planning_protocol": _planning_protocol(),
    }


def test_task_execution_packet_attaches_task_contract_manifest_without_prompt_drift() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_task_execution_packet(
        session_id="session:task-contract-manifest",
        task_run={"task_run_id": "taskrun:task-contract-manifest", "diagnostics": {"executor_status": "running"}},
        contract=_contract(),
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    contract_payload = _message_payload_with_title(packet, "Task execution task contract")
    contract_segment = next(
        segment
        for segment in list(packet.segment_plan.get("segments") or [])
        if dict(segment).get("kind") == "task_contract_stable"
    )
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert contract_payload == {
        "task_contract": packet.task_contract_manifest["model_visible_contract"],
        "planning_protocol": packet.task_contract_manifest["planning_protocol"],
    }
    assert contract_payload["task_contract"] == packet.task_contract_manifest["model_visible_contract"]
    assert contract_payload["planning_protocol"] == packet.task_contract_manifest["planning_protocol"]
    assert contract_segment["source_ref"] == packet.task_contract_manifest["source_ref"]
    assert prompt_manifest["task_contract_manifest"] == packet.task_contract_manifest
    assert packet.diagnostics["task_contract_manifest"] == packet.task_contract_manifest
    assert packet.task_contract_manifest["source_ref"] == "contract:task-contract-manifest"


def test_single_agent_turn_does_not_attach_task_contract_manifest() -> None:
    result = RuntimeCompiler(base_dir=_backend_dir()).compile_single_agent_turn_packet(
        session_id="session:task-contract-single",
        turn_id="turn:task-contract-single",
        agent_invocation_id="aginvoke:task-contract-single",
        user_message="Answer briefly.",
        history=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    packet = result.packet
    prompt_manifest = dict(packet.diagnostics["prompt_manifest"])

    assert packet.task_contract_manifest == {}
    assert "task_contract_manifest" not in prompt_manifest
    assert "task_contract_manifest" not in packet.diagnostics
