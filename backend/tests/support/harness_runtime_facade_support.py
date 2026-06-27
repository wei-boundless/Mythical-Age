from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.entrypoint.models import HarnessRuntimeRequest
from api.chat import (
    _project_public_stream_event,
    _runtime_run_refs_from_event,
)
from runtime.shared.models import AgentRunResult, TaskRun, TurnRun
from runtime.tool_runtime import ToolObservation
from harness.loop.model_action_protocol import ModelActionRequest
from memory_system import MemoryFacade
from memory_system.storage.models import MemoryNote
from harness.loop.task_executor import (
    TaskRunExecutorInterrupted,
    _duplicate_read_only_tool_call_observation,
    _matching_model_action_admission_denial_observations,
    _model_action_admission_recovery_observation,
    _tool_call_progress_summary,
)
from harness.loop.task_run_execution_control import ExecutorControlSignal
from harness.runtime.tool_batch_planner import ToolBatchGroup

task_executor_module = sys.modules["harness.loop.task_executor"]
from harness.loop.task_lifecycle import (
    TaskLifecycleRecord,
    TaskRunContract,
    start_task_lifecycle_from_action_request,
)
from sessions import SessionManager
from capability_system.tools.native_tool_catalog import build_tool_instances, get_tool_definitions
from tests.support.runtime_stubs import (
    NativeToolCallSequenceModelRuntimeStub,
    NativeToolCallModelRuntimeStub,
    PrimarySettingsStub,
    SingleMessageModelRuntimeStub,
    StreamingMessageModelRuntimeStub,
    build_harness_runtime,
    isolated_backend_root,
)
from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptCachePlanner,
    extract_provider_usage,
)
from runtime.model_gateway.model_request import ModelRequestBuilder


_VISIBLE_RUNTIME_INTERNAL_MARKERS = (
    "TaskRun",
    "runtime packet",
    "正式任务生命周期",
    "执行器",
    "agent 已返回",
    "agent 动作",
    "等待 agent",
    "回灌给 agent",
)


def _assert_no_visible_runtime_internals(text: str) -> None:
    leaked = [marker for marker in _VISIBLE_RUNTIME_INTERNAL_MARKERS if marker in text]
    assert leaked == []


def _packet_payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert content.startswith(marker)
    return json.loads(content[len(marker):])


