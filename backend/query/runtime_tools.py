from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable

from query.output_boundary import sanitize_visible_assistant_content
from query.output_classifier import build_output_decision, classify_output_candidate
from query.tool_output_adapter import build_tool_result_envelope
from runtime.model_runtime import stringify_content
from tasks.context_models import TaskConstraints
from tools.contracts import ToolContractDecision, ToolContractGate, ToolScope
from tools.definitions import get_tool_definition_map
from tools.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION, get_mcp_tool_view


class RuntimeToolBridge:
    def __init__(
        self,
        *,
        permission_service,
        tool_runtime,
        task_coordinator,
        tool_contract_gate: ToolContractGate,
        output_policy,
        skill_allowed_tool_scope: Callable[[Any], ToolScope],
        extract_active_constraints: Callable[[str], dict[str, Any]],
        build_direct_tool_main_context: Callable[..., Any],
        task_summary_ref_from_task: Callable[[Any], Any],
    ) -> None:
        self.permission_service = permission_service
        self.tool_runtime = tool_runtime
        self.task_coordinator = task_coordinator
        self.tool_contract_gate = tool_contract_gate
        self.output_policy = output_policy
        self._skill_allowed_tool_scope = skill_allowed_tool_scope
        self._extract_active_constraints = extract_active_constraints
        self._build_direct_tool_main_context = build_direct_tool_main_context
        self._task_summary_ref_from_task = task_summary_ref_from_task

    def allowed_tool_names_for_plan(self, plan) -> set[str]:
        return self.allowed_tool_names_for_execution(plan.iter_executions()[0])

    def allowed_tool_names_for_execution(self, execution) -> set[str]:
        route = str(execution.query_understanding.route or "").strip()
        execution_posture = str(
            execution.execution_posture or getattr(execution.query_understanding, "execution_posture", "") or ""
        ).strip()
        skill_scope = self._tool_scope_for_execution(execution)

        if route == "memory":
            return set()
        if route == "rag" and execution_posture != "bounded_agent":
            return set()

        if execution_posture == "bounded_agent":
            requested = list(getattr(execution.query_understanding, "candidate_tools", []) or [])
            if not requested and skill_scope.has_allowed_filter:
                requested.extend(skill_scope.to_allowed_tools())
            return self._without_worker_only_tools(
                self.permission_service.allowed_tool_names(allowed_tools=requested or None)
            )

        if route == "tool":
            requested: list[str] = []
            if execution.query_understanding.tool_name:
                requested.append(execution.query_understanding.tool_name)
            elif getattr(execution.query_understanding, "candidate_tools", None):
                requested.extend(list(execution.query_understanding.candidate_tools))
            elif skill_scope.has_allowed_filter:
                requested.extend(skill_scope.to_allowed_tools())
            return set(self.permission_service.allowed_tool_names(allowed_tools=requested))

        return self._without_worker_only_tools(
            self.permission_service.allowed_tool_names(
                allowed_tools=skill_scope.to_allowed_tools() if skill_scope.has_allowed_filter else None
            )
        )

    def _without_worker_only_tools(self, tool_names: list[str] | set[str] | tuple[str, ...]) -> set[str]:
        # RAG is now a RetrievalWorker capability. Keeping the retrieval facade out
        # of the model-visible tool schema prevents bounded-agent retrieval loops.
        return {str(name) for name in list(tool_names or []) if str(name) != "search_knowledge"}

    async def stream_direct_tool_execution(
        self,
        session_id: str,
        execution,
        *,
        trace=None,
    ):
        tool_name = str(execution.query_understanding.tool_name or "").strip()
        tool_input = dict(execution.tool_input or execution.query_understanding.tool_input or {"query": execution.message})
        mcp_metadata = self._mcp_event_metadata(tool_name)
        message_id = f"mcp-tool-message:{uuid.uuid4().hex}"
        contract_decision = self.evaluate_tool_contract(
            tool_name=tool_name,
            tool_input=tool_input,
            execution=execution,
        )
        if trace is not None:
            trace.annotate(
                {
                    "app.tool_contract_mode": contract_decision.mode,
                    "app.tool_contract_action": contract_decision.action,
                    "app.tool_contract_reason": contract_decision.reason,
                }
            )
        if contract_decision.should_block:
            yield {
                "type": "done",
                "content": self.tool_contract_failure_message(
                    tool_name=tool_name,
                    contract_decision=contract_decision,
                ),
                "answer_channel": "fallback_answer",
                "answer_source": "tool_contract_gate",
                "answer_fallback_reason": "tool_contract_blocked",
                "answer_leak_flags": [],
                "contract": contract_decision.to_dict(),
                "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
                "message_id": message_id,
                "mcp": mcp_metadata,
            }
            return

        decision = self.permission_service.can_invoke_tool(
            tool_name,
            allowed_tools=self._tool_scope_for_execution(execution),
            direct_route=True,
            tool_input=tool_input,
        )
        if not decision.allowed:
            yield {
                "type": "done",
                "content": f"无法调用工具 {tool_name}：{decision.reason}",
                "answer_channel": "fallback_answer",
                "answer_source": "permission_guard",
                "answer_fallback_reason": "tool_permission_denied",
                "answer_leak_flags": [],
                "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
                "message_id": message_id,
                "mcp": mcp_metadata,
            }
            return

        tool = self.tool_runtime.get_instance(tool_name)
        if tool is None:
            yield {
                "type": "done",
                "content": f"工具 {tool_name} 当前不可用。",
                "answer_channel": "fallback_answer",
                "answer_source": "tool_runtime",
                "answer_fallback_reason": "tool_unavailable",
                "answer_leak_flags": [],
                "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
                "message_id": message_id,
                "mcp": mcp_metadata,
            }
            return

        if trace is not None:
            trace.annotate(
                {
                    "app.route": "tool",
                    "app.tool_name": tool_name,
                    "app.structured_binding_path": (
                        execution.structured_binding.dataset_path
                        if getattr(execution, "structured_binding", None) is not None
                        else ""
                    ),
                    "app.structured_binding_source": (
                        execution.structured_binding.source
                        if getattr(execution, "structured_binding", None) is not None
                        else ""
                    ),
                }
            )

        yield {
            "type": "tool_start",
            "tool": tool_name,
            "input": tool_input,
            "contract": contract_decision.to_dict(),
            "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
            "message_id": message_id,
            "mcp": mcp_metadata,
            "structured_binding": (
                execution.structured_binding.to_dict()
                if getattr(execution, "structured_binding", None) is not None
                else None
            ),
        }

        active_constraints = self._extract_active_constraints(execution.message)
        raw_tool_output: Any = None
        rendered_tool_decision = None

        async def invoke_tool() -> Any:
            nonlocal raw_tool_output
            if trace is not None:
                with trace.stage(
                    "query.direct_tool",
                    run_type="tool",
                    inputs={"tool": tool_name, "input": tool_input},
                ):
                    raw_tool_output = await asyncio.to_thread(tool.invoke, tool_input)
                    return raw_tool_output
            raw_tool_output = await asyncio.to_thread(tool.invoke, tool_input)
            return raw_tool_output

        def _render_content(output: Any) -> str:
            nonlocal rendered_tool_decision
            rendered_tool_decision = self.build_direct_tool_output_decision(
                output,
                tool_name=tool_name,
                query=execution.message,
                route=str(execution.query_understanding.route or "tool"),
            )
            return rendered_tool_decision.canonical_answer.strip()

        task = await self.task_coordinator.run_tool_task(
            session_id,
            tool_name,
            invoke_tool,
            query=execution.message,
            tool_input=tool_input,
            structured_binding=getattr(execution, "structured_binding", None),
            task_kind=str(getattr(execution.query_understanding, "task_kind", "") or ""),
            constraints=TaskConstraints(
                top_n=active_constraints.get("top_n"),
                group_by=str(active_constraints.get("group_by", "") or ""),
                page=active_constraints.get("page"),
                response_style=str(active_constraints.get("response_style", "") or ""),
                pdf_mode=str(active_constraints.get("pdf_mode", "") or ""),
                pdf_section=str(active_constraints.get("pdf_section", "") or ""),
            ),
            render_content=_render_content,
        )
        tool_decision = rendered_tool_decision or self.build_direct_tool_output_decision(
            raw_tool_output,
            tool_name=tool_name,
            query=execution.message,
            route=str(execution.query_understanding.route or "tool"),
        )
        visible_content = tool_decision.canonical_answer.strip() or f"{tool_name} 已执行，但未返回可展示结果。"
        tool_content = task.result
        binding_payload = (
            execution.structured_binding.to_dict()
            if getattr(execution, "structured_binding", None) is not None
            else None
        )
        task_summary_ref = self._task_summary_ref_from_task(task)
        yield {
            "type": "tool_end",
            "tool": tool_name,
            "output": tool_content,
            "structured_binding": binding_payload,
            "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
            "message_id": message_id,
            "mcp": mcp_metadata,
        }
        yield {
            "type": "done",
            "content": visible_content,
            "task_id": task.task_id,
            "summary": task.summary.to_dict() if task.summary is not None else None,
            "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
            "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
            "main_context": self._build_direct_tool_main_context(execution.message, task=task).to_dict(),
            "structured_binding": binding_payload,
            "object_handle_ids": list(task.metadata.get("object_handle_ids", []) or []),
            "result_handle_ids": list(task.metadata.get("result_handle_ids", []) or []),
            "presentation_hints": {
                "subset_handle_id": str(getattr(task.result_ref, "subset_handle_id", "") or ""),
                "subset_labels": list(getattr(task.result_ref, "subset_labels", []) or []),
                "subset_filter_column": str(getattr(task.result_ref, "subset_filter_column", "") or ""),
                "subset_hint_query": str(getattr(task.result_ref, "subset_hint_query", "") or ""),
            },
            "binding_owner_task_id": str(task.metadata.get("binding_owner_task_id", "") or task.task_id),
            "degraded_reason_typed": str(task.metadata.get("degraded_reason_typed", "") or ""),
            "execution_protocol": "direct_tool",
            "tool_protocol": MCP_COMPATIBLE_PROTOCOL_VERSION,
            "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
            "message_id": message_id,
            "mcp": mcp_metadata,
            "answer_channel": tool_decision.selected_channel,
            "answer_source": tool_decision.selected_source,
            "answer_fallback_reason": tool_decision.fallback_reason,
            "answer_leak_flags": list(tool_decision.leak_flags),
            "contract": contract_decision.to_dict(),
            "task_summary_refs": [task_summary_ref.to_dict()] if task_summary_ref is not None else [],
        }

    def _mcp_event_metadata(self, tool_name: str) -> dict[str, Any]:
        view = get_mcp_tool_view(tool_name)
        if view is None:
            return {
                "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
                "server_name": "local-tools",
                "tool_name": str(tool_name or "").strip(),
                "schema_identity": "",
                "runtime_visibility": "unknown",
                "prompt_exposure_policy": "hidden",
                "resource_exposure_policy": "none",
            }
        return view.to_event_metadata()

    def evaluate_tool_contract(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        execution,
    ) -> ToolContractDecision:
        effective_mode = self.effective_tool_contract_mode(tool_name)
        contract = None
        runtime_get_contract = getattr(self.tool_runtime, "get_contract", None)
        if callable(runtime_get_contract):
            contract = runtime_get_contract(tool_name)
        if contract is None:
            definition = get_tool_definition_map().get(tool_name)
            if definition is not None:
                contract = definition.contract
        if contract is None:
            return ToolContractDecision(
                tool_name=tool_name,
                mode=effective_mode,
                action="deny",
                reason="missing_tool_contract",
            )

        binding_context = {
            "active_dataset": (
                execution.structured_binding.dataset_path
                if getattr(execution, "structured_binding", None) is not None
                else ""
            ),
            "active_pdf": str(tool_input.get("path", "") or "").strip(),
        }
        local_gate = ToolContractGate(mode=effective_mode)
        return local_gate.evaluate(
            tool_name=tool_name,
            contract=contract,
            tool_input=tool_input,
            tool_scope=self._tool_scope_for_execution(execution),
            binding_context=binding_context,
        )

    def _tool_scope_for_execution(self, execution) -> ToolScope:
        dispatch_scope = getattr(getattr(execution, "dispatch_plan", None), "effective_tool_scope", None)
        if isinstance(dispatch_scope, ToolScope):
            return dispatch_scope
        return self._skill_allowed_tool_scope(execution.active_skill)

    def effective_tool_contract_mode(self, tool_name: str) -> str:
        base_mode = str(self.tool_contract_gate.mode or "shadow").strip().lower() or "shadow"
        if base_mode == "off":
            return "off"
        if tool_name in {
            "pdf_analysis",
            "structured_data_analysis",
            "analyze_multimodal_file",
            "index_multimodal_file",
        }:
            return "enforce"
        return base_mode

    def tool_contract_failure_message(
        self,
        *,
        tool_name: str,
        contract_decision: ToolContractDecision,
    ) -> str:
        if contract_decision.reason == "missing_required_binding":
            if tool_name == "pdf_analysis":
                return "无法调用 PDF 工具：需要先明确 PDF 文件 path，或已有已确认的 PDF 绑定。"
            if tool_name == "structured_data_analysis":
                return "无法调用表格工具：需要先明确数据文件 path，或已有已确认的数据集绑定。"
            if contract_decision.missing_bindings:
                return f"无法调用工具 {tool_name}：缺少绑定 {', '.join(contract_decision.missing_bindings)}。"
        if contract_decision.reason == "missing_required_input":
            if contract_decision.missing_inputs:
                return f"无法调用工具 {tool_name}：缺少输入 {', '.join(contract_decision.missing_inputs)}。"
        return f"无法调用工具 {tool_name}：{contract_decision.reason}"

    def normalize_direct_tool_output(
        self,
        output: Any,
        *,
        tool_name: str = "",
        query: str = "",
        route: str = "tool",
    ) -> str:
        decision = self.build_direct_tool_output_decision(
            output,
            tool_name=tool_name,
            query=query,
            route=route,
        )
        return decision.canonical_answer.strip()

    def build_direct_tool_output_decision(
        self,
        output: Any,
        *,
        tool_name: str = "",
        query: str = "",
        route: str = "tool",
        force_allow_unlabeled: bool = False,
    ):
        normalized_text, allow_unlabeled_answer = self.prepare_direct_tool_output_candidate(
            output,
            tool_name=tool_name,
        )
        candidate = classify_output_candidate(
            text=normalized_text,
            route=route,
            source=f"direct_tool.{tool_name or 'tool'}",
            tool_name=tool_name,
            allow_unlabeled_answer=allow_unlabeled_answer or force_allow_unlabeled,
            has_tool_receipt=True,
        )
        return build_output_decision(
            candidates=[candidate] if candidate is not None else [],
            route=route,
            execution_posture="direct_tool",
            user_message=query,
            tool_name=tool_name,
            retrieval_results=None,
            has_tool_receipt=True,
        )

    def prepare_direct_tool_output_candidate(self, output: Any, *, tool_name: str = "") -> tuple[str, bool]:
        envelope = build_tool_result_envelope(
            output,
            tool_name=tool_name,
            stringify_output=self.stringify_tool_output,
        )
        return envelope.display_text, envelope.allow_unlabeled_answer

    def stringify_tool_output(self, output: Any) -> str:
        if isinstance(output, str):
            return sanitize_visible_assistant_content(output).strip()
        if isinstance(output, dict):
            for key in ("answer", "content", "summary", "result", "output", "text"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return sanitize_visible_assistant_content(value).strip()
            return json.dumps(output, ensure_ascii=False, indent=2)
        if isinstance(output, (list, tuple)):
            if all(isinstance(item, str) for item in output):
                parts = [sanitize_visible_assistant_content(str(item)).strip() for item in output]
                return "\n".join(item for item in parts if item).strip()
            return json.dumps(list(output), ensure_ascii=False, indent=2)
        normalized = stringify_content(output)
        return sanitize_visible_assistant_content(normalized).strip() if isinstance(normalized, str) else str(output)
