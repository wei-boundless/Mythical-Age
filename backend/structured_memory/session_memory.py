from __future__ import annotations

from pathlib import Path
from typing import Any

from .dialogue_state import ContextSlots, DialogueState, FlowState, TaskState, TurnUnderstanding
from .flow_snapshots import FlowSnapshot, FlowSnapshotManager
from .models import Message, utc_now_iso
from .process_state import ProcessStateManager
from .session_memory_view import DEFAULT_TEMPLATE, SessionMemoryViewBuilder
from .session_processor import SessionUnderstandingProcessor
from .text_utils import normalize_storage_text
from .turn_understanding import FILE_PATTERN


class SessionMemoryManager:
    """Maintains per-session working memory as a rendered process-state view."""

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
        self.processor = SessionUnderstandingProcessor()
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

    def preview_state(
        self,
        messages: list[Message],
        max_items: int = 6,
        *,
        previous_state: DialogueState | None = None,
    ) -> DialogueState:
        baseline = previous_state if previous_state is not None else self.load_state()
        return self.processor.process(messages, baseline, max_items=max_items)

    def update_from_messages(
        self,
        messages: list[Message],
        max_items: int = 6,
        *,
        persist: bool = True,
    ) -> str:
        previous_state = self.load_state()
        state = self.preview_state(messages, max_items=max_items, previous_state=previous_state)
        content = self._render_state(state)
        debug_content = self._render_debug_state(state)
        if persist:
            self.overwrite(content, debug_content=debug_content)
            self.state_manager.overwrite(state)
            self.flow_snapshot_manager.update_for_transition(previous_state, state)
        return content

    def update_from_context_state(
        self,
        main_context: Any,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
        max_items: int = 6,
        *,
        persist: bool = True,
    ) -> str:
        previous_state = self.load_state()
        state = self._build_state_from_context_state(
            main_context=main_context,
            task_summaries=task_summaries or [],
            corrections=corrections or [],
            previous_state=previous_state,
            max_items=max_items,
        )
        content = self._render_state(state)
        debug_content = self._render_debug_state(state)
        if persist:
            self.overwrite(content, debug_content=debug_content)
            self.state_manager.overwrite(state)
            self.flow_snapshot_manager.update_for_transition(previous_state, state)
        return content

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
        corrections: list[str],
        previous_state: DialogueState,
        max_items: int,
    ) -> DialogueState:
        active_goal = self._coerce_text(self._read_value(main_context, "active_goal"))
        normalized_task_summaries = self._normalize_projection_task_summaries(task_summaries)
        if not active_goal and normalized_task_summaries:
            active_goal = normalized_task_summaries[0]["query"]
        if not active_goal:
            active_goal = previous_state.active_goal or "继续当前任务"

        active_work_item = self._coerce_text(self._read_value(main_context, "active_work_item"))
        active_constraints = self._coerce_mapping(self._read_value(main_context, "active_constraints"))
        latest_correction = self._coerce_text(self._read_value(main_context, "latest_correction"))
        next_step_value = self._coerce_text(self._read_value(main_context, "next_step"))

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
        task_switch = self._detect_projection_task_switch(previous_state, active_goal)
        turn_trace = self._build_projection_turn_trace(
            active_goal=active_goal,
            active_work_item=active_work_item,
            normalized_task_summaries=normalized_task_summaries,
            correction_items=correction_items,
            constraint_items=constraint_items,
            previous_state=previous_state,
            task_switch=task_switch,
        )

        turn_analyzer = self.processor.turn_analyzer
        process_engine = self.processor.process_engine
        understanding = turn_analyzer._understanding_for_text(active_goal)
        flow_type = process_engine._infer_flow_type(
            active_goal,
            understanding,
            previous_state,
            file_hints,
        )
        flow_id = (
            previous_state.flow_state.flow_id
            if not task_switch and previous_state.flow_state.flow_type == flow_type
            else f"{flow_type}:{turn_analyzer._slugify(understanding.target_object or active_goal or 'active')}"
        )
        flow_state = FlowState(
            flow_id=flow_id,
            flow_type=flow_type,
            status="awaiting_user" if normalized_task_summaries else "active",
            confidence=round(max(understanding.confidence, 0.72 if active_goal else 0.0), 2),
        )

        context_slots = self._build_projection_context_slots(
            active_goal=active_goal,
            active_constraints=active_constraints,
            active_work_item=active_work_item,
            file_hints=file_hints,
            previous_state=previous_state,
            task_switch=task_switch,
            flow_type=flow_type,
        )
        current_task_state = self._build_projection_current_task_state(
            active_goal=active_goal,
            active_work_item=active_work_item,
            constraint_items=constraint_items,
            normalized_task_summaries=normalized_task_summaries,
            correction_items=correction_items,
            next_step_value=next_step_value,
            max_items=max_items,
        )
        key_results = process_engine._dedupe_items(
            [item["summary"] for item in normalized_task_summaries if item["summary"]],
            max_items=max_items,
            max_chars=260,
        )
        decision_items = process_engine._dedupe_items(
            [item["summary"] for item in normalized_task_summaries if item["summary"]],
            max_items=max_items,
            max_chars=240,
        )
        key_user_requests = process_engine._dedupe_items(
            [active_goal],
            max_items=max_items,
        )
        warm_context = self._build_projection_warm_context(
            previous_state=previous_state,
            active_goal=active_goal,
            key_results=key_results,
            task_switch=task_switch,
            normalized_task_summaries=normalized_task_summaries,
            max_items=max_items,
        )
        next_steps = process_engine._dedupe_items(
            [next_step_value or f"继续处理当前用户请求：{process_engine._shorten(active_goal, 120)}"],
            max_items=max_items,
        )
        task_state = TaskState(
            current_step=current_task_state[0] if current_task_state else f"处理当前请求：{process_engine._shorten(active_goal, 120)}",
            completed_steps=process_engine._dedupe_items(
                [f"已完成：{item}" for item in key_results[:2]],
                max_items=3,
            ),
            pending_steps=process_engine._dedupe_items(list(next_steps[:2]), max_items=3),
            next_step=next_steps[0] if next_steps else "",
        )
        errors_and_corrections = process_engine._dedupe_items(
            list(correction_items),
            max_items=max_items,
        )
        worklog = process_engine._dedupe_items(
            [
                f"user: {process_engine._shorten(active_goal, 140)}",
                *[
                    f"assistant: {process_engine._shorten(item, 140)}"
                    for item in key_results[:2]
                ],
                *[
                    f"user-correction: {process_engine._shorten(item, 140)}"
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
            active_goal_turn_type="task_switch" if task_switch else "goal_request",
            last_turn_type=turn_trace[-1].turn_type if turn_trace else "summary_projection",
            flow_state=flow_state,
            task_state=task_state,
            context_slots=context_slots,
            current_task_state=current_task_state,
            warm_context=warm_context,
            key_user_requests=key_user_requests,
            files_and_functions=process_engine._dedupe_items(file_hints, max_items=max_items),
            conventions_and_constraints=process_engine._dedupe_items(constraint_items, max_items=max_items),
            errors_and_corrections=errors_and_corrections,
            decisions_and_learnings=decision_items,
            key_results=key_results,
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
            summary = self._coerce_task_summary_text(item)
            key_points = self._coerce_text_list(self._read_value(item, "key_points"))
            if not query and not summary and not key_points:
                continue
            normalized.append(
                {
                    "query": query,
                    "summary": summary,
                    "key_points": key_points,
                }
            )
        return normalized

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
        active_work_item: str,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        correction_items: list[str],
        constraint_items: list[str],
        previous_state: DialogueState,
        task_switch: bool,
    ) -> list[TurnUnderstanding]:
        understanding = self.processor.turn_analyzer._understanding_for_text(active_goal)
        flow_hint = self.processor.process_engine._infer_flow_type(
            active_goal,
            understanding,
            previous_state,
            self._extract_projection_file_hints([active_goal]),
        )
        turns = [
            TurnUnderstanding(
                role="user",
                turn_type="task_switch" if task_switch else "goal_request",
                excerpt=self._shorten(active_goal, 180),
                intent=active_work_item or understanding.intent,
                modality=understanding.modality,
                target_object=understanding.target_object or "",
                flow_hint=flow_hint,
                constraints=list(constraint_items[:3]),
            )
        ]
        for correction in correction_items:
            turns.append(
                TurnUnderstanding(
                    role="user",
                    turn_type="correction_feedback",
                    excerpt=self._shorten(correction, 180),
                    intent="correction_feedback",
                    modality=understanding.modality,
                    target_object=understanding.target_object or "",
                    flow_hint=flow_hint,
                    constraints=[],
                )
            )
        for item in normalized_task_summaries:
            summary_text = self._coerce_text(item.get("summary"))
            if not summary_text:
                continue
            turns.append(
                TurnUnderstanding(
                    role="assistant",
                    turn_type="result_delivery",
                    excerpt=self._shorten(summary_text, 180),
                    intent="result_delivery",
                    modality=understanding.modality,
                    target_object=understanding.target_object or "",
                    flow_hint="assistant_support",
                    constraints=[],
                )
            )
        return turns

    def _build_projection_context_slots(
        self,
        *,
        active_goal: str,
        active_constraints: dict[str, Any],
        active_work_item: str,
        file_hints: list[str],
        previous_state: DialogueState,
        task_switch: bool,
        flow_type: str,
    ) -> ContextSlots:
        pdf_files = [item for item in file_hints if item.lower().endswith(".pdf")]
        dataset_files = [
            item
            for item in file_hints
            if item.lower().endswith((".csv", ".xlsx", ".xls", ".json", ".parquet"))
        ]
        active_pdf = pdf_files[-1] if pdf_files else ("" if task_switch else previous_state.context_slots.active_pdf)
        active_dataset = dataset_files[-1] if dataset_files else ("" if task_switch else previous_state.context_slots.active_dataset)
        source_kind = self._coerce_text(active_constraints.get("source_kind"))
        active_entity = ""
        lowered_goal = active_goal.lower()
        if "session memory" in lowered_goal:
            active_entity = "session_memory"
        elif "memory bridge" in lowered_goal:
            active_entity = "memory_bridge"
        elif "memory" in lowered_goal and "system" in lowered_goal:
            active_entity = "memory_system"
        elif source_kind == "pdf":
            active_entity = "pdf_document"
        elif source_kind == "dataset":
            active_entity = "dataset"
        elif not task_switch:
            active_entity = previous_state.context_slots.active_entity
        active_rule = ""
        rendered_constraints = self._render_constraints(active_constraints)
        if rendered_constraints:
            active_rule = rendered_constraints
        elif not task_switch:
            active_rule = previous_state.context_slots.active_rule
        if flow_type == "external_lookup_flow":
            active_pdf = ""
            active_dataset = ""
        if flow_type == "pdf_analysis_flow":
            active_dataset = ""
        if flow_type == "structured_data_flow":
            active_pdf = ""
        return ContextSlots(
            active_pdf=active_pdf,
            active_dataset=active_dataset,
            active_entity=active_entity,
            active_rule=self._shorten(active_rule, 120),
        )

    def _build_projection_current_task_state(
        self,
        *,
        active_goal: str,
        active_work_item: str,
        constraint_items: list[str],
        normalized_task_summaries: list[dict[str, str | list[str]]],
        correction_items: list[str],
        next_step_value: str,
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        if active_work_item:
            items.append(f"当前工作项：{active_work_item}")
        items.append(f"当前目标：{self._shorten(active_goal, 160)}")
        if constraint_items:
            items.append(f"当前约束：{self._shorten(constraint_items[0], 160)}")
        if normalized_task_summaries:
            items.append(
                f"最新结果摘要：{self._shorten(self._coerce_text(normalized_task_summaries[-1].get('summary')), 160)}"
            )
        if correction_items:
            items.append(f"最新纠正：{self._shorten(correction_items[-1], 160)}")
        if next_step_value:
            items.append(f"当前下一步：{self._shorten(next_step_value, 160)}")
        return self.processor.process_engine._dedupe_items(items, max_items=max_items, max_chars=220)

    def _build_projection_warm_context(
        self,
        *,
        previous_state: DialogueState,
        active_goal: str,
        key_results: list[str],
        task_switch: bool,
        normalized_task_summaries: list[dict[str, str | list[str]]],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        if task_switch and previous_state.active_goal and previous_state.active_goal != active_goal:
            items.append(f"上一阶段目标：{self._shorten(previous_state.active_goal, 120)}")
            if previous_state.current_task_state:
                items.append(f"上一阶段状态：{self._shorten(previous_state.current_task_state[0], 120)}")
            if previous_state.key_results:
                items.append(f"上一阶段结果：{self._shorten(previous_state.key_results[0], 120)}")
            items.extend(previous_state.warm_context[:2])
        else:
            items.extend(previous_state.warm_context[:2])
            if previous_state.current_task_state:
                items.append(f"延续状态：{self._shorten(previous_state.current_task_state[0], 120)}")
        prior_query = previous_state.active_goal if previous_state.active_goal and previous_state.active_goal != active_goal else ""
        if prior_query and not task_switch:
            items.append(f"此前请求：{self._shorten(prior_query, 120)}")
        if len(normalized_task_summaries) > 1:
            items.append(f"近期结果：{self._shorten(self._coerce_text(normalized_task_summaries[-2].get('summary')), 120)}")
        if task_switch and key_results:
            items.append(f"当前切换后结果：{self._shorten(key_results[0], 120)}")
        return self.processor.process_engine._dedupe_items(items, max_items=max_items, max_chars=200)

    def _extract_projection_file_hints(self, items: list[str]) -> list[str]:
        hints: list[str] = []
        for item in items:
            text = self._coerce_text(item)
            if not text:
                continue
            for found in FILE_PATTERN.finditer(text):
                hints.append(found.group(0))
        return self._dedupe_text_items(hints)

    def _detect_projection_task_switch(
        self,
        previous_state: DialogueState,
        active_goal: str,
    ) -> bool:
        previous_goal = self._coerce_text(previous_state.active_goal)
        current_goal = self._coerce_text(active_goal)
        if not previous_goal or not current_goal or previous_goal == current_goal:
            return False
        if any(marker in current_goal for marker in ("换个问题", "新的问题", "另一个问题", "顺便")):
            return True
        previous_terms = self.processor.turn_analyzer._extract_terms(previous_goal)
        current_terms = self.processor.turn_analyzer._extract_terms(current_goal)
        if len(previous_terms) < 2 or len(current_terms) < 2:
            return False
        return len(previous_terms & current_terms) == 0

    def _title_from_goal(self, active_goal: str) -> str:
        words = " ".join(self._coerce_text(active_goal).split()).split()[:8]
        return " ".join(words) or "Ongoing session"

    def _shorten(self, text: str, limit: int) -> str:
        return self.processor.process_engine._shorten(self._coerce_text(text), limit)

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

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        return normalize_storage_text(str(value)).strip()

    def _coerce_text_list(self, value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [item for item in (self._coerce_text(entry) for entry in value) if item]
        return []

    def _coerce_task_summary_text(self, task_summary: Any) -> str:
        summary_text = self._coerce_text(self._read_value(task_summary, "summary"))
        if summary_text:
            return summary_text
        response_text = self._coerce_text(self._read_value(task_summary, "response"))
        if response_text:
            return response_text
        return ""

    def _render_constraints(self, constraints: dict[str, Any]) -> str:
        rendered: list[str] = []
        for key, value in constraints.items():
            if value in ("", None, [], {}):
                continue
            rendered.append(f"{key}={value}")
        return "；".join(rendered)

    def _dedupe_text_items(self, items: list[str]) -> list[str]:
        deduped: list[str] = []
        for item in items:
            cleaned = self._coerce_text(item)
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

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
