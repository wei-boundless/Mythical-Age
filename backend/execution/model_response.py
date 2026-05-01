from __future__ import annotations

from typing import Any

from orchestration import RuntimeDirective, build_blocked_runtime_commit_gate
from output_boundary import AssistantOutputBoundary, sanitize_visible_assistant_content
from runtime.model_runtime import stringify_content

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
        if tools and callable(tool_invoker):
            response = await tool_invoker(model_messages, tools)
        else:
            response = await invoker(model_messages)
        raw_content = stringify_content(getattr(response, "content", response))
        tool_calls = _normalize_tool_calls(getattr(response, "tool_calls", None))
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
            "legacy_query_chain_removed": True,
        }

    def _operation_id_for_tool(self, tool_name: str) -> str:
        resolver = self.tool_definition_resolver
        if callable(resolver):
            definition = resolver(tool_name)
            operation_id = str(getattr(definition, "operation_id", "") or "").strip()
            if operation_id:
                return operation_id
        return str(tool_name or "").strip()


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
