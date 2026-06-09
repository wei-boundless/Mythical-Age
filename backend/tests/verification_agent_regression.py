from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.task_executor import _verify_completion
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract
from runtime.shared.models import AgentRun, TaskRun
from tests.support.runtime_stubs import build_harness_runtime


class _RespondingTaskModelRuntime:
    def __init__(self, final_answer: str = "已完成。") -> None:
        self.final_answer = final_answer
        self.task_invocation_count = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.task_invocation_count += 1
        return SimpleNamespace(
            content=json.dumps(
                _task_action(action_type="respond", final_answer=self.final_answer),
                ensure_ascii=False,
            )
        )


def test_verify_completion_requires_verifier_verdict_when_gate_is_enforced() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    verdict = _verify_completion(
        runtime_host=host,
        runtime_assembly={"task_environment": {"storage_space": {"artifact_root": "storage/task_environments/coding/vibe-workspace/artifacts"}}},
        task_run_id="taskrun:verify-gate:missing",
        contract={"required_verifications": [{"verification_kind": "pytest"}]},
        artifact_refs=[],
        observations=[],
        enforce_verification_gate=True,
    )

    assert verdict["ok"] is False
    assert verdict["missing"] == ["verification_worker_verdict"]
    assert verdict["verification_gate"]["required_reasons"] == ["required_verifications"]
    assert "spawn_subagent" in verdict["repair_instruction"]


def test_verify_completion_accepts_pass_verifier_wait_result_and_rejects_partial() -> None:
    runtime = build_harness_runtime()
    host = runtime.single_agent_runtime_host
    pass_observation = _seed_verifier_wait_observation(host, task_run_id="taskrun:verify-gate:pass", verdict="PASS")
    partial_observation = _seed_verifier_wait_observation(host, task_run_id="taskrun:verify-gate:partial", verdict="PARTIAL")

    passed = _verify_completion(
        runtime_host=host,
        runtime_assembly={"task_environment": {"storage_space": {"artifact_root": "storage/task_environments/coding/vibe-workspace/artifacts"}}},
        task_run_id="taskrun:verify-gate:pass",
        contract={"required_verifications": [{"verification_kind": "pytest"}]},
        artifact_refs=[],
        observations=[pass_observation],
        enforce_verification_gate=True,
    )
    partial = _verify_completion(
        runtime_host=host,
        runtime_assembly={"task_environment": {"storage_space": {"artifact_root": "storage/task_environments/coding/vibe-workspace/artifacts"}}},
        task_run_id="taskrun:verify-gate:partial",
        contract={"required_verifications": [{"verification_kind": "pytest"}]},
        artifact_refs=[],
        observations=[partial_observation],
        enforce_verification_gate=True,
    )

    assert passed["ok"] is True
    assert passed["verification_gate"]["latest_verdict"]["verdict"] == "PASS"
    assert partial["ok"] is False
    assert partial["missing"] == ["verification_worker_pass"]
    assert partial["verification_gate"]["latest_verdict"]["verdict"] == "PARTIAL"


def test_task_executor_completion_gate_blocks_direct_finish_without_verifier() -> None:
    model = _RespondingTaskModelRuntime()
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_task_with_required_verification(runtime, task_run_id="taskrun:executor:verify-gate:missing")
    host = runtime.single_agent_runtime_host

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = host.state_index.get_task_run(task_run_id)
    repair_events = [
        event
        for event in host.event_log.list_events(task_run_id)
        if event.event_type == "task_completion_repair_required"
    ]

    assert result["ok"] is False
    assert task_run is not None
    assert task_run.status == "waiting_executor"
    assert model.task_invocation_count == 1
    assert repair_events
    repair_payload = dict(repair_events[-1].payload or {})
    repair_verdict = dict(repair_payload.get("verdict") or {})
    assert repair_verdict["missing"] == ["verification_worker_verdict"]
    assert "spawn_subagent" in repair_verdict["repair_instruction"]


def test_task_executor_completion_gate_allows_finish_after_pass_verifier() -> None:
    model = _RespondingTaskModelRuntime(final_answer="验证员 PASS 后完成。")
    runtime = build_harness_runtime(model_runtime=model)
    task_run_id = _seed_task_with_required_verification(runtime, task_run_id="taskrun:executor:verify-gate:pass")
    host = runtime.single_agent_runtime_host
    _record_verifier_wait_observation(host, task_run_id=task_run_id, verdict="PASS")

    result = asyncio.run(runtime.execute_task_run(task_run_id, max_steps=1))
    task_run = host.state_index.get_task_run(task_run_id)

    assert result["ok"] is True
    assert task_run is not None
    assert task_run.status == "completed"
    completion_verdict = dict(dict(task_run.diagnostics or {}).get("final_action_diagnostics") or {}).get("completion_verdict")
    assert dict(dict(completion_verdict or {}).get("verification_gate") or {}).get("latest_verdict", {}).get("verdict") == "PASS"