def _admission_payloads(events: list[dict[str, object]]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for event in events:
        if event.get("type") != "model_action_admission":
            continue
        runtime_event = dict(event.get("event") or {})
        payload = dict(runtime_event.get("payload") or {})
        if payload:
            payloads.append(payload)
    return payloads


def _action_request(
    *,
    action_type: str,
    final_answer: str = "",
    user_question: str = "",
    blocking_reason: str = "",
    public_progress_note: str = "正在处理当前请求。",
    task_contract_seed: dict[str, object] | None = None,
    tool_call: dict[str, object] | None = None,
    active_work_control: dict[str, object] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"model-action:test:{action_type}",
        "turn_id": "",
        "action_type": action_type,
        "public_progress_note": public_progress_note,
        "public_action_state": {
            "current_judgment": "测试动作可继续执行。",
            "next_action": public_progress_note,
        },
        "final_answer": final_answer,
        "user_question": user_question,
        "blocking_reason": blocking_reason,
        "tool_call": dict(tool_call or {}),
        "task_contract_seed": dict(task_contract_seed or {}),
        "completion_contract": {},
        "permission_request": {},
        "active_work_control": dict(active_work_control or {}),
        "diagnostics": {"test_action_request": True, **dict(diagnostics or {})},
    }


def _canonical_task_contract_seed(
    seed: dict[str, object] | None = None,
    *,
    target_objects: list[object] | None = None,
    known_constraints: list[str] | None = None,
    capability_groups: list[str] | None = None,
    tool_namespaces: list[str] | None = None,
    selected_skill_ids: list[str] | None = None,
    candidate_skill_ids: list[str] | None = None,
    capability_reason: str = "测试任务需要系统提供对应能力服务。",
    evidence_policy: str = "observation_required",
) -> dict[str, object]:
    del capability_groups, tool_namespaces, selected_skill_ids, candidate_skill_ids, capability_reason, evidence_policy
    payload = dict(seed or {})
    if "working_scope" not in payload:
        payload["working_scope"] = {
            "target_objects": list(
                target_objects
                or [
                    str(
                        payload.get("task_run_goal")
                        or payload.get("user_visible_goal")
                        or "测试任务对象"
                    )
                ]
            ),
            "workspace_refs": [],
            "source_refs": [],
            "excluded_scope": [],
            "known_constraints": list(known_constraints or []),
        }
    return payload


def _project_backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_test_root(tmp_path: Path) -> Path:
    root = tmp_path / "runtime-root"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tool_runtime_for_names(tool_base_dir: Path, names: set[str]) -> SimpleNamespace:
    selected = {str(name) for name in names if str(name)}
    tool_instances = [tool for tool in build_tool_instances(tool_base_dir) if getattr(tool, "name", "") in selected]
    definitions = [definition for definition in get_tool_definitions() if definition.name in selected]
    return SimpleNamespace(
        base_dir=tool_base_dir,
        definitions=definitions,
        instances=tool_instances,
        get_definition=lambda name: next((definition for definition in definitions if definition.name == name), None),
        get_instance=lambda name: next((tool for tool in tool_instances if getattr(tool, "name", "") == name), None),
    )


def _session_artifact_path(session_id: str, namespace: str, filename: str) -> str:
    return f"mythical-agent/sessions/{session_id}/environments/{namespace}/artifacts/{filename}"


class _MalformedModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(content=json.dumps({"authority": "bad"}))


class _FailingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        raise TimeoutError("model timed out")


class _SlowRespondingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(0.02)
        return SimpleNamespace(
            content=json.dumps(
                _action_request(
                    action_type="respond",
                    final_answer="慢模型完成。",
                ),
                ensure_ascii=False,
            )
        )


class _NeverRespondingModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(60)
        return SimpleNamespace(content="{}")


class _TurnActionSequenceModelRuntime:
    def __init__(self, actions: list[dict[str, object]]) -> None:
        self.actions = list(actions)
        self.invocation_count = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.invocation_count += 1
        if self.actions:
            action = self.actions.pop(0)
        else:
            action = _action_request(action_type="respond", final_answer="完成。")
        return SimpleNamespace(content=json.dumps(action, ensure_ascii=False))


class _UnexpectedNativeToolCallModelRuntime:
    def __init__(self, tool_calls: list[dict[str, object]], *, recovery_action: dict[str, object] | None = None) -> None:
        self.tool_calls = [dict(item) for item in tool_calls]
        self.recovery_action = dict(recovery_action or {})
        self.invocation_count = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.invocation_count += 1
        if self.invocation_count == 1:
            return SimpleNamespace(content="", tool_calls=[dict(item) for item in self.tool_calls])
        if self.recovery_action:
            return SimpleNamespace(content=json.dumps(self.recovery_action, ensure_ascii=False))
        return SimpleNamespace(content="")


class _ActiveWorkDecisionModelRuntime:
    def __init__(self, decisions: list[dict[str, object]]) -> None:
        self.decisions = list(decisions)
        self.active_work_decision_count = 0
        self.active_work_followup_count = 0
        self.last_active_work_decision: dict[str, object] = {}

    async def invoke_messages_with_tools(self, _messages, tools, **_kwargs):
        del tools
        return await self._active_work_response(_messages)

    async def _active_work_response(self, messages):
        if self._allows_active_work_control(messages):
            self.active_work_decision_count += 1
            decision = dict(self.decisions.pop(0) if self.decisions else {
                "action": "answer_about_active_work",
                "relation_to_current_work": "current_work",
                "evidence": "测试桩默认指向当前工作",
                "response": "现在是正在处理。",
            })
            decision.pop("authority", None)
            self.last_active_work_decision = dict(decision)
            if str(decision.get("action") or "") in {"normal_response", "start_new_work"}:
                return SimpleNamespace(content="普通回复。", tool_calls=[])
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="active_work_control",
                        public_progress_note="正在处理当前工作控制请求。",
                        active_work_control=decision,
                    ),
                    ensure_ascii=False,
                ),
                tool_calls=[],
            )
        self.active_work_followup_count += 1
        return SimpleNamespace(content=self._active_work_followup_answer(messages), tool_calls=[])

    def _allows_active_work_control(self, messages) -> bool:
        marker = "Operating Contract\n"
        for message in list(messages or []):
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "")
            if not content.startswith(marker):
                continue
            try:
                payload = json.loads(content[len(marker):])
            except Exception:
                return False
            output_contract = dict(payload.get("output_contract") or {})
            allowed = {str(item) for item in list(output_contract.get("allowed_actions") or []) if str(item)}
            return "active_work_control" in allowed
        return False

    async def invoke_messages(self, messages, **_kwargs):
        response = await self._active_work_response(messages)
        content = str(getattr(response, "content", "") or "")
        if content and not content.lstrip().startswith("{"):
            return SimpleNamespace(content=json.dumps(_action_request(action_type="respond", final_answer=content), ensure_ascii=False))
        return response

    def _active_work_followup_answer(self, messages) -> str:
        observation = self._active_work_observation(messages)
        runtime_result = str(observation.get("runtime_result") or "").strip()
        status = str(observation.get("status") or "").strip()
        terminal_reason = str(observation.get("terminal_reason") or "").strip()
        control_action = str(observation.get("action") or self.last_active_work_decision.get("action") or "").strip()
        decision_response = str(self.last_active_work_decision.get("response") or "").strip()
        if terminal_reason in {
            "active_work_relation_declared_independent",
            "active_work_relation_ambiguous",
            "active_work_control_action_not_allowed",
        }:
            return decision_response or "普通回复。"
        if status == "blocked":
            return runtime_result or decision_response or "当前工作控制没有完成。"
        if control_action == "append_instruction_to_active_work" and runtime_result:
            return runtime_result
        if control_action == "answer_about_active_work" and decision_response:
            return decision_response
        return decision_response or runtime_result or "普通回复。"

    def _active_work_observation(self, messages) -> dict[str, str]:
        content = "\n".join(str(dict(message).get("content") or "") for message in list(messages or []) if isinstance(message, dict))
        if (
            "active_work_control_observation" not in content
            and "当前工作控制观察" not in content
            and '"observation_kind":"active_work_control"' not in content
            and '"observation_kind": "active_work_control"' not in content
        ):
            return {}
        anchor = max(
            content.rfind('"observation_kind":"active_work_control"'),
            content.rfind('"observation_kind": "active_work_control"'),
            content.rfind("active_work_control_observation"),
            content.rfind("当前工作控制观察"),
        )
        observation_content = content[max(0, anchor - 1000): anchor + 4000] if anchor >= 0 else content
        return {
            "status": self._json_text_field(observation_content, "status"),
            "terminal_reason": self._json_text_field(observation_content, "terminal_reason"),
            "runtime_result": self._json_text_field(observation_content, "runtime_result"),
            "action": self._json_text_field(observation_content, "control_action") or self._json_nested_action(observation_content),
        }

    @staticmethod
    def _json_text_field(content: str, field: str) -> str:
        match = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]*)"', content)
        return match.group(1) if match else ""

    @staticmethod
    def _json_nested_action(content: str) -> str:
        match = re.search(r'"active_work_control"\s*:\s*\{.*?"(?:resolved_action|action)"\s*:\s*"([^"]*)"', content, flags=re.S)
        return match.group(1) if match else ""


