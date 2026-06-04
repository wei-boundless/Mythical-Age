from __future__ import annotations

import asyncio
import contextlib
import inspect
import threading
from dataclasses import is_dataclass, replace
from types import SimpleNamespace
from typing import Any

from runtime.model_gateway.model_response_protocol import model_response_protocol_from_response
from runtime.model_gateway.model_runtime import ModelRuntimeError, stringify_content, utility_accounting_context
from task_system.runtime_semantics.protocol_boundary import detect_protocol_leak
from orchestration.commit_gate import build_blocked_runtime_commit_gate
from orchestration.runtime_directive import RuntimeDirective
from runtime.output_boundary import AssistantOutputBoundary, sanitize_visible_assistant_content

class ModelResponseRuntimeExecutor:
    """Directive-only executor for the current agent invocation."""

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
        tool_call_options: Any | None = None,
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
        plain_streamer = getattr(self.model_runtime, "astream_messages", None)
        stream_policy = dict(model_stream_policy or {})
        stream_enabled = bool(stream_policy.get("enabled") is True)
        emit_content_delta = bool(stream_policy.get("emit_content_delta") is not False)
        accounting_context = _accounting_context_from_directive(
            directive,
            stream_policy=stream_policy,
            model_messages=model_messages,
        )
        response_timeout_seconds = _model_response_timeout_seconds(
            self.model_runtime,
            model_spec=model_spec,
            policy=stream_policy,
        )
        effective_model_spec = _model_spec_for_stream_policy(
            model_spec,
            policy=stream_policy,
            timeout_seconds=response_timeout_seconds,
            tool_call_options=tool_call_options,
        )
        delta_index = 0
        raw_content = ""
        partial_timeout_metadata: dict[str, Any] = {}
        response: Any = None
        try:
            if stream_enabled and tools and callable(tool_streamer):
                aggregated_chunk = None
                async for chunk in _iterate_stream_with_hard_timeout(
                    _call_streamer_with_optional_model_spec(
                        tool_streamer,
                        model_messages,
                        tools,
                        model_spec=effective_model_spec,
                        tool_call_options=tool_call_options,
                        accounting_context=accounting_context,
                    ),
                    timeout_seconds=response_timeout_seconds,
                ):
                    aggregated_chunk = chunk if aggregated_chunk is None else aggregated_chunk + chunk
                    delta_text = _chunk_text(chunk)
                    if not delta_text:
                        continue
                    raw_content += delta_text
                    if emit_content_delta:
                        delta_index += 1
                        yield {
                            "type": "content_delta",
                            "content": delta_text,
                            "delta_index": delta_index,
                            "delta_chars": len(delta_text),
                            "accumulated_chars": len(raw_content),
                            "stream_ref": directive.directive_id,
                        }
                response = aggregated_chunk if aggregated_chunk is not None else raw_content
            elif stream_enabled and callable(plain_streamer):
                async for chunk in _iterate_stream_with_hard_timeout(
                    _call_streamer_with_optional_model_spec(
                        plain_streamer,
                        model_messages,
                        model_spec=effective_model_spec,
                        accounting_context=accounting_context,
                    ),
                    timeout_seconds=response_timeout_seconds,
                ):
                    delta_text = _chunk_text(chunk)
                    if not delta_text:
                        continue
                    raw_content += delta_text
                    if emit_content_delta:
                        delta_index += 1
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
                response = await _await_model_invocation(
                    lambda: _call_invoker_with_optional_model_spec(
                        tool_invoker,
                        model_messages,
                        tools,
                        model_spec=effective_model_spec,
                        tool_call_options=tool_call_options,
                        accounting_context=accounting_context,
                    ),
                    timeout_seconds=response_timeout_seconds,
                    policy=stream_policy,
                )
            else:
                response = await _await_model_invocation(
                    lambda: _call_invoker_with_optional_model_spec(
                        invoker,
                        model_messages,
                        model_spec=effective_model_spec,
                        accounting_context=accounting_context,
                    ),
                    timeout_seconds=response_timeout_seconds,
                    policy=stream_policy,
                )
        except ModelRuntimeError as exc:
            if stream_enabled and exc.retryable and _stream_recovery_enabled(stream_policy):
                fallback_timeout_seconds = _stream_recovery_timeout_seconds(stream_policy)
                if delta_index > 0:
                    yield {
                        "type": "stream_recovery",
                        "status": "suppressed",
                        "reason": "partial_output_already_emitted",
                        "code": exc.code,
                        "provider": exc.provider,
                        "model": exc.model,
                        "detail": exc.detail,
                        "partial_delta_count": delta_index,
                        "fallback_timeout_seconds": fallback_timeout_seconds,
                        "directive_ref": directive.directive_id,
                    }
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
                    response = await _await_model_invocation(
                        lambda: _invoke_non_stream_after_stream_error(
                            invoker=invoker,
                            tool_invoker=tool_invoker,
                            model_messages=model_messages,
                            tools=tools,
                            model_spec=effective_model_spec,
                            tool_call_options=tool_call_options,
                            accounting_context={**accounting_context, "source": "runtime_directive.model_response.stream_recovery"},
                        ),
                        timeout_seconds=fallback_timeout_seconds,
                        policy=stream_policy,
                    )
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
        except asyncio.TimeoutError:
            if stream_enabled and raw_content.strip():
                response = raw_content
                partial_timeout_metadata = {
                    "completion_state": "partial_timeout",
                    "terminal_reason": "model_response_timeout_after_partial_output",
                    "timeout_seconds": response_timeout_seconds,
                    "partial_delta_count": delta_index,
                    "provider": str(getattr(model_spec, "provider", "") or ""),
                    "model": str(getattr(model_spec, "model", "") or ""),
                    "detail": f"model response exceeded {response_timeout_seconds:g}s after partial output",
                    "answer_canonical_state": "partial_timeout",
                    "answer_persist_policy": "persist_canonical",
                    "answer_finalization_policy": "partial_output_committed",
                    "answer_fallback_reason": "model_response_timeout_after_partial_output",
                }
            else:
                yield {
                    "type": "error",
                    "error": "model_response_timeout",
                    "content": "模型响应超过节点执行时限，本节点未产出有效结果，请从当前节点断点重跑。",
                    "code": "timeout",
                    "provider": str(getattr(effective_model_spec, "provider", "") or ""),
                    "model": str(getattr(effective_model_spec, "model", "") or ""),
                    "detail": f"model response exceeded {response_timeout_seconds:g}s",
                    "timeout_seconds": response_timeout_seconds,
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
        additional_kwargs = dict(getattr(response, "additional_kwargs", {}) or {})
        protocol_result = model_response_protocol_from_response(
            response,
            request_id=str(accounting_context.get("request_id") or directive.directive_id),
            turn_id=str(accounting_context.get("turn_id") or ""),
            provider=str(additional_kwargs.get("provider") or getattr(response, "provider", "") or ""),
        )
        raw_content = protocol_result.content
        tool_calls = [dict(item) for item in protocol_result.native_tool_calls]
        reasoning_content = str(additional_kwargs.get("reasoning_content") or "").strip()
        stream_preview_text = ""
        if stream_enabled and delta_index <= 0:
            stream_preview_text = raw_content.strip()
        if stream_preview_text and emit_content_delta:
            yield {
                "type": "content_delta",
                "content": stream_preview_text,
                "delta_index": 1,
                "delta_chars": len(stream_preview_text),
                "accumulated_chars": len(stream_preview_text),
                "stream_ref": directive.directive_id,
                "is_final_chunk": bool(tool_calls),
            }
        if tool_calls and tools:
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
        if tool_calls and not tools:
            yield {
                "type": "model_protocol_violation",
                "content": raw_content,
                "directive_ref": directive.directive_id,
                "protocol_leak": {
                    "detected": True,
                    "markers": ["provider_tool_call_without_bound_tools"],
                    "authority": "orchestration.protocol_boundary",
                },
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_directive:model_response",
            }
            return
        protocol_leak = detect_protocol_leak(raw_content)
        if protocol_leak.detected and tools:
            yield {
                "type": "model_protocol_violation",
                "content": raw_content,
                "directive_ref": directive.directive_id,
                "protocol_leak": protocol_leak.to_dict(),
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_directive:model_response",
            }
            return
        output_boundary = AssistantOutputBoundary()
        _seed_boundary_with_prior_tool_receipts(output_boundary, model_messages)
        output_boundary.ingest_ai_update(raw_content, has_tool_calls=False)
        output_boundary.finalize_segment(fallback_content=raw_content)
        output_response = output_boundary.build_response(
            route="",
            execution_posture="model",
            user_message=user_message,
            tool_name="",
            retrieval_results=None,
        )
        if output_response.selected_channel == "progress_text" and _model_only_finalization(directive):
            output_response = output_boundary.build_response(
                route="",
                execution_posture="tool_closeout",
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
            **partial_timeout_metadata,
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
            "answer_canonical_state": str(partial_timeout_metadata.get("answer_canonical_state") or output_response.canonical_state),
            "answer_persist_policy": str(partial_timeout_metadata.get("answer_persist_policy") or output_response.persist_policy),
            "answer_finalization_policy": str(partial_timeout_metadata.get("answer_finalization_policy") or output_response.finalization_policy),
            "answer_fallback_reason": str(partial_timeout_metadata.get("answer_fallback_reason") or output_response.fallback_reason),
            "answer_leak_flags": list(output_response.leak_flags),
            "persist_policy": "partial_timeout" if partial_timeout_metadata else "commit_gate_blocked",
            "commit_gate": runtime_commit_gate.to_dict(),
            **partial_timeout_metadata,
        }

    def _operation_id_for_tool(self, tool_name: str) -> str:
        resolver = self.tool_definition_resolver
        if callable(resolver):
            definition = resolver(tool_name)
            operation_id = str(getattr(definition, "operation_id", "") or "").strip()
            if operation_id:
                return operation_id
        return str(tool_name or "").strip()


def _model_only_finalization(directive: RuntimeDirective) -> bool:
    diagnostics = dict(getattr(directive, "diagnostics", {}) or {})
    return bool(diagnostics.get("model_only") is True)


def _accounting_context_from_directive(
    directive: RuntimeDirective,
    *,
    stream_policy: dict[str, Any],
    model_messages: list[Any],
) -> dict[str, Any]:
    diagnostics = dict(getattr(directive, "diagnostics", {}) or {})
    session_id = str(
        diagnostics.get("session_id")
        or diagnostics.get("conversation_session_id")
        or dict(diagnostics.get("task_run") or {}).get("session_id")
        or ""
    )
    task_run_id = str(
        diagnostics.get("task_run_id")
        or diagnostics.get("root_task_run_id")
        or diagnostics.get("observed_task_run_id")
        or directive.task_id
        or ""
    )
    request_id = str(
        diagnostics.get("model_request_id")
        or diagnostics.get("runtime_invocation_packet_ref")
        or diagnostics.get("packet_ref")
        or f"modelreq:{directive.directive_id}"
    )
    source = str(stream_policy.get("source") or "runtime_directive.model_response")
    context = utility_accounting_context(
        source=source,
        messages=_messages_for_utility_accounting(model_messages),
        purpose=source,
        cache_metric_scope="runtime_directive_model_response",
        session_id=session_id,
        run_id=task_run_id,
        task_run_id=task_run_id,
    )
    return {
        **context,
        "request_id": request_id,
        "session_id": session_id,
        "task_run_id": task_run_id,
        "turn_id": str(diagnostics.get("turn_id") or ""),
        "packet_ref": str(diagnostics.get("runtime_invocation_packet_ref") or diagnostics.get("packet_ref") or ""),
        "source": source,
    }


def _messages_for_utility_accounting(messages: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in list(messages or []):
        if isinstance(message, dict):
            normalized.append(
                {
                    "role": str(message.get("role") or message.get("type") or "user"),
                    "content": stringify_content(message.get("content") or ""),
                }
            )
            continue
        normalized.append(
            {
                "role": str(getattr(message, "role", "") or getattr(message, "type", "") or message.__class__.__name__ or "user"),
                "content": stringify_content(getattr(message, "content", "") or ""),
            }
        )
    return normalized


def _seed_boundary_with_prior_tool_receipts(
    output_boundary: AssistantOutputBoundary,
    model_messages: list[Any],
) -> None:
    tool_name_by_call_id: dict[str, str] = {}
    for message in list(model_messages or []):
        for tool_call in _message_tool_calls(message):
            call_id = str(tool_call.get("id") or "").strip()
            name = str(tool_call.get("name") or "").strip()
            if call_id and name:
                tool_name_by_call_id[call_id] = name
        if not _is_tool_message(message):
            continue
        content = stringify_content(getattr(message, "content", ""))
        if not content.strip():
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "").strip()
        tool_name = (
            str(getattr(message, "name", "") or "").strip()
            or tool_name_by_call_id.get(call_id, "")
            or "tool"
        )
        output_boundary.ingest_tool_result(tool_name, content)


def _message_tool_calls(message: Any) -> list[dict[str, Any]]:
    raw_tool_calls = getattr(message, "tool_calls", None)
    if raw_tool_calls is None and isinstance(message, dict):
        raw_tool_calls = message.get("tool_calls")
    result: list[dict[str, Any]] = []
    for item in list(raw_tool_calls or []):
        if isinstance(item, dict):
            result.append(dict(item))
    return result


def _is_tool_message(message: Any) -> bool:
    if message.__class__.__name__ == "ToolMessage":
        return True
    message_type = str(getattr(message, "type", "") or getattr(message, "role", "") or "").strip().lower()
    if message_type == "tool":
        return True
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "").strip().lower() == "tool"
    return False


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
    tool_call_options: Any | None = None,
    accounting_context: dict[str, Any] | None = None,
) -> Any:
    if tools and callable(tool_invoker):
        return await _call_invoker_with_optional_model_spec(
            tool_invoker,
            model_messages,
            tools,
            model_spec=model_spec,
            tool_call_options=tool_call_options,
            accounting_context=accounting_context,
        )
    return await _call_invoker_with_optional_model_spec(
        invoker,
        model_messages,
        model_spec=model_spec,
        accounting_context=accounting_context,
    )


