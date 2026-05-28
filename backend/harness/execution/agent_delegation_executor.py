from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from capability_system.search_policy import agent_allowed_by_search_policy, normalize_search_policy
from capability_system import build_default_operation_registry
from permissions import OperationGate, OperationGatePipelineContext
from runtime.shared.safety import build_task_safety_validators
from runtime.model_gateway.model_runtime import stringify_content
from agent_system.identity import normalize_agent_id
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.models.model_profile_resolver import ModelProfileResolver

from .child_agent_capability_executor import ChildAgentCapabilityExecutor
from .delegation_models import AgentDelegationRequest, AgentDelegationResult
from .delegation_policy import (
    build_child_operation_resource_policy,
    merge_child_operation_gate_results,
    required_operations_for_delegation,
)
from .delegation_result_policy import (
    agent_evidence_shadow_readiness,
    build_parent_delegation_observation,
    delegation_consumed_handles,
    delegation_payload_primary_path,
    delegation_produced_handles,
    validate_delegation_result_quality,
)
from .delegation_review import (
    child_system_prompt,
    child_user_message,
    delegation_kind_is_model_only_review,
    delegation_requires_model_only_review,
    parse_model_only_review_payload,
)
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.models import AgentRun, AgentRunResult

if TYPE_CHECKING:
    from runtime.memory.state_index import RuntimeStateIndex


ChildRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