class _TaskExecutorSequenceModelRuntime:
    def __init__(self, task_actions: list[dict[str, object]], *, agent_turn_action_request: dict[str, object]) -> None:
        self.task_actions = list(task_actions)
        self.agent_turn_action_request = dict(agent_turn_action_request)
        self.task_invocation_count = 0

    async def invoke_messages(self, messages, **_kwargs):
        content = str(list(messages or [])[0].get("content") or "")
        if "持续处理流程" in content or "task_execution" in str(messages):
            self.task_invocation_count += 1
            action = self.task_actions.pop(0) if self.task_actions else self.task_actions[-1]
            return SimpleNamespace(content=json.dumps(action, ensure_ascii=False))
        return SimpleNamespace(content=json.dumps(self.agent_turn_action_request, ensure_ascii=False))


class _ProtocolRepairPromptProbeModelRuntime:
    def __init__(self) -> None:
        self.task_invocation_count = 0
        self.task_inputs: list[str] = []

    async def invoke_messages(self, messages, **_kwargs):
        model_input = "\n\n".join(str(dict(message).get("content") or "") for message in list(messages or []) if isinstance(message, dict))
        if "持续任务生命周期" not in model_input:
            return SimpleNamespace(
                content=json.dumps(
                    _action_request(
                        action_type="request_task_run",
                        task_contract_seed=_canonical_task_contract_seed({
                            "user_visible_goal": "协议恢复。",
                            "task_run_goal": "协议恢复。",
                            "completion_criteria": ["完成"],
                        }),
                    ),
                    ensure_ascii=False,
                )
            )
        self.task_invocation_count += 1
        self.task_inputs.append(model_input)
        if self.task_invocation_count == 1:
            return SimpleNamespace(
                content='{"action_type":"tool_call","tool_calls":[{"tool_name":"write_file","args":{"path":"artifacts/large.html","content":"<html>',
                response_metadata={"finish_reason": "length"},
                usage_metadata={"output_tokens": 2048},
            )
        assert "上一轮输出疑似达到模型输出上限并被截断" in model_input
        assert "上一轮动作没有进入执行队列" in model_input
        assert "改用 action_type=tool_call" in model_input
        assert "在 tool_calls 数组中调用 write_file 或 terminal" in model_input
        assert "tool_calls[0].args" in model_input
        return SimpleNamespace(
            content=json.dumps(
                _action_request(action_type="respond", final_answer="已按恢复协议收口。"),
                ensure_ascii=False,
            )
        )


