from __future__ import annotations

import uuid
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from evidence import (
    MCPExecutionPlan,
    MCPRequest,
    PDFWorker,
    StructuredDataWorker,
    build_agent_evidence_packet_from_mcp_payload,
    build_agent_evidence_packet_from_web_payload,
)
from runtime.codebase_search_runtime import (
    CODEBASE_SEARCH_TEMPLATE_ID,
    CodebaseSearchRuntime,
    normalize_codebase_search_config,
)
from runtime.search_agent_runtime import DEEPSEARCH_TEMPLATE_ID, SearchAgentRuntime, normalize_runtime_config
from runtime_encoding import utf8_subprocess_text_kwargs

from .delegation_models import AgentDelegationRequest


class ChildAgentRuntimeExecutor:
    """Runs a registered child Agent through its profile-authorized specialist capability."""

    def __init__(
        self,
        root_dir: Path,
        *,
        evidence_orchestrator: Any | None = None,
        search_runtime_factory: Any | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.evidence_orchestrator = evidence_orchestrator
        self.search_runtime_factory = search_runtime_factory

    async def run(self, *, request: AgentDelegationRequest, agent: Any, profile: Any, model_runtime: Any | None = None) -> dict[str, Any]:
        runtime_config = normalize_runtime_config(dict(getattr(profile, "metadata", {}) or {}).get("runtime_config"))
        if runtime_config.template_id == CODEBASE_SEARCH_TEMPLATE_ID:
            codebase_runtime = CodebaseSearchRuntime(self.root_dir)
            return await codebase_runtime.run(
                request=request,
                agent=agent,
                profile=profile,
                config=normalize_codebase_search_config(runtime_config.raw),
            )
        if runtime_config.template_id == DEEPSEARCH_TEMPLATE_ID:
            search_runtime = (
                self.search_runtime_factory(self.root_dir)
                if self.search_runtime_factory is not None
                else SearchAgentRuntime(self.root_dir, model_runtime=model_runtime)
            )
            return await search_runtime.run(
                request=request,
                agent=agent,
                profile=profile,
                config=runtime_config.search or normalize_runtime_config({"search": {}}).search,
            )
        operation_id = _operation_for_delegation(request=request, profile=profile)
        if not operation_id:
            return {
                "status": "failed",
                "summary": "子 Agent 未获得可执行的专业能力。",
                "limitations": ["child_operation_not_authorized"],
                "diagnostics": {"child_execution_mode": "profile_authorized_specialist"},
            }
        mcp_route = _mcp_route_for_operation(operation_id)
        if operation_id == "op.web_search":
            return await self._run_web_research(request=request, agent=agent)
        if not mcp_route:
            return {
                "status": "failed",
                "summary": "子 Agent 的专业能力暂不支持当前委派类型。",
                "limitations": ["unsupported_child_operation"],
                "diagnostics": {"operation_id": operation_id, "child_execution_mode": "profile_authorized_specialist"},
            }
        mcp_request = _build_mcp_request(request, mcp_route=mcp_route, agent_id=str(getattr(agent, "agent_id", "") or ""))
        mcp_result_payload = await self._run_mcp(mcp_route=mcp_route, mcp_request=mcp_request)
        evidence_packet = build_agent_evidence_packet_from_mcp_payload(
            mcp_result_payload=mcp_result_payload,
            mcp_request=mcp_request,
            source_agent_id=str(getattr(agent, "agent_id", "") or ""),
            target_task_id=request.task_run_id,
            task_goal=request.instruction,
            domain=mcp_route,
        )
        canonical = dict(mcp_result_payload.get("canonical_result") or {})
        answer = str(canonical.get("answer") or "").strip()
        ok = bool(canonical.get("ok", False))
        status = "completed" if ok else "failed"
        limitations: list[str] = []
        degraded_reason = str(canonical.get("degraded_reason_typed") or canonical.get("degraded_reason") or "").strip()
        if degraded_reason:
            limitations.append(degraded_reason)
        if not answer:
            status = "failed"
            answer = "子 Agent 专业能力执行完成，但没有形成可用结果。"
            limitations.append("child_specialist_empty_answer")
        return {
            "status": status,
            "summary": answer,
            "answer_candidate": answer,
            "evidence_refs": list(canonical.get("evidence_refs") or []),
            "artifact_refs": list(canonical.get("artifact_refs") or []),
            "confidence": "high" if ok else "low",
            "limitations": limitations,
            "diagnostics": {
                "child_execution_mode": "profile_authorized_specialist",
                "operation_id": operation_id,
                "mcp_route": mcp_route,
                "mcp_status": str(mcp_result_payload.get("status") or ""),
                "mcp_result": mcp_result_payload,
                "agent_evidence_packet": evidence_packet.to_dict(),
                "visible_packet_summary": evidence_packet.visible_summary(),
            },
        }

    async def _run_web_research(self, *, request: AgentDelegationRequest, agent: Any) -> dict[str, Any]:
        payload = dict(request.input_payload or {})
        query = str(payload.get("query") or payload.get("question") or request.instruction or "").strip()
        topic = str(payload.get("topic") or "general").strip() or "general"
        time_range = str(payload.get("time_range") or "").strip()
        max_results = int(payload.get("max_results") or 5)
        web_payload = await self._run_web_search(
            query=query,
            topic=topic,
            time_range=time_range,
            max_results=max_results,
        )
        packet = build_agent_evidence_packet_from_web_payload(
            web_payload=web_payload,
            source_agent_id=str(getattr(agent, "agent_id", "") or "agent:web_researcher"),
            target_task_id=request.task_run_id,
            task_goal=request.instruction,
        )
        ok = bool(web_payload.get("ok", True)) and bool(packet.evidence)
        answer = _web_research_summary(web_payload=web_payload, packet=packet)
        limitations: list[str] = []
        if not ok:
            reason = str(web_payload.get("error") or "web_research_no_sources").strip()
            limitations.append(reason)
        return {
            "status": "completed" if ok else "failed",
            "summary": answer,
            "answer_candidate": answer,
            "evidence_refs": [item.evidence_id for item in packet.evidence],
            "artifact_refs": [],
            "confidence": packet.confidence,
            "limitations": limitations,
            "diagnostics": {
                "child_execution_mode": "profile_authorized_specialist",
                "operation_id": "op.web_search",
                "specialist_route": "web_research",
                "web_payload": web_payload,
                "agent_evidence_packet": packet.to_dict(),
                "visible_packet_summary": packet.visible_summary(),
            },
        }

    async def _run_web_search(self, *, query: str, topic: str, time_range: str, max_results: int) -> dict[str, Any]:
        return await asyncio.to_thread(
            _run_web_search_sync,
            root_dir=self.root_dir,
            query=query,
            topic=topic,
            time_range=time_range,
            max_results=max_results,
        )

    async def _run_mcp(self, *, mcp_route: str, mcp_request: MCPRequest) -> dict[str, Any]:
        if self.evidence_orchestrator is not None:
            done_event: dict[str, Any] = {}
            mcp_end_event: dict[str, Any] = {}
            evidence_envelope: dict[str, Any] = {}
            plan = MCPExecutionPlan(
                mcp_route=mcp_route,
                request=mcp_request,
                expected_result="canonical",
                fallback_execution_kind="none",
                cutover_mode="primary",
            )
            async for event in self.evidence_orchestrator.stream_execution(
                session_id=mcp_request.session_id,
                execution=None,
                mcp_plan=plan,
                main_context={},
                trace=None,
            ):
                if event.get("type") == "mcp_evidence":
                    evidence_envelope = dict(event.get("evidence") or {})
                if event.get("type") == "mcp_end":
                    mcp_end_event = dict(event)
                if event.get("type") == "done":
                    done_event = dict(event)
            result = dict(mcp_end_event.get("result") or done_event.get("result") or {})
            return {
                "mcp_name": mcp_route,
                "status": "ok" if bool(result.get("ok", False)) else "error",
                "task_status": str(mcp_end_event.get("task_status") or done_event.get("task_status") or ""),
                "stream_event_type": str(mcp_end_event.get("stream_event_type") or done_event.get("stream_event_type") or ""),
                "evidence_envelope": evidence_envelope or None,
                "canonical_result": result,
                "binding_candidates": list(mcp_end_event.get("binding_candidates") or []),
                "diagnostics": {
                    "source": "evidence_orchestrator.stream_execution",
                    "evidence_envelope_captured": bool(evidence_envelope),
                    "degraded_reason_typed": str(mcp_end_event.get("degraded_reason_typed") or done_event.get("degraded_reason_typed") or ""),
                },
            }
        if mcp_route == "pdf":
            return (await PDFWorker(root_dir=self.root_dir).run(mcp_request)).to_dict()
        if mcp_route == "structured_data":
            return (await StructuredDataWorker(root_dir=self.root_dir).run(mcp_request)).to_dict()
        return {
            "mcp_name": mcp_route,
            "status": "error",
            "canonical_result": {
                "ok": False,
                "answer": "当前检索服务不可用，无法完成证据检索。",
                "degraded_reason": "retrieval_worker_unavailable",
                "degraded_reason_typed": "retrieval_worker_unavailable",
            },
            "diagnostics": {"source": "child_runtime_fallback"},
        }


def _operation_for_delegation(*, request: AgentDelegationRequest, profile: Any) -> str:
    allowed = {str(item).strip() for item in tuple(getattr(profile, "allowed_operations", ()) or ()) if str(item).strip()}
    blocked = {str(item).strip() for item in tuple(getattr(profile, "blocked_operations", ()) or ()) if str(item).strip()}
    available = allowed - blocked
    kind = str(request.delegation_kind or "").strip()
    if kind in {"pdf", "pdf_reading", "document_reading"} and "op.mcp_pdf" in available:
        return "op.mcp_pdf"
    if kind in {"structured_data", "table_analysis", "structured_data_lookup"} and "op.mcp_structured_data" in available:
        return "op.mcp_structured_data"
    if kind in {"retrieval", "evidence_lookup", "knowledge_retrieval", "knowledge_search"} and "op.mcp_retrieval" in available:
        return "op.mcp_retrieval"
    if kind in {"web", "web_research", "external_web_lookup", "current_information_lookup", "official_source_lookup"} and "op.web_search" in available:
        return "op.web_search"
    if kind in {"codebase_search", "local_search", "workspace_search", "file_search"} and "op.search_text" in available:
        return "op.search_text"
    if kind in {"memory_search", "memory_lookup", "memory_recall"} and "op.memory_read" in available:
        return "op.memory_read"
    for operation_id in ("op.mcp_pdf", "op.mcp_structured_data", "op.mcp_retrieval", "op.web_search"):
        if operation_id in available:
            return operation_id
    return ""


def _mcp_route_for_operation(operation_id: str) -> str:
    return {
        "op.mcp_pdf": "pdf",
        "op.mcp_structured_data": "structured_data",
        "op.mcp_retrieval": "retrieval",
    }.get(str(operation_id or "").strip(), "")


def _run_web_search_sync(*, root_dir: Path, query: str, topic: str, time_range: str, max_results: int) -> dict[str, Any]:
    script_path = Path(root_dir) / "capability_system" / "units" / "tools" / "tavily_search.py"
    if not script_path.exists() and (Path(root_dir) / "backend" / "capability_system" / "units" / "tools" / "tavily_search.py").exists():
        script_path = Path(root_dir) / "backend" / "capability_system" / "units" / "tools" / "tavily_search.py"
    if not script_path.exists():
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_script_not_found"}
    script_path = script_path.resolve()
    command = [
        sys.executable,
        str(script_path),
        "--query",
        query,
        "--topic",
        topic if topic in {"general", "news", "finance"} else "general",
        "--max-results",
        str(max(1, min(int(max_results or 5), 10))),
    ]
    if time_range in {"day", "week", "month", "year", "d", "w", "m", "y"}:
        command.extend(["--time-range", time_range])
    try:
        completed = subprocess.run(
            command,
            cwd=str(script_path.parents[3]),
            capture_output=True,
            timeout=25,
            check=False,
            **utf8_subprocess_text_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_timeout"}
    raw = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not raw and stderr:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_process_error", "details": stderr[:1000]}
    if not raw:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_empty_output"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_invalid_json", "raw": raw[:1000], "stderr": stderr[:1000]}
    if "query" not in payload:
        payload["query"] = query
    if "topic" not in payload:
        payload["topic"] = topic
    return dict(payload)


def _web_research_summary(*, web_payload: dict[str, Any], packet: Any) -> str:
    query = str(web_payload.get("query") or dict(getattr(packet, "method", {}) or {}).get("query") or "").strip()
    lines = [f"网页研究完成：{query}" if query else "网页研究完成。"]
    if getattr(packet, "facts", ()):
        lines.append("可用事实证据：")
        for fact in list(packet.facts)[:3]:
            lines.append(f"- {fact.claim}")
    if getattr(packet, "unknowns", ()):
        lines.append("未知与限制：")
        for unknown in list(packet.unknowns)[:2]:
            lines.append(f"- {unknown.description}")
    return "\n".join(lines).strip()


def _build_mcp_request(request: AgentDelegationRequest, *, mcp_route: str, agent_id: str) -> MCPRequest:
    payload = dict(request.input_payload or {})
    query = str(payload.get("query") or request.instruction or "").strip()
    path = _primary_payload_path(payload)
    bindings: dict[str, Any] = {}
    constraints: dict[str, Any] = dict(payload)
    constraints = _normalize_followup_constraints(constraints)
    if mcp_route == "pdf" and path:
        bindings["active_pdf"] = path
        constraints.setdefault("path", path)
        constraints.setdefault("mode", str(payload.get("mode") or payload.get("extract_mode") or "document"))
    if mcp_route == "structured_data" and path:
        bindings["active_dataset"] = path
        constraints.setdefault("path", path)
    return MCPRequest(
        request_id=f"mcpreq:delegation:{uuid.uuid4().hex[:10]}",
        session_id=request.session_id,
        query=query,
        mcp_route=mcp_route,
        task_frame={"delegation_request_id": request.request_id, "target_agent_id": request.target_agent_id},
        bindings=bindings,
        constraints=constraints,
        owner_task_id=request.task_run_id,
        arbitration_reason=f"agent_delegation:{request.delegation_kind}",
        agent_id=agent_id,
        message_id=f"{request.request_id}:{mcp_route}",
    )


def _primary_payload_path(payload: dict[str, Any]) -> str:
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


def _normalize_followup_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(constraints or {})
    semantic_hints = dict(normalized.get("semantic_hints") or {})
    subset_labels = [
        str(item or "").strip()
        for item in list(normalized.get("subset_labels") or [])
        if str(item or "").strip()
    ]
    subset_filter_column = str(normalized.get("subset_filter_column") or "").strip()
    if subset_labels:
        semantic_hints.setdefault("subset_allowed_values", subset_labels)
    if subset_filter_column:
        semantic_hints.setdefault("subset_filter_column", subset_filter_column)
    if semantic_hints:
        normalized["semantic_hints"] = semantic_hints
    return normalized