class AgentDelegationExecutor:
    def __init__(
        self,
        root_dir: Path,
        *,
        state_index: RuntimeStateIndex | None = None,
        event_log: RuntimeEventLog | None = None,
        child_runner: ChildRunner | None = None,
        evidence_orchestrator: Any | None = None,
        operation_gate: OperationGate | None = None,
        permission_mode_provider: Callable[[], str] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        if state_index is None:
            from runtime.memory.state_index import RuntimeStateIndex

            state_index = RuntimeStateIndex(self.root_dir)
        self.state_index = state_index
        self.event_log = event_log or RuntimeEventLog(self.root_dir)
        self.agent_registry = AgentRegistry(self.root_dir)
        self.runtime_registry = AgentRuntimeRegistry(self.root_dir)
        self.child_runner = child_runner
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.permission_mode_provider = permission_mode_provider
        self.child_capability_executor = ChildAgentCapabilityExecutor(
            self.root_dir,
            evidence_orchestrator=evidence_orchestrator,
        )

    async def execute(
        self,
        *,
        request: AgentDelegationRequest,
        parent_agent_run: AgentRun,
        model_response_executor: Any | None = None,
    ) -> dict[str, Any]:
        request = self._normalize_request_target(request, parent_agent_run=parent_agent_run)
        self.state_index.upsert_agent_delegation_request(request)
        request_event = self.event_log.append(
            request.task_run_id,
            "agent_delegation_requested",
            payload={"agent_delegation_request": request.to_dict()},
            refs={"delegation_request_ref": request.request_id, "target_agent_id": request.target_agent_id},
        )
        validation = self.validate_request(request, parent_agent_run=parent_agent_run)
        if validation["blocked_reasons"]:
            result = self._blocked_result(request, parent_agent_run=parent_agent_run, reasons=validation["blocked_reasons"])
            self.state_index.upsert_agent_delegation_result(result)
            result_event = self.event_log.append(
                request.task_run_id,
                "agent_delegation_result_created",
                payload={"agent_delegation_result": result.to_dict()},
                refs={"delegation_request_ref": request.request_id, "delegation_result_ref": result.result_id},
            )
            return {
                "request": request,
                "result": result,
                "observation": self.build_parent_observation(result),
                "events": (request_event, result_event),
            }

        child_agent_run = self.prepare_child_agent_run(request, parent_agent_run=parent_agent_run)
        self.state_index.upsert_agent_run(child_agent_run)
        agent_run_event = self.event_log.append(
            request.task_run_id,
            "agent_run_created",
            payload={"agent_run": child_agent_run.to_dict()},
            refs={"agent_run_ref": child_agent_run.agent_run_id, "delegation_request_ref": request.request_id},
        )
        child_context = self.build_child_delegation_context(request, child_agent_run=child_agent_run)
        child_delegation_event = self.event_log.append(
            request.task_run_id,
            "child_agent_delegation_started",
            payload={
                "target_agent_id": request.target_agent_id,
                "agent_profile_id": child_agent_run.agent_profile_id,
                "delegation_kind": request.delegation_kind,
                "runtime_profile": dict(child_context.get("runtime_profile") or {}),
            },
            refs={"agent_run_ref": child_agent_run.agent_run_id, "delegation_request_ref": request.request_id},
        )
        gate_event = None
        try:
            gate_result = self.check_child_operation_permit(
                request=request,
                child_agent_run=child_agent_run,
                context=child_context,
            )
            gate_event = self.event_log.append(
                request.task_run_id,
                "child_agent_operation_gate_checked",
                payload={"gate": gate_result.to_dict()},
                refs={
                    "agent_run_ref": child_agent_run.agent_run_id,
                    "delegation_request_ref": request.request_id,
                    "operation_id": gate_result.operation_id,
                },
            )
            if not gate_result.allowed:
                child_payload = {
                    "status": "failed",
                    "summary": "子 Agent 专业能力未获系统授权，已停止执行。",
                    "answer_candidate": "子 Agent 专业能力未获系统授权，已停止执行。",
                    "confidence": "low",
                    "limitations": ["child_operation_gate_blocked", gate_result.reason],
                    "diagnostics": {
                        "child_operation_gate": gate_result.to_dict(),
                        "child_execution_mode": "profile_authorized_specialist",
                    },
                }
            else:
                child_context["child_operation_gate"] = gate_result.to_dict()
                child_payload = await asyncio.wait_for(
                    self.execute_child_agent(
                        context=child_context,
                        model_response_executor=model_response_executor,
                    ),
                    timeout=_delegation_timeout_seconds(request),
                )
        except asyncio.TimeoutError:
            child_payload = {
                "status": "failed",
                "summary": "子 Agent 执行超时，已停止等待本次委派结果。",
                "answer_candidate": "子 Agent 执行超时，已停止等待本次委派结果。",
                "confidence": "low",
                "limitations": ["delegation_timeout"],
                "diagnostics": {
                    "timeout_policy": dict(request.timeout_policy or {}),
                    "timeout_seconds": _delegation_timeout_seconds(request),
                },
            }
        status = "completed" if str(child_payload.get("status") or "completed") == "completed" else "failed"
        result = self.normalize_child_output(
            request=request,
            child_agent_run=child_agent_run,
            child_payload=child_payload,
            status=status,
        )
        quality_event = self.event_log.append(
            request.task_run_id,
            "agent_delegation_quality_checked",
            payload={
                "delegation_result_ref": result.result_id,
                "status": result.status,
                "quality_gate": dict(result.diagnostics.get("quality_gate") or {}),
                "limitations": list(result.limitations),
            },
            refs={"delegation_request_ref": request.request_id, "delegation_result_ref": result.result_id},
        )
        agent_run_result = AgentRunResult(
            agent_run_result_id=f"agrunresult:{child_agent_run.agent_run_id}",
            agent_run_id=child_agent_run.agent_run_id,
            task_run_id=request.task_run_id,
            agent_id=request.target_agent_id,
            status="completed" if result.status == "completed" else "failed",
            output_ref=result.result_id,
            summary=result.summary,
            artifact_refs=result.artifact_refs,
            created_at=time.time(),
            diagnostics={"delegation_request_ref": request.request_id},
        )
        self.state_index.upsert_agent_run_result(agent_run_result)
        self.state_index.upsert_agent_run(
            AgentRun(
                agent_run_id=child_agent_run.agent_run_id,
                task_run_id=child_agent_run.task_run_id,
                agent_id=child_agent_run.agent_id,
                agent_profile_id=child_agent_run.agent_profile_id,
                role=child_agent_run.role,
                spawn_mode=child_agent_run.spawn_mode,
                context_scope=child_agent_run.context_scope,
                execution_runtime_kind=child_agent_run.execution_runtime_kind,
                parent_agent_run_ref=child_agent_run.parent_agent_run_ref,
                coordination_run_ref="",
                status=agent_run_result.status,
                result_ref=agent_run_result.agent_run_result_id,
                created_at=child_agent_run.created_at,
                updated_at=time.time(),
                diagnostics={
                    **dict(child_agent_run.diagnostics),
                    "delegation_executor": "direct_agent_communication",
                },
            )
        )
        self.state_index.upsert_agent_delegation_result(result)
        completion_events = [
            quality_event,
            self.event_log.append(
                request.task_run_id,
                "agent_run_result_created",
                payload={"agent_run_result": agent_run_result.to_dict()},
                refs={
                    "agent_run_ref": child_agent_run.agent_run_id,
                    "agent_run_result_ref": agent_run_result.agent_run_result_id,
                    "delegation_request_ref": request.request_id,
                },
            ),
            self.event_log.append(
                request.task_run_id,
                "agent_delegation_result_created",
                payload={"agent_delegation_result": result.to_dict()},
                refs={"delegation_request_ref": request.request_id, "delegation_result_ref": result.result_id},
            ),
            self.event_log.append(
                request.task_run_id,
                "agent_delegation_parent_observation_created",
                payload={"parent_observation": self.build_parent_observation(result)},
                refs={
                    "delegation_request_ref": request.request_id,
                    "delegation_result_ref": result.result_id,
                    "agent_run_ref": child_agent_run.agent_run_id,
                },
            ),
        ]
        return {
            "request": request,
            "result": result,
            "observation": self.build_parent_observation(result),
            "events": tuple(
                event
                for event in (request_event, agent_run_event, child_delegation_event, gate_event, *completion_events)
                if event is not None
            ),
        }

    def check_child_operation_permit(
        self,
        *,
        request: AgentDelegationRequest,
        child_agent_run: AgentRun,
        context: dict[str, Any],
    ):
        profile = type("ProfilePayload", (), dict(context.get("runtime_profile") or {}))()
        operation_ids = required_operations_for_delegation(delegation_kind=request.delegation_kind, profile=profile)
        if delegation_requires_model_only_review(request, profile):
            operation_ids = ("op.model_response",)
        policy = build_child_operation_resource_policy(
            request=request,
            child_agent_run=child_agent_run,
            operation_ids=operation_ids,
            profile=profile,
            operation_gate=self.operation_gate,
        )
        directive_ref = f"runtime-directive:{request.task_run_id}:delegation:{request.request_id}"
        results = [
            self.operation_gate.check(
                operation_id,
                resource_policy=policy,
                directive_ref=directive_ref,
                context=OperationGatePipelineContext(
                    permission_mode=self._current_permission_mode(),
                    headless_mode=True,
                    operation_input={
                        "operation_id": operation_id,
                        "path": delegation_payload_primary_path(dict(request.input_payload or {})),
                        "args": dict(request.input_payload or {}),
                        "delegation_request_id": request.request_id,
                        "target_agent_id": request.target_agent_id,
                        "delegation_kind": request.delegation_kind,
                    },
                    validators=build_task_safety_validators(
                        root_dir=self.root_dir,
                        safety_envelope={},
                        sandbox_policy={},
                    ),
                ),
            )
            for operation_id in operation_ids
        ]
        return merge_child_operation_gate_results(
            request=request,
            child_agent_run=child_agent_run,
            results=results,
        )

    def validate_request(self, request: AgentDelegationRequest, *, parent_agent_run: AgentRun) -> dict[str, Any]:
        reasons: list[str] = []
        if not str(request.target_agent_id or "").strip():
            reasons.append("target_agent_required")
        allowed_search_sources = normalize_search_policy(
            list(dict(request.diagnostics or {}).get("allowed_search_sources") or [])
            if "allowed_search_sources" in dict(request.diagnostics or {})
            else None
        )
        if not agent_allowed_by_search_policy(request.target_agent_id, allowed_search_sources):
            reasons.append("target_agent_blocked_by_search_policy")
        parent_profile = self.runtime_registry.get_profile(parent_agent_run.agent_id)
        if parent_profile is None:
            reasons.append("parent_runtime_profile_missing")
        else:
            if not bool(getattr(parent_profile, "can_delegate_to_agents", False)):
                reasons.append("parent_delegation_not_authorized")
            parent_allowed = {str(item).strip() for item in parent_profile.allowed_operations if str(item).strip()}
            parent_blocked = {str(item).strip() for item in parent_profile.blocked_operations if str(item).strip()}
            if "op.delegate_to_agent" not in parent_allowed or "op.delegate_to_agent" in parent_blocked:
                reasons.append("parent_delegate_operation_not_allowed")
            allowed_target_ids = {
                str(item).strip()
                for item in tuple(getattr(parent_profile, "allowed_delegate_agent_ids", ()) or ())
                if str(item).strip()
            }
            if allowed_target_ids and request.target_agent_id not in allowed_target_ids:
                reasons.append("target_agent_not_allowed_by_parent")
            if parent_agent_run.spawn_mode == "delegation":
                reasons.append("nested_delegation_denied")
            max_calls = max(0, int(getattr(parent_profile, "max_delegate_calls_per_turn", 1) or 0))
            if max_calls > 0:
                prior_requests = self.state_index.list_task_agent_delegation_requests(request.task_run_id)
                results_by_request = {
                    str(item.request_id or ""): item
                    for item in self.state_index.list_task_agent_delegation_results(request.task_run_id)
                }
                existing_count = sum(
                    1
                    for item in prior_requests
                    if item.request_id != request.request_id
                    and str(item.source_agent_id or "") == str(parent_agent_run.agent_id or "")
                    and _delegation_request_counts_against_budget(
                        item,
                        current_request=request,
                        result=results_by_request.get(str(item.request_id or "")),
                    )
                )
                if existing_count >= max_calls:
                    reasons.append("max_delegate_calls_per_turn_exceeded")
        agent = self.agent_registry.get_agent(request.target_agent_id)
        profile = self.runtime_registry.get_profile(request.target_agent_id)
        if agent is None:
            reasons.append("target_agent_unavailable")
        elif not agent.enabled:
            reasons.append("target_agent_disabled")
        elif not agent.delegation_enabled:
            reasons.append("target_agent_delegation_disabled")
        if profile is None:
            reasons.append("target_runtime_profile_missing")
        else:
            allowed = {str(item).strip() for item in profile.allowed_operations if str(item).strip()}
            blocked = {str(item).strip() for item in profile.blocked_operations if str(item).strip()}
            if not (allowed - blocked):
                reasons.append("target_operations_empty")
            kinds = set(_delegation_kinds_from_profile(profile))
            if request.delegation_kind and request.delegation_kind not in kinds:
                reasons.append("delegation_kind_not_allowed")
        if parent_agent_run.agent_id == request.target_agent_id:
            reasons.append("self_delegation_denied")
        return {"blocked_reasons": list(dict.fromkeys(reasons))}

    def _current_permission_mode(self) -> str:
        provider = self.permission_mode_provider
        if callable(provider):
            try:
                mode = str(provider() or "").strip()
                if mode:
                    return mode
            except Exception:
                return "default"
        return "default"

    def _normalize_request_target(
        self,
        request: AgentDelegationRequest,
        *,
        parent_agent_run: AgentRun,
    ) -> AgentDelegationRequest:
        _ = parent_agent_run
        resolved_target = normalize_agent_id(request.target_agent_id)
        if not resolved_target or resolved_target == request.target_agent_id:
            return request
        diagnostics = dict(request.diagnostics or {})
        diagnostics.setdefault("requested_target_agent_id", request.target_agent_id)
        diagnostics["resolved_target_agent_id"] = resolved_target
        return replace(
            request,
            target_agent_id=resolved_target,
            diagnostics=diagnostics,
        )

    def prepare_child_agent_run(self, request: AgentDelegationRequest, *, parent_agent_run: AgentRun) -> AgentRun:
        profile = self.runtime_registry.get_profile(request.target_agent_id)
        return AgentRun(
            agent_run_id=f"agrun:{request.task_run_id}:delegation:{request.request_id.split(':')[-1]}",
            task_run_id=request.task_run_id,
            agent_id=request.target_agent_id,
            agent_profile_id=(profile.agent_profile_id if profile is not None else ""),
            role="delegated_worker",
            spawn_mode="delegation",
            context_scope="delegation_scoped",
            execution_runtime_kind="delegation",
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={"delegation_request_ref": request.request_id, "delegation_kind": request.delegation_kind},
        )

    def build_child_delegation_context(self, request: AgentDelegationRequest, *, child_agent_run: AgentRun) -> dict[str, Any]:
        profile = self.runtime_registry.get_profile(request.target_agent_id)
        agent = self.agent_registry.get_agent(request.target_agent_id)
        return {
            "request": request.to_dict(),
            "agent_run": child_agent_run.to_dict(),
            "agent": agent.to_dict() if agent is not None else {},
            "runtime_profile": profile.to_dict() if profile is not None else {},
            "system_prompt": child_system_prompt(agent, profile),
            "user_message": child_user_message(request),
            "communication_protocol": dict(dict(request.input_payload or {}).get("agent_communication_protocol") or {}),
        }

    async def execute_child_agent(self, *, context: dict[str, Any], model_response_executor: Any | None = None) -> dict[str, Any]:
        if self.child_runner is not None:
            value = self.child_runner(context)
            if inspect.isawaitable(value):
                value = await value
            return dict(value or {})
        request = AgentDelegationRequest(**dict(context.get("request") or {}))
        agent = type("AgentPayload", (), dict(context.get("agent") or {}))()
        profile = type("ProfilePayload", (), dict(context.get("runtime_profile") or {}))()
        requires_model_only_review = delegation_requires_model_only_review(request, profile)
        if not requires_model_only_review:
            specialist_payload = await self.child_capability_executor.run(
                request=request,
                agent=agent,
                profile=profile,
                model_runtime=getattr(model_response_executor, "model_runtime", None),
            )
            return specialist_payload
        invoker_owner = getattr(model_response_executor, "model_runtime", None)
        invoker = getattr(invoker_owner, "invoke_messages", None)
        if not callable(invoker):
            return {
                "status": "failed",
                "summary": "子 Agent 执行失败：模型运行时不可用。",
                "limitations": ["model_runtime_unavailable"],
            }
        messages = [
            {"role": "system", "content": str(context.get("system_prompt") or "")},
            {"role": "user", "content": str(context.get("user_message") or "")},
        ]
        resolved_model_spec = None
        model_resolution: dict[str, Any] = {}
        settings_service = getattr(invoker_owner, "settings_service", None)
        if settings_service is not None:
            runtime_profile_payload = dict(context.get("runtime_profile") or {})
            runtime_profile = self.runtime_registry.get_profile(str(runtime_profile_payload.get("agent_id") or request.target_agent_id))
            resolved_model_spec = ModelProfileResolver(settings_service).resolve_model_spec(
                agent_runtime_profile=runtime_profile,
                model_requirement=dict(dict(request.input_payload or {}).get("model_requirement") or {}),
            )
            model_resolution = resolved_model_spec.to_public_dict()
        try:
            response = await invoker(messages, model_spec=resolved_model_spec) if resolved_model_spec is not None else await invoker(messages)
        except Exception as exc:
            return {
                "status": "failed",
                "summary": "子 Agent 执行失败。",
                "limitations": [str(exc) or exc.__class__.__name__],
                "diagnostics": {"model_resolution": model_resolution} if model_resolution else {},
            }
        content = stringify_content(getattr(response, "content", response)).strip()
        structured = parse_model_only_review_payload(content)
        if structured:
            verdict = str(structured.get("verdict") or "").strip()
            limitations = [
                str(item)
                for item in list(structured.get("limitations") or [])
                if str(item)
            ]
            status = "completed" if verdict in {"pass", "needs_revision", "blocked"} else "failed"
            return {
                "status": status,
                "summary": str(structured.get("summary") or content or "复核 Agent 未返回有效摘要。").strip(),
                "answer_candidate": content,
                "verdict": verdict,
                "confidence": str(structured.get("confidence") or "unknown"),
                "limitations": limitations,
                "evidence_refs": [str(item) for item in list(structured.get("evidence_refs") or []) if str(item)],
                "artifact_refs": [str(item) for item in list(structured.get("artifact_refs") or []) if str(item)],
                "diagnostics": {
                    "child_execution_mode": "model_only_review",
                    "model_resolution": model_resolution,
                    "verifier_review": structured,
                    "verdict": verdict,
                    "missing_requirements": list(structured.get("missing_requirements") or []),
                    "unsupported_claims": list(structured.get("unsupported_claims") or []),
                    "required_revisions": list(structured.get("required_revisions") or []),
                },
            }
        return {
            "status": "completed",
            "summary": content or "子 Agent 未返回有效摘要。",
            "answer_candidate": content,
            "confidence": "unknown",
            "diagnostics": {"model_resolution": model_resolution} if model_resolution else {},
        }

    def normalize_child_output(
        self,
        *,
        request: AgentDelegationRequest,
        child_agent_run: AgentRun,
        child_payload: dict[str, Any],
        status: str,
    ) -> AgentDelegationResult:
        summary = str(child_payload.get("summary") or child_payload.get("answer_candidate") or "").strip()
        if not summary:
            summary = "子 Agent 执行完成，但没有返回可用摘要。" if status == "completed" else "子 Agent 执行失败。"
        quality = validate_delegation_result_quality(request=request, child_payload=child_payload, summary=summary)
        normalized_status = str(quality.get("normalized_status") or status)
        limitations = [
            str(item)
            for item in list(child_payload.get("limitations") or [])
            if str(item)
        ]
        for reason in list(quality.get("reasons") or []):
            if reason not in limitations and normalized_status in {"failed", "invalid_output"}:
                limitations.append(str(reason))
        diagnostics = dict(child_payload.get("diagnostics") or {})
        direct_writeback_hints = dict(child_payload.get("context_writeback_hints") or {})
        if direct_writeback_hints:
            diagnostics["context_writeback_hints"] = direct_writeback_hints
        evidence_packet = dict(diagnostics.get("agent_evidence_packet") or {})
        consumed_handles = delegation_consumed_handles(request=request, child_payload=child_payload)
        produced_handles = delegation_produced_handles(child_payload=child_payload)
        if evidence_packet:
            diagnostics["agent_evidence_shadow_readiness"] = agent_evidence_shadow_readiness(
                packet=evidence_packet,
                summary=summary,
            )
        diagnostics["quality_gate"] = quality
        return AgentDelegationResult(
            result_id=f"delegation:result:{request.request_id.split(':')[-1]}",
            request_id=request.request_id,
            task_run_id=request.task_run_id,
            parent_agent_run_ref=request.parent_agent_run_ref,
            child_agent_run_ref=child_agent_run.agent_run_id,
            target_agent_id=request.target_agent_id,
            status=normalized_status,
            summary=summary,
            answer_candidate=str(child_payload.get("answer_candidate") or summary).strip(),
            evidence_refs=tuple(str(item) for item in list(child_payload.get("evidence_refs") or []) if str(item)),
            artifact_refs=tuple(str(item) for item in list(child_payload.get("artifact_refs") or []) if str(item)),
            confidence=str(child_payload.get("confidence") or "unknown"),
            limitations=tuple(limitations),
            followup_questions=tuple(str(item) for item in list(child_payload.get("followup_questions") or []) if str(item)),
            consumed_handles=tuple(consumed_handles),
            produced_handles=tuple(produced_handles),
            created_at=time.time(),
            diagnostics=diagnostics,
        )

    def build_parent_observation(self, result: AgentDelegationResult) -> dict[str, Any]:
        return build_parent_delegation_observation(result=result, root_dir=self.root_dir)

    def _blocked_result(self, request: AgentDelegationRequest, *, parent_agent_run: AgentRun, reasons: list[str]) -> AgentDelegationResult:
        _ = parent_agent_run
        return AgentDelegationResult(
            result_id=f"delegation:result:{request.request_id.split(':')[-1]}",
            request_id=request.request_id,
            task_run_id=request.task_run_id,
            parent_agent_run_ref=request.parent_agent_run_ref,
            child_agent_run_ref="",
            target_agent_id=request.target_agent_id,
            status="blocked",
            summary="委派未执行。",
            limitations=tuple(reasons),
            created_at=time.time(),
            diagnostics={"blocked_reasons": list(reasons)},
        )

def _delegation_timeout_seconds(request: AgentDelegationRequest) -> float:
    policy = dict(request.timeout_policy or {})
    raw = policy.get("timeout_seconds")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 90.0
    return min(max(value, 1.0), 300.0)


def _delegation_request_counts_against_budget(
    previous_request: AgentDelegationRequest,
    *,
    current_request: AgentDelegationRequest,
    result: AgentDelegationResult | None,
) -> bool:
    previous_alignment = str(dict(previous_request.diagnostics or {}).get("goal_alignment") or "").strip().lower()
    current_alignment = str(dict(current_request.diagnostics or {}).get("goal_alignment") or "").strip().lower()
    if previous_alignment == "offtopic" and current_alignment == "aligned":
        return False
    previous_payload = dict(previous_request.input_payload or {})
    current_payload = dict(current_request.input_payload or {})
    previous_path = delegation_payload_primary_path(previous_payload)
    current_path = delegation_payload_primary_path(current_payload)
    limitations = tuple(getattr(result, "limitations", ()) or ())
    if limitations == ("missing_object_handle",) and current_path and not previous_path:
        return False
    return True


def _delegation_kinds_from_profile(profile: Any) -> tuple[str, ...]:
    metadata = dict(getattr(profile, "metadata", {}) or {})
    values = [str(item).strip() for item in list(metadata.get("delegation_kinds") or []) if str(item).strip()]
    single = str(metadata.get("delegation_kind") or "").strip()
    if single:
        values.append(single)
    return tuple(dict.fromkeys(values))