def _tool_action_request(
    *,
    tool_name: str,
    args: dict[str, object],
    public_progress_note: str = "准备调用工具。",
) -> dict[str, object]:
    payload = _action_request(action_type="tool_call", public_progress_note=public_progress_note)
    payload.pop("tool_call", None)
    payload["tool_calls"] = [{"tool_name": tool_name, "args": dict(args)}]
    return payload


def _tool_calls_action_request(
    *,
    tool_calls: list[dict[str, object]],
    public_progress_note: str = "准备调用工具。",
) -> dict[str, object]:
    payload = _action_request(action_type="tool_call", public_progress_note=public_progress_note)
    payload.pop("tool_call", None)
    payload["tool_calls"] = [dict(item) for item in tool_calls]
    return payload


class _SlowTaskExecutorModelRuntime:
    async def invoke_messages(self, _messages, **_kwargs):
        await asyncio.sleep(0.1)
        return SimpleNamespace(
            content=json.dumps(
                _action_request(action_type="respond", final_answer="慢任务完成。"),
                ensure_ascii=False,
            )
        )


def _seed_active_work(
    runtime,
    *,
    task_run_id: str = "taskrun:active-work",
    session_id: str = "session-active-work",
    status: str = "waiting_executor",
    runtime_profile: dict[str, object] | None = None,
) -> str:
    host = runtime.single_agent_runtime_host
    contract = TaskRunContract(
        contract_id=f"task-contract:{task_run_id.replace(':', '-')}",
        contract_source="test",
        user_visible_goal="继续优化会话体验。",
        task_run_goal="继续优化会话体验。",
        completion_criteria=("同一个当前工作可以被自然语言控制",),
        runtime_profile=dict(runtime_profile or {}),
    )
    contract_ref = host.runtime_objects.put_object("task_run_contract", contract.contract_id, contract.to_dict())
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status=status,
        created_at=1.0,
        updated_at=1.0,
    )
    host.runtime_objects.put_object("task_lifecycle", task_run_id, lifecycle.to_dict())
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:{task_run_id}",
            task_contract_ref=contract_ref,
            agent_profile_id="main_interactive_agent",
            execution_runtime_kind="single_agent_task",
            status=status,
            terminal_reason="",
            created_at=1.0,
            updated_at=1.0,
            diagnostics={
                "contract": contract.to_dict(),
                "latest_step_summary": "正在整理上下文，准备继续处理。",
                "runtime_contract": {"runtime_profile": dict(runtime_profile or {})},
            },
        )
    )
    return task_run_id

__all__ = [name for name in globals() if not name.startswith('__')]

