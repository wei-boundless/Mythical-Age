
from __future__ import annotations

import re

from .process_state import ContextSlots, DialogueState, FlowState, TaskState, TurnUnderstanding
from .models import Message, utc_now_iso
from .text_utils import normalize_storage_text
from .turn_projection import (
    COMMAND_PREFIXES,
    DECISION_MARKERS,
    ENGLISH_RESULT_MARKERS,
    ERROR_MARKERS,
    FILE_PATTERN,
    RESULT_MARKERS,
    SECRET_PATTERNS,
    TurnProjectionBuilder,
    TurnProjectionSnapshot,
    WARM_CONTEXT_CHAR_BUDGET,
)

ENGLISH_PREFERENCE_MARKERS = (
    "prefer",
    "preference",
    "powershell",
    "by default",
    "default to",
    "answer style",
    "reply style",
    "response style",
    "conclusion first",
    "give the conclusion first",
    "then explain",
)
ENGLISH_CONVENTION_MARKERS = (
    "powershell",
    "workflow",
    "convention",
    "rule",
    "terminal commands",
    "by default",
    "default to",
)

class ProcessStateEngine:
    """Owns process-state projection from conversation facts."""

    def __init__(self, turn_projector: TurnProjectionBuilder | None = None) -> None:
        self.turn_projector = turn_projector or TurnProjectionBuilder()

    def assemble(
        self,
        snapshot: TurnProjectionSnapshot,
        previous_state: DialogueState,
        *,
        max_items: int = 6,
    ) -> DialogueState:
        active_goal, active_goal_turn_type = self._resolve_active_goal_fields(
            snapshot,
        )
        projected_messages = snapshot.cleaned_messages
        projected_assistant_messages = [message for message in projected_messages if message.role == "assistant"]
        file_hints = self._extract_file_hints(projected_messages)
        convention_hints = self._extract_convention_hints(projected_messages)
        decision_items = self._extract_decisions(projected_assistant_messages)
        current_assistant_messages, historical_assistant_messages = self._split_assistant_messages_for_current_turn(
            projected_messages
        )
        current_result_items = self._extract_results(current_assistant_messages)
        historical_result_items = self._build_historical_result_refs(
            previous_state,
            historical_assistant_messages=historical_assistant_messages,
            current_result_items=current_result_items,
            max_items=max_items,
        )
        request_items = self._extract_user_requests(snapshot.turn_trace, max_items=max_items)
        next_steps = self._infer_next_steps(active_goal, snapshot.turn_trace, projected_assistant_messages)
        current_task_state = self._build_current_state(
            active_goal,
            snapshot.turn_trace,
            current_assistant_messages,
            current_result_items=current_result_items,
            max_items=max_items,
        )
        warm_context = self._build_warm_context(
            previous_state,
            active_goal,
            snapshot.turn_trace,
            projected_assistant_messages,
            current_result_refs=current_result_items,
            historical_result_refs=historical_result_items,
            max_items=max_items,
        )
        flow_state = self._build_flow_state(
            active_goal,
            previous_state=previous_state,
            turn_trace=snapshot.turn_trace,
        )
        task_state = self._build_task_state(
            active_goal,
            snapshot.turn_trace,
            current_assistant_messages,
            previous_state=previous_state,
            next_steps=next_steps,
            current_result_items=current_result_items,
        )
        context_slots = self._build_context_slots(
            active_goal,
            previous_state=previous_state,
            convention_hints=convention_hints,
        )
        risk_flags, risk_notes, warm_context = self._assess_and_guard_risks(
            cleaned_messages=projected_messages,
            previous_state=previous_state,
            turn_trace=snapshot.turn_trace,
            active_goal=active_goal,
            flow_state=flow_state,
            context_slots=context_slots,
            warm_context=warm_context,
            current_task_state=current_task_state,
        )
        errors_and_corrections = self._dedupe_items(
            self._extract_error_hints(projected_assistant_messages),
            max_items=max_items,
        )

        return DialogueState(
            version=2,
            updated_at=utc_now_iso(),
            session_title=self._title_from_messages(snapshot.user_messages or projected_messages),
            active_goal=active_goal,
            active_goal_turn_type=active_goal_turn_type,
            restore_goal_hint="",
            restore_flow_hint="",
            last_turn_type=snapshot.last_turn_type,
            flow_state=flow_state,
            task_state=task_state,
            context_slots=context_slots,
            current_task_state=current_task_state,
            warm_context=warm_context,
            key_user_requests=request_items,
            files_and_functions=self._dedupe_items(file_hints, max_items=max_items),
            conventions_and_constraints=self._dedupe_items(convention_hints, max_items=max_items),
            errors_and_corrections=errors_and_corrections,
            decisions_and_learnings=self._dedupe_items(decision_items, max_items=max_items),
            current_result_refs=self._dedupe_items(current_result_items, max_items=max_items),
            historical_result_refs=self._dedupe_items(historical_result_items, max_items=max_items),
            key_results=self._dedupe_items(current_result_items, max_items=max_items),
            risk_flags=self._dedupe_items(risk_flags, max_items=max_items),
            risk_notes=self._dedupe_items(risk_notes, max_items=max_items),
            next_step=self._dedupe_items(next_steps, max_items=max_items),
            worklog=self._dedupe_items(
                [f"{msg.role}: {self._shorten(msg.content, 140)}" for msg in projected_messages[-max_items:]],
                max_items=max_items,
            ),
            turn_trace=snapshot.turn_trace[-12:],
        )

    def _resolve_active_goal_fields(
        self,
        snapshot: TurnProjectionSnapshot,
    ) -> tuple[str, str]:
        active_goal = snapshot.active_goal
        active_goal_turn_type = snapshot.active_goal_turn_type

        return active_goal, active_goal_turn_type

    def _split_assistant_messages_for_current_turn(
        self,
        messages: list[Message],
    ) -> tuple[list[Message], list[Message]]:
        last_user_index = None
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].role == "user":
                last_user_index = index
                break
        if last_user_index is None:
            assistant_messages = [message for message in messages if message.role == "assistant"]
            return assistant_messages, []
        current_assistant_messages = [
            message
            for message in messages[last_user_index + 1 :]
            if message.role == "assistant"
        ]
        historical_assistant_messages = [
            message
            for message in messages[:last_user_index]
            if message.role == "assistant"
        ]
        return current_assistant_messages, historical_assistant_messages

    def _build_historical_result_refs(
        self,
        previous_state: DialogueState,
        *,
        historical_assistant_messages: list[Message],
        current_result_items: list[str],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        items.extend(list(previous_state.historical_result_refs))
        previous_visible = self._visible_result_refs(previous_state)
        items.extend(previous_visible[:2])
        items.extend(self._extract_results(historical_assistant_messages)[-2:])
        filtered = [item for item in items if item not in current_result_items]
        return self._dedupe_items(filtered, max_items=max_items, max_chars=260)

    def _visible_result_refs(self, state: DialogueState) -> list[str]:
        items = list(getattr(state, "current_result_refs", []) or [])
        if items:
            return items
        return list(state.key_results)

    def _slugify(self, text: str) -> str:
        return self.turn_projector._slugify(text)

    def _build_flow_state(
        self,
        active_goal: str,
        *,
        previous_state: DialogueState,
        turn_trace: list[TurnUnderstanding],
    ) -> FlowState:
        flow_type = "memory_projection"
        if previous_state.flow_state.flow_type == flow_type:
            flow_id = previous_state.flow_state.flow_id
        else:
            flow_id = f"{flow_type}:{self._slugify(active_goal or 'active')}"
        return FlowState(
            flow_id=flow_id,
            flow_type=flow_type,
            status=self._infer_flow_status(turn_trace),
            confidence=1.0 if active_goal else 0.0,
        )

    def _build_task_state(
        self,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        assistant_messages: list[Message],
        *,
        previous_state: DialogueState,
        next_steps: list[str],
        current_result_items: list[str],
    ) -> TaskState:
        completed_steps: list[str] = []
        completed_steps.extend(previous_state.task_state.completed_steps[-1:])
        completed_steps.extend(
            f"已完成：{self._shorten(item, 120)}"
            for item in current_result_items[-2:]
        )
        completed_steps.extend(
            f"已确定：{self._shorten(item, 120)}"
            for item in self._extract_decisions(assistant_messages)[-1:]
        )

        pending_steps = list(next_steps[:2])
        current_step = self._infer_current_step(active_goal, turn_trace, assistant_messages)

        return TaskState(
            current_step=current_step,
            completed_steps=self._dedupe_items(completed_steps, max_items=3),
            pending_steps=self._dedupe_items(pending_steps, max_items=3),
            next_step=next_steps[0] if next_steps else "",
        )

    def _build_context_slots(
        self,
        active_goal: str,
        *,
        previous_state: DialogueState,
        convention_hints: list[str],
    ) -> ContextSlots:
        active_pdf, active_dataset = self._extract_slots_from_active_goal(active_goal)
        active_pdf_mode = self._infer_pdf_mode_from_goal(active_goal)
        active_pdf_section = self._extract_pdf_section_from_goal(active_goal)
        active_pdf_pages = self._extract_pdf_pages_from_goal(active_goal)
        previous_slots = previous_state.context_slots
        previous_committed_pdf = normalize_storage_text(
            getattr(previous_slots, "committed_pdf", "") or previous_slots.active_pdf
        ).strip()
        previous_committed_pdf_owner_task_id = normalize_storage_text(
            getattr(previous_slots, "committed_pdf_owner_task_id", "")
            or (previous_slots.active_binding_owner_task_id if previous_slots.active_pdf else "")
        ).strip()
        previous_committed_dataset = normalize_storage_text(
            getattr(previous_slots, "committed_dataset", "") or previous_slots.active_dataset
        ).strip()
        previous_committed_dataset_owner_task_id = normalize_storage_text(
            getattr(previous_slots, "committed_dataset_owner_task_id", "")
            or (previous_slots.active_binding_owner_task_id if previous_slots.active_dataset else "")
        ).strip()
        previous_active_pdf = normalize_storage_text(getattr(previous_slots, "active_pdf", "")).strip()
        previous_active_dataset = normalize_storage_text(getattr(previous_slots, "active_dataset", "")).strip()
        active_entity = "pdf_document" if active_pdf else "dataset" if active_dataset else ""
        active_rule = self._extract_constraint_slot(convention_hints, previous_state)
        committed_pdf = active_pdf or previous_committed_pdf
        committed_pdf_owner_task_id = (
            previous_committed_pdf_owner_task_id
            if normalize_storage_text(active_pdf).strip() == previous_committed_pdf
            else ""
        )
        if not active_pdf:
            committed_pdf_owner_task_id = previous_committed_pdf_owner_task_id
        committed_dataset = active_dataset or previous_committed_dataset
        committed_dataset_owner_task_id = (
            previous_committed_dataset_owner_task_id
            if normalize_storage_text(active_dataset).strip() == previous_committed_dataset
            else ""
        )
        if not active_dataset:
            committed_dataset_owner_task_id = previous_committed_dataset_owner_task_id

        active_binding_kind = ""
        active_binding_identity = ""
        active_binding_owner_task_id = ""
        active_object_handle_id = ""
        active_result_handle_id = ""
        active_subset_handle_id = ""
        active_subset_labels: list[str] = []
        active_subset_filter_column = ""
        if active_pdf:
            active_binding_kind = "active_pdf"
            active_binding_identity = _binding_identity(active_pdf)
            active_binding_owner_task_id = (
                previous_slots.active_binding_owner_task_id
                if active_pdf == previous_active_pdf
                else committed_pdf_owner_task_id
            )
            active_object_handle_id = previous_slots.active_object_handle_id if active_pdf == previous_active_pdf else ""
            active_result_handle_id = previous_slots.active_result_handle_id if active_pdf == previous_active_pdf else ""
            active_subset_handle_id = previous_slots.active_subset_handle_id if active_pdf == previous_active_pdf else ""
        elif active_dataset:
            active_binding_kind = "active_dataset"
            active_binding_identity = _binding_identity(active_dataset)
            active_binding_owner_task_id = (
                previous_slots.active_binding_owner_task_id
                if active_dataset == previous_active_dataset
                else committed_dataset_owner_task_id
            )
            active_object_handle_id = (
                previous_slots.active_object_handle_id if active_dataset == previous_active_dataset else ""
            )
            active_result_handle_id = (
                previous_slots.active_result_handle_id if active_dataset == previous_active_dataset else ""
            )
            active_subset_handle_id = (
                previous_slots.active_subset_handle_id if active_dataset == previous_active_dataset else ""
            )
            active_subset_labels = (
                list(previous_slots.active_subset_labels) if active_dataset == previous_active_dataset else []
            )
            active_subset_filter_column = (
                previous_slots.active_subset_filter_column if active_dataset == previous_active_dataset else ""
            )

        return ContextSlots(
            active_pdf=active_pdf,
            active_pdf_mode=active_pdf_mode if active_pdf else "",
            active_pdf_section=active_pdf_section if active_pdf else "",
            active_pdf_pages=active_pdf_pages if active_pdf else [],
            active_dataset=active_dataset,
            active_subset_labels=active_subset_labels if active_dataset else [],
            active_subset_filter_column=active_subset_filter_column if active_dataset else "",
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
            active_rule=active_rule,
        )

    def _extract_slots_from_active_goal(self, active_goal: str) -> tuple[str, str]:
        pdf_files: list[str] = []
        dataset_files: list[str] = []
        for found in FILE_PATTERN.finditer(active_goal or ""):
            candidate = found.group(0)
            lowered = candidate.lower()
            if lowered.endswith(".pdf"):
                pdf_files.append(candidate)
            elif lowered.endswith((".csv", ".xlsx", ".xls", ".json", ".parquet")):
                dataset_files.append(candidate)
        return (
            pdf_files[-1] if pdf_files else "",
            dataset_files[-1] if dataset_files else "",
        )

    def _infer_pdf_mode_from_goal(self, active_goal: str) -> str:
        normalized = normalize_storage_text(active_goal).lower()
        if re.search(r"第\s*\d+\s*页", active_goal) or re.search(r"page\s*\d+", normalized):
            return "page"
        if re.search(r"第\s*[一二三四五六七八九十百千两零\d]+\s*(?:部分|章|节)", active_goal):
            return "section"
        if any(marker in active_goal for marker in ("这一部分", "那一部分", "这一章", "那一章", "这一节", "那一节")):
            return "section"
        return "document" if ".pdf" in normalized or "pdf" in normalized else ""

    def _extract_pdf_section_from_goal(self, active_goal: str) -> str:
        match = re.search(r"(第\s*[一二三四五六七八九十百千两零\d]+\s*(?:部分|章|节))", active_goal)
        if match:
            return str(match.group(1) or "").strip()
        for marker in ("这一部分", "那一部分", "这一章", "那一章", "这一节", "那一节"):
            if marker in active_goal:
                return marker
        return ""

    def _extract_pdf_pages_from_goal(self, active_goal: str) -> list[int]:
        direct = re.search(r"第\s*(\d+)\s*页", active_goal)
        if direct:
            return [int(direct.group(1))]
        return []

    def _build_current_state(
        self,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        assistant_messages: list[Message],
        *,
        current_result_items: list[str],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        last_user_turn = next((turn for turn in reversed(turn_trace) if turn.role == "user"), None)

        if active_goal:
            items.append(f"当前关注的用户问题：{active_goal}")
        if last_user_turn is not None:
            items.append(f"最新用户消息：{last_user_turn.excerpt}")
        if current_result_items:
            items.append(f"最近产出：{self._shorten(current_result_items[-1], 180)}")
        latest_error = self._extract_error_hints(assistant_messages)
        if latest_error:
            items.append(f"最近问题：{self._shorten(latest_error[-1], 180)}")
        return self._dedupe_items(items, max_items=max_items)

    def _build_warm_context(
        self,
        previous_state: DialogueState,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        assistant_messages: list[Message],
        *,
        current_result_refs: list[str],
        historical_result_refs: list[str],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        previous_state_items = list(previous_state.current_task_state)
        previous_warm = list(previous_state.warm_context)

        items.extend(previous_warm[:2])
        items.extend(f"延续状态：{item}" for item in previous_state_items[:1])

        recent_decisions = list(previous_state.decisions_and_learnings[-1:])
        items.extend(f"近期结论：{item}" for item in recent_decisions)

        if not current_result_refs:
            items.extend(f"近期结果：{item}" for item in historical_result_refs[:1])

        prior_requests = [
            turn.excerpt
            for turn in turn_trace[:-1]
            if turn.role == "user"
        ][-1:]
        items.extend(f"此前请求：{item}" for item in prior_requests)

        return self._dedupe_items(items, max_items=max_items)

    def _infer_flow_status(self, turn_trace: list[TurnUnderstanding]) -> str:
        last_turn = turn_trace[-1] if turn_trace else None
        if last_turn is None:
            return "idle"
        if last_turn.role == "assistant":
            return "awaiting_user"
        return "active"

    def _infer_current_step(
        self,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        assistant_messages: list[Message],
    ) -> str:
        last_turn = turn_trace[-1] if turn_trace else None
        if last_turn is None:
            return ""
        if last_turn.role == "user":
            return f"记录最新用户消息：{last_turn.excerpt}"
        if assistant_messages:
            return self._shorten(assistant_messages[-1].content, 120)
        return active_goal

    def _extract_constraint_slot(
        self,
        convention_hints: list[str],
        previous_state: DialogueState,
    ) -> str:
        convention_hint = next(
            (
                item
                for item in reversed(convention_hints)
                if "powershell" in item.lower()
                or any(marker in item for marker in ("默认", "优先", "规范", "约定"))
                or any(marker in item.lower() for marker in ENGLISH_PREFERENCE_MARKERS + ENGLISH_CONVENTION_MARKERS)
            ),
            "",
        )
        if convention_hint:
            return self._shorten(convention_hint, 120)
        return previous_state.context_slots.active_rule

    def _extract_file_hints(self, messages: list[Message]) -> list[str]:
        hints: list[str] = []
        for msg in messages[-20:]:
            for found in FILE_PATTERN.finditer(msg.content):
                hints.append(found.group(0))
        return list(dict.fromkeys(hints))

    def _extract_convention_hints(self, messages: list[Message]) -> list[str]:
        hints: list[str] = []
        for msg in messages[-20:]:
            for line in msg.content.splitlines():
                stripped = line.strip()
                lowered = stripped.lower()
                if any(stripped.startswith(prefix) for prefix in COMMAND_PREFIXES):
                    hints.append(stripped)
                if any(
                    marker in lowered
                    for marker in ("powershell", "默认", "优先", "工作流", "规范", "约定", "流程", *ENGLISH_CONVENTION_MARKERS, *ENGLISH_PREFERENCE_MARKERS)
                ):
                    hints.append(stripped)
        return list(dict.fromkeys(hints))

    def _extract_error_hints(self, messages: list[Message]) -> list[str]:
        hints: list[str] = []
        for msg in messages[-20:]:
            lowered = msg.content.lower()
            if any(marker in lowered for marker in ERROR_MARKERS):
                hints.append(self._shorten(msg.content, 220))
        return hints

    def _extract_user_requests(
        self,
        turn_trace: list[TurnUnderstanding],
        *,
        max_items: int,
    ) -> list[str]:
        requests = [
            turn.excerpt
            for turn in turn_trace
            if turn.role == "user"
        ]
        if not requests:
            last_user = next((turn.excerpt for turn in reversed(turn_trace) if turn.role == "user"), "")
            if last_user:
                requests = [last_user]
        return self._dedupe_items(requests, max_items=max_items)

    def _extract_results(self, messages: list[Message]) -> list[str]:
        results: list[str] = []
        for msg in messages[-20:]:
            if self._contains_marker(msg.content, RESULT_MARKERS + ENGLISH_RESULT_MARKERS):
                results.append(self._shorten(msg.content, 240))
        return results

    def _extract_decisions(self, messages: list[Message]) -> list[str]:
        decisions: list[str] = []
        for msg in messages[-20:]:
            if self._contains_marker(msg.content, DECISION_MARKERS):
                decisions.append(self._shorten(msg.content, 220))
        return decisions

    def _infer_next_steps(
        self,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        assistant_messages: list[Message],
    ) -> list[str]:
        target = active_goal or next((turn.excerpt for turn in reversed(turn_trace) if turn.role == "user"), "")
        if not target:
            return []
        if assistant_messages:
            latest_assistant = assistant_messages[-1].content
            if any(marker in latest_assistant for marker in ("完成", "已修复", "已通过测试")):
                return [f"如果用户继续推进，优先沿着“{self._shorten(target, 60)}”继续细化。"]
        return [f"继续处理当前用户请求：{self._shorten(target, 120)}"]

    def _title_from_messages(self, messages: list[Message]) -> str:
        if not messages:
            return "Ongoing session"
        words = " ".join(messages[-1].content.split()).split()[:8]
        return " ".join(words) or "Ongoing session"

    def _assess_and_guard_risks(
        self,
        *,
        cleaned_messages: list[Message],
        previous_state: DialogueState,
        turn_trace: list[TurnUnderstanding],
        active_goal: str,
        flow_state: FlowState,
        context_slots: ContextSlots,
        warm_context: list[str],
        current_task_state: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        risk_flags: list[str] = []
        risk_notes: list[str] = []

        if self._is_cross_flow_slot_contamination(flow_state=flow_state, context_slots=context_slots):
            risk_flags.append("cross_flow_slot_contamination")
            risk_notes.append("Memory projection contains inconsistent material slots.")

        if self._has_unresolved_error_loop(turn_trace):
            risk_flags.append("unresolved_error_loop")
            risk_notes.append("Recent turns contain repeated error events; prioritize unblock and recovery step.")

        if self._contains_sensitive_pattern(cleaned_messages):
            risk_flags.append("sensitive_data_exposure")
            risk_notes.append("Potential secret-like token detected in session truth; avoid persisting raw value in memory view.")

        trimmed_warm_context = warm_context
        total_chars = sum(len(item) for item in warm_context + current_task_state)
        if total_chars > WARM_CONTEXT_CHAR_BUDGET:
            risk_flags.append("working_memory_pressure")
            risk_notes.append("Working-memory payload exceeded budget; older warm context was trimmed.")
            trimmed_warm_context = self._trim_context_by_budget(
                warm_context,
                budget=max(320, WARM_CONTEXT_CHAR_BUDGET - sum(len(item) for item in current_task_state)),
            )

        return risk_flags, risk_notes, trimmed_warm_context

    def _is_cross_flow_slot_contamination(
        self,
        *,
        flow_state: FlowState,
        context_slots: ContextSlots,
    ) -> bool:
        return bool(context_slots.active_dataset and context_slots.active_pdf)

    def _has_unresolved_error_loop(self, turn_trace: list[TurnUnderstanding]) -> bool:
        assistant_turns = [turn for turn in turn_trace[-6:] if turn.role == "assistant"]
        if len(assistant_turns) < 2:
            return False
        error_count = sum(1 for turn in assistant_turns if turn.turn_type == "error_event")
        return error_count >= 2

    def _contains_sensitive_pattern(self, messages: list[Message]) -> bool:
        for message in messages:
            content = normalize_storage_text(message.content)
            if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                return True
        return False

    def _trim_context_by_budget(self, items: list[str], *, budget: int) -> list[str]:
        remaining = max(0, budget)
        kept_reversed: list[str] = []
        for item in reversed(items):
            if remaining <= 0:
                break
            shortened = item[:remaining].rstrip()
            if shortened:
                kept_reversed.append(shortened)
                remaining -= len(shortened)
        return list(reversed(kept_reversed))

    def _dedupe_items(
        self,
        items: list[str],
        *,
        max_items: int,
        max_chars: int = 240,
    ) -> list[str]:
        deduped: list[str] = []
        for item in items:
            cleaned = " ".join(normalize_storage_text(item).split()).strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned[:max_chars].rstrip())
        return deduped[:max_items]

    def _shorten(self, text: str, limit: int) -> str:
        return self.turn_projector._shorten(text, limit)

    def _contains_marker(self, text: str, markers: tuple[str, ...]) -> bool:
        lowered = normalize_storage_text(text).lower()
        for marker in markers:
            needle = normalize_storage_text(marker).lower()
            if needle and needle in lowered:
                return True
        return False


def _binding_identity(value: str) -> str:
    return normalize_storage_text(value).replace("\\", "/").strip().lower()

