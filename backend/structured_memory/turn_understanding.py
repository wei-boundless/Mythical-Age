from __future__ import annotations

from dataclasses import dataclass
import re

from understanding.task_understanding import TaskUnderstanding, analyze_task_understanding

from .dialogue_state import DialogueState, TurnUnderstanding
from .models import Message
from .text_utils import normalize_storage_text

FILE_PATTERN = re.compile(
    r"[\w./-]+\.(?:py|ts|tsx|js|md|json|yaml|yml|pdf|csv|xlsx|xls|parquet)"
)
COMMAND_PREFIXES = ("python ", "pytest", "uv ", "npm ", "pnpm ", "bun ", "powershell", "Get-", "git ")
ERROR_MARKERS = ("error", "failed", "exception", "traceback", "报错", "失败", "异常")
REQUEST_MARKERS = ("请", "帮我", "记住", "以后", "默认", "不要", "优先", "应该", "需要", "请你")
RESULT_MARKERS = (
    "数据源：",
    "结论",
    "当前价格",
    "已完成",
    "完成了",
    "修复了",
    "结果",
    "Conclusion:",
    "Data source:",
    "Result:",
)
FOLLOW_UP_MARKERS = ("继续", "然后", "接着", "另外", "还有", "顺便", "那", "再", "下一步")
EXPLICIT_SWITCH_MARKERS = ("换个问题", "新的问题", "另一个问题", "先不说这个", "顺便问一个", "回到刚才")
META_DIALOGUE_MARKERS = (
    "你在干什么",
    "你为什么这么做",
    "你刚刚在查什么",
    "你现在在做什么",
    "why are you",
    "what are you doing",
)
CORRECTION_MARKERS = ("不对", "错了", "不是这个意思", "理解错", "查错", "你查的不对", "that is wrong", "not correct")
CONSTRAINT_MARKERS = ("默认", "优先", "不要", "先给结论", "简洁", "详细一点", "powershell", "风格", "偏好")
DECISION_MARKERS = ("建议", "结论", "应该", "优先", "下一步", "我会", "改成", "计划", "设计完成", "Conclusion:")
ENGLISH_RESULT_MARKERS = (
    "conclusion:",
    "data source:",
    "result:",
    "correction:",
    "corrected",
    "updated result:",
)
ENGLISH_CONSTRAINT_MARKERS = (
    "remember that i prefer",
    "i prefer",
    "preference",
    "by default",
    "default to",
    "answer style",
    "reply style",
    "response style",
    "conclusion first",
    "give the conclusion first",
    "then explain",
)
NOISE_MARKERS = (
    "我是**",
    "我是河伯",
    "基础定位",
    "核心能力",
    "技能快照",
    "SKILLS_SNAPSHOT",
    "Title:",
)
GENERIC_TASK_TERMS = {
    "请",
    "帮我",
    "继续",
    "然后",
    "接着",
    "另外",
    "还有",
    "顺便",
    "问题",
    "新的",
    "另一个",
    "当前",
    "用户",
    "请求",
    "回到",
    "那个",
    "这个",
    "事情",
    "处理",
    "优化",
    "修改",
    "the",
    "this",
    "that",
    "with",
    "from",
    "user",
    "request",
    "current",
    "continue",
    "next",
}
TASKFUL_USER_TURNS = {"goal_request", "followup_request", "task_switch", "constraint_or_preference"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)password\s*[:=]\s*\S+"),
    re.compile(r"(?i)token\s*[:=]\s*[A-Za-z0-9._-]{8,}"),
)
WARM_CONTEXT_CHAR_BUDGET = 960


@dataclass(slots=True)
class ActiveUnderstanding:
    understanding: TaskUnderstanding
    source_excerpt: str


@dataclass(slots=True)
class TurnUnderstandingSnapshot:
    cleaned_messages: list[Message]
    user_messages: list[Message]
    assistant_messages: list[Message]
    turn_trace: list[TurnUnderstanding]
    active_goal: str
    active_goal_turn_type: str
    last_turn_type: str
    task_switch: bool
    active_understanding: ActiveUnderstanding


