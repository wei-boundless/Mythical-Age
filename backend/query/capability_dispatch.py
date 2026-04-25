from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from skill_system import SkillDefinition
from tools.contracts import ToolScope
from query.worker_models import WorkerRequest


@dataclass(frozen=True, slots=True)
class PromptExposurePlan:
    """Model-visible exposure plan.

    This deliberately carries prompt views and tool schema names only. Runtime
    policy, permission decisions, and raw tool outputs must not cross this
    boundary.
    """

    active_skill_name: str = ""
    skill_prompt_block: str = ""
    tool_schema_names: tuple[str, ...] = ()
    exposure_policy: str = "model_visible_only"
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolCandidate:
    name: str
    satisfies_scope: bool = True
    satisfies_capability: bool = True
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolInvocationRequest:
    tool_name: str
    capability: str = ""
    route: str = "tool"
    unresolved_input: dict[str, Any] = field(default_factory=dict)
    anchors: dict[str, Any] = field(default_factory=dict)
    contract_status: str = "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DispatchPlan:
    route: str
    skill_policy: SkillDefinition | None = None
    effective_tool_scope: ToolScope = field(default_factory=ToolScope)
    tool_candidates: tuple[ToolCandidate, ...] = ()
    selected_tool_request: ToolInvocationRequest | None = None
    selected_worker_request: WorkerRequest | None = None
    worker_route: str = ""
    prompt_exposure: PromptExposurePlan = field(default_factory=PromptExposurePlan)
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.skill_policy is not None:
            payload["skill_policy"] = {
                "name": self.skill_policy.name,
                "title": self.skill_policy.title,
            }
        return payload


