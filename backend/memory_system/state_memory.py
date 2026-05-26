from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from token_accounting import count_text_tokens

from .contracts import (
    MemoryContextCandidate,
    StateMemoryRestoreCandidate,
    StateMemorySnapshot,
)
from .paths import normalize_session_id, safe_session_dir
from .storage.session_memory import SessionMemoryManager


class StateMemoryStoreAdapter:
    """Read-only adapter over the current process-state storage.

    This is the first landing layer for the new StateMemory boundary. It wraps
    existing `process_state.json` / `flow_snapshots.json` material into
    candidate-only contracts without changing the old storage format.
    """

    def __init__(self, session_root: str | Path) -> None:
        self.session_root = Path(session_root)
        self.session_root.mkdir(parents=True, exist_ok=True)

    def manager(self, session_id: str) -> SessionMemoryManager:
        return SessionMemoryManager(safe_session_dir(self.session_root, session_id))

    def load_snapshot(self, session_id: str) -> StateMemorySnapshot:
        manager = self.manager(session_id)
        state = manager.load_state()
        slots = getattr(state, "context_slots", None)
        flow_state = getattr(state, "flow_state", None)
        task_state = getattr(state, "task_state", None)
        context_slots = _object_to_dict(slots)
        active_handles = {
            key: value
            for key, value in {
                "active_object_handle_id": context_slots.get("active_object_handle_id", ""),
                "active_result_handle_id": context_slots.get("active_result_handle_id", ""),
                "active_subset_handle_id": context_slots.get("active_subset_handle_id", ""),
            }.items()
            if _clean(value)
        }
        active_constraints = _active_constraints_from_context_slots(context_slots)
        return StateMemorySnapshot(
            session_id=normalize_session_id(session_id),
            active_goal=_clean(getattr(state, "active_goal", "")),
            flow_state=_object_to_dict(flow_state),
            task_state=_object_to_dict(task_state),
            context_slots={
                **context_slots,
                **({"active_constraints": active_constraints} if active_constraints else {}),
            },
            active_handles={key: _clean(value) for key, value in active_handles.items()},
            bundle_result_refs=tuple(
                dict(item)
                for item in list(getattr(state, "bundle_result_refs", []) or [])
                if isinstance(item, dict)
            ),
            task_summary_refs=tuple(
                _task_summary_from_current_result_ref(index=index, value=value, context_slots=context_slots)
                for index, value in enumerate(list(getattr(state, "current_result_refs", []) or []), start=1)
                if _clean(value)
            ),
            operation_refs=tuple(_clean(item) for item in getattr(state, "current_result_refs", []) or [] if _clean(item)),
            key_results=tuple(_clean(item) for item in getattr(state, "key_results", []) or [] if _clean(item)),
            historical_result_refs=tuple(
                _clean(item)
                for item in getattr(state, "historical_result_refs", []) or []
                if _clean(item)
            ),
            next_step=tuple(_clean(item) for item in getattr(state, "next_step", []) or [] if _clean(item)),
            updated_at=_clean(getattr(state, "updated_at", "")),
            source="memory_system.storage.process_state",
        )

    def restore_candidates(self, session_id: str) -> tuple[StateMemoryRestoreCandidate, ...]:
        snapshot = self.load_snapshot(session_id)
        return self.restore_candidates_from_snapshot(snapshot)

    def restore_candidates_from_snapshot(
        self,
        snapshot: StateMemorySnapshot,
    ) -> tuple[StateMemoryRestoreCandidate, ...]:
        candidates: list[StateMemoryRestoreCandidate] = []
        slots = dict(snapshot.context_slots)

        for key, owner_key in (
            ("committed_pdf", "committed_pdf_owner_task_id"),
            ("committed_dataset", "committed_dataset_owner_task_id"),
            ("active_pdf", "active_binding_owner_task_id"),
            ("active_dataset", "active_binding_owner_task_id"),
            ("active_entity", "active_binding_owner_task_id"),
            ("active_rule", "active_binding_owner_task_id"),
        ):
            value = _clean(slots.get(key))
            if not value:
                continue
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:context_slot:{key}",
                    restore_kind="context_slot",
                    value=value,
                    source=f"{snapshot.source}.context_slots.{key}",
                    owner_task_id=_clean(slots.get(owner_key)),
                    observed_at=snapshot.updated_at,
                    confidence=0.72 if key.startswith("committed_") else 0.55,
                    metadata={"slot_name": key},
                )
            )

        binding_kind = _clean(slots.get("active_binding_kind"))
        binding_identity = _clean(slots.get("active_binding_identity"))
        if binding_kind and binding_identity:
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:active_binding",
                    restore_kind="active_binding",
                    value={"kind": binding_kind, "identity": binding_identity},
                    source=f"{snapshot.source}.context_slots.active_binding",
                    owner_task_id=_clean(slots.get("active_binding_owner_task_id")),
                    observed_at=snapshot.updated_at,
                    confidence=0.68,
                )
            )

        for key, value in snapshot.active_handles.items():
            clean_value = _clean(value)
            if not clean_value:
                continue
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:handle:{key}",
                    restore_kind="result_handle",
                    value=clean_value,
                    source=f"{snapshot.source}.context_slots.{key}",
                    owner_task_id=_clean(slots.get("active_binding_owner_task_id")),
                    observed_at=snapshot.updated_at,
                    confidence=0.64,
                    metadata={"handle_name": key},
                )
            )

        for item in snapshot.bundle_result_refs:
            if not isinstance(item, dict):
                continue
            ordinal = _safe_int(item.get("ordinal"))
            task_id = _clean(item.get("task_id"))
            if ordinal <= 0 or not task_id:
                continue
            candidates.append(
                StateMemoryRestoreCandidate(
                    candidate_id=f"state-restore:{snapshot.session_id}:bundle:{ordinal}",
                    restore_kind="bundle_ref",
                    value=dict(item),
                    source=f"{snapshot.source}.bundle_result_refs",
                    owner_task_id=task_id,
                    observed_at=snapshot.updated_at,
                    confidence=0.82,
                    metadata={"ordinal": ordinal, "task_kind": _clean(item.get("task_kind"))},
                )
            )

        if snapshot.flow_state:
            flow_id = _clean(snapshot.flow_state.get("flow_id"))
            if flow_id:
                candidates.append(
                    StateMemoryRestoreCandidate(
                        candidate_id=f"state-restore:{snapshot.session_id}:flow:{flow_id}",
                        restore_kind="flow_state",
                        value=dict(snapshot.flow_state),
                        source=f"{snapshot.source}.flow_state",
                        observed_at=snapshot.updated_at,
                        confidence=float(snapshot.flow_state.get("confidence") or 0.0),
                    )
                )

        if snapshot.task_state:
            has_task_state = any(_clean(value) for value in snapshot.task_state.values())
            if has_task_state:
                candidates.append(
                    StateMemoryRestoreCandidate(
                        candidate_id=f"state-restore:{snapshot.session_id}:task_state",
                        restore_kind="task_state",
                        value=dict(snapshot.task_state),
                        source=f"{snapshot.source}.task_state",
                        observed_at=snapshot.updated_at,
                        confidence=0.6,
                    )
                )

        return tuple(candidates)

    def context_candidates(self, session_id: str) -> tuple[MemoryContextCandidate, ...]:
        snapshot = self.load_snapshot(session_id)
        preview_parts = []
        file_signal_count = 0
        for key in ("committed_pdf", "committed_dataset", "active_pdf", "active_dataset"):
            value = _clean(snapshot.context_slots.get(key))
            if value:
                file_signal_count += 1
        if _clean(snapshot.context_slots.get("active_pdf")) or _clean(snapshot.context_slots.get("committed_pdf")):
            preview_parts.append("当前有一个 PDF 工作对象可继续处理。")
        if _clean(snapshot.context_slots.get("active_dataset")) or _clean(snapshot.context_slots.get("committed_dataset")):
            preview_parts.append("当前有一个表格/数据集工作对象可继续处理。")
        for key, value in snapshot.active_handles.items():
            if value:
                preview_parts.append(f"当前有一个已完成的分析结果可继续展开：{key}={value}。")
                break
        if snapshot.bundle_result_refs:
            preview_parts.append(f"上一轮包含 {len(snapshot.bundle_result_refs)} 个子任务结果，可按序号继续处理。")
        if snapshot.next_step and not preview_parts:
            preview_parts.append("当前有一个未完成的会话流程可继续推进。")
        preview = "\n".join(preview_parts).strip()
        if not preview:
            return ()
        return (
            MemoryContextCandidate(
                candidate_id=f"memory-context:{snapshot.session_id}:state:snapshot",
                memory_layer="state",
                source=snapshot.source,
                content_ref=f"state-memory:{snapshot.session_id}",
                rendered_preview=preview,
                relevance=0.8,
                confidence=0.68,
                staleness="session_scoped",
                token_estimate=max(1, count_text_tokens(preview)),
                budget_class="preferred",
                requires_verification_before_use=False,
                metadata={
                    "restore_candidate_count": len(self.restore_candidates_from_snapshot(snapshot)),
                    "file_signal_count": file_signal_count,
                    "updated_at": snapshot.updated_at,
                },
            ),
        )


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _object_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        payload = dict(value)
    elif hasattr(value, "to_dict"):
        payload = dict(value.to_dict())
    else:
        try:
            payload = asdict(value)
        except TypeError as exc:
            raise ValueError(f"State memory object is not serializable: {type(value).__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"State memory object did not serialize to a mapping: {type(value).__name__}")
    return {
        str(key): item
        for key, item in payload.items()
        if item not in ("", [], {}, None)
    }


def _active_constraints_from_context_slots(context_slots: dict[str, Any]) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    active_pdf = _clean(context_slots.get("active_pdf"))
    active_dataset = _clean(context_slots.get("active_dataset"))
    if active_pdf:
        constraints["active_pdf"] = active_pdf
        constraints["source_kind"] = "pdf"
    if active_dataset:
        constraints["active_dataset"] = active_dataset
        constraints["source_kind"] = "dataset"
    active_pdf_mode = _clean(context_slots.get("active_pdf_mode"))
    active_pdf_section = _clean(context_slots.get("active_pdf_section"))
    active_pdf_pages = [
        int(item)
        for item in list(context_slots.get("active_pdf_pages") or [])
        if str(item).strip().isdigit()
    ]
    if active_pdf_mode:
        constraints["active_pdf_mode"] = active_pdf_mode
    if active_pdf_section:
        constraints["active_pdf_section"] = active_pdf_section
    if active_pdf_pages:
        constraints["active_pdf_pages"] = active_pdf_pages
    subset_labels = [
        _clean(item)
        for item in list(context_slots.get("active_subset_labels") or [])
        if _clean(item)
    ]
    subset_filter_column = _clean(context_slots.get("active_subset_filter_column"))
    if subset_labels:
        constraints["subset_labels"] = subset_labels
    if subset_filter_column:
        constraints["subset_filter_column"] = subset_filter_column
    active_binding_identity = _clean(context_slots.get("active_binding_identity"))
    if active_binding_identity:
        constraints["active_binding_identity"] = active_binding_identity
    return constraints


def _task_summary_from_current_result_ref(
    *,
    index: int,
    value: Any,
    context_slots: dict[str, Any],
) -> dict[str, Any]:
    summary = _clean(value)
    active_dataset = _clean(context_slots.get("active_dataset"))
    active_pdf = _clean(context_slots.get("active_pdf"))
    task_id = _clean(context_slots.get("active_result_handle_id")) or f"state-result:{index}"
    if active_dataset:
        key_points = [f"dataset={active_dataset}"]
        subset_labels = [
            _clean(item)
            for item in list(context_slots.get("active_subset_labels") or [])
            if _clean(item)
        ]
        return {
            "task_id": task_id,
            "summary": summary,
            "answer": summary,
            "task_kind": "structured_data",
            "key_points": key_points,
            "active_result_handle_id": task_id,
            "active_object_handle_id": _clean(context_slots.get("active_object_handle_id")),
            "active_subset_handle_id": _clean(context_slots.get("active_subset_handle_id")),
            **({"subset_labels": subset_labels} if subset_labels else {}),
            **(
                {"subset_filter_column": _clean(context_slots.get("active_subset_filter_column"))}
                if _clean(context_slots.get("active_subset_filter_column"))
                else {}
            ),
        }
    if active_pdf:
        key_points = [f"pdf={active_pdf}"]
        pdf_mode = _clean(context_slots.get("active_pdf_mode"))
        if pdf_mode:
            key_points.append(f"pdf_mode={pdf_mode}")
        pages = [
            int(item)
            for item in list(context_slots.get("active_pdf_pages") or [])
            if str(item).strip().isdigit()
        ]
        if pages:
            key_points.append(f"pdf_pages={','.join(str(page) for page in pages)}")
        return {
            "task_id": task_id,
            "summary": summary,
            "answer": summary,
            "task_kind": "pdf",
            "key_points": key_points,
        }
    return {
        "task_id": task_id,
        "summary": summary,
        "answer": summary,
        "task_kind": "general",
        "key_points": [],
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

