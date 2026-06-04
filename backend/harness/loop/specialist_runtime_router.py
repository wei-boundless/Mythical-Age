from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capability_system.capabilities.codebase_search import CodebaseSearchCapability, normalize_codebase_search_config
from capability_system.capabilities.deepsearch import DeepSearchCapability, normalize_runtime_config


@dataclass(frozen=True, slots=True)
class SpecialistCapabilityRequest:
    request_id: str
    task_run_id: str
    session_id: str
    parent_agent_run_ref: str
    source_agent_id: str
    target_agent_id: str
    subagent_task_kind: str
    instruction: str
    input_payload: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpecialistRuntimeExecution:
    handled: bool
    runtime_kind: str = ""
    route: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class SpecialistRuntimeRouter:
    """Routes specialist profiles to capability bodies without owning lifecycle state."""

    def __init__(
        self,
        backend_dir: Path,
        *,
        model_runtime: Any | None = None,
        deepsearch_capability: Any | None = None,
        codebase_search_capability: Any | None = None,
    ) -> None:
        self.backend_dir = Path(backend_dir)
        self.model_runtime = model_runtime
        self.deepsearch_capability = deepsearch_capability
        self.codebase_search_capability = codebase_search_capability

    async def try_run(
        self,
        *,
        task_run: Any,
        agent_run: Any,
        profile: Any,
        contract: dict[str, Any],
    ) -> SpecialistRuntimeExecution:
        runtime_config = _runtime_config(profile)
        runtime_kind = _runtime_kind(runtime_config)
        if runtime_kind == "search_agent":
            return await self._run_deepsearch(
                task_run=task_run,
                agent_run=agent_run,
                profile=profile,
                contract=contract,
                runtime_config=runtime_config,
            )
        if runtime_kind == "codebase_search_agent":
            return await self._run_codebase_search(
                task_run=task_run,
                agent_run=agent_run,
                profile=profile,
                contract=contract,
                runtime_config=runtime_config,
            )
        return SpecialistRuntimeExecution(handled=False, runtime_kind=runtime_kind)

    async def _run_deepsearch(
        self,
        *,
        task_run: Any,
        agent_run: Any,
        profile: Any,
        contract: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> SpecialistRuntimeExecution:
        config = normalize_runtime_config(runtime_config).search
        if config is None:
            return _failed_execution(
                runtime_kind="search_agent",
                route="deepsearch",
                summary="Search Agent 缺少 DeepSearch 搜索配置。",
                limitations=["deepsearch_config_missing"],
            )
        capability = self.deepsearch_capability or DeepSearchCapability(self.backend_dir, model_runtime=self.model_runtime)
        request = _request_from_task_run(
            task_run=task_run,
            agent_run=agent_run,
            profile=profile,
            contract=contract,
            route="deepsearch",
        )
        try:
            result = await capability.run(request=request, agent=agent_run, profile=profile, config=config)
        except Exception as exc:
            return _failed_execution(
                runtime_kind="search_agent",
                route="deepsearch",
                summary="DeepSearch 能力执行失败。",
                limitations=[f"deepsearch_exception:{exc.__class__.__name__}"],
                diagnostics={"error": str(exc)},
            )
        return SpecialistRuntimeExecution(
            handled=True,
            runtime_kind="search_agent",
            route="deepsearch",
            result=dict(result or {}),
            diagnostics={"authority": "harness.loop.specialist_runtime_router", "route": "deepsearch"},
        )

    async def _run_codebase_search(
        self,
        *,
        task_run: Any,
        agent_run: Any,
        profile: Any,
        contract: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> SpecialistRuntimeExecution:
        config = normalize_codebase_search_config(runtime_config)
        capability = self.codebase_search_capability or CodebaseSearchCapability(self.backend_dir)
        request = _request_from_task_run(
            task_run=task_run,
            agent_run=agent_run,
            profile=profile,
            contract=contract,
            route="codebase_search",
        )
        try:
            result = await capability.run(request=request, agent=agent_run, profile=profile, config=config)
        except Exception as exc:
            return _failed_execution(
                runtime_kind="codebase_search_agent",
                route="codebase_search",
                summary="Codebase Search 能力执行失败。",
                limitations=[f"codebase_search_exception:{exc.__class__.__name__}"],
                diagnostics={"error": str(exc)},
            )
        return SpecialistRuntimeExecution(
            handled=True,
            runtime_kind="codebase_search_agent",
            route="codebase_search",
            result=dict(result or {}),
            diagnostics={"authority": "harness.loop.specialist_runtime_router", "route": "codebase_search"},
        )


def _request_from_task_run(
    *,
    task_run: Any,
    agent_run: Any,
    profile: Any,
    contract: dict[str, Any],
    route: str,
) -> SpecialistCapabilityRequest:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    subagent = dict(diagnostics.get("subagent_control") or {})
    origin = dict(diagnostics.get("origin") or {})
    instruction = _instruction(contract=contract, subagent=subagent)
    payload = _input_payload(contract=contract, subagent=subagent, instruction=instruction)
    payload.setdefault("route", route)
    return SpecialistCapabilityRequest(
        request_id=f"specialist:{getattr(task_run, 'task_run_id', '')}",
        task_run_id=str(getattr(task_run, "task_run_id", "") or ""),
        session_id=str(getattr(task_run, "session_id", "") or ""),
        parent_agent_run_ref=str(subagent.get("parent_agent_run_ref") or origin.get("parent_agent_run_ref") or getattr(agent_run, "parent_agent_run_ref", "") or ""),
        source_agent_id=str(origin.get("source_agent_id") or "agent:0"),
        target_agent_id=str(getattr(profile, "agent_id", "") or getattr(task_run, "agent_id", "") or getattr(agent_run, "agent_id", "") or ""),
        subagent_task_kind=str(_profile_metadata(profile).get("subagent_task_kind") or subagent.get("subagent_task_kind") or route),
        instruction=instruction,
        input_payload=payload,
        diagnostics={
            "origin": origin,
            "subagent_control": subagent,
            "authority": "harness.loop.specialist_capability_request",
        },
    )


def _runtime_config(profile: Any) -> dict[str, Any]:
    metadata = _profile_metadata(profile)
    value = metadata.get("runtime_config")
    return dict(value) if isinstance(value, dict) else {}


def _runtime_kind(runtime_config: dict[str, Any]) -> str:
    return str(dict(runtime_config or {}).get("runtime_kind") or "").strip()


def _profile_metadata(profile: Any) -> dict[str, Any]:
    value = getattr(profile, "metadata", None)
    return dict(value) if isinstance(value, dict) else {}


def _instruction(*, contract: dict[str, Any], subagent: dict[str, Any]) -> str:
    for value in (
        subagent.get("instructions"),
        subagent.get("goal"),
        contract.get("instructions"),
        contract.get("task_run_goal"),
        contract.get("objective"),
        contract.get("user_visible_goal"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _input_payload(*, contract: dict[str, Any], subagent: dict[str, Any], instruction: str) -> dict[str, Any]:
    raw = subagent.get("input_payload")
    payload = dict(raw) if isinstance(raw, dict) else {}
    goal = str(subagent.get("goal") or contract.get("task_run_goal") or contract.get("objective") or instruction or "").strip()
    if goal:
        payload.setdefault("query", goal)
        payload.setdefault("question", goal)
    if instruction:
        payload.setdefault("instructions", instruction)
    context_refs = [str(item) for item in list(subagent.get("context_refs") or contract.get("context_refs") or []) if str(item)]
    expected_outputs = [str(item) for item in list(subagent.get("expected_outputs") or contract.get("expected_outputs") or []) if str(item)]
    if context_refs:
        payload["context_refs"] = context_refs
    if expected_outputs:
        payload["expected_outputs"] = expected_outputs
    return payload


def _failed_execution(
    *,
    runtime_kind: str,
    route: str,
    summary: str,
    limitations: list[str],
    diagnostics: dict[str, Any] | None = None,
) -> SpecialistRuntimeExecution:
    return SpecialistRuntimeExecution(
        handled=True,
        runtime_kind=runtime_kind,
        route=route,
        result={
            "status": "failed",
            "summary": summary,
            "answer_candidate": summary,
            "artifact_refs": [],
            "evidence_refs": [],
            "limitations": list(limitations),
            "diagnostics": {
                "authority": "harness.loop.specialist_runtime_router",
                "route": route,
                **dict(diagnostics or {}),
            },
        },
        diagnostics={"authority": "harness.loop.specialist_runtime_router", "route": route},
    )
