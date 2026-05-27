from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from task_system.runtime_semantics.protocol_boundary import is_internal_protocol_input_key

from runtime.agent_assembly import (
    WorkOrder,
    build_agent_invocation,
    build_model_context_payload,
    build_task_selection_payload,
    node_work_order_from_runtime_control,
    stage_execution_request_from_runtime_control,
    strip_control_context,
)
from runtime.contracts.deliverable_validator import _protocol_leak_detected
from harness.execution.node_protocol.node_execution_request import build_node_execution_idempotency_key
from harness.runtime import AgentRunRequest, CoordinationStageAgentRunRequest


_STANDARD_INPUT_MODEL_TEXT_LIMIT = 120_000
_STANDARD_INPUT_ITEM_TEXT_LIMIT = 24_000


async def run_coordination_delivery_stream(
    runtime_host: Any,
    agent_runtime: Any,
    request: CoordinationStageAgentRunRequest,
) -> AsyncIterator[dict[str, Any]]:
    """Execute one graph coordination stage as a bounded agent invocation."""

    session_id = request.session_id
    history = [dict(item) for item in request.history]
    source = request.source
    agent_runtime_chain = request.agent_runtime_chain
    model_response_executor = request.model_response_executor
    runtime_context_manager = request.runtime_context_manager
    memory_intent = request.memory_intent
    assistant_message_committer = request.assistant_message_committer
    tool_runtime_executor = request.tool_runtime_executor
    tool_instances = list(request.tool_instances or [])
    agent_runtime_profile = request.agent_runtime_profile
    continuation_payload = dict(request.continuation_payload or {})
    next_task_ref = str(continuation_payload.get("next_task_ref") or "").strip()
    next_message = str(continuation_payload.get("message") or "").strip()
    runtime_control = dict(continuation_payload.get("runtime_control") or {})
    next_turn_context = _model_context_from_continuation_payload(continuation_payload)
    agent_invocation = _agent_invocation_from_continuation_payload(
        continuation_payload,
        base_dir=runtime_host.backend_dir,
    )
    invocation_payload = agent_invocation.to_dict() if agent_invocation is not None else {}
    assembly_contract = dict(invocation_payload.get("assembly_contract") or {})
    if not next_task_ref or not next_message:
        return
    stage_agent_id = str(assembly_contract.get("agent_id") or next_turn_context.get("agent_id") or "").strip()
    stage_agent_profile_id = str(assembly_contract.get("agent_profile_id") or next_turn_context.get("agent_profile_id") or "").strip()
    stage_runtime_lane = str(assembly_contract.get("runtime_lane") or next_turn_context.get("runtime_lane") or "").strip()
    if stage_agent_id:
        next_turn_context["agent_id"] = stage_agent_id
    if stage_agent_profile_id:
        next_turn_context["agent_profile_id"] = stage_agent_profile_id
    if stage_runtime_lane:
        next_turn_context["runtime_lane"] = stage_runtime_lane
    stage_agent_runtime_profile = None
    if stage_agent_id:
        stage_agent_runtime_profile = runtime_host.agent_runtime_registry.get_profile(stage_agent_id)
        if stage_agent_runtime_profile is None:
            raise ValueError(f"TaskGraph node agent has no runtime profile: {stage_agent_id}")
    stage_request = stage_execution_request_from_runtime_control(continuation_payload)
    standard_input_package = dict(runtime_control.get("standard_input_package") or stage_request.get("standard_input_package") or {})
    standard_input_materials = _render_standard_input_package_for_model(standard_input_package)
    if standard_input_materials and standard_input_materials not in next_message:
        next_message = f"{next_message}\n\n{standard_input_materials}"
    turn_marker = str(next_turn_context.get("turn_id") or "").strip() or _stable_stage_turn_id(
        session_id=session_id,
        task_ref=next_task_ref,
        stage_request=stage_request,
    )
    next_turn_context["turn_id"] = turn_marker
    next_task_id = f"taskinst:{turn_marker}:{next_task_ref.split('.')[-1]}"
    task_selection = _task_selection_from_continuation_context(
        continuation_payload=continuation_payload,
        current_turn_context=next_turn_context,
    )
    if invocation_payload:
        task_selection = {
            **task_selection,
            **dict(invocation_payload.get("task_selection") or {}),
            "agent_invocation": invocation_payload,
            "agent_invocation_id": str(invocation_payload.get("invocation_id") or ""),
        }
    if stage_request:
        task_selection["stage_execution_request"] = stage_request
    if assembly_contract:
        task_selection.update(
            {
                "agent_id": stage_agent_id,
                "agent_profile_id": stage_agent_profile_id,
                "runtime_lane": stage_runtime_lane,
                "work_order_id": str(assembly_contract.get("work_order_id") or ""),
                "assembly_id": str(assembly_contract.get("assembly_id") or ""),
                "executor_type": str(assembly_contract.get("executor_type") or ""),
            }
        )
    if agent_runtime is None:
        raise RuntimeError("AgentRuntime is required to continue a coordination delivery")
    async for event in agent_runtime.run_stream(
        AgentRunRequest(
            session_id=session_id,
            task_id=next_task_id,
            user_message=next_message,
            history=list(history or []),
            source=source,
            agent_runtime_chain=_ContinuationAgentRuntimeChain(
                base=_ContinuationAgentRuntimeChain.unwrap(agent_runtime_chain),
                forced_turn_context=next_turn_context,
                assembly_contract=assembly_contract,
                agent_invocation=invocation_payload,
            ),
            model_response_executor=model_response_executor,
            runtime_context_manager=runtime_context_manager,
            memory_intent=memory_intent,
            task_selection=task_selection,
            assistant_message_committer=assistant_message_committer,
            tool_runtime_executor=tool_runtime_executor,
            tool_instances=tool_instances,
            agent_runtime_profile=stage_agent_runtime_profile,
            agent_invocation=invocation_payload,
        )
    ):
        yield event