async def _await_model_invocation(
    invocation_factory: Any,
    *,
    timeout_seconds: float,
    policy: dict[str, Any],
) -> Any:
    if _thread_isolated_invocation_enabled(policy):
        return await _await_invocation_in_thread(invocation_factory, timeout_seconds=timeout_seconds)
    return await _await_with_hard_timeout(invocation_factory(), timeout_seconds=timeout_seconds)


def _thread_isolated_invocation_enabled(policy: dict[str, Any]) -> bool:
    if "isolate_blocking_model_invocation" in policy:
        return bool(policy.get("isolate_blocking_model_invocation") is not False)
    return bool(policy.get("forced_tool_timeout_applied") is True)


async def _await_invocation_in_thread(invocation_factory: Any, *, timeout_seconds: float) -> Any:
    timeout = max(0.01, float(timeout_seconds or 0.01))
    loop = asyncio.get_running_loop()
    outer_future: asyncio.Future[Any] = loop.create_future()

    def _runner() -> None:
        try:
            result = asyncio.run(_resolve_invocation_result(invocation_factory()))
        except BaseException as exc:
            _call_soon_threadsafe_if_open(loop, _set_future_exception_if_pending, outer_future, exc)
            return
        _call_soon_threadsafe_if_open(loop, _set_future_result_if_pending, outer_future, result)

    thread = threading.Thread(target=_runner, name="model-invocation-deadline", daemon=True)
    thread.start()
    try:
        return await asyncio.wait_for(asyncio.shield(outer_future), timeout=timeout)
    except asyncio.TimeoutError:
        outer_future.cancel()
        raise