class TurnUnderstandingAnalyzer:
    """Owns turn-level interpretation and task/flow heuristics."""

    def analyze(
        self,
        messages: list[Message],
        previous_state: DialogueState,
    ) -> TurnUnderstandingSnapshot:
        cleaned_messages = self._clean_messages(messages)
        user_messages = [msg for msg in cleaned_messages if msg.role == "user"]
        assistant_messages = [msg for msg in cleaned_messages if msg.role == "assistant"]
        turn_trace = self._classify_turns(cleaned_messages)
        active_goal, active_goal_turn_type = self._select_active_goal(turn_trace, previous_state)
        last_turn_type = turn_trace[-1].turn_type if turn_trace else "unknown"
        task_switch = self._detect_task_switch(previous_state, turn_trace)
        active_understanding = self._resolve_active_understanding(
            active_goal,
            turn_trace,
            previous_state,
            task_switch=task_switch,
        )
        return TurnUnderstandingSnapshot(
            cleaned_messages=cleaned_messages,
            user_messages=user_messages,
            assistant_messages=assistant_messages,
            turn_trace=turn_trace,
            active_goal=active_goal,
            active_goal_turn_type=active_goal_turn_type,
            last_turn_type=last_turn_type,
            task_switch=task_switch,
            active_understanding=active_understanding,
        )

    def _resolve_active_understanding(
        self,
        active_goal: str,
        turn_trace: list[TurnUnderstanding],
        previous_state: DialogueState,
        *,
        task_switch: bool,
    ) -> ActiveUnderstanding:
        source_excerpt = active_goal
        if not source_excerpt:
            last_user_turn = next((turn for turn in reversed(turn_trace) if turn.role == "user"), None)
            if last_user_turn is not None:
                source_excerpt = last_user_turn.excerpt

        understanding = self._understanding_for_text(source_excerpt)
        last_user_turn = next((turn for turn in reversed(turn_trace) if turn.role == "user"), None)
        should_inherit_previous_flow = (
            last_user_turn is not None
            and last_user_turn.turn_type
            in {"followup_request", "correction_feedback", "meta_dialogue", "constraint_or_preference"}
        )
        if (
            understanding.confidence < 0.55
            and not task_switch
            and should_inherit_previous_flow
            and previous_state.flow_state.flow_type != "general_problem_solving_flow"
        ):
            inherited_flow = previous_state.flow_state.flow_type
            inherited_target_object = understanding.target_object
            if inherited_target_object is None and inherited_flow not in {
                "general_problem_solving_flow",
                "external_lookup_flow",
            }:
                inherited_target_object = previous_state.context_slots.active_entity or None
            understanding = TaskUnderstanding(
                intent=understanding.intent,
                source_kind=understanding.source_kind,
                task_kind=understanding.task_kind,
                target_object=inherited_target_object,
                modality=understanding.modality,
                route_hint=understanding.route_hint,
                preferred_skill=understanding.preferred_skill,
                candidate_tools=list(understanding.candidate_tools),
                parameters=dict(understanding.parameters),
                should_skip_rag=understanding.should_skip_rag,
                confidence=max(understanding.confidence, 0.6),
                reasons=list(understanding.reasons) + [f"inherited_flow:{inherited_flow}"],
            )
        return ActiveUnderstanding(understanding=understanding, source_excerpt=source_excerpt)

    def _clean_messages(self, messages: list[Message]) -> list[Message]:
        cleaned: list[Message] = []
        for msg in messages[-30:]:
            if msg.role not in {"user", "assistant"}:
                continue
            content = normalize_storage_text(msg.content)
            if not content:
                continue
            content = self._sanitize_message_content(content)
            if not content:
                continue
            cleaned.append(Message(role=msg.role, content=content, meta=msg.meta))
        return cleaned

    def _sanitize_message_content(self, content: str) -> str:
        normalized = normalize_storage_text(content)
        if not normalized:
            return ""
        if self._looks_like_noise(normalized):
            return ""
        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        collapsed = " ".join(lines)
        return self._shorten(collapsed, 320)

    def _looks_like_noise(self, text: str) -> bool:
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in NOISE_MARKERS):
            return True
        if text.startswith("{") and any(token in lowered for token in ('"results"', '"ok"', '"query"', '"request_id"')):
            return True
        if text.startswith("[") and '"type"' in lowered:
            return True
        if text.count("{") + text.count("[") >= 8 and len(text) > 220:
            return True
        if len(text) > 900:
            return True
        return False

    def _classify_turns(self, messages: list[Message]) -> list[TurnUnderstanding]:
        turns: list[TurnUnderstanding] = []
        for message in messages:
            if message.role == "user":
                task = self._understanding_for_text(message.content)
                turn_type = self._classify_user_turn(message.content)
                turns.append(
                    TurnUnderstanding(
                        role=message.role,
                        turn_type=turn_type,
                        excerpt=self._shorten(message.content, 180),
                        intent=task.intent,
                        modality=task.modality,
                        target_object=task.target_object or "",
                        flow_hint=self._flow_hint_from_understanding(message.content, task),
                        constraints=self._extract_inline_constraints(message.content),
                    )
                )
                continue

            turn_type = self._classify_assistant_turn(message.content)
            turns.append(
                TurnUnderstanding(
                    role=message.role,
                    turn_type=turn_type,
                    excerpt=self._shorten(message.content, 180),
                    intent=turn_type,
                    modality="general",
                    target_object="",
                    flow_hint="assistant_support",
                    constraints=[],
                )
            )
        return turns

    def _classify_user_turn(self, content: str) -> str:
        if self._contains_marker(content, EXPLICIT_SWITCH_MARKERS):
            return "task_switch"
        if self._contains_marker(content, META_DIALOGUE_MARKERS):
            return "meta_dialogue"
        if self._contains_marker(content, CORRECTION_MARKERS):
            return "correction_feedback"
        if self._contains_marker(content, FOLLOW_UP_MARKERS) and len(content) <= 80:
            return "followup_request"
        if self._contains_marker(content, CONSTRAINT_MARKERS + ENGLISH_CONSTRAINT_MARKERS):
            return "constraint_or_preference"
        return "goal_request"

    def _classify_assistant_turn(self, content: str) -> str:
        if self._contains_marker(content, ERROR_MARKERS):
            return "error_event"
        if self._contains_marker(content, RESULT_MARKERS + ENGLISH_RESULT_MARKERS):
            return "result_delivery"
        if self._contains_marker(content, DECISION_MARKERS):
            return "decision_or_plan"
        return "assistant_update"

    def _select_active_goal(
        self,
        turn_trace: list[TurnUnderstanding],
        previous_state: DialogueState,
    ) -> tuple[str, str]:
        active_goal = previous_state.active_goal.strip()
        active_goal_turn_type = previous_state.active_goal_turn_type or "unknown"
        for turn in turn_trace:
            if turn.role != "user":
                continue
            if turn.turn_type in {"goal_request", "task_switch"}:
                active_goal = turn.excerpt
                active_goal_turn_type = turn.turn_type
            elif turn.turn_type == "followup_request" and not active_goal:
                active_goal = turn.excerpt
                active_goal_turn_type = turn.turn_type
        if not active_goal:
            last_user_turn = next((turn for turn in reversed(turn_trace) if turn.role == "user"), None)
            if last_user_turn is not None:
                active_goal = last_user_turn.excerpt
                active_goal_turn_type = last_user_turn.turn_type
        return active_goal, active_goal_turn_type

    def _understanding_for_text(self, text: str) -> TaskUnderstanding:
        understanding = analyze_task_understanding(text)
        if understanding.confidence >= 0.6:
            return understanding

        lowered = normalize_storage_text(text).lower()
        if self._looks_like_coding_request(text):
            return TaskUnderstanding(
                intent="coding_change_query",
                source_kind="workspace",
                task_kind="code_change",
                target_object=self._infer_code_target(text),
                modality="code",
                route_hint="tool",
                candidate_tools=["workspace_search"],
                should_skip_rag=True,
                confidence=0.9,
                reasons=["coding_markers"],
            )
        if self._looks_like_architecture_request(text):
            return TaskUnderstanding(
                intent="architecture_design_query",
                source_kind="workspace",
                task_kind="architecture_design",
                target_object=self._infer_architecture_target(lowered),
                modality="code",
                route_hint="tool",
                candidate_tools=["workspace_search"],
                should_skip_rag=True,
                confidence=0.88,
                reasons=["architecture_markers"],
            )
        return understanding

    def _flow_hint_from_understanding(self, content: str, understanding: TaskUnderstanding) -> str:
        if understanding.modality == "pdf":
            return "pdf_analysis_flow"
        if understanding.modality == "table":
            return "structured_data_flow"
        if understanding.modality in {"realtime", "web"}:
            return "external_lookup_flow"
        if self._looks_like_coding_request(content):
            return "coding_change_flow"
        if self._looks_like_architecture_request(content):
            return "architecture_design_flow"
        if understanding.route_hint == "rag":
            return "knowledge_lookup_flow"
        return "general_problem_solving_flow"

    def _extract_inline_constraints(self, content: str) -> list[str]:
        if self._contains_marker(content, CONSTRAINT_MARKERS + ENGLISH_CONSTRAINT_MARKERS):
            return [self._shorten(content, 120)]
        return []

    def _contains_marker(self, text: str, markers: tuple[str, ...]) -> bool:
        haystack = normalize_storage_text(text).lower()
        for marker in markers:
            needle = normalize_storage_text(marker).lower()
            if needle and needle in haystack:
                return True
        return False

    def _detect_task_switch(
        self,
        previous_state: DialogueState,
        turn_trace: list[TurnUnderstanding],
    ) -> bool:
        last_user_turn = next((turn for turn in reversed(turn_trace) if turn.role == "user"), None)
        if last_user_turn is None:
            return False
        if last_user_turn.turn_type == "task_switch":
            return True
        if last_user_turn.turn_type in {"followup_request", "correction_feedback", "meta_dialogue", "constraint_or_preference"}:
            return False
        previous_goal = previous_state.active_goal.strip()
        if not previous_goal or last_user_turn.turn_type != "goal_request":
            return False
        previous_terms = self._extract_terms(previous_goal)
        latest_terms = self._extract_terms(last_user_turn.excerpt)
        if len(previous_terms) < 2 or len(latest_terms) < 2:
            return False
        return len(previous_terms & latest_terms) == 0

    def _extract_terms(self, text: str) -> set[str]:
        normalized = normalize_storage_text(text).lower()
        terms: set[str] = set(re.findall(r"[a-z0-9_.+#-]{2,}", normalized))
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", normalized):
            terms.add(chunk)
            max_window = min(4, len(chunk))
            for window in range(2, max_window + 1):
                for start in range(0, len(chunk) - window + 1):
                    terms.add(chunk[start : start + window])
        return {
            term
            for term in terms
            if term.strip() and term not in GENERIC_TASK_TERMS and len(term.strip()) >= 2
        }

    def _candidate_hints(self, text: str) -> list[str]:
        hints: list[str] = []
        normalized = normalize_storage_text(text)
        for token in re.findall(r"[A-Za-z0-9_.+#-]{2,}", normalized):
            if token not in hints:
                hints.append(token)
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,10}", normalized):
            if chunk not in hints:
                hints.append(chunk)
        return hints[:6]

    def _looks_like_coding_request(self, text: str) -> bool:
        lowered = normalize_storage_text(text).lower()
        return any(
            marker in lowered
            for marker in (
                ".py",
                ".ts",
                ".tsx",
                "backend/",
                "frontend/",
                "session memory",
                "memory bridge",
                "memory system",
                "code",
                "fix",
                "refactor",
                "implement",
                "optimize",
                "重构",
                "修复",
                "实现",
                "修改",
                "代码",
                "项目",
            )
        )

    def _looks_like_architecture_request(self, text: str) -> bool:
        lowered = normalize_storage_text(text).lower()
        return any(
            marker in lowered
            for marker in (
                "architecture",
                "design",
                "flow",
                "pipeline",
                "memory system",
                "session state",
                "working memory",
                "架构",
                "流程",
                "状态层",
                "工作记忆",
                "上下文管理",
            )
        )

    def _infer_code_target(self, text: str) -> str | None:
        match = FILE_PATTERN.search(normalize_storage_text(text))
        if match:
            return match.group(0)
        lowered = normalize_storage_text(text).lower()
        if "session memory" in lowered:
            return "session_memory"
        if "memory bridge" in lowered:
            return "memory_bridge"
        return None

    def _infer_architecture_target(self, lowered: str) -> str | None:
        if "session memory" in lowered:
            return "session_memory"
        if "memory system" in lowered:
            return "memory_system"
        if "context management" in lowered:
            return "context_management"
        return None

    def _slugify(self, text: str) -> str:
        normalized = normalize_storage_text(text).lower()
        ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if ascii_slug:
            return ascii_slug[:48]
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", normalized):
            if chunk:
                return chunk[:12]
        return "active"

    def _shorten(self, text: str, limit: int) -> str:
        compact = " ".join(normalize_storage_text(text).split())
        return compact[:limit] + ("..." if len(compact) > limit else "")