def _task_action(*, action_type: str, final_answer: str = "") -> dict[str, object]:
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"model-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "public_progress_note": "正在收口当前任务。",
        "public_action_state": {
            "current_judgment": "当前任务已有候选结果。",
            "next_action": "准备完成。",
            "completion_status": "ready_to_finish",
        },
        "final_answer": final_answer,
        "diagnostics": {},
    }


def _seed_task_with_required_verification(runtime, *, task_run_id: str) -> str:
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id=f"task-contract:{task_run_id.replace(':', '-')}",
        contract_source="test",
        user_visible_goal="验证 completion verifier gate。",
        task_run_goal="验证 completion verifier gate。",
        required_verifications=({"verification_kind": "pytest"},),
        completion_criteria=("必须有 completion verifier PASS verdict",),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status="waiting_executor",
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=f"session:{task_run_id}",
            task_id=f"task:{task_run_id}",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            terminal_reason="waiting_executor",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "contract": contract.to_dict(),
                "runtime_contract": {"runtime_profile": {}},
            },
        )
    )
    return task_run_id


def _record_verifier_wait_observation(host, *, task_run_id: str, verdict: str) -> dict[str, object]:
    observation = _seed_verifier_wait_observation(host, task_run_id=task_run_id, verdict=verdict)
    host.event_log.append(
        task_run_id,
        "task_tool_observation_recorded",
        payload={"observation": observation},
        refs={"task_run_ref": task_run_id, "observation_ref": observation["observation_id"]},
    )
    return observation


def _seed_verifier_wait_observation(host, *, task_run_id: str, verdict: str) -> dict[str, object]:
    child_task_run_id = f"{task_run_id}:subagent:verifier:{verdict.lower()}"
    child_run_id = f"agrun:{child_task_run_id}:main"
    final_answer = (
        f"verdict: {verdict}\n"
        "checks:\n"
        "- command: pytest -q\n"
        "- evidence: rtobs:child:pytest\n"
        "- adversarial probe: checked completion criteria against artifacts."
    )
    result_payload = {
        "status": "completed",
        "final_answer": final_answer,
        "summary": final_answer,
        "verdict": verdict,
        "checks": [{"kind": "command", "command": "pytest -q", "result": "passed"}],
        "evidence_refs": ["rtobs:child:pytest"],
        "observation_refs": ["rtobs:child:pytest"],
        "artifact_refs": [],
    }
    result_ref = host.runtime_objects.put_object("agent_run_result", f"{child_run_id}:result", result_payload)
    host.state_index.upsert_agent_run(
        AgentRun(
            agent_run_id=child_run_id,
            task_run_id=child_task_run_id,
            agent_id="agent:verifier",
            agent_profile_id="completion_verifier_agent",
            role="subagent_worker",
            spawn_mode="subagent",
            parent_agent_run_ref=f"agrun:{task_run_id}:main",
            execution_runtime_kind="subagent_task",
            status="completed",
            result_ref=result_ref,
            created_at=1.0,
            updated_at=1.0,
        )
    )
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=child_task_run_id,
            session_id=f"session:{task_run_id}",
            task_id=f"task:{child_task_run_id}",
            agent_id="agent:verifier",
            agent_profile_id="completion_verifier_agent",
            execution_runtime_kind="subagent_task",
            status="completed",
            terminal_reason="completed",
            diagnostics={"final_answer": final_answer, "final_action_diagnostics": {"verdict": verdict}},
        )
    )
    result_view = {
        "status": "completed",
        "result_ref": result_ref,
        "final_answer": final_answer,
        "summary": final_answer,
        "artifact_refs": [],
        "observation_refs": ["rtobs:child:pytest"],
        "authority": "orchestration.subagent_result_projection",
    }
    control = {
        "ok": True,
        "status": "completed",
        "subagent_run_ref": child_run_id,
        "result_available": True,
        "result": result_view,
    }
    envelope = {
        "tool_name": "wait_subagent",
        "tool_args": {"subagent_run_ref": child_run_id},
        "status": "ok",
        "text": json.dumps(control, ensure_ascii=False, sort_keys=True),
        "structured_payload": {
            "subagent_control": control,
            "artifact_refs": [],
        },
        "artifact_refs": [],
        "authority": "execution.tool_result_envelope",
    }
    return {
        "observation_id": f"rtobs:{task_run_id}:wait-verifier:{verdict.lower()}",
        "task_run_id": task_run_id,
        "observation_type": "tool_result",
        "source": "tool:wait_subagent",
        "request_ref": f"model-action:test:wait-verifier:{verdict.lower()}",
        "directive_ref": f"runtime-directive:{task_run_id}:tool:wait-verifier",
        "content_chars": len(envelope["text"]),
        "payload": {
            "tool_name": "wait_subagent",
            "tool_args": {"subagent_run_ref": child_run_id},
            "result_envelope": envelope,
        },
        "needs_model_followup": False,
        "authority": "orchestration.runtime_observation",
    }
