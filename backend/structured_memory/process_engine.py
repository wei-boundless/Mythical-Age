
from __future__ import annotations

import re

from understanding.task_understanding import TaskUnderstanding

from .dialogue_state import ContextSlots, DialogueState, FlowState, TaskState, TurnUnderstanding
from .models import Message, utc_now_iso
from .text_utils import normalize_storage_text
from .turn_understanding import (
    ActiveUnderstanding,
    COMMAND_PREFIXES,
    DECISION_MARKERS,
    ENGLISH_RESULT_MARKERS,
    ERROR_MARKERS,
    FILE_PATTERN,
    RESULT_MARKERS,
    SECRET_PATTERNS,
    TASKFUL_USER_TURNS,
    TurnUnderstandingAnalyzer,
    TurnUnderstandingSnapshot,
    WARM_CONTEXT_CHAR_BUDGET,
)
from .understanding_reconciliation import ReconciliationDecision

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
    """Owns process-state assembly from a reconciled understanding snapshot."""

    def __init__(self, turn_analyzer: TurnUnderstandingAnalyzer | None = None) -> None:
        self.turn_analyzer = turn_analyzer or TurnUnderstandingAnalyzer()

    def assemble(
        self,
        snapshot: TurnUnderstandingSnapshot,
        previous_state: DialogueState,
        *,
        decision: ReconciliationDecision | None = None,
        max_items: int = 6,
    ) -> DialogueState:
        decision = decision or ReconciliationDecision()
        active_goal, active_goal_turn_type, task_switch = self._resolve_active_goal_fields(
            snapshot,
            previous_state,
            decision=decision,
        )
        projected_messages, projected_assistant_messages = self._apply_reconciliation_to_projection(
            snapshot.cleaned_messages,
            snapshot.turn_trace,
            decision=decision,
        )
        file_hints = self._extract_file_hints(projected_messages)
        convention_hints = self._extract_convention_hints(projected_messages)
        decision_items = self._extract_decisions(projected_assistant_messages)
        result_items = self._extract_results(projected_assistant_messages)
        request_items = self._extract_user_requests(snapshot.turn_trace, max_items=max_items)
        next_steps = self._infer_next_steps(active_goal, snapshot.turn_trace, projected_assistant_messages)
        next_steps = self._apply_reconciliation_to_next_steps(
            next_steps,
            active_goal=active_goal,
            decision=decision,
            max_items=max_items,
        )
        current_task_state = self._build_current_state(
            active_goal,
            snapshot.turn_trace,
            projected_assistant_messages,
            active_understanding=snapshot.active_understanding,
            max_items=max_items,
        )
        warm_context = self._build_warm_context(
            previous_state,
            active_goal,
            snapshot.turn_trace,
            projected_assistant_messages,
            task_switch=task_switch,
            max_items=max_items,
        )
        flow_state = self._build_flow_state(
            active_goal,
            active_understanding=snapshot.active_understanding,
            previous_state=previous_state,
            turn_trace=snapshot.turn_trace,
            task_switch=task_switch,
            file_hints=file_hints,
        )
        flow_state = self._apply_reconciliation_to_flow_state(
            flow_state,
            previous_state=previous_state,
            decision=decision,
        )
        task_state = self._build_task_state(
            active_goal,
            snapshot.turn_trace,
            projected_assistant_messages,
            previous_state=previous_state,
            task_switch=task_switch,
            next_steps=next_steps,
        )
        context_slots = self._build_context_slots(
            active_goal,
            active_understanding=snapshot.active_understanding,
            previous_state=previous_state,
            task_switch=task_switch,
            convention_hints=convention_hints,
            turn_trace=snapshot.turn_trace,
        )
        context_slots = self._apply_reconciliation_to_context_slots(
            context_slots,
            turn_trace=snapshot.turn_trace,
            decision=decision,
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
            task_switch=task_switch,
        )
        risk_flags, risk_notes = self._apply_reconciliation_to_risks(
            risk_flags,
            risk_notes,
            decision=decision,
            max_items=max_items,
        )
        errors_and_corrections = self._apply_reconciliation_to_errors(
            self._extract_error_hints(projected_assistant_messages),
            decision=decision,
            max_items=max_items,
        )

        return DialogueState(
            version=2,
            updated_at=utc_now_iso(),
            session_title=self._title_from_messages(snapshot.user_messages or projected_messages),
            active_goal=active_goal,
            active_goal_turn_type=active_goal_turn_type,
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
            key_results=self._dedupe_items(result_items, max_items=max_items),
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
        snapshot: TurnUnderstandingSnapshot,
        previous_state: DialogueState,
        *,
        decision: ReconciliationDecision,
    ) -> tuple[str, str, bool]:
        active_goal = snapshot.active_goal
        active_goal_turn_type = snapshot.active_goal_turn_type
        task_switch = snapshot.task_switch

        if decision.preserve_previous_goal and previous_state.active_goal.strip():
            active_goal = previous_state.active_goal
            active_goal_turn_type = previous_state.active_goal_turn_type or active_goal_turn_type
            task_switch = False

        if decision.preserve_previous_flow:
            task_switch = False

        return active_goal, active_goal_turn_type, task_switch

    def _apply_reconciliation_to_projection(
        self,
        cleaned_messages: list[Message],
        turn_trace: list[TurnUnderstanding],
        *,
        decision: ReconciliationDecision,
    ) -> tuple[list[Message], list[Message]]:
        if not decision.facts_to_block:
            assistant_messages = [message for message in cleaned_messages if message.role == "assistant"]
            return cleaned_messages, assistant_messages

        blocked_indexes: set[int] = set()
        correction_boundary = self._latest_turn_index(
            turn_trace,
            role="user",
            turn_type="correction_feedback",
        )

        for fact_name in decision.facts_to_block:
            if fact_name == "latest_assistant_result":
                blocked_index = self._latest_turn_index(
                    turn_trace,
                    role="assistant",
                    turn_type="result_delivery",
                    before_index=correction_boundary,
                )
            elif fact_name == "latest_assistant_decision":
                blocked_index = self._latest_turn_index(
                    turn_trace,
                    role="assistant",
                    turn_type="decision_or_plan",
                    before_index=correction_boundary,
                )
            else:
                blocked_index = None
            if blocked_index is not None:
                blocked_indexes.add(blocked_index)

        projected_messages = [
            message
            for index, message in enumerate(cleaned_messages)
            if index not in blocked_indexes
        ]
        projected_assistant_messages = [message for message in projected_messages if message.role == "assistant"]
        return projected_messages, projected_assistant_messages

    def _latest_turn_index(
        self,
        turn_trace: list[TurnUnderstanding],
        *,
        role: str,
        turn_type: str,
        before_index: int | None = None,
    ) -> int | None:
        end_index = before_index if before_index is not None else len(turn_trace)
        for index in range(min(len(turn_trace), end_index) - 1, -1, -1):
            turn = turn_trace[index]
            if turn.role == role and turn.turn_type == turn_type:
                return index
        return None

    def _apply_reconciliation_to_flow_state(
        self,
        flow_state: FlowState,
        *,
        previous_state: DialogueState,
        decision: ReconciliationDecision,
    ) -> FlowState:
        next_flow_state = FlowState(
            flow_id=flow_state.flow_id,
            flow_type=flow_state.flow_type,
            status=flow_state.status,
            confidence=flow_state.confidence,
        )

        if decision.preserve_previous_flow:
            next_flow_state = FlowState(
                flow_id=previous_state.flow_state.flow_id,
                flow_type=previous_state.flow_state.flow_type,
                status=flow_state.status or previous_state.flow_state.status,
                confidence=previous_state.flow_state.confidence,
            )

        if decision.confidence_override is not None:
            next_flow_state.confidence = round(max(0.0, min(1.0, decision.confidence_override)), 2)

        return next_flow_state

    def _apply_reconciliation_to_context_slots(
        self,
        context_slots: ContextSlots,
        *,
        turn_trace: list[TurnUnderstanding],
        decision: ReconciliationDecision,
    ) -> ContextSlots:
        next_slots = ContextSlots(
            active_pdf=context_slots.active_pdf,
            active_pdf_mode=context_slots.active_pdf_mode,
            active_pdf_section=context_slots.active_pdf_section,
            active_pdf_pages=list(context_slots.active_pdf_pages),
            active_dataset=context_slots.active_dataset,
            active_entity=context_slots.active_entity,
            active_rule=context_slots.active_rule,
        )

        latest_turn = turn_trace[-1] if turn_trace else None
        immediate_correction_turn = (
            latest_turn is not None
            and latest_turn.role == "user"
            and latest_turn.turn_type == "correction_feedback"
        )
        if not immediate_correction_turn:
            return next_slots

        for slot_name in decision.slots_to_clear:
            if hasattr(next_slots, slot_name):
                setattr(next_slots, slot_name, "")

        return next_slots

    def _apply_reconciliation_to_next_steps(
        self,
        next_steps: list[str],
        *,
        active_goal: str,
        decision: ReconciliationDecision,
        max_items: int,
    ) -> list[str]:
        items = list(next_steps)
        target = self._shorten(active_goal, 80) if active_goal else "当前请求"

        if decision.needs_clarification:
            items.insert(0, f"先向用户澄清当前目标，再决定是否切换流程：{target}")
        elif decision.action == "repair_state":
            items.insert(0, f"根据最新纠正回收偏差，并重新确认后继续推进：{target}")
        elif decision.action == "rollback_partial":
            items.insert(0, "先回滚冲突事实，再基于新证据恢复流程。")

        return self._dedupe_items(items, max_items=max_items)

    def _apply_reconciliation_to_risks(
        self,
        risk_flags: list[str],
        risk_notes: list[str],
        *,
        decision: ReconciliationDecision,
        max_items: int,
    ) -> tuple[list[str], list[str]]:
        next_flags = list(risk_flags)
        next_notes = list(risk_notes)

        if decision.action == "repair_state":
            next_flags.append("state_repair_pending")
            next_notes.append(
                "User correction invalidated part of the last committed interpretation; stale state was cleared conservatively."
            )
        if decision.action == "rollback_partial":
            next_flags.append("partial_state_rollback")
            next_notes.append("Conflicting evidence blocked part of the current state commit; revalidation is required.")
        if decision.needs_clarification:
            next_flags.append("clarification_required")
            next_notes.append("Potential flow switch was downgraded because understanding confidence is too low.")
        elif decision.preserve_previous_flow and decision.conflict_type:
            next_notes.append("A potential flow switch was detected, but the prior flow stayed active until evidence improves.")

        return (
            self._dedupe_items(next_flags, max_items=max_items),
            self._dedupe_items(next_notes, max_items=max_items),
        )

    def _apply_reconciliation_to_errors(
        self,
        error_items: list[str],
        *,
        decision: ReconciliationDecision,
        max_items: int,
    ) -> list[str]:
        items = list(error_items)
        if decision.action == "repair_state":
            items.append("用户纠正触发状态修复，上一轮冲突结果不会继续晋升到工作记忆。")
        if decision.needs_clarification:
            items.append("低置信度流程切换已降级处理，等待进一步澄清。")
        return self._dedupe_items(items, max_items=max_items)

    def _extract_terms(self, text: str) -> set[str]:
        return self.turn_analyzer._extract_terms(text)

    def _looks_like_coding_request(self, text: str) -> bool:
        return self.turn_analyzer._looks_like_coding_request(text)

    def _looks_like_architecture_request(self, text: str) -> bool:
        return self.turn_analyzer._looks_like_architecture_request(text)

    def _slugify(self, text: str) -> str:
        return self.turn_analyzer._slugify(text)

    def _build_flow_state(
        self,
        active_goal: str,
        *,
        active_understanding: ActiveUnderstanding,
        previous_state: DialogueState,
        turn_trace: list[TurnUnderstanding],
        task_switch: bool,
        file_hints: list[str],
    ) -> FlowState:
        understanding = active_understanding.understanding
        flow_type = self._infer_flow_type(active_goal, understanding, previous_state, file_hints)
        if not task_switch and previous_state.flow_state.flow_type == flow_type:
            flow_id = previous_state.flow_state.flow_id
        else:
            flow_id = f"{flow_type}:{self._slugify(active_goal or 'active')}"
        return FlowState(
            flow_id=flow_id,
            flow_type=flow_type,
            status=self._infer_flow_status(turn_trace),
            confidence=round(max(understanding.confidence, 0.35 if active_goal else 0.0), 2),
        )

    def _build_task_state(
        self,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        assistant_messages: list[Message],
        *,
        previous_state: DialogueState,
        task_switch: bool,
        next_steps: list[str],
    ) -> TaskState:
        completed_steps: list[str] = []
        if not task_switch:
            completed_steps.extend(previous_state.task_state.completed_steps[-1:])
        completed_steps.extend(
            f"已完成：{self._shorten(item, 120)}"
            for item in self._extract_results(assistant_messages)[-2:]
        )
        completed_steps.extend(
            f"已确定：{self._shorten(item, 120)}"
            for item in self._extract_decisions(assistant_messages)[-1:]
        )

        pending_steps = list(next_steps[:2])
        current_step = self._infer_current_step(active_goal, turn_trace, assistant_messages)
        if task_switch and active_goal:
            pending_steps.insert(0, f"为新流程建立上下文：{self._shorten(active_goal, 80)}")

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
        active_understanding: ActiveUnderstanding,
        previous_state: DialogueState,
        task_switch: bool,
        convention_hints: list[str],
        turn_trace: list[TurnUnderstanding],
    ) -> ContextSlots:
        active_pdf, active_dataset = self._extract_slots_from_active_goal(active_goal)
        active_pdf_mode = self._infer_pdf_mode_from_goal(active_goal)
        active_pdf_section = self._extract_pdf_section_from_goal(active_goal)
        active_pdf_pages = self._extract_pdf_pages_from_goal(active_goal)

        active_entity = self._infer_active_entity(
            active_goal,
            active_understanding.understanding,
            previous_state,
            active_pdf=active_pdf,
            active_dataset=active_dataset,
            task_switch=task_switch,
        )
        active_rule = self._extract_constraint_slot(turn_trace, convention_hints, previous_state, task_switch=task_switch)

        return ContextSlots(
            active_pdf=active_pdf,
            active_pdf_mode=active_pdf_mode if active_pdf else "",
            active_pdf_section=active_pdf_section if active_pdf else "",
            active_pdf_pages=active_pdf_pages if active_pdf else [],
            active_dataset=active_dataset,
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
        active_understanding: ActiveUnderstanding,
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        last_user_turn = next((turn for turn in reversed(turn_trace) if turn.role == "user"), None)
        understanding = active_understanding.understanding

        if active_goal:
            items.append(f"当前关注的用户问题：{active_goal}")
        if understanding.task_kind and understanding.task_kind != "knowledge_lookup":
            items.append(f"当前处理形态：{understanding.task_kind}")
        if last_user_turn is not None and last_user_turn.turn_type == "correction_feedback":
            items.append(f"最新用户反馈：{last_user_turn.excerpt}")
        if last_user_turn is not None and last_user_turn.turn_type == "meta_dialogue":
            items.append(f"最新元对话：{last_user_turn.excerpt}")
        latest_result = self._extract_results(assistant_messages)
        if latest_result:
            items.append(f"最近产出：{self._shorten(latest_result[-1], 180)}")
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
        task_switch: bool,
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        previous_goal = previous_state.active_goal
        previous_state_items = list(previous_state.current_task_state)
        previous_results = list(previous_state.key_results)
        previous_warm = list(previous_state.warm_context)

        if task_switch and previous_goal and previous_goal != active_goal:
            items.extend(f"上一阶段目标：{item}" for item in [previous_goal][:1])
            items.extend(f"上一阶段状态：{item}" for item in previous_state_items[:1])
            items.extend(f"上一阶段结果：{item}" for item in previous_results[:1])
            items.extend(previous_warm[:2])
        else:
            items.extend(previous_warm[:2])
            items.extend(f"延续状态：{item}" for item in previous_state_items[:1])

        assistant_context = assistant_messages[:-1] if len(assistant_messages) > 1 else []
        recent_decisions = self._extract_decisions(assistant_context)[-1:]
        items.extend(f"近期结论：{item}" for item in recent_decisions)

        recent_results = self._extract_results(assistant_context)[-1:]
        items.extend(f"近期结果：{item}" for item in recent_results)

        prior_requests = [
            turn.excerpt
            for turn in turn_trace[:-1]
            if turn.role == "user" and turn.turn_type in TASKFUL_USER_TURNS
        ][-1:]
        items.extend(f"此前请求：{item}" for item in prior_requests)

        return self._dedupe_items(items, max_items=max_items)

    def _infer_flow_type(
        self,
        active_goal: str,
        understanding: TaskUnderstanding,
        previous_state: DialogueState,
        file_hints: list[str],
    ) -> str:
        lowered = normalize_storage_text(active_goal).lower()
        if any(item.lower().endswith(".pdf") for item in file_hints) or understanding.modality == "pdf":
            return "pdf_analysis_flow"
        if understanding.modality == "table" or any(
            item.lower().endswith((".csv", ".xlsx", ".xls", ".parquet"))
            for item in file_hints
        ):
            return "structured_data_flow"
        if understanding.modality in {"realtime", "web"}:
            return "external_lookup_flow"
        if self._looks_like_coding_request(active_goal):
            return "coding_change_flow"
        if self._looks_like_architecture_request(active_goal):
            return "architecture_design_flow"
        if understanding.route_hint == "rag":
            return "knowledge_lookup_flow"
        if previous_state.flow_state.flow_type != "general_problem_solving_flow" and not lowered:
            return previous_state.flow_state.flow_type
        return "general_problem_solving_flow"

    def _infer_flow_status(self, turn_trace: list[TurnUnderstanding]) -> str:
        last_turn = turn_trace[-1] if turn_trace else None
        if last_turn is None:
            return "idle"
        if last_turn.role == "assistant" and last_turn.turn_type == "error_event":
            return "blocked"
        if last_turn.role == "assistant" and last_turn.turn_type in {"result_delivery", "decision_or_plan"}:
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
            mapping = {
                "goal_request": "处理当前用户目标",
                "followup_request": "承接当前流程继续推进",
                "task_switch": "切换到新流程并建立上下文",
                "constraint_or_preference": "吸收用户约束并调整输出",
                "correction_feedback": "根据用户纠正回收偏差",
                "meta_dialogue": "解释当前处理进度并保持主目标稳定",
            }
            prefix = mapping.get(last_turn.turn_type, "推进当前流程")
            return f"{prefix}：{last_turn.excerpt}"
        if last_turn.turn_type == "error_event":
            return "修复当前阻塞并恢复主流程"
        if last_turn.turn_type == "result_delivery":
            return "基于当前结果等待用户确认或继续下一步"
        if last_turn.turn_type == "decision_or_plan":
            return "按照当前方案继续执行"
        if assistant_messages:
            return self._shorten(assistant_messages[-1].content, 120)
        return active_goal

    def _infer_active_entity(
        self,
        active_goal: str,
        understanding: TaskUnderstanding,
        previous_state: DialogueState,
        *,
        active_pdf: str,
        active_dataset: str,
        task_switch: bool,
    ) -> str:
        if active_pdf:
            return "pdf_document"
        if active_dataset:
            return "dataset"
        if understanding.modality in {"realtime", "web"}:
            return ""

        lowered = normalize_storage_text(active_goal).lower()
        if "session memory" in lowered:
            return "session_memory"
        if "memory bridge" in lowered:
            return "memory_bridge"
        if "memory system" in lowered or "记忆系统" in active_goal:
            return "memory_system"
        if "context management" in lowered:
            return "context_management"
        if not task_switch and self._can_carry_forward_active_entity(previous_state.context_slots.active_entity):
            return previous_state.context_slots.active_entity
        return ""

    def _can_carry_forward_active_entity(self, active_entity: str) -> bool:
        entity = normalize_storage_text(active_entity)
        return bool(entity) and entity not in {"pdf_document", "dataset"}

    def _extract_constraint_slot(
        self,
        turn_trace: list[TurnUnderstanding],
        convention_hints: list[str],
        previous_state: DialogueState,
        *,
        task_switch: bool,
    ) -> str:
        latest_constraint = next(
            (
                turn.excerpt
                for turn in reversed(turn_trace)
                if turn.role == "user" and turn.turn_type == "constraint_or_preference"
            ),
            "",
        )
        if latest_constraint:
            return self._shorten(latest_constraint, 120)
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
        if not task_switch:
            return previous_state.context_slots.active_rule
        return ""

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
            if turn.role == "user" and turn.turn_type in TASKFUL_USER_TURNS
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
        task_switch: bool,
    ) -> tuple[list[str], list[str], list[str]]:
        risk_flags: list[str] = []
        risk_notes: list[str] = []

        if flow_state.confidence < 0.55 and active_goal.strip():
            risk_flags.append("low_flow_confidence")
            risk_notes.append("Flow confidence is low; keep state conservative and verify user intent before major shifts.")

        if self._is_cross_flow_slot_contamination(flow_state=flow_state, context_slots=context_slots):
            risk_flags.append("cross_flow_slot_contamination")
            risk_notes.append("Slot data appears inconsistent with current flow; stale context may bleed into this turn.")

        if self._is_implicit_goal_jump(previous_state=previous_state, active_goal=active_goal, task_switch=task_switch):
            risk_flags.append("implicit_goal_jump")
            risk_notes.append("Active goal changed without explicit switch signal; this may indicate state drift.")

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
        if flow_state.flow_type in {"external_lookup_flow", "general_problem_solving_flow"}:
            if context_slots.active_dataset or context_slots.active_pdf:
                return True
        if flow_state.flow_type == "pdf_analysis_flow" and context_slots.active_dataset:
            return True
        if flow_state.flow_type == "structured_data_flow" and context_slots.active_pdf:
            return True
        return False

    def _is_implicit_goal_jump(
        self,
        *,
        previous_state: DialogueState,
        active_goal: str,
        task_switch: bool,
    ) -> bool:
        if task_switch:
            return False
        previous_goal = previous_state.active_goal.strip()
        current_goal = active_goal.strip()
        if not previous_goal or not current_goal or previous_goal == current_goal:
            return False
        previous_terms = self._extract_terms(previous_goal)
        current_terms = self._extract_terms(current_goal)
        if len(previous_terms) < 2 or len(current_terms) < 2:
            return False
        return len(previous_terms & current_terms) == 0

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
        return self.turn_analyzer._shorten(text, limit)

    def _contains_marker(self, text: str, markers: tuple[str, ...]) -> bool:
        lowered = normalize_storage_text(text).lower()
        for marker in markers:
            needle = normalize_storage_text(marker).lower()
            if needle and needle in lowered:
                return True
        return False