def _render_standard_input_package_for_model(standard_input_package: dict[str, Any]) -> str:
    package = dict(standard_input_package or {})
    if "input_items" not in package and isinstance(package.get("standard_input_package"), dict):
        package = dict(package.get("standard_input_package") or {})
    items = [dict(item) for item in list(package.get("input_items") or []) if isinstance(item, dict)]
    if not items:
        return ""

    rendered_items: list[str] = []
    total_chars = 0
    for item in items:
        input_key = str(item.get("input_key") or "").strip() or "unnamed_input"
        if is_internal_protocol_input_key(input_key):
            continue
        content_type = str(item.get("content_type") or "").strip()
        usage_instruction = str(item.get("usage_instruction") or "").strip()
        source_node_id = str(item.get("source_node_id") or "").strip()
        metadata = dict(item.get("metadata") or {})
        text = str(metadata.get("text") or "").strip()
        if not text:
            text = str(item.get("content_preview") or "").strip()
        if not text:
            continue
        if _protocol_leak_detected(text):
            text = re.sub(
                r"<\s*/?\s*(?:tool_call|invoke|read_file|search_text|search_files|delegate_to_agent)[^>]*>",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
        if len(text) > _STANDARD_INPUT_ITEM_TEXT_LIMIT:
            text = text[:_STANDARD_INPUT_ITEM_TEXT_LIMIT].rstrip() + "\n\n[上游材料因长度限制已截断，请只依据已展示内容继续。]"
        header_bits = [f"输入键：{input_key}"]
        if content_type:
            header_bits.append(f"类型：{content_type}")
        if source_node_id:
            header_bits.append(f"来源节点：{source_node_id}")
        if usage_instruction:
            header_bits.append(f"用途：{usage_instruction}")
        block = "\n".join(
            [
                "## " + "；".join(header_bits),
                text,
            ]
        )
        if total_chars + len(block) > _STANDARD_INPUT_MODEL_TEXT_LIMIT:
            remaining = max(_STANDARD_INPUT_MODEL_TEXT_LIMIT - total_chars, 0)
            if remaining <= 200:
                break
            block = block[:remaining].rstrip() + "\n\n[标准输入材料因总长度限制已截断。]"
        rendered_items.append(block)
        total_chars += len(block)

    if not rendered_items:
        return ""
    return "\n".join(
        [
            "# 标准节点输入材料",
            "以下内容由编排运行层预读取并展开，模型只能依据这些已展开材料工作；不得要求读取文件、调用工具或输出伪工具标签。",
            *rendered_items,
        ]
    )


def _model_context_from_continuation_payload(continuation_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_control = dict(continuation_payload.get("runtime_control") or {})
    return build_model_context_payload(
        current_turn_context=dict(continuation_payload.get("current_turn_context") or {}),
        stage_execution_request=dict(runtime_control.get("stage_execution_request") or {}),
        node_work_order=dict(runtime_control.get("node_work_order") or {}),
        stage_execution_request_ref=str(runtime_control.get("stage_execution_request_ref") or ""),
    )


def _task_selection_from_continuation_context(
    *,
    continuation_payload: dict[str, Any],
    current_turn_context: dict[str, Any],
) -> dict[str, Any]:
    return build_task_selection_payload(
        task_selection=dict(continuation_payload.get("task_selection") or {}),
        current_turn_context=current_turn_context,
        runtime_control=dict(continuation_payload.get("runtime_control") or {}),
    )


def _stable_stage_turn_id(*, session_id: str, task_ref: str, stage_request: dict[str, Any] | None) -> str:
    request = dict(stage_request or {})
    stage_id = str(request.get("stage_id") or request.get("node_id") or task_ref.rsplit(".", 1)[-1] or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if not idempotency_key and request:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=str(request.get("coordination_run_id") or ""),
            node_id=str(request.get("node_id") or stage_id),
            explicit_inputs=dict(request.get("explicit_inputs") or {}),
            dispatch_context=dict(request.get("dispatch_context") or {}),
        )
    identity = idempotency_key or str(request.get("request_id") or "").strip()
    if not identity:
        identity = f"{session_id}:{task_ref}:{uuid.uuid4().hex[:8]}"
    return f"turn:{session_id}:{_stable_stage_turn_suffix(identity)}:{_safe_task_id_component(stage_id or 'stage')}"


def _stable_stage_turn_suffix(value: str) -> str:
    import hashlib

    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:12]


def _safe_task_id_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip())[:80] or "stage"