async def _resolve_invocation_result(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _set_future_result_if_pending(future: asyncio.Future[Any], result: Any) -> None:
    if not future.done():
        future.set_result(result)


def _set_future_exception_if_pending(future: asyncio.Future[Any], exc: BaseException) -> None:
    if not future.done():
        future.set_exception(exc)


def _call_soon_threadsafe_if_open(loop: asyncio.AbstractEventLoop, callback: Any, *args: Any) -> None:
    if loop.is_closed():
        return
    with contextlib.suppress(RuntimeError):
        loop.call_soon_threadsafe(callback, *args)


async def _call_invoker_with_optional_model_spec(
    invoker: Any,
    *args: Any,
    model_spec: Any | None = None,
    tool_call_options: Any | None = None,
    accounting_context: dict[str, Any] | None = None,
) -> Any:
    try:
        return await invoker(
            *args,
            model_spec=model_spec,
            tool_call_options=tool_call_options,
            accounting_context=accounting_context,
        )
    except TypeError as exc:
        if "model_spec" not in str(exc) and "tool_call_options" not in str(exc) and "accounting_context" not in str(exc):
            raise
    try:
        return await invoker(*args, model_spec=model_spec, accounting_context=accounting_context)
    except TypeError as exc:
        if "model_spec" not in str(exc) and "accounting_context" not in str(exc):
            raise
    try:
        return await invoker(*args, model_spec=model_spec)
    except TypeError as exc:
        if "model_spec" not in str(exc):
            raise
        return await invoker(*args)


async def _await_with_hard_timeout(awaitable: Any, *, timeout_seconds: float) -> Any:
    timeout = max(0.01, float(timeout_seconds or 0.01))
    task = asyncio.create_task(awaitable)
    done, _pending = await asyncio.wait({task}, timeout=timeout)
    if task in done:
        return task.result()
    task.cancel()
    task.add_done_callback(_discard_task_exception)
    raise asyncio.TimeoutError


async def _iterate_stream_with_hard_timeout(stream: Any, *, timeout_seconds: float):
    timeout = max(0.01, float(timeout_seconds or 0.01))
    iterator = stream.__aiter__()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            close = getattr(iterator, "aclose", None) or getattr(stream, "aclose", None)
            if callable(close):
                with contextlib.suppress(BaseException):
                    await close()
            raise asyncio.TimeoutError
        try:
            yield await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return


def _discard_task_exception(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(BaseException):
        task.exception()


def _model_response_timeout_seconds(model_runtime: Any, *, model_spec: Any | None, policy: dict[str, Any]) -> float:
    for key in (
        "model_response_timeout_seconds",
        "model_timeout_seconds",
        "request_timeout_seconds",
    ):
        if key not in policy:
            continue
        try:
            value = float(policy.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value

    resolver = getattr(model_runtime, "_model_call_timeout_seconds_for_spec", None)
    if callable(resolver) and model_spec is not None:
        try:
            return max(0.01, float(resolver(model_spec) or 0.01))
        except Exception:
            pass

    for attr_name in ("model_call_timeout_seconds", "long_output_timeout_seconds", "request_timeout_seconds"):
        try:
            value = float(getattr(model_runtime, attr_name) or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 180.0


def _model_spec_for_stream_policy(
    model_spec: Any | None,
    *,
    policy: dict[str, Any],
    timeout_seconds: float,
    tool_call_options: Any | None = None,
) -> Any | None:
    if model_spec is None:
        return None
    timeout = max(0.01, float(timeout_seconds or 0.01))
    current_timeout = _positive_model_spec_float(getattr(model_spec, "timeout_seconds", None), timeout)
    current_long_timeout = _positive_model_spec_float(
        getattr(model_spec, "long_output_timeout_seconds", None),
        max(timeout, current_timeout),
    )
    bounded_timeout = min(current_timeout, timeout)
    bounded_long_timeout = min(current_long_timeout, timeout)
    updates: dict[str, Any] = {
        "timeout_seconds": bounded_timeout,
        "long_output_timeout_seconds": max(bounded_timeout, bounded_long_timeout),
    }
    forced_tool_timeout_applied = bool(policy.get("forced_tool_timeout_applied") is True)
    if forced_tool_timeout_applied:
        updates["max_retries"] = 0
    forced_tool_name = _forced_tool_choice_name(tool_call_options)
    diagnostics = getattr(model_spec, "diagnostics", None)
    if isinstance(diagnostics, dict):
        updates["diagnostics"] = {
            **diagnostics,
            "runtime_policy_timeout_seconds": timeout,
            "runtime_policy_timeout_applied": True,
            **(
                {
                    "forced_tool_choice_name": forced_tool_name,
                    "forced_tool_choice_requires_tool_compatible_model": True,
                }
                if forced_tool_name and forced_tool_timeout_applied
                else {}
            ),
            **(
                {
                    "forced_tool_timeout_applied": True,
                }
                if forced_tool_timeout_applied
                else {}
            ),
        }
    return _copy_model_spec(model_spec, updates)


def _positive_model_spec_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _copy_model_spec(model_spec: Any, updates: dict[str, Any]) -> Any:
    if is_dataclass(model_spec):
        try:
            return replace(model_spec, **updates)
        except TypeError:
            pass
    if isinstance(model_spec, dict):
        payload = {
            key: model_spec.get(key)
            for key in (
                "provider",
                "model",
                "api_key",
                "base_url",
                "max_output_tokens",
                "timeout_seconds",
                "long_output_timeout_seconds",
                "max_retries",
                "temperature",
                "thinking_mode",
                "reasoning_effort",
                "stream_policy",
                "completion_profile",
                "source_chain",
                "diagnostics",
            )
            if key in model_spec
        }
        payload.update(updates)
        return SimpleNamespace(**payload)
    payload = {
        key: getattr(model_spec, key)
        for key in (
            "provider",
            "model",
            "api_key",
            "base_url",
            "max_output_tokens",
            "timeout_seconds",
            "long_output_timeout_seconds",
            "max_retries",
            "temperature",
            "thinking_mode",
            "reasoning_effort",
            "stream_policy",
            "completion_profile",
            "source_chain",
            "diagnostics",
        )
        if hasattr(model_spec, key)
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


def _forced_tool_choice_name(tool_call_options: Any | None) -> str:
    if tool_call_options is None:
        return ""
    raw_choice = None
    if isinstance(tool_call_options, dict):
        raw_choice = tool_call_options.get("tool_choice")
    else:
        raw_choice = getattr(tool_call_options, "tool_choice", None)
    if isinstance(raw_choice, dict):
        function = raw_choice.get("function") if isinstance(raw_choice.get("function"), dict) else {}
        return str(function.get("name") or raw_choice.get("name") or "").strip()
    if isinstance(raw_choice, str):
        return raw_choice.strip()
    return ""


def _call_streamer_with_optional_model_spec(
    streamer: Any,
    *args: Any,
    model_spec: Any | None = None,
    tool_call_options: Any | None = None,
    accounting_context: dict[str, Any] | None = None,
):
    try:
        return streamer(
            *args,
            model_spec=model_spec,
            tool_call_options=tool_call_options,
            accounting_context=accounting_context,
        )
    except TypeError as exc:
        if "model_spec" not in str(exc) and "tool_call_options" not in str(exc) and "accounting_context" not in str(exc):
            raise
    try:
        return streamer(*args, model_spec=model_spec, accounting_context=accounting_context)
    except TypeError as exc:
        if "model_spec" not in str(exc) and "accounting_context" not in str(exc):
            raise
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


