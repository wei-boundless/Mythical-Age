from __future__ import annotations

import asyncio
from typing import Any

from execution.model_runtime import ModelRuntimeError, stringify_content
from orchestration import RuntimeDirective, build_blocked_runtime_commit_gate
from output_boundary.boundary import AssistantOutputBoundary, sanitize_visible_assistant_content

class ModelResponseRuntimeExecutor:
    """Directive-only executor for the current single-agent runtime lane."""

    def __init__(
        self,
        *,
        model_runtime,
        tool_definition_resolver=None,
    ) -> None:
        self.model_runtime = model_runtime
        self.tool_definition_resolver = tool_definition_resolver

    async def stream(
        self,
        *,
        user_message: str,
        model_messages: list[Any],
        directive: RuntimeDirective,
        tool_instances: list[Any] | None = None,
        model_stream_policy: dict[str, Any] | None = None,
        model_spec: Any | None = None,
    ):
        if directive.executor_type != "model":
            yield {
                "type": "error",
                "error": "invalid_directive_executor_type",
                "content": "模型执行器只接受 executor_type=model 的 RuntimeDirective。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_directive_executor",
            }
            return

        invoker = getattr(self.model_runtime, "invoke_messages", None)
        if not callable(invoker):
            yield {
                "type": "error",
                "error": "model_runtime_unavailable",
                "content": "模型运行时不可用，本轮停止执行。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_directive_executor",
            }
            return

        tools = list(tool_instances or [])
        tool_invoker = getattr(self.model_runtime, "invoke_messages_with_tools", None)
        tool_streamer = getattr(self.model_runtime, "astream_messages_with_tools", None)
        stream_policy = dict(model_stream_policy or {})
        stream_enabled = bool(stream_policy.get("enabled") is True)
        delta_index = 0
        response: Any = None
        try:
            if stream_enabled and tools and callable(tool_streamer):
                raw_content = ""
                aggregated_chunk = None
                async for chunk in _call_streamer_with_optional_model_spec(tool_streamer, model_messages, tools, model_spec=model_spec):
                    aggregated_chunk = chunk if aggregated_chunk is None else aggregated_chunk + chunk
                    delta_text = _chunk_text(chunk)
                    if not delta_text:
                        continue
                    delta_index += 1
                    raw_content += delta_text
                    yield {
                        "type": "content_delta",
                        "content": delta_text,
                        "delta_index": delta_index,
                        "delta_chars": len(delta_text),
                        "accumulated_chars": len(raw_content),
                        "stream_ref": directive.directive_id,
                    }
                response = aggregated_chunk if aggregated_chunk is not None else raw_content
            elif stream_enabled:
                raw_content = ""
                async for chunk in _call_streamer_with_optional_model_spec(self.model_runtime.astream_messages, model_messages, model_spec=model_spec):
                    delta_text = _chunk_text(chunk)
                    if not delta_text:
                        continue
                    delta_index += 1
                    raw_content += delta_text
                    yield {
                        "type": "content_delta",
                        "content": delta_text,
                        "delta_index": delta_index,
                        "delta_chars": len(delta_text),
                        "accumulated_chars": len(raw_content),
                        "stream_ref": directive.directive_id,
                    }
                response = raw_content
            elif tools and callable(tool_invoker):
                response = await _call_invoker_with_optional_model_spec(tool_invoker, model_messages, tools, model_spec=model_spec)
            else:
                response = await _call_invoker_with_optional_model_spec(invoker, model_messages, model_spec=model_spec)
        except ModelRuntimeError as exc:
            if stream_enabled and exc.retryable and _stream_recovery_enabled(stream_policy):
                fallback_timeout_seconds = _stream_recovery_timeout_seconds(stream_policy)
                yield {
                    "type": "stream_recovery",
                    "status": "started",
                    "reason": "retryable_stream_error",
                    "code": exc.code,
                    "provider": exc.provider,
                    "model": exc.model,
                    "detail": exc.detail,
                    "partial_delta_count": delta_index,
                    "fallback_timeout_seconds": fallback_timeout_seconds,
                    "directive_ref": directive.directive_id,
                }
                try:
                    fallback_call = _invoke_non_stream_after_stream_error(
                        invoker=invoker,
                        tool_invoker=tool_invoker,
                        model_messages=model_messages,
                        tools=tools,
                        model_spec=model_spec,
                    )
                    response = await asyncio.wait_for(fallback_call, timeout=fallback_timeout_seconds)
                except asyncio.TimeoutError:
                    yield {
                        "type": "stream_recovery",
                        "status": "failed",
                        "reason": "non_stream_fallback_timeout",
                        "code": "timeout",
                        "provider": exc.provider,
                        "model": exc.model,
                        "detail": f"non-stream fallback exceeded {fallback_timeout_seconds:g}s",
                        "partial_delta_count": delta_index,
                        "fallback_timeout_seconds": fallback_timeout_seconds,
                        "directive_ref": directive.directive_id,
                    }
                    yield {
                        "type": "error",
                        "error": "model_stream_recovery_timeout",
                        "content": "模型流式恢复超时，本节点未产出有效结果，请从当前节点断点重跑。",
                        "code": "timeout",
                        "provider": exc.provider,
                        "model": exc.model,
                        "detail": f"non-stream fallback exceeded {fallback_timeout_seconds:g}s",
                        "answer_channel": "orchestration_fail_closed",
                        "answer_source": "runtime_directive_executor",
                    }
                    return
                except ModelRuntimeError as fallback_exc:
                    yield {
                        "type": "stream_recovery",
                        "status": "failed",
                        "reason": "non_stream_fallback_failed",
                        "code": fallback_exc.code,
                        "provider": fallback_exc.provider,
                        "model": fallback_exc.model,
                        "detail": fallback_exc.detail,
                        "partial_delta_count": delta_index,
                        "fallback_timeout_seconds": fallback_timeout_seconds,
                        "directive_ref": directive.directive_id,
                    }
                    yield {
                        "type": "error",
                        "error": fallback_exc.user_message,
                        "content": fallback_exc.user_message,
                        "code": fallback_exc.code,
                        "provider": fallback_exc.provider,
                        "model": fallback_exc.model,
                        "detail": fallback_exc.detail,
                        "answer_channel": "orchestration_fail_closed",
                        "answer_source": "runtime_directive_executor",
                    }
                    return
                except Exception as fallback_exc:
                    yield {
                        "type": "stream_recovery",
                        "status": "failed",
                        "reason": "non_stream_fallback_failed",
                        "code": "model_runtime_error",
                        "provider": exc.provider,
                        "model": exc.model,
                        "detail": str(fallback_exc) or fallback_exc.__class__.__name__,
                        "partial_delta_count": delta_index,
                        "fallback_timeout_seconds": fallback_timeout_seconds,
                        "directive_ref": directive.directive_id,
                    }
                    yield {
                        "type": "error",
                        "error": str(fallback_exc) or "model_runtime_error",
                        "content": "模型运行时失败，本轮停止执行。",
                        "answer_channel": "orchestration_fail_closed",
                        "answer_source": "runtime_directive_executor",
                    }
                    return
                yield {
                    "type": "stream_recovery",
                    "status": "recovered",
                    "reason": "non_stream_fallback_succeeded",
                    "code": exc.code,
                    "provider": exc.provider,
                    "model": exc.model,
                    "partial_delta_count": delta_index,
                    "fallback_timeout_seconds": fallback_timeout_seconds,
                    "directive_ref": directive.directive_id,
                }
            else:
                yield {
                    "type": "error",
                    "error": exc.user_message,
                    "content": exc.user_message,
                    "code": exc.code,
                    "provider": exc.provider,
                    "model": exc.model,
                    "detail": exc.detail,
                    "answer_channel": "orchestration_fail_closed",
                    "answer_source": "runtime_directive_executor",
                }
                return
        except Exception as exc:
            yield {
                "type": "error",
                "error": str(exc) or "model_runtime_error",
                "content": "模型运行时失败，本轮停止执行。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_directive_executor",
            }
            return
        raw_content = stringify_content(getattr(response, "content", response))
        tool_calls = _normalize_tool_calls(getattr(response, "tool_calls", None))
        additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
        reasoning_content = str(additional_kwargs.get("reasoning_content") or "").strip()
        stream_preview_text = ""
        if stream_enabled and delta_index <= 0:
            stream_preview_text = raw_content.strip() or reasoning_content
        if stream_preview_text:
            yield {
                "type": "content_delta",
                "content": stream_preview_text,
                "delta_index": 1,
                "delta_chars": len(stream_preview_text),
                "accumulated_chars": len(stream_preview_text),
                "stream_ref": directive.directive_id,
                "is_final_chunk": bool(tool_calls),
            }
        if tool_calls:
            for tool_call in tool_calls:
                tool_name = str(tool_call.get("name") or "")
                operation_id = self._operation_id_for_tool(tool_name)
                yield {
                    "type": "tool_call_requested",
                    "tool_call": tool_call,
                    "tool_name": tool_name,
                    "operation_id": operation_id,
                    "directive_ref": directive.directive_id,
                    "assistant_content": raw_content,
                    "assistant_additional_kwargs": {"reasoning_content": reasoning_content} if reasoning_content else {},
                }
            return
        if _should_auto_delegate_model_answer(directive=directive, model_messages=model_messages):
            yield {
                "type": "tool_call_requested",
                "tool_call": {
                    "id": f"auto_delegate:{directive.task_id}",
                    "name": "delegate_to_agent",
                    "args": {
                        "instruction": str(user_message or "").strip(),
                        "input_payload": {"query": str(user_message or "").strip()},
                    },
                    "type": "tool_call",
                },
                "tool_name": "delegate_to_agent",
                "operation_id": "op.delegate_to_agent",
                "directive_ref": directive.directive_id,
                "assistant_content": "",
                "assistant_additional_kwargs": {
                    "auto_dispatch_reason": "delegate_required_model_answer_blocked",
                },
            }
            return
        output_boundary = AssistantOutputBoundary()
        output_boundary.ingest_ai_update(raw_content, has_tool_calls=False)
        output_boundary.finalize_segment(fallback_content=raw_content)
        output_response = output_boundary.build_response(
            route="",
            execution_posture="model",
            user_message=user_message,
            tool_name="",
            retrieval_results=None,
        )
        content = sanitize_visible_assistant_content(output_response.canonical_answer).strip()
        if not content:
            content = "我已接入新的单 agent 主链，但这轮模型没有返回可展示内容。"

        runtime_commit_gate = build_blocked_runtime_commit_gate(
            task_id=directive.task_id,
            plan_ref=directive.plan_ref,
            execution_graph_ref=directive.execution_graph_ref,
            directive_ref=directive.directive_id,
            output_response=output_response,
        )
        yield {
            "type": "answer_candidate",
            "content": content,
            "source": "runtime_directive:model_response",
            "directive_ref": directive.directive_id,
        }
        yield {
            "type": "output_boundary",
            "output": {
                "visible_text": output_response.visible_text,
                "canonical_answer": content,
                "selected_channel": output_response.selected_channel,
                "selected_source": output_response.selected_source,
                "canonical_state": output_response.canonical_state,
                "persist_policy": output_response.persist_policy,
                "finalization_policy": output_response.finalization_policy,
                "leak_flags": list(output_response.leak_flags),
                "fallback_reason": output_response.fallback_reason,
            },
        }
        yield {
            "type": "runtime_commit_gate",
            "commit_gate": runtime_commit_gate.to_dict(),
        }
        yield {
            "type": "done",
            "content": content,
            "main_context": {},
            "task_summary_refs": [],
            "answer_channel": output_response.selected_channel,
            "answer_source": "runtime_directive:model_response",
            "answer_canonical_state": output_response.canonical_state,
            "answer_persist_policy": output_response.persist_policy,
            "answer_finalization_policy": output_response.finalization_policy,
            "answer_fallback_reason": output_response.fallback_reason,
            "answer_leak_flags": list(output_response.leak_flags),
            "persist_policy": "commit_gate_blocked",
            "commit_gate": runtime_commit_gate.to_dict(),
        }

    def _operation_id_for_tool(self, tool_name: str) -> str:
        resolver = self.tool_definition_resolver
        if callable(resolver):
            definition = resolver(tool_name)
            operation_id = str(getattr(definition, "operation_id", "") or "").strip()
            if operation_id:
                return operation_id
        return str(tool_name or "").strip()