def _agent_invocation_from_continuation_payload(
    continuation_payload: dict[str, Any] | None,
    *,
    base_dir: Path,
) -> Any | None:
    payload = dict(continuation_payload or {})
    work_order = node_work_order_from_runtime_control(payload)
    if not work_order:
        return None
    return build_agent_invocation(WorkOrder.from_dict(work_order), base_dir=base_dir)


class _ContinuationAgentRuntimeChain:
    def __init__(
        self,
        *,
        base: Any,
        forced_turn_context: dict[str, Any],
        assembly_contract: dict[str, Any] | None = None,
        agent_invocation: dict[str, Any] | None = None,
    ) -> None:
        self._base = base
        self._forced_turn_context = dict(forced_turn_context or {})
        self._assembly_contract = dict(assembly_contract or {})
        self._agent_invocation = dict(agent_invocation or {})

    def build_runtime(self, **kwargs) -> dict[str, Any]:
        override = {
            **strip_control_context(dict(kwargs.get("current_turn_context_override") or {})),
            **dict(self._forced_turn_context),
        }
        forced_agent_id = str(self._assembly_contract.get("agent_id") or self._forced_turn_context.get("agent_id") or "").strip()
        forced_agent_profile_id = str(self._assembly_contract.get("agent_profile_id") or self._forced_turn_context.get("agent_profile_id") or "").strip()
        forced_runtime_lane = str(self._assembly_contract.get("runtime_lane") or self._forced_turn_context.get("runtime_lane") or "").strip()
        if forced_agent_id:
            override["agent_id"] = forced_agent_id
        if forced_agent_profile_id:
            override["agent_profile_id"] = forced_agent_profile_id
        if forced_runtime_lane:
            override["runtime_lane"] = forced_runtime_lane
        override = strip_control_context(override)
        kwargs["current_turn_context_override"] = override
        task_selection = build_task_selection_payload(
            task_selection=dict(kwargs.get("task_selection") or {}),
            current_turn_context=override,
        )
        if forced_agent_id:
            task_selection["agent_id"] = forced_agent_id
        if forced_agent_profile_id:
            task_selection["agent_profile_id"] = forced_agent_profile_id
        if forced_runtime_lane:
            task_selection["runtime_lane"] = forced_runtime_lane
        if self._assembly_contract:
            task_selection["assembly_id"] = str(self._assembly_contract.get("assembly_id") or "")
            task_selection["work_order_id"] = str(self._assembly_contract.get("work_order_id") or "")
            task_selection["executor_type"] = str(self._assembly_contract.get("executor_type") or "")
        if self._agent_invocation:
            task_selection["agent_invocation_id"] = str(self._agent_invocation.get("invocation_id") or "")
        kwargs["task_selection"] = task_selection
        runtime = dict(self._base.build_runtime(**kwargs) or {})
        current_turn_context = {
            **strip_control_context(dict(runtime.get("current_turn_context") or {})),
            **dict(self._forced_turn_context),
        }
        current_turn_context = build_model_context_payload(current_turn_context=current_turn_context)
        if self._assembly_contract:
            current_turn_context["agent_id"] = forced_agent_id
            current_turn_context["agent_profile_id"] = forced_agent_profile_id
            current_turn_context["runtime_lane"] = forced_runtime_lane
        task_operation = dict(runtime.get("task_operation") or {})
        task_operation["current_turn_context"] = current_turn_context
        task_spec = dict(task_operation.get("task_spec") or {})
        task_spec["inputs"] = {
            **dict(task_spec.get("inputs") or {}),
            **dict(current_turn_context.get("explicit_inputs") or {}),
        }
        task_operation["task_spec"] = task_spec
        expected_agent_id = str(self._assembly_contract.get("agent_id") or current_turn_context.get("agent_id") or "").strip()
        if expected_agent_id:
            agent_runtime_spec = dict(runtime.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {})
            actual_agent_id = str(agent_runtime_spec.get("agent_id") or "").strip()
            if actual_agent_id != expected_agent_id:
                raise ValueError(
                    "TaskGraph node runtime assembled with wrong agent: "
                    f"expected {expected_agent_id}, got {actual_agent_id or '<empty>'}"
                )
        runtime["current_turn_context"] = current_turn_context
        runtime["task_operation"] = task_operation
        return runtime

    def build_context_policy_result(self, *args, **kwargs):
        return self._base.build_context_policy_result(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._base, name)

    @staticmethod
    def unwrap(chain: Any) -> Any:
        while isinstance(chain, _ContinuationAgentRuntimeChain):
            chain = chain._base
        return chain
