from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .process_state import ContextSlots, DialogueState, FlowState, TaskState, TurnUnderstanding
from .flow_snapshots import FlowSnapshot, FlowSnapshotManager
from .models import utc_now_iso
from .process_state import ProcessStateManager
from .session_memory_view import DEFAULT_TEMPLATE, SessionMemoryViewBuilder
from .text_utils import normalize_storage_text


FILE_PATTERN = re.compile(
    r"[\w./-]+\.(?:py|ts|tsx|js|md|json|yaml|yml|pdf|csv|xlsx|xls|parquet)"
)


class SessionMemoryManager:
    """Stores agent-maintained session memory and runtime process state views."""

    def __init__(self, session_dir: str | Path) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.views_dir = self.session_dir / "views"
        self.views_dir.mkdir(parents=True, exist_ok=True)
        self.agent_view_path = self.views_dir / "agent_view.md"
        self.debug_view_path = self.views_dir / "debug_view.md"
        self.compaction_view_path = self.views_dir / "compaction_view.md"
        self.summary_path = self.session_dir / "summary.md"
        self.state_manager = ProcessStateManager(self.session_dir)
        self.flow_snapshot_manager = FlowSnapshotManager(self.session_dir)
        self.view_builder = SessionMemoryViewBuilder()
        self._ensure_view_files()

    def load(self) -> str:
        source_path = self.summary_path if self.summary_path.exists() else self.agent_view_path
        return normalize_storage_text(source_path.read_text(encoding="utf-8")) + "\n"

    def load_debug_view(self) -> str:
        source_path = self.debug_view_path if self.debug_view_path.exists() else self.agent_view_path
        return normalize_storage_text(source_path.read_text(encoding="utf-8")) + "\n"

    def load_state(self) -> DialogueState:
        return self.state_manager.load()

    def load_flow_snapshots(self) -> list[FlowSnapshot]:
        return self.flow_snapshot_manager.load()

    def overwrite(self, model_content: str, *, debug_content: str | None = None) -> None:
        model_rendered = normalize_storage_text(model_content) + "\n"
        debug_rendered = normalize_storage_text(debug_content if debug_content is not None else model_content) + "\n"
        compaction_rendered = self.view_builder.render_compaction_view(model_rendered)
        self.agent_view_path.write_text(debug_rendered, encoding="utf-8")
        self.debug_view_path.write_text(debug_rendered, encoding="utf-8")
        self.summary_path.write_text(model_rendered, encoding="utf-8")
        self.compaction_view_path.write_text(compaction_rendered, encoding="utf-8")

    def update_runtime_state_from_context_state(
        self,
        main_context: Any,
        task_summaries: list[Any] | None = None,
        bundle_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
        max_items: int = 6,
    ) -> DialogueState:
        previous_state = self.load_state()
        state = self._build_state_from_context_state(
            main_context=main_context,
            task_summaries=task_summaries or [],
            bundle_summaries=bundle_summaries or [],
            corrections=corrections or [],
            previous_state=previous_state,
            max_items=max_items,
        )
        self.state_manager.overwrite(state)
        self.flow_snapshot_manager.update_for_transition(previous_state, state)
        return state

    def compact_view(
        self,
        max_chars_per_section: int = 800,
        *,
        content: str | None = None,
    ) -> str:
        if content is not None:
            return self.view_builder.render_compaction_view(
                content,
                max_chars_per_section=max_chars_per_section,
            )
        if max_chars_per_section == 800 and self.compaction_view_path.exists():
            return normalize_storage_text(self.compaction_view_path.read_text(encoding="utf-8")) + "\n"
        source = self.load()
        return self.view_builder.render_compaction_view(
            source,
            max_chars_per_section=max_chars_per_section,
        )

    def _render_state(self, state: DialogueState) -> str:
        return self.view_builder.render_state(state, mode="model")

    def _render_debug_state(self, state: DialogueState) -> str:
        return self.view_builder.render_state(state, mode="debug")

    def _parse_sections(self, content: str) -> dict[str, list[str]]:
        return self.view_builder.parse_sections(content)

    def parse_sections(self, content: str) -> dict[str, list[str]]:
        return self._parse_sections(content)

    def _description_for_header(self, header: str) -> list[str]:
        return self.view_builder.description_for_header(header)

    def describe_storage(self) -> dict[str, object]:
        return {
            "primary_state_path": str(self.state_manager.process_state_path),
            "state_mirror_path": str(self.state_manager.state_mirror_path),
            "flow_snapshot_path": str(self.flow_snapshot_manager.snapshot_path),
            "primary_view_path": str(self.agent_view_path),
            "debug_view_path": str(self.debug_view_path),
            "primary_compaction_view_path": str(self.compaction_view_path),
            "view_mirror_path": str(self.summary_path),
            "primary_state_exists": self.state_manager.process_state_path.exists(),
            "state_mirror_exists": self.state_manager.state_mirror_path.exists(),
            "flow_snapshot_exists": self.flow_snapshot_manager.snapshot_path.exists(),
            "primary_view_exists": self.agent_view_path.exists(),
            "debug_view_exists": self.debug_view_path.exists(),
            "primary_compaction_view_exists": self.compaction_view_path.exists(),
            "view_mirror_exists": self.summary_path.exists(),
        }

    def _build_state_from_context_state(
        self,
        *,
        main_context: Any,
        task_summaries: list[Any],
        bundle_summaries: list[Any],
        corrections: list[str],
        previous_state: DialogueState,
        max_items: int,
    ) -> DialogueState:
        active_goal = self._coerce_text(self._read_value(main_context, "active_goal"))
        normalized_task_summaries = self._normalize_projection_task_summaries(task_summaries)
        normalized_bundle_summaries = self._normalize_bundle_summaries(bundle_summaries)
        if not active_goal and normalized_task_summaries:
            active_goal = normalized_task_summaries[0]["query"]
        if not active_goal and normalized_bundle_summaries:
            active_goal = "继续上一轮复合任务"
        if not active_goal:
            active_goal = previous_state.active_goal or "继续当前任务"

        active_constraints = self._coerce_mapping(self._read_value(main_context, "active_constraints"))
        latest_correction = self._coerce_text(self._read_value(main_context, "latest_correction"))
        correction_items = self._dedupe_text_items(
            [latest_correction, *corrections]
        )
        constraint_items = self._build_constraint_items(
            active_constraints,
            normalized_task_summaries=normalized_task_summaries,
        )
        file_hints = self._extract_projection_file_hints(
            [
                active_goal,
                *[item["query"] for item in normalized_task_summaries],
                *[item["summary"] for item in normalized_task_summaries],
                *constraint_items,
            ]
        )
        turn_trace = self._build_projection_turn_trace(
            active_goal=active_goal,
            normalized_task_summaries=normalized_task_summaries,
            normalized_bundle_summaries=normalized_bundle_summaries,
            correction_items=correction_items,
            constraint_items=constraint_items,
        )

        flow_type = "memory_projection"
        flow_id = (
            previous_state.flow_state.flow_id
            if previous_state.flow_state.flow_type == flow_type
            else f"{flow_type}:{self._slugify(active_goal or 'active')}"
        )
        flow_state = FlowState(
            flow_id=flow_id,
            flow_type=flow_type,
            status="awaiting_user" if normalized_task_summaries else "active",
            confidence=1.0 if active_goal else 0.0,
        )

        context_slots = self._build_projection_context_slots(
            main_context=main_context,
            active_goal=active_goal,
            active_constraints=active_constraints,
            normalized_task_summaries=normalized_task_summaries,
            previous_state=previous_state,
        )
        current_task_state = self._build_projection_current_task_state(
            active_goal=active_goal,
            constraint_items=constraint_items,
            normalized_task_summaries=normalized_task_summaries,
            max_items=max_items,
        )
        current_step = self._build_projection_task_current_step(
            active_goal=active_goal,
            current_task_state=current_task_state,
            normalized_task_summaries=normalized_task_summaries,
        )
        current_result_refs = self._dedupe_items(
            [item["answer"] or item["summary"] for item in normalized_task_summaries if item["answer"] or item["summary"]],
            max_items=max_items,
            max_chars=260,
        )
        bundle_result_refs = normalized_bundle_summaries or []
        bundle_result_text_refs = [
            f"子任务 {item.get('ordinal')}: {item.get('summary')}"
            for item in bundle_result_refs
            if item.get("ordinal") and item.get("summary")
        ]
        current_result_refs = self._dedupe_items(
            [*current_result_refs, *bundle_result_text_refs],
            max_items=max_items,
            max_chars=260,
        )
        historical_result_refs = self._dedupe_items(
            [
                *list(previous_state.historical_result_refs),
                *[
                    item
                    for item in (
                        list(getattr(previous_state, "current_result_refs", []) or previous_state.key_results)[:2]
                    )
                    if item not in current_result_refs
                ],
            ],
            max_items=max_items,
            max_chars=260,
        )
        decision_items = self._dedupe_items(
            [item["answer"] or item["summary"] for item in normalized_task_summaries if item["answer"] or item["summary"]],
            max_items=max_items,
            max_chars=240,
        )
        key_user_requests = self._dedupe_items(
            [active_goal],
            max_items=max_items,
        )
        warm_context = self._build_projection_warm_context(
            previous_state=previous_state,
            active_goal=active_goal,
            current_result_refs=current_result_refs,
            historical_result_refs=historical_result_refs,
            normalized_task_summaries=normalized_task_summaries,
            max_items=max_items,
        )
        next_steps: list[str] = []
        task_state = TaskState(
            current_step=current_step,
            completed_steps=self._dedupe_items(
                [f"已完成：{item}" for item in current_result_refs[:2]],
                max_items=3,
            ),
            pending_steps=[],
            next_step="",
        )
        errors_and_corrections = self._dedupe_items(
            list(correction_items),
            max_items=max_items,
        )
        worklog = self._dedupe_items(
            [
                f"user: {self._shorten(active_goal, 140)}",
                *[
                    f"assistant: {self._shorten(item, 140)}"
                    for item in current_result_refs[:2]
                ],
                *[
                    f"user-correction: {self._shorten(item, 140)}"
                    for item in correction_items[:2]
                ],
            ],
            max_items=max_items,
            max_chars=180,
        )

        return DialogueState(
            version=2,
            updated_at=utc_now_iso(),
            session_title=self._title_from_goal(active_goal),
            active_goal=active_goal,
            active_goal_turn_type="user_message",
            last_turn_type=turn_trace[-1].turn_type if turn_trace else "summary_projection",
            flow_state=flow_state,
            task_state=task_state,
            context_slots=context_slots,
            current_task_state=current_task_state,
            warm_context=warm_context,
            key_user_requests=key_user_requests,
            files_and_functions=self._dedupe_items(file_hints, max_items=max_items),
            conventions_and_constraints=self._dedupe_items(constraint_items, max_items=max_items),
            errors_and_corrections=errors_and_corrections,
            decisions_and_learnings=decision_items,
            current_result_refs=current_result_refs,
            bundle_result_refs=bundle_result_refs,
            historical_result_refs=historical_result_refs,
            key_results=current_result_refs,
            risk_flags=[],
            risk_notes=[],
            next_step=next_steps,
            worklog=worklog,
            turn_trace=turn_trace[-12:],
        )

    def _normalize_projection_task_summaries(
        self,
        task_summaries: list[Any],
    ) -> list[dict[str, str | list[str]]]:
        normalized: list[dict[str, str | list[str]]] = []
        for item in task_summaries:
            query = self._coerce_text(self._read_value(item, "query"))
            answer = self._coerce_text(self._read_value(item, "answer"))
            summary = self._coerce_task_summary_text(item)
            if not answer:
                answer = summary
            if answer and not summary:
                summary = self._shorten(answer, 120)
            key_points = self._coerce_text_list(self._read_value(item, "key_points"))
            if not query and not answer and not summary and not key_points:
                continue
            normalized.append(
                {
                    "task_id": self._coerce_text(self._read_value(item, "task_id")),
                    "query": query,
                    "answer": answer,
                    "summary": summary,
                    "key_points": key_points,
                }
            )
        return normalized

    def _normalize_bundle_summaries(
        self,
        bundle_summaries: list[Any],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in bundle_summaries:
            if not isinstance(item, dict):
                continue
            ordinal = self._safe_int(self._read_value(item, "ordinal"))
            task_id = self._coerce_text(self._read_value(item, "task_id"))
            summary = self._coerce_task_summary_text(item)
            answer = self._coerce_text(self._read_value(item, "answer")) or summary
            query = self._coerce_text(self._read_value(item, "query"))
            task_kind = self._coerce_text(self._read_value(item, "task_kind"))
            capability_kind = self._coerce_text(self._read_value(item, "capability_kind"))
            required_tool = self._coerce_text(self._read_value(item, "required_tool"))
            key_points = self._coerce_text_list(self._read_value(item, "key_points"))
            if ordinal <= 0 or (not task_id and not answer and not summary and not query):
                continue
            normalized.append(
                {
                    "ordinal": ordinal,
                    "task_id": task_id or f"bundle:{ordinal}",
                    "query": query,
                    "answer": answer,
                    "summary": summary,
                    "task_kind": task_kind,
                    "capability_kind": capability_kind,
                    "required_tool": required_tool,
                    "key_points": key_points,
                }
            )
        return sorted(normalized, key=lambda item: int(item.get("ordinal") or 0))

    def _build_constraint_items(
        self,
        active_constraints: dict[str, Any],
        *,
        normalized_task_summaries: list[dict[str, str | list[str]]],
    ) -> list[str]:
        items: list[str] = []
        rendered_constraints = self._render_constraints(active_constraints)
        if rendered_constraints:
            items.append(rendered_constraints)
        for summary in normalized_task_summaries:
            key_points = summary.get("key_points", [])
            if isinstance(key_points, list):
                items.extend(self._coerce_text_list(key_points))
        return self._dedupe_text_items(items)

    def _build_projection_turn_trace(
        self,
        *,
        active_goal: str,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        normalized_bundle_summaries: list[dict[str, Any]],
        correction_items: list[str],
        constraint_items: list[str],
    ) -> list[TurnUnderstanding]:
        flow_hint = "not_decided"
        modality = "not_decided"
        turns = [
            TurnUnderstanding(
                role="user",
                turn_type="user_message",
                excerpt=self._shorten(active_goal, 180),
                intent="not_decided",
                modality=modality,
                target_object="",
                flow_hint=flow_hint,
                constraints=list(constraint_items[:3]),
            )
        ]
        for correction in correction_items:
            turns.append(
                TurnUnderstanding(
                    role="user",
                    turn_type="user_message",
                    excerpt=self._shorten(correction, 180),
                    intent="not_decided",
                    modality=modality,
                    target_object="",
                    flow_hint=flow_hint,
                    constraints=[],
                )
            )
        for item in normalized_task_summaries:
            summary_text = self._coerce_text(item.get("answer") or item.get("summary"))
            if not summary_text:
                continue
            turns.append(
                TurnUnderstanding(
                    role="assistant",
                    turn_type="assistant_message",
                    excerpt=self._shorten(summary_text, 180),
                    intent="not_decided",
                    modality=modality,
                    target_object="",
                    flow_hint="not_decided",
                    constraints=[],
                )
            )
        for item in normalized_bundle_summaries:
            summary_text = self._coerce_text(item.get("summary"))
            ordinal = self._safe_int(item.get("ordinal"))
            if ordinal <= 0 or not summary_text:
                continue
            turns.append(
                TurnUnderstanding(
                    role="assistant",
                    turn_type="assistant_message",
                    excerpt=self._shorten(f"子任务 {ordinal}: {summary_text}", 180),
                    intent="not_decided",
                    modality=modality,
                    target_object="",
                    flow_hint="not_decided",
                    constraints=[],
                )
            )
        return turns

    def _build_projection_context_slots(
        self,
        *,
        main_context: Any,
        active_goal: str,
        active_constraints: dict[str, Any],
        normalized_task_summaries: list[dict[str, str | list[str]]],
        previous_state: DialogueState,
    ) -> ContextSlots:
        previous_slots = previous_state.context_slots
        committed_pdf = self._coerce_text(
            getattr(previous_slots, "committed_pdf", "") or previous_slots.active_pdf
        )
        committed_pdf_owner_task_id = self._coerce_text(
            getattr(previous_slots, "committed_pdf_owner_task_id", "")
            or (previous_slots.active_binding_owner_task_id if previous_slots.active_pdf else "")
        )
        committed_dataset = self._coerce_text(
            getattr(previous_slots, "committed_dataset", "") or previous_slots.active_dataset
        )
        committed_dataset_owner_task_id = self._coerce_text(
            getattr(previous_slots, "committed_dataset_owner_task_id", "")
            or (previous_slots.active_binding_owner_task_id if previous_slots.active_dataset else "")
        )
        active_pdf = self._coerce_text(active_constraints.get("active_pdf"))
        active_dataset = self._coerce_text(active_constraints.get("active_dataset"))
        active_subset_labels = self._coerce_text_list(active_constraints.get("subset_labels"))
        active_subset_filter_column = self._coerce_text(active_constraints.get("subset_filter_column"))
        active_pdf_mode = self._normalize_pdf_scope(self._coerce_text(active_constraints.get("pdf_mode")))
        active_pdf_section = self._coerce_text(active_constraints.get("pdf_section"))
        active_pdf_pages = self._coerce_int_list(active_constraints.get("pdf_focus_pages"))
        if not active_pdf:
            active_pdf = self._extract_projection_binding_from_summaries(normalized_task_summaries, "pdf")
        if not active_pdf_mode:
            active_pdf_mode = self._normalize_pdf_scope(
                self._extract_projection_value_from_summaries(normalized_task_summaries, "pdf_mode")
            )
        if not active_pdf_section:
            active_pdf_section = self._extract_projection_value_from_summaries(normalized_task_summaries, "pdf_section")
        if not active_pdf_pages:
            active_pdf_pages = self._extract_projection_int_list_from_summaries(normalized_task_summaries, "pdf_pages")
        if not active_dataset:
            active_dataset = self._extract_projection_binding_from_summaries(normalized_task_summaries, "dataset")
        active_binding_identity = self._coerce_text(self._read_value(main_context, "active_binding_identity"))
        if not active_binding_identity:
            active_binding_identity = self._coerce_text(active_constraints.get("active_binding_identity"))
        if not active_binding_identity:
            active_binding_identity = self._binding_identity_from_slot_values(active_pdf=active_pdf, active_dataset=active_dataset)
        active_binding_kind = self._coerce_text(self._read_value(main_context, "followup_binding_key"))
        if not active_binding_kind:
            active_binding_kind = "active_pdf" if active_pdf else "active_dataset" if active_dataset else ""
        active_binding_owner_task_id = self._projection_binding_owner_task_id(
            main_context=main_context,
            normalized_task_summaries=normalized_task_summaries,
            active_binding_kind=active_binding_kind,
        )
        active_object_handle_id = self._coerce_text(self._read_value(main_context, "active_object_handle_id"))
        active_result_handle_id = self._coerce_text(self._read_value(main_context, "active_result_handle_id"))
        active_subset_handle_id = self._coerce_text(self._read_value(main_context, "active_subset_handle_id"))
        active_entity = ""
        if active_pdf:
            active_entity = "pdf_document"
        elif active_dataset:
            active_entity = "dataset"
        if not active_pdf and not active_dataset:
            active_binding_kind = ""
            active_binding_identity = ""
            active_binding_owner_task_id = ""
            active_object_handle_id = ""
            active_result_handle_id = ""
            active_subset_handle_id = ""
            active_subset_labels = []
            active_subset_filter_column = ""
        if not active_pdf:
            active_pdf_mode = ""
            active_pdf_section = ""
            active_pdf_pages = []
        if not active_dataset:
            active_subset_labels = []
            active_subset_filter_column = ""
        if active_pdf:
            committed_pdf = active_pdf
            if active_binding_owner_task_id:
                committed_pdf_owner_task_id = active_binding_owner_task_id
        if active_dataset:
            committed_dataset = active_dataset
            if active_binding_owner_task_id:
                committed_dataset_owner_task_id = active_binding_owner_task_id
        return ContextSlots(
            active_pdf=active_pdf,
            active_pdf_mode=active_pdf_mode,
            active_pdf_section=active_pdf_section,
            active_pdf_pages=active_pdf_pages,
            active_dataset=active_dataset,
            active_subset_labels=active_subset_labels,
            active_subset_filter_column=active_subset_filter_column,
            active_binding_kind=active_binding_kind,
            active_binding_identity=active_binding_identity,
            active_binding_owner_task_id=active_binding_owner_task_id,
            active_object_handle_id=active_object_handle_id,
            active_result_handle_id=active_result_handle_id,
            active_subset_handle_id=active_subset_handle_id,
            committed_pdf=committed_pdf,
            committed_pdf_owner_task_id=committed_pdf_owner_task_id,
            committed_dataset=committed_dataset,
            committed_dataset_owner_task_id=committed_dataset_owner_task_id,
            active_entity=active_entity,
            active_rule="",
        )

    def _normalize_pdf_scope(self, value: str) -> str:
        normalized = self._coerce_text(value).lower()
        if normalized in {"page", "page-read", "page_read"}:
            return "page"
        if normalized in {"section", "section-read", "section_read"}:
            return "section"
        if normalized:
            return "document"
        return ""

    def _can_carry_forward_active_entity(self, active_entity: str) -> bool:
        entity = self._coerce_text(active_entity)
        return bool(entity) and entity not in {"pdf_document", "dataset"}

    def _extract_projection_binding_from_summaries(
        self,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        binding_kind: str,
    ) -> str:
        prefix = f"{binding_kind}="
        for summary in reversed(normalized_task_summaries):
            key_points = summary.get("key_points", [])
            if not isinstance(key_points, list):
                continue
            for item in reversed(key_points):
                text = self._coerce_text(item)
                if text.startswith(prefix):
                    return text[len(prefix):].strip()
        return ""

    def _extract_projection_value_from_summaries(
        self,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        key: str,
    ) -> str:
        prefix = f"{key}="
        for summary in reversed(normalized_task_summaries):
            key_points = summary.get("key_points", [])
            if not isinstance(key_points, list):
                continue
            for item in reversed(key_points):
                text = self._coerce_text(item)
                if text.startswith(prefix):
                    return text[len(prefix):].strip()
        return ""

    def _extract_projection_int_list_from_summaries(
        self,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        key: str,
    ) -> list[int]:
        raw = self._extract_projection_value_from_summaries(normalized_task_summaries, key)
        if not raw:
            return []
        return [int(part) for part in raw.split(",") if part.strip().isdigit()]

    def _projection_binding_owner_task_id(
        self,
        *,
        main_context: Any,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        active_binding_kind: str,
    ) -> str:
        explicit_owner = self._coerce_text(self._read_value(main_context, "followup_binding_owner_task_id"))
        if explicit_owner:
            return explicit_owner
        target_task_id = self._coerce_text(self._read_value(main_context, "followup_target_task_id"))
        if target_task_id:
            return target_task_id
        expected_prefix = "pdf=" if active_binding_kind == "active_pdf" else "dataset=" if active_binding_kind == "active_dataset" else ""
        for summary in reversed(normalized_task_summaries):
            task_id = self._coerce_text(summary.get("task_id"))
            key_points = summary.get("key_points", [])
            if task_id and expected_prefix and isinstance(key_points, list):
                if any(self._coerce_text(item).startswith(expected_prefix) for item in key_points):
                    return task_id
        for summary in reversed(normalized_task_summaries):
            task_id = self._coerce_text(summary.get("task_id"))
            if task_id:
                return task_id
        return ""

    def _binding_identity_from_slot_values(
        self,
        *,
        active_pdf: str,
        active_dataset: str,
    ) -> str:
        if active_pdf:
            return active_pdf.replace("\\", "/").strip().lower()
        if active_dataset:
            return active_dataset.replace("\\", "/").strip().lower()
        return ""

    def _build_projection_current_task_state(
        self,
        *,
        active_goal: str,
        constraint_items: list[str],
        normalized_task_summaries: list[dict[str, str | list[str]]],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        items.append(f"当前目标：{self._shorten(active_goal, 160)}")
        if constraint_items:
            items.append(f"当前约束：{self._shorten(constraint_items[0], 160)}")
        if normalized_task_summaries:
            items.append(
                f"最新结果摘要：{self._shorten(self._coerce_text(normalized_task_summaries[-1].get('summary')), 160)}"
            )
        return self._dedupe_items(items, max_items=max_items, max_chars=220)

    def _build_projection_task_current_step(
        self,
        *,
        active_goal: str,
        current_task_state: list[str],
        normalized_task_summaries: list[dict[str, str | list[str]]],
    ) -> str:
        if normalized_task_summaries:
            latest_summary = self._coerce_text(normalized_task_summaries[-1].get("summary"))
            if latest_summary:
                return f"整理结果：{self._shorten(latest_summary, 120)}"
        for item in current_task_state:
            compact = self._coerce_text(item)
            if compact.startswith("当前目标：") or compact.startswith("当前约束："):
                return compact
        return f"围绕当前目标回答：{self._shorten(active_goal, 120)}"

    def _build_projection_warm_context(
        self,
        *,
        previous_state: DialogueState,
        active_goal: str,
        current_result_refs: list[str],
        historical_result_refs: list[str],
        normalized_task_summaries: list[dict[str, str | list[str]]],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        items.extend(previous_state.warm_context[:2])
        prior_query = previous_state.active_goal if previous_state.active_goal and previous_state.active_goal != active_goal else ""
        if prior_query:
            items.append(f"此前请求：{self._shorten(prior_query, 120)}")
        if len(normalized_task_summaries) > 1:
            items.append(f"近期结果：{self._shorten(self._coerce_text(normalized_task_summaries[-2].get('answer') or normalized_task_summaries[-2].get('summary')), 120)}")
        elif not current_result_refs and historical_result_refs:
            items.append(f"近期结果：{self._shorten(historical_result_refs[0], 120)}")
        return self._dedupe_items(items, max_items=max_items, max_chars=200)

    def _extract_projection_file_hints(self, items: list[str]) -> list[str]:
        hints: list[str] = []
        for item in items:
            text = self._coerce_text(item)
            if not text:
                continue
            for found in FILE_PATTERN.finditer(text):
                hints.append(found.group(0))
        return self._dedupe_text_items(hints)

    def _title_from_goal(self, active_goal: str) -> str:
        words = " ".join(self._coerce_text(active_goal).split()).split()[:8]
        return " ".join(words) or "Ongoing session"

    def _shorten(self, text: str, limit: int) -> str:
        compact = " ".join(self._coerce_text(text).split())
        return compact[:limit] + ("..." if len(compact) > limit else "")

    def _slugify(self, text: str) -> str:
        normalized = self._coerce_text(text).lower()
        ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if ascii_slug:
            return ascii_slug[:48]
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", normalized):
            if chunk:
                return chunk[:12]
        return "active"

    def _read_value(self, source: Any, key: str) -> Any:
        if source is None:
            return None
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _coerce_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "items"):
            return {str(key): item for key, item in value.items()}
        return {}

    def _coerce_int_list(self, value: Any) -> list[int]:
        if isinstance(value, (list, tuple)):
            return [int(item) for item in value if str(item).strip().isdigit()]
        if isinstance(value, str):
            return [int(item) for item in value.split(",") if item.strip().isdigit()]
        return []

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        return normalize_storage_text(str(value)).strip()

    def _coerce_text_list(self, value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [item for item in (self._coerce_text(entry) for entry in value) if item]
        return []

    def _coerce_task_summary_text(self, task_summary: Any) -> str:
        answer_text = self._coerce_text(self._read_value(task_summary, "answer"))
        if answer_text:
            return answer_text
        summary_text = self._coerce_text(self._read_value(task_summary, "summary"))
        if summary_text:
            return summary_text
        response_text = self._coerce_text(self._read_value(task_summary, "response"))
        if response_text:
            return response_text
        return ""

    def _render_constraints(self, constraints: dict[str, Any]) -> str:
        safe_keys = {
            "append_mode",
            "dedupe",
            "group_by",
            "page",
            "pdf_focus_pages",
            "pdf_mode",
            "pdf_section",
            "response_style",
            "source_kind",
            "top_n",
        }
        aliases = {
            "active_pdf_mode": "pdf_mode",
            "active_pdf_pages": "pdf_focus_pages",
        }
        rendered: list[str] = []
        for key, value in constraints.items():
            if value in ("", None, [], {}):
                continue
            normalized_key = aliases.get(str(key), str(key))
            if normalized_key not in safe_keys:
                continue
            rendered.append(f"{normalized_key}={value}")
        return "；".join(rendered)

    def _dedupe_text_items(self, items: list[str]) -> list[str]:
        deduped: list[str] = []
        for item in items:
            cleaned = self._coerce_text(item)
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

    def _dedupe_items(
        self,
        items: list[str],
        *,
        max_items: int,
        max_chars: int = 240,
    ) -> list[str]:
        deduped: list[str] = []
        for item in items:
            cleaned = " ".join(self._coerce_text(item).split()).strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned[:max_chars].rstrip())
        return deduped[:max_items]

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _ensure_view_files(self) -> None:
        if self.agent_view_path.exists():
            source = self.agent_view_path.read_text(encoding="utf-8")
            if not self.debug_view_path.exists():
                self.debug_view_path.write_text(source, encoding="utf-8")
            if not self.summary_path.exists():
                self.summary_path.write_text(source, encoding="utf-8")
            if not self.compaction_view_path.exists():
                self.compaction_view_path.write_text(
                    self.view_builder.render_compaction_view(source),
                    encoding="utf-8",
                )
            return
        if self.summary_path.exists():
            source = self.summary_path.read_text(encoding="utf-8")
            self.agent_view_path.write_text(source, encoding="utf-8")
            self.debug_view_path.write_text(source, encoding="utf-8")
            self.compaction_view_path.write_text(
                self.view_builder.render_compaction_view(source),
                encoding="utf-8",
            )
            return
        default_view = DEFAULT_TEMPLATE
        self.agent_view_path.write_text(default_view, encoding="utf-8")
        self.debug_view_path.write_text(default_view, encoding="utf-8")
        self.summary_path.write_text(default_view, encoding="utf-8")
        self.compaction_view_path.write_text(
            self.view_builder.render_compaction_view(default_view),
            encoding="utf-8",
        )
