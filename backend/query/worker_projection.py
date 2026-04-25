from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from query.context_models import MainContextState, TaskSummaryRef
from query.worker_models import CanonicalResult, WorkerResult


@dataclass(frozen=True, slots=True)
class WorkerProjection:
    main_context: MainContextState
    task_summary_refs: list[TaskSummaryRef] = field(default_factory=list)
    candidate_refs: list[str] = field(default_factory=list)
    object_handle_ids: list[str] = field(default_factory=list)
    result_handle_ids: list[str] = field(default_factory=list)
    binding_owner_task_id: str = ""
    degraded_reason_typed: str = ""
    memory_policy: str = "session_context_only"


class WorkerProjectionAdapter:
    def project_done_event(
        self,
        *,
        query: str,
        canonical_result: CanonicalResult,
        worker_result: WorkerResult | None,
        previous_main_context: MainContextState | Any,
    ) -> WorkerProjection:
        main_context = self._project_main_context(
            query=query,
            canonical_result=canonical_result,
            previous_main_context=previous_main_context,
        )
        task_summary_refs = self._project_task_summary_refs(
            query=query,
            canonical_result=canonical_result,
        )
        return WorkerProjection(
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            candidate_refs=[
                str(candidate.candidate_id)
                for candidate in list(getattr(worker_result, "binding_candidates", []) or [])
                if str(candidate.candidate_id or "").strip()
            ],
            object_handle_ids=list(canonical_result.object_handle_ids or []),
            result_handle_ids=list(canonical_result.result_handle_ids or []),
            binding_owner_task_id=str(
                getattr(worker_result, "binding_owner_task_id", "")
                or getattr(canonical_result, "diagnostics", {}).get("binding_owner_task_id", "")
                or ""
            ).strip(),
            degraded_reason_typed=str(
                canonical_result.degraded_reason_typed or canonical_result.degraded_reason or ""
            ).strip(),
            memory_policy=self._memory_policy(canonical_result),
        )

    def _project_main_context(
        self,
        *,
        query: str,
        canonical_result: CanonicalResult,
        previous_main_context: MainContextState | Any,
    ) -> MainContextState:
        projected = self._copy_main_context(previous_main_context, fallback_goal=query)
        bindings = dict(canonical_result.bindings or {})
        active_dataset = str(bindings.get("active_dataset", "") or "").strip()
        active_pdf = str(bindings.get("active_pdf", "") or "").strip()
        active_table = str(bindings.get("active_table", "") or "").strip()
        if active_dataset:
            self._apply_binding(
                projected,
                key="active_dataset",
                value=active_dataset,
                source_kind="dataset",
                active_work_item="structured_data",
            )
        elif active_pdf:
            self._apply_binding(
                projected,
                key="active_pdf",
                value=active_pdf,
                source_kind="pdf",
                active_work_item="pdf",
            )
            pages = bindings.get("active_pdf_pages")
            if isinstance(pages, list):
                normalized_pages = [int(page) for page in pages if _positive_int(page) is not None]
                if normalized_pages:
                    projected.active_constraints["active_pdf_pages"] = normalized_pages
            mode = str(bindings.get("active_pdf_mode", "") or "").strip()
            if mode:
                projected.active_constraints["active_pdf_mode"] = mode
            section = str(bindings.get("active_pdf_section", "") or "").strip()
            if section:
                projected.active_constraints["active_pdf_section"] = section
            section_key = str(bindings.get("active_pdf_section_key", "") or "").strip()
            if section_key:
                projected.active_constraints["active_pdf_section_key"] = section_key
        elif active_table:
            self._apply_binding(
                projected,
                key="active_table",
                value=active_table,
                source_kind="table",
                active_work_item="structured_data",
            )
        if active_table:
            projected.active_constraints["active_table"] = active_table
        object_handle_ids = [str(item).strip() for item in list(canonical_result.object_handle_ids or []) if str(item).strip()]
        result_handle_ids = [str(item).strip() for item in list(canonical_result.result_handle_ids or []) if str(item).strip()]
        if object_handle_ids:
            projected.active_object_handle_id = object_handle_ids[0]
        if result_handle_ids:
            projected.active_result_handle_id = result_handle_ids[0]
            projected.followup_mode = "task_ref"
            synthetic_task_id = f"{canonical_result.result_kind or 'worker'}:{_slug(query)}"
            projected.followup_target_task_id = projected.followup_target_task_id or synthetic_task_id
            projected.followup_target_task_ids = list(projected.followup_target_task_ids or [synthetic_task_id])
        subset_handle_id = str(dict(canonical_result.presentation_hints or {}).get("subset_handle_id", "") or "").strip()
        if subset_handle_id:
            projected.active_subset_handle_id = subset_handle_id
        return projected

    def _project_task_summary_refs(
        self,
        *,
        query: str,
        canonical_result: CanonicalResult,
    ) -> list[TaskSummaryRef]:
        if not canonical_result.ok or canonical_result.projection_policy != "persist_canonical":
            return []
        summary = " ".join(str(canonical_result.answer or "").split()).strip()
        if not summary:
            return []
        bindings = dict(canonical_result.bindings or {})
        key_points: list[str] = []
        task_kind = str(canonical_result.result_kind or "worker")
        if bindings.get("active_dataset"):
            key_points.append(f"dataset={bindings['active_dataset']}")
            task_kind = "structured_data"
        if bindings.get("active_pdf"):
            key_points.append(f"pdf={bindings['active_pdf']}")
            if bindings.get("active_pdf_mode"):
                key_points.append(f"pdf_mode={bindings['active_pdf_mode']}")
            if bindings.get("active_pdf_section"):
                key_points.append(f"pdf_section={bindings['active_pdf_section']}")
            pages = bindings.get("active_pdf_pages")
            if isinstance(pages, list) and pages:
                key_points.append("pdf_pages=" + ",".join(str(page) for page in pages[:8]))
            task_kind = "pdf"
        if bindings.get("active_table"):
            key_points.append(f"table={bindings['active_table']}")
            task_kind = "structured_data"
        key_points.extend(f"artifact={item}" for item in canonical_result.artifact_refs[:3] if str(item).strip())
        return [
            TaskSummaryRef(
                task_id=f"{canonical_result.result_kind or 'worker'}:{_slug(query)}",
                query=str(query or "").strip(),
                summary=summary[:280],
                task_kind=task_kind,
                key_points=key_points,
            )
        ]

    def _copy_main_context(self, source: MainContextState | Any, *, fallback_goal: str) -> MainContextState:
        if isinstance(source, MainContextState):
            return MainContextState(
                active_goal=source.active_goal or fallback_goal,
                active_work_item=source.active_work_item,
                active_binding_identity=source.active_binding_identity,
                active_object_handle_id=source.active_object_handle_id,
                active_result_handle_id=source.active_result_handle_id,
                active_subset_handle_id=source.active_subset_handle_id,
                followup_mode=source.followup_mode,
                followup_resolution_source=source.followup_resolution_source,
                followup_target_task_id=source.followup_target_task_id,
                followup_target_task_ids=list(source.followup_target_task_ids),
                followup_binding_key=source.followup_binding_key,
                followup_binding_identity=source.followup_binding_identity,
                followup_binding_owner_task_id=source.followup_binding_owner_task_id,
                active_constraints=dict(source.active_constraints),
                latest_correction=source.latest_correction,
                next_step=source.next_step,
            )
        return MainContextState(active_goal=fallback_goal)

    def _apply_binding(
        self,
        context: MainContextState,
        *,
        key: str,
        value: str,
        source_kind: str,
        active_work_item: str,
    ) -> None:
        identity = value.replace("\\", "/").strip().lower()
        context.active_work_item = context.active_work_item or active_work_item
        context.active_binding_identity = identity
        context.followup_binding_key = context.followup_binding_key or key
        context.followup_binding_identity = context.followup_binding_identity or identity
        context.active_constraints[key] = value
        context.active_constraints["active_binding_identity"] = identity
        context.active_constraints.setdefault("source_kind", source_kind)

    def _memory_policy(self, canonical_result: CanonicalResult) -> str:
        if not canonical_result.ok:
            return "do_not_persist"
        if canonical_result.projection_policy != "persist_canonical":
            return "do_not_persist"
        return "session_context_only"


def _slug(value: str) -> str:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", str(value or "").lower()).strip("-")
    return compact[:48] or "main"


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
