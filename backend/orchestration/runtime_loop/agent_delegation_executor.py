from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable

from capability_system.search_policy import agent_allowed_by_search_policy, normalize_search_policy
from execution.model_runtime import stringify_content
from orchestration.agent_identity import normalize_agent_id
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.delegation_protocol import default_expected_output_contract
from soul.projection_store import get_projection_card

from .child_agent_runtime_executor import ChildAgentRuntimeExecutor
from .delegation_models import AgentDelegationRequest, AgentDelegationResult
from .event_log import RuntimeEventLog
from .models import AgentRun, AgentRunResult
from .state_index import RuntimeStateIndex


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
    ) -> None:
        self.root_dir = Path(root_dir)
        self.state_index = state_index or RuntimeStateIndex(self.root_dir)
        self.event_log = event_log or RuntimeEventLog(self.root_dir)
        self.agent_registry = AgentRegistry(self.root_dir)
        self.runtime_registry = AgentRuntimeRegistry(self.root_dir)
        self.child_runner = child_runner
        self.child_runtime_executor = ChildAgentRuntimeExecutor(self.root_dir, evidence_orchestrator=evidence_orchestrator)

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
        child_context = self.build_child_runtime_context(request, child_agent_run=child_agent_run)
        child_runtime_event = self.event_log.append(
            request.task_run_id,
            "child_agent_runtime_started",
            payload={
                "target_agent_id": request.target_agent_id,
                "agent_profile_id": child_agent_run.agent_profile_id,
                "delegation_kind": request.delegation_kind,
                "runtime_profile": dict(child_context.get("runtime_profile") or {}),
            },
            refs={"agent_run_ref": child_agent_run.agent_run_id, "delegation_request_ref": request.request_id},
        )
        try:
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
                runtime_lane=child_agent_run.runtime_lane,
                parent_agent_run_ref=child_agent_run.parent_agent_run_ref,
                coordination_run_ref="",
                status=agent_run_result.status,
                result_ref=agent_run_result.agent_run_result_id,
                created_at=child_agent_run.created_at,
                updated_at=time.time(),
                diagnostics={
                    **dict(child_agent_run.diagnostics),
                    "delegation_runtime": "direct_agent_communication",
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
            "events": (request_event, agent_run_event, child_runtime_event, *completion_events),
        }

    def validate_request(self, request: AgentDelegationRequest, *, parent_agent_run: AgentRun) -> dict[str, Any]:
        reasons: list[str] = []
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

    def _normalize_request_target(
        self,
        request: AgentDelegationRequest,
        *,
        parent_agent_run: AgentRun,
    ) -> AgentDelegationRequest:
        resolved_target = self._resolve_target_agent_id(
            request.target_agent_id,
            delegation_kind=request.delegation_kind,
            parent_agent_run=parent_agent_run,
        )
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

    def _resolve_target_agent_id(
        self,
        target_agent_id: str,
        *,
        delegation_kind: str,
        parent_agent_run: AgentRun,
    ) -> str:
        target = normalize_agent_id(target_agent_id)
        normalized_kind = str(delegation_kind or "").strip()
        if target and self.agent_registry.get_agent(target) is not None:
            return target
        allowed_ids: set[str] = set()
        parent_profile = self.runtime_registry.get_profile(parent_agent_run.agent_id)
        if parent_profile is not None:
            allowed_ids = {
                str(item).strip()
                for item in tuple(getattr(parent_profile, "allowed_delegate_agent_ids", ()) or ())
                if str(item).strip()
            }
        normalized_kind = str(delegation_kind or "").strip()
        candidates = [
            agent
            for agent in self.agent_registry.list_agents()
            if agent.delegation_enabled
            and agent.enabled
            and (not allowed_ids or agent.agent_id in allowed_ids)
        ]
        if normalized_kind:
            for agent in candidates:
                profile = self.runtime_registry.get_profile(agent.agent_id)
                if profile is None:
                    continue
                if normalized_kind in set(_delegation_kinds_from_profile(profile)):
                    return agent.agent_id
        return target

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
            runtime_lane=(profile.allowed_runtime_lanes[0] if profile is not None and profile.allowed_runtime_lanes else "delegation"),
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={"delegation_request_ref": request.request_id, "delegation_kind": request.delegation_kind},
        )

    def build_child_runtime_context(self, request: AgentDelegationRequest, *, child_agent_run: AgentRun) -> dict[str, Any]:
        profile = self.runtime_registry.get_profile(request.target_agent_id)
        agent = self.agent_registry.get_agent(request.target_agent_id)
        projection_card = _child_projection_card(self.root_dir, agent)
        return {
            "request": request.to_dict(),
            "agent_run": child_agent_run.to_dict(),
            "agent": agent.to_dict() if agent is not None else {},
            "runtime_profile": profile.to_dict() if profile is not None else {},
            "projection_card": projection_card,
            "system_prompt": _child_system_prompt(agent, profile, projection_card=projection_card),
            "user_message": _child_user_message(request),
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
        specialist_payload = await self.child_runtime_executor.run(request=request, agent=agent, profile=profile)
        if str(specialist_payload.get("status") or "") != "failed" or specialist_payload.get("summary"):
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
        try:
            response = await invoker(messages)
        except Exception as exc:
            return {
                "status": "failed",
                "summary": "子 Agent 执行失败。",
                "limitations": [str(exc) or exc.__class__.__name__],
            }
        return {
            "status": "completed",
            "summary": stringify_content(getattr(response, "content", response)).strip() or "子 Agent 未返回有效摘要。",
            "answer_candidate": stringify_content(getattr(response, "content", response)).strip(),
            "confidence": "unknown",
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
        evidence_packet = dict(diagnostics.get("agent_evidence_packet") or {})
        consumed_handles = _delegation_consumed_handles(request=request, child_payload=child_payload)
        produced_handles = _delegation_produced_handles(child_payload=child_payload)
        if evidence_packet:
            diagnostics["agent_evidence_shadow_readiness"] = _agent_evidence_shadow_readiness(
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
        context_writeback_hints = _context_writeback_hints_from_result(result)
        return {
            "type": "agent_delegation_result",
            "status": result.status,
            "target_agent_id": result.target_agent_id,
            "summary": result.summary,
            "answer_candidate": result.answer_candidate,
            "evidence_refs": list(result.evidence_refs),
            "artifact_refs": list(result.artifact_refs),
            "confidence": result.confidence,
            "limitations": list(result.limitations),
            "followup_questions": list(result.followup_questions),
            "consumed_handles": list(result.consumed_handles),
            "produced_handles": list(result.produced_handles),
            "result_ref": result.result_id,
            "child_agent_run_ref": result.child_agent_run_ref,
            **({"context_writeback_hints": context_writeback_hints} if context_writeback_hints else {}),
        }

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

def _child_projection_card(root_dir: Path, agent: Any | None) -> dict[str, Any]:
    projection_id = str(getattr(agent, "default_projection_id", "") or "").strip()
    if not projection_id:
        return {}
    return dict(get_projection_card(_soul_base_dir(root_dir), projection_id) or {})


def _soul_base_dir(root_dir: Path) -> Path:
    resolved = Path(root_dir)
    if (resolved / "soul" / "projections").exists():
        return resolved
    if (resolved / "backend" / "soul" / "projections").exists():
        return resolved / "backend"
    return resolved


def _context_writeback_hints_from_result(result: AgentDelegationResult) -> dict[str, Any]:
    diagnostics = dict(result.diagnostics or {})
    mcp_result = dict(diagnostics.get("mcp_result") or {})
    canonical = dict(mcp_result.get("canonical_result") or {})
    bindings = dict(canonical.get("bindings") or {})
    presentation_hints = dict(canonical.get("presentation_hints") or {})
    source_path = str(bindings.get("active_dataset") or bindings.get("active_pdf") or bindings.get("active_table") or "").strip()
    source_kind = "dataset" if bindings.get("active_dataset") else "pdf" if bindings.get("active_pdf") else "table" if bindings.get("active_table") else ""
    subset_labels = [
        str(item or "").strip()
        for item in list(presentation_hints.get("subset_labels") or [])
        if str(item or "").strip()
    ]
    payload = {
        "source_kind": source_kind,
        "source_path": source_path,
        "active_object_handle_id": _first_text(canonical.get("object_handle_ids")),
        "active_result_handle_id": str(canonical.get("primary_result_handle_id") or _first_text(canonical.get("result_handle_ids"))),
        "active_subset_handle_id": str(presentation_hints.get("subset_handle_id") or ""),
        "subset_filter_column": str(presentation_hints.get("subset_filter_column") or ""),
        "subset_labels": subset_labels,
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _delegation_timeout_seconds(request: AgentDelegationRequest) -> float:
    policy = dict(request.timeout_policy or {})
    raw = policy.get("timeout_seconds")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 90.0
    return min(max(value, 1.0), 300.0)


def _first_text(values: Any) -> str:
    for item in list(values or []):
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _child_system_prompt(agent: Any | None, profile: Any | None, *, projection_card: dict[str, Any] | None = None) -> str:
    description = str(getattr(agent, "description", "") or "").strip()
    operations = ", ".join(str(item) for item in tuple(getattr(profile, "allowed_operations", ()) or ()))
    projection = dict(projection_card or {})
    identity_anchor = str(projection.get("identity_anchor") or "").strip()
    projection_prompt = str(projection.get("projection_prompt") or "").strip()
    lines: list[str] = []
    if identity_anchor:
        lines.append(identity_anchor)
    else:
        lines.append(description or "你是一名受限子 Agent，只负责完成委派给你的边界化任务。")
    if projection_prompt:
        lines.append(projection_prompt)
    lines.extend(
        [
            "## 协作边界",
            "你服务于主 Agent 的委派任务。你要把专业材料整理成主 Agent 可以判断和收口的结果。",
            "你不负责替主 Agent 做最终面向用户的表达，也不要扩大任务范围。",
            "你只返回已经完成的结果、证据引用、产物引用、置信度和限制说明。",
            f"你可使用的操作范围是：{operations or '仅模型响应'}。",
            "不要输出执行计划、伪工具调用语法或“我将调用某工具”的描述。",
            "如果已经拿到结果，直接整理结果；如果无法执行，直接说明失败原因和限制。",
            "如果信息不足或能力不可用，请明确写入限制和缺口，不要假装完成。",
        ]
    )
    return "\n\n".join(part for part in lines if str(part).strip())


def _child_user_message(request: AgentDelegationRequest) -> str:
    payload = dict(request.input_payload or {})
    protocol = dict(payload.get("agent_communication_protocol") or {})
    expected_output_contract = dict(
        request.expected_output_contract
        or protocol.get("expected_output_contract")
        or default_expected_output_contract(
            source_kind=str(protocol.get("source_kind") or payload.get("source_kind") or ""),
            delegation_kind=request.delegation_kind,
        )
    )
    return "\n".join(
        [
            f"委派类型：{request.delegation_kind}",
            f"任务说明：{request.instruction}",
            "通信协议：",
            json.dumps(
                {
                    "protocol_id": str(protocol.get("protocol_id") or "protocol.agent.direct_delegation.v1"),
                    "child_agent_contract": dict(protocol.get("child_agent_contract") or {}),
                    "expected_output_contract": expected_output_contract,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "输入：",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "请返回可供主 Agent 收口使用的中文结果摘要，只写已经完成的结果或明确失败原因。",
            "不要写执行计划，不要输出 <op.*> 或 JSON action 这类工具调用文本。",
        ]
    )


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
    previous_path = _delegation_payload_primary_path(previous_payload)
    current_path = _delegation_payload_primary_path(current_payload)
    limitations = tuple(getattr(result, "limitations", ()) or ())
    if limitations == ("missing_object_handle",) and current_path and not previous_path:
        return False
    return True


def _delegation_payload_primary_path(payload: dict[str, Any]) -> str:
    direct = str(
        payload.get("file_path")
        or payload.get("path")
        or payload.get("active_pdf")
        or payload.get("active_dataset")
        or ""
    ).strip()
    if direct:
        return direct
    for key in ("file_paths", "paths", "active_pdfs", "active_datasets"):
        values = payload.get(key)
        if isinstance(values, (list, tuple)):
            for item in values:
                value = str(item or "").strip()
                if value:
                    return value
        elif isinstance(values, str) and values.strip():
            return values.strip()
    return ""


def _delegation_consumed_handles(*, request: AgentDelegationRequest, child_payload: dict[str, Any]) -> list[str]:
    explicit = [
        str(item).strip()
        for item in list(child_payload.get("consumed_handles") or [])
        if str(item).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))
    payload = dict(request.input_payload or {})
    handles = [
        str(payload.get("active_subset_handle_id") or "").strip(),
        str(payload.get("active_result_handle_id") or "").strip(),
        str(payload.get("active_object_handle_id") or "").strip(),
        _delegation_payload_primary_path(payload),
    ]
    return [item for item in dict.fromkeys(handles) if item]


def _delegation_produced_handles(*, child_payload: dict[str, Any]) -> list[str]:
    explicit = [
        str(item).strip()
        for item in list(child_payload.get("produced_handles") or [])
        if str(item).strip()
    ]
    if explicit:
        return list(dict.fromkeys(explicit))
    diagnostics = dict(child_payload.get("diagnostics") or {})
    mcp_result = dict(diagnostics.get("mcp_result") or {})
    canonical = dict(mcp_result.get("canonical_result") or {})
    handles = [
        str(canonical.get("primary_result_handle_id") or "").strip(),
        *[str(item or "").strip() for item in list(canonical.get("result_handle_ids") or [])],
        *[str(item or "").strip() for item in list(canonical.get("artifact_refs") or [])],
    ]
    return [item for item in dict.fromkeys(handles) if item]


def _agent_evidence_shadow_readiness(*, packet: dict[str, Any], summary: str) -> dict[str, Any]:
    facts = list(packet.get("facts") or [])
    evidence = list(packet.get("evidence") or [])
    hints = list(packet.get("hints") or [])
    unknowns = list(packet.get("unknowns") or [])
    limits = list(packet.get("limits") or [])
    confidence = str(packet.get("confidence") or "unknown")
    fact_count = len(facts)
    evidence_count = len(evidence)
    unknown_count = len(unknowns)
    limit_count = len(limits)
    evidence_sufficient = fact_count > 0 and evidence_count > 0 and confidence in {"high", "medium"}
    if evidence_sufficient and not unknowns:
        recommendation = "main_agent_can_reason_from_facts"
    elif evidence_sufficient:
        recommendation = "main_agent_can_reason_from_facts_with_caveats"
    elif hints:
        recommendation = "main_agent_should_treat_child_answer_as_hint_only"
    else:
        recommendation = "main_agent_should_request_or_recover_evidence"
    return {
        "mode": "shadow_only",
        "packet_id": str(packet.get("packet_id") or ""),
        "domain": str(packet.get("domain") or "other"),
        "evidence_sufficient": evidence_sufficient,
        "fact_count": fact_count,
        "evidence_count": evidence_count,
        "hint_count": len(hints),
        "unknown_count": unknown_count,
        "limit_count": limit_count,
        "confidence": confidence,
        "summary_is_primary_path": True,
        "summary_chars": len(str(summary or "")),
        "recommendation": recommendation,
    }


def validate_delegation_result_quality(
    *,
    request: AgentDelegationRequest,
    child_payload: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    text = str(summary or "").strip()
    evidence_refs = [str(item) for item in list(child_payload.get("evidence_refs") or []) if str(item)]
    artifact_refs = [str(item) for item in list(child_payload.get("artifact_refs") or []) if str(item)]
    limitations = [str(item) for item in list(child_payload.get("limitations") or []) if str(item)]
    reasons: list[str] = []
    lowered = text.casefold()
    plan_markers = (
        "我将",
        "我会",
        "首先，我将",
        "让我",
        "将使用",
        "尝试读取",
        "i will",
        "i'll",
    )
    pseudo_tool_markers = (
        "<op.",
        "</op.",
        '"action"',
        "```json",
        "op.mcp_pdf",
        "op.read_structured_file",
        "op.mcp_structured_data",
        "op.mcp_retrieval",
    )
    if not text:
        reasons.append("empty_child_summary")
    if any(marker.casefold() in lowered for marker in plan_markers) and not (evidence_refs or artifact_refs or limitations):
        reasons.append("plan_text_without_evidence")
    if any(marker.casefold() in lowered for marker in pseudo_tool_markers) and not (evidence_refs or artifact_refs):
        reasons.append("pseudo_tool_text_without_execution_refs")
    specialist_kind = str(request.delegation_kind or "").strip()
    if specialist_kind in {
        "pdf",
        "pdf_reading",
        "table_analysis",
        "structured_data",
        "structured_data_lookup",
        "retrieval",
        "evidence_lookup",
        "web",
        "web_research",
        "external_web_lookup",
        "current_information_lookup",
        "official_source_lookup",
    }:
        if not (evidence_refs or artifact_refs or limitations):
            reasons.append("specialist_result_without_refs_or_limitations")
    status = "pass"
    normalized_status = str(child_payload.get("status") or "completed")
    invalid_reasons = {"empty_child_summary", "plan_text_without_evidence", "pseudo_tool_text_without_execution_refs"}
    if any(reason in invalid_reasons for reason in reasons):
        status = "invalid"
        normalized_status = "invalid_output"
    elif reasons:
        status = "warning"
    if limitations and normalized_status == "completed" and not (evidence_refs or artifact_refs):
        normalized_status = "failed"
    return {
        "status": status,
        "reasons": reasons,
        "normalized_status": normalized_status,
    }


def _delegation_kinds_from_profile(profile: Any) -> tuple[str, ...]:
    metadata = dict(getattr(profile, "metadata", {}) or {})
    values = [str(item).strip() for item in list(metadata.get("delegation_kinds") or []) if str(item).strip()]
    single = str(metadata.get("delegation_kind") or "").strip()
    if single:
        values.append(single)
    if values:
        return tuple(dict.fromkeys(values))
    operations = set(tuple(getattr(profile, "allowed_operations", ()) or ()))
    inferred: list[str] = []
    if "op.mcp_retrieval" in operations:
        inferred.append("evidence_lookup")
    if "op.mcp_pdf" in operations:
        inferred.append("pdf_reading")
    if "op.mcp_structured_data" in operations:
        inferred.append("structured_data_lookup")
    if "op.web_search" in operations:
        inferred.append("web_research")
    return tuple(inferred or ["bounded_analysis"])
