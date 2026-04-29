from __future__ import annotations

from collections.abc import Callable
from typing import Any

from operations import OperationGate, ResourceDecision, ResourcePolicy, build_default_operation_registry
from orchestration import RuntimeDirective, build_blocked_runtime_commit_gate
from output_boundary import AssistantOutputBoundary, sanitize_visible_assistant_content
from runtime.model_runtime import stringify_content


SystemPromptBuilder = Callable[..., str]


class ModelResponseRuntimeExecutor:
    """Directive-only executor for the current model-only runtime lane."""

    def __init__(
        self,
        *,
        model_runtime,
        system_prompt_builder: SystemPromptBuilder,
        operation_gate: OperationGate | None = None,
    ) -> None:
        self.model_runtime = model_runtime
        self.system_prompt_builder = system_prompt_builder
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())

    async def stream(
        self,
        *,
        session_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        task_operation_preview: dict[str, Any],
        memory_intent: Any | None = None,
    ):
        directive, resource_policy = self.build_runtime_directive(task_operation_preview)
        gate_result = self.operation_gate.check(
            "op.model_response",
            resource_policy=resource_policy,
            directive_ref=directive.directive_id,
        )
        yield {
            "type": "runtime_directive",
            "directive": directive.to_dict(),
            "resource_policy": resource_policy.to_dict(),
        }
        yield {
            "type": "operation_gate",
            "gate": gate_result.to_dict(),
        }
        if not gate_result.allowed:
            yield {
                "type": "error",
                "error": gate_result.reason,
                "content": "OperationGate 未放行模型回答，本轮停止执行。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "operation_gate",
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

        system_prompt = self.system_prompt_builder(
            session_id=session_id,
            pending_user_message=user_message,
            memory_intent=memory_intent,
        )
        model_messages = [
            {"role": "system", "content": system_prompt},
            *[
                {
                    "role": str(item.get("role") or "user"),
                    "content": str(item.get("content") or ""),
                }
                for item in list(history or [])
                if str(item.get("content") or "").strip()
            ],
            {"role": "user", "content": user_message},
        ]
        response = await invoker(model_messages)
        raw_content = stringify_content(getattr(response, "content", response))
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

    def build_runtime_directive(
        self,
        task_operation_preview: dict[str, Any],
    ) -> tuple[RuntimeDirective, ResourcePolicy]:
        task_contract = dict(task_operation_preview.get("task_contract") or {})
        task_id = str(task_contract.get("task_id") or "task-runtime")
        plan_preview = dict(task_operation_preview.get("orchestration_plan_preview") or {})
        stages = list(plan_preview.get("stages") or [])
        stage_preview = dict(stages[0] if stages else {})
        policy_ref = f"respol:{task_id}:model-response:runtime"
        decision = ResourceDecision(
            operation_id="op.model_response",
            decision="allow",
            reason="model-only response is the phase-1 executable lane",
            risk_tags=("model_only", "read_only"),
        )
        resource_policy = ResourcePolicy(
            policy_id=policy_ref,
            task_id=task_id,
            allowed_operations=("op.model_response",),
            denied_operations=(),
            requires_approval_operations=(),
            preview_only_operations=(),
            allowed_tools=(),
            denied_tools=(),
            allowed_workers=(),
            denied_workers=(),
            allowed_agents=(),
            denied_agents=(),
            memory_read_scope="context_package_preview",
            memory_write_scope="none",
            approval_policy="model_only",
            preview_only=False,
            adopted=True,
            runtime_executable=True,
            decisions=(decision,),
            diagnostics={
                "runtime_executable": True,
                "adopted": True,
                "model_only": True,
                "tools_allowed": False,
                "workers_allowed": False,
                "memory_write_allowed": False,
                "filesystem_write_allowed": False,
                "legacy_query_chain_removed": True,
            },
        )
        directive = RuntimeDirective(
            directive_id=f"runtime-directive:{task_id}:model-response",
            task_id=task_id,
            plan_ref=str(plan_preview.get("plan_id") or f"orchplan:{task_id}").replace(":preview", ":runtime"),
            stage_ref=str(stage_preview.get("stage_id") or f"orchstage:{task_id}:model").replace(":preview", ":runtime"),
            executor_type="model",
            adopted_resource_policy_ref=policy_ref,
            operation_refs=("op.model_response",),
            input_contract_ref=str(task_operation_preview.get("task_prompt_contract", {}).get("contract_id") or ""),
            output_contract_ref=str(task_operation_preview.get("task_prompt_contract", {}).get("contract_id") or ""),
            execution_graph_ref=str(
                task_operation_preview.get("execution_graph_preview", {}).get("graph_preview_id") or ""
            ).replace(":preview", ":runtime"),
            runtime_executable=True,
            diagnostics={
                "source_preview_plan_ref": str(plan_preview.get("plan_id") or ""),
                "source_preview_stage_ref": str(stage_preview.get("stage_id") or ""),
                "directive_only_executor": True,
                "model_only": True,
                "legacy_query_chain_removed": True,
            },
        )
        return directive, resource_policy