def _should_auto_delegate_model_answer(*, directive: RuntimeDirective, model_messages: list[Any]) -> bool:
    diagnostics = dict(getattr(directive, "diagnostics", {}) or {})
    if diagnostics.get("auto_delegate_model_answer") is False:
        return False
    if "op.delegate_to_agent" not in {str(item or "").strip() for item in tuple(directive.operation_refs or ())}:
        return False
    for message in list(model_messages or []):
        if str(getattr(message, "type", "") or "").strip().lower() == "tool":
            return False
        if message.__class__.__name__ == "ToolMessage":
            return False
    return True


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", chunk)
    return stringify_content(content)


async def _invoke_non_stream_after_stream_error(
    *,
    invoker: Any,
    tool_invoker: Any,
    model_messages: list[Any],
    tools: list[Any],
    model_spec: Any | None = None,
) -> Any:
    if tools and callable(tool_invoker):
        return await _call_invoker_with_optional_model_spec(tool_invoker, model_messages, tools, model_spec=model_spec)
    return await _call_invoker_with_optional_model_spec(invoker, model_messages, model_spec=model_spec)


async def _call_invoker_with_optional_model_spec(invoker: Any, *args: Any, model_spec: Any | None = None) -> Any:
    try:
        return await invoker(*args, model_spec=model_spec)
    except TypeError as exc:
        if "model_spec" not in str(exc):
            raise
        return await invoker(*args)