class CapabilityDispatchScheduler:
    """Single dispatch pass for skills/tools.

    The initial implementation is intentionally behavior-compatible: it records
    the dispatch decision without changing the planner's existing route. Later
    phases can move selection authority here once tests are in place.
    """

    def resolve(
        self,
        *,
        task_frame: Any,
        active_skill: SkillDefinition | None,
        tool_registry: Any,
    ) -> DispatchPlan:
        route = str(getattr(task_frame, "route", "") or "rag")
        tool_scope = active_skill.tool_scope() if active_skill is not None else ToolScope(source="skill", reason="no_active_skill")
        candidate_names = self._candidate_names(task_frame, active_skill=active_skill, tool_registry=tool_registry)
        candidates = tuple(
            ToolCandidate(
                name=name,
                satisfies_scope=tool_scope.allows(name),
                satisfies_capability=True,
                reasons=("scope_satisfied",) if tool_scope.allows(name) else ("scope_filtered",),
            )
            for name in candidate_names
        )
        selected_worker_request = self._selected_worker_request(task_frame)
        selected_request = None if selected_worker_request is not None else self._selected_tool_request(task_frame, candidates)
        prompt_exposure = self._prompt_exposure(active_skill=active_skill, candidates=candidates)
        return DispatchPlan(
            route=route,
            skill_policy=active_skill,
            effective_tool_scope=tool_scope,
            tool_candidates=candidates,
            selected_tool_request=selected_request,
            selected_worker_request=selected_worker_request,
            worker_route=str(getattr(selected_worker_request, "worker_route", "") or ""),
            prompt_exposure=prompt_exposure,
            reasons=self._reasons(
                task_frame,
                active_skill=active_skill,
                selected_request=selected_request,
                selected_worker_request=selected_worker_request,
            ),
        )

    def _candidate_names(
        self,
        task_frame: Any,
        *,
        active_skill: SkillDefinition | None,
        tool_registry: Any,
    ) -> list[str]:
        existing = [str(item).strip() for item in list(getattr(task_frame, "candidate_tools", []) or []) if str(item).strip()]
        if existing:
            return existing
        resolver = getattr(tool_registry, "resolve_candidate_names", None)
        if callable(resolver):
            resolved = list(
                resolver(
                    capability_requests=list(getattr(task_frame, "capability_requests", []) or []),
                    route=str(getattr(task_frame, "route", "") or ""),
                    modality=str(getattr(task_frame, "modality", "") or ""),
                    safe_only=True,
                )
            )
            if resolved:
                return resolved
        selected = str(getattr(task_frame, "tool_name", "") or "").strip()
        if selected:
            return [selected]
        return []

    def _selected_tool_request(
        self,
        task_frame: Any,
        candidates: tuple[ToolCandidate, ...],
    ) -> ToolInvocationRequest | None:
        tool_name = str(getattr(task_frame, "tool_name", "") or "").strip()
        if not tool_name:
            return None
        return ToolInvocationRequest(
            tool_name=tool_name,
            capability=",".join(str(item) for item in list(getattr(task_frame, "capability_requests", []) or [])),
            route=str(getattr(task_frame, "route", "") or "tool"),
            unresolved_input=dict(getattr(task_frame, "tool_input", {}) or {}),
            anchors=dict(getattr(task_frame, "structural_signals", {}) or {}),
            contract_status="selected_existing_tool",
        )

    def _selected_worker_request(self, task_frame: Any) -> WorkerRequest | None:
        route = str(getattr(task_frame, "route", "") or "").strip()
        execution_posture = str(getattr(task_frame, "execution_posture", "") or "").strip()
        tool_name = str(getattr(task_frame, "tool_name", "") or "").strip()
        if route == "tool" and tool_name == "pdf_analysis":
            return self._selected_pdf_worker_request(task_frame)
        if route != "rag" or execution_posture not in {"", "direct_rag"}:
            return None
        if bool(getattr(task_frame, "should_skip_rag", False)):
            return None
        capabilities = {str(item or "").strip() for item in list(getattr(task_frame, "capability_requests", []) or [])}
        if "knowledge_lookup" not in capabilities and "faq" not in capabilities:
            return None
        query = str(dict(getattr(task_frame, "tool_input", {}) or {}).get("query", "") or "").strip()
        if not query:
            query = str(getattr(task_frame, "message", "") or "").strip()
        if not query:
            query = str(getattr(task_frame, "target_object", "") or "").strip()
        return WorkerRequest(
            request_id="worker:retrieval:main",
            query=query,
            worker_route="retrieval",
            task_frame={
                "intent": str(getattr(task_frame, "intent", "") or ""),
                "source_kind": str(getattr(task_frame, "source_kind", "") or ""),
                "task_kind": str(getattr(task_frame, "task_kind", "") or ""),
                "modality": str(getattr(task_frame, "modality", "") or ""),
                "route": route,
                "capability_requests": list(getattr(task_frame, "capability_requests", []) or []),
            },
            constraints=dict(getattr(task_frame, "structural_signals", {}) or {}),
        )

    def _selected_pdf_worker_request(self, task_frame: Any) -> WorkerRequest | None:
        tool_input = dict(getattr(task_frame, "tool_input", {}) or {})
        query = str(tool_input.get("query", "") or getattr(task_frame, "target_object", "") or "").strip()
        path = str(tool_input.get("path", "") or "").strip()
        mode = str(tool_input.get("mode", "") or "").strip()
        constraints = {
            key: value
            for key, value in {
                "path": path,
                "active_pdf": path,
                "mode": mode,
                "page": tool_input.get("page"),
                "section": tool_input.get("section"),
                "max_chunks": tool_input.get("max_chunks"),
            }.items()
            if value not in (None, "")
        }
        return WorkerRequest(
            request_id="worker:pdf:main",
            query=query,
            worker_route="pdf",
            task_frame={
                "intent": str(getattr(task_frame, "intent", "") or ""),
                "source_kind": str(getattr(task_frame, "source_kind", "") or ""),
                "task_kind": str(getattr(task_frame, "task_kind", "") or ""),
                "modality": str(getattr(task_frame, "modality", "") or ""),
                "route": str(getattr(task_frame, "route", "") or ""),
                "capability_requests": list(getattr(task_frame, "capability_requests", []) or []),
            },
            bindings={"active_pdf": path} if path else {},
            constraints=constraints,
        )

    def _prompt_exposure(
        self,
        *,
        active_skill: SkillDefinition | None,
        candidates: tuple[ToolCandidate, ...],
    ) -> PromptExposurePlan:
        if active_skill is None:
            return PromptExposurePlan(
                tool_schema_names=_model_visible_tool_schema_names(candidates),
                reasons=("no_active_skill",),
            )
        return PromptExposurePlan(
            active_skill_name=active_skill.name,
            skill_prompt_block=active_skill.render_prompt_block(),
            tool_schema_names=_model_visible_tool_schema_names(candidates),
            reasons=("skill_prompt_view_only",),
        )

    def _reasons(
        self,
        task_frame: Any,
        *,
        active_skill: SkillDefinition | None,
        selected_request: ToolInvocationRequest | None,
        selected_worker_request: WorkerRequest | None,
    ) -> tuple[str, ...]:
        reasons = ["dispatch_shadow_recorded"]
        if active_skill is not None:
            reasons.append("skill_policy_attached")
        if selected_request is not None:
            reasons.append("tool_request_preserved")
        if selected_worker_request is not None:
            reasons.append("worker_request_selected")
        if str(getattr(task_frame, "route", "") or "") != "tool":
            reasons.append("non_tool_route")
        return tuple(reasons)


def _model_visible_tool_schema_names(candidates: tuple[ToolCandidate, ...]) -> tuple[str, ...]:
    return tuple(candidate.name for candidate in candidates if candidate.name not in {"search_knowledge"})
