from __future__ import annotations

from pathlib import Path
from typing import Any

from .compaction import replacement_history_ref
from .execution_state_projector import ExecutionStateProjector
from .history_projector import HistoryProjector
from .models import DynamicContextInput, DynamicContextProjection, VolatileSectionReport, drop_empty, estimate_chars
from .observation_projector import ObservationProjector
from .replacement_store import MemoryReplacementStore, ReplacementStore
from .runtime_delta_projector import RuntimeDeltaProjector
from .token_budget import build_budget_report
from .tool_result_projector import ToolResultProjector
from .work_history_projector import WorkHistoryProjector


class DynamicContextManager:
    def __init__(self, *, base_dir: Path | None = None, replacement_store: ReplacementStore | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.replacement_store = replacement_store or MemoryReplacementStore()
        self._explicit_replacement_store = replacement_store is not None
        self.execution_state_projector = ExecutionStateProjector()
        self.work_history_projector = WorkHistoryProjector()
        self.history_projector = HistoryProjector()
        self.runtime_delta_projector = RuntimeDeltaProjector()

    def project(self, request: DynamicContextInput) -> DynamicContextProjection:
        replacement_store, storage_root = self._replacement_store_for_request(request)
        tool_result_projector = ToolResultProjector(root_dir=storage_root, replacement_store=replacement_store)
        observation_projector = ObservationProjector(
            replacement_store=replacement_store,
            tool_result_projector=tool_result_projector,
        )
        baseline_refs, runtime_delta, envelope_projection = self.runtime_delta_projector.project(
            runtime_assembly=dict(request.runtime_assembly or {}),
            runtime_envelope=dict(request.runtime_envelope or {}),
            projection_policy=dict(request.projection_policy or {}),
        )
        tool_results, tool_records = tool_result_projector.project_many(
            request.tool_results,
            task_run_id=request.task_run_id,
            projection_policy=request.projection_policy,
        )
        observation_projection, observation_refs, observation_artifacts, observation_records = observation_projector.project(
            request.observations,
            task_run_id=request.task_run_id,
            projection_policy=request.projection_policy,
        )
        execution_projection = self.execution_state_projector.project(
            request.execution_state,
            task_run=request.task_run,
        )
        history_projection = self.history_projector.project(
            request.history,
            current_user_message=request.current_user_message,
            projection_policy=request.projection_policy,
        )
        work_history_projection = self.work_history_projector.project(
            request.work_rollout,
            projection_policy=request.projection_policy,
        )
        volatile_request = self._volatile_request_projection(
            request,
            envelope_projection=envelope_projection,
            history_projection=history_projection,
            observation_projection=observation_projection,
        )
        volatile_state = self._volatile_state_projection(
            request,
            envelope_projection=envelope_projection,
            execution_projection=execution_projection,
            observation_projection=observation_projection,
            work_history_projection=work_history_projection,
        )
        dynamic_payload = dict(runtime_delta)
        budget_report = build_budget_report(
            invocation_kind=request.invocation_kind,
            projection_policy=request.projection_policy,
            volatile_payload=volatile_state or volatile_request,
            dynamic_payload=dynamic_payload,
        )
        context_refs = [
            str(baseline_refs.get("runtime_baseline_hash") or ""),
            replacement_history_ref(
                session_id=request.session_id,
                task_run_id=request.task_run_id,
                history_projection=history_projection,
            )
            if history_projection.get("omitted_history")
            else "",
        ]
        artifact_refs = _dedupe_artifacts(
            [
                *observation_artifacts,
                *list(work_history_projection.get("active_artifacts") or []),
            ]
        )
        return DynamicContextProjection(
            stable_runtime_baseline_refs=baseline_refs,
            dynamic_runtime_delta=runtime_delta,
            dynamic_runtime_projection=dynamic_payload,
            volatile_request_projection=volatile_request,
            volatile_state_projection=volatile_state,
            tool_result_refs=tuple(str(item.get("tool_result_ref") or item.get("replacement_ref") or "") for item in tool_results if item),
            observation_refs=tuple(ref for ref in observation_refs if ref),
            context_refs=tuple(ref for ref in context_refs if ref),
            artifact_refs=tuple(_artifact_ref_value(item) for item in artifact_refs if _artifact_ref_value(item)),
            budget_report=budget_report,
            section_reports=self._section_reports(
                request,
                dynamic_payload=dynamic_payload,
                volatile_request=volatile_request,
                volatile_state=volatile_state,
                tool_record_count=len(tool_records),
                observation_record_count=len(observation_records),
            ),
            diagnostics=drop_empty(
                {
                    "tool_projection_replacement_count": len(tool_records),
                    "observation_projection_replacement_count": len(observation_records),
                }
            ),
        )

    def _volatile_request_projection(
        self,
        request: DynamicContextInput,
        *,
        envelope_projection: dict[str, Any],
        history_projection: dict[str, Any],
        observation_projection: dict[str, Any],
    ) -> dict[str, Any]:
        if request.invocation_kind == "task_execution":
            return {}
        payload = {
            "runtime_envelope": envelope_projection,
            "turn_id": request.turn_id,
            "history": history_projection,
            "user_message": str(request.current_user_message or ""),
        }
        if request.invocation_kind == "tool_observation_followup":
            payload["observations"] = observation_projection
        return drop_empty(payload)

    def _volatile_state_projection(
        self,
        request: DynamicContextInput,
        *,
        envelope_projection: dict[str, Any],
        execution_projection: dict[str, Any],
        observation_projection: dict[str, Any],
        work_history_projection: dict[str, Any],
    ) -> dict[str, Any]:
        if request.invocation_kind != "task_execution":
            return {}
        payload = {
            "execution_state": execution_projection,
            "observations": observation_projection,
        }
        if bool(dict(request.projection_policy or {}).get("include_task_run_context", True)):
            payload["runtime_envelope"] = envelope_projection
            payload["task_run_state"] = self.execution_state_projector.task_run_state(request.task_run)
            payload["work_history"] = work_history_projection
        return drop_empty(payload)

    def _section_reports(
        self,
        request: DynamicContextInput,
        *,
        dynamic_payload: dict[str, Any],
        volatile_request: dict[str, Any],
        volatile_state: dict[str, Any],
        tool_record_count: int,
        observation_record_count: int,
    ) -> tuple[VolatileSectionReport, ...]:
        reports = [
            VolatileSectionReport(
                section_id=f"dynamic_context:{request.invocation_kind}:runtime_delta",
                source="runtime_delta",
                volatility_reason="runtime assembly, authorization, or envelope can vary by invocation",
                input_chars=estimate_chars({"runtime_assembly": request.runtime_assembly, "runtime_envelope": request.runtime_envelope}),
                output_chars=estimate_chars(dynamic_payload),
                projection_strategy="runtime_baseline_refs_plus_delta",
                refs=(),
            )
        ]
        if volatile_request:
            reports.append(
                VolatileSectionReport(
                    section_id=f"dynamic_context:{request.invocation_kind}:current_request",
                    source="current_request",
                    volatility_reason="current user message and recent history are invocation-local",
                    input_chars=estimate_chars({"history": request.history, "user_message": request.current_user_message, "observations": request.observations}),
                    output_chars=estimate_chars(volatile_request),
                    projection_strategy="history_recent_turns_and_current_request",
                    refs=(),
                )
            )
        if volatile_state:
            reports.append(
                VolatileSectionReport(
                    section_id=f"dynamic_context:{request.invocation_kind}:task_state",
                    source="execution_state",
                    volatility_reason="task execution state, observations, and work progress change each step",
                    input_chars=estimate_chars({"execution_state": request.execution_state, "observations": request.observations, "work_rollout": request.work_rollout}),
                    output_chars=estimate_chars(volatile_state),
                    projection_strategy="white_listed_task_state_projection",
                    refs=(),
                )
            )
        if tool_record_count:
            reports.append(
                VolatileSectionReport(
                    section_id=f"dynamic_context:{request.invocation_kind}:tool_results",
                    source="tool_results",
                    volatility_reason="tool outputs are produced by current or prior runtime actions",
                    input_chars=estimate_chars(request.tool_results),
                    output_chars=0,
                    projection_strategy="tool_result_preview_ref_projection",
                    refs=(),
                )
            )
        if observation_record_count:
            reports.append(
                VolatileSectionReport(
                    section_id=f"dynamic_context:{request.invocation_kind}:observations",
                    source="observations",
                    volatility_reason="observations are runtime feedback and failure evidence",
                    input_chars=estimate_chars(request.observations),
                    output_chars=0,
                    projection_strategy="observation_failure_artifact_projection",
                    refs=(),
                )
            )
        return tuple(reports)

    def _replacement_store_for_request(self, request: DynamicContextInput) -> tuple[ReplacementStore, Path]:
        if self._explicit_replacement_store:
            return self.replacement_store, self.base_dir
        storage_root = _dynamic_context_storage_root(self.base_dir, dict(request.runtime_assembly or {}))
        if storage_root is None:
            return self.replacement_store, self.base_dir
        try:
            return ReplacementStore(storage_root), storage_root
        except Exception:
            return MemoryReplacementStore(), self.base_dir


def _dedupe_artifacts(refs: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = _artifact_ref_value(ref) or repr(sorted(ref.items()))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(dict(ref))
    return result


def _artifact_ref_value(ref: dict[str, Any]) -> str:
    return str(dict(ref or {}).get("path") or dict(ref or {}).get("src") or dict(ref or {}).get("artifact_ref") or "")


def _dynamic_context_storage_root(base_dir: Path, runtime_assembly: dict[str, Any]) -> Path | None:
    environment = dict(runtime_assembly.get("task_environment") or {})
    storage = dict(environment.get("storage_space") or {})
    for key in ("runtime_state_root", "cache_root", "environment_storage_root"):
        value = str(storage.get(key) or "").strip()
        if value:
            path = Path(value)
            return path if path.is_absolute() else Path(base_dir) / path
    return None