def _call_streamer_with_optional_model_spec(streamer: Any, *args: Any, model_spec: Any | None = None):
    try:
        return streamer(*args, model_spec=model_spec)
    except TypeError as exc:
        if "model_spec" not in str(exc):
            raise
        return streamer(*args)


def _stream_recovery_enabled(policy: dict[str, Any]) -> bool:
    for key in (
        "recover_with_non_stream",
        "fallback_to_non_stream",
        "fallback_to_non_stream_on_error",
    ):
        if key in policy:
            return bool(policy.get(key) is not False)
    return True


def _stream_recovery_timeout_seconds(policy: dict[str, Any]) -> float:
    for key in (
        "non_stream_fallback_timeout_seconds",
        "fallback_timeout_seconds",
        "recovery_timeout_seconds",
        "stream_recovery_timeout_seconds",
    ):
        if key not in policy:
            continue
        try:
            value = float(policy.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 180.0


def _normalize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(list(raw_tool_calls or []), start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        args = item.get("args")
        if not isinstance(args, dict):
            args = {}
        call_id = str(item.get("id") or f"tool-call-{index}")
        if not name:
            continue
        normalized.append(
            {
                "id": call_id,
                "name": name,
                "args": dict(args),
                "type": str(item.get("type") or "tool_call"),
            }
        )
    return normalized
