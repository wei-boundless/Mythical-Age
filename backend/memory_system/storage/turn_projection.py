from __future__ import annotations

from dataclasses import dataclass
import re

from .models import Message
from .process_state import DialogueState, TurnUnderstanding
from .text_utils import normalize_storage_text

FILE_PATTERN = re.compile(
    r"[\w./-]+\.(?:py|ts|tsx|js|md|json|yaml|yml|pdf|csv|xlsx|xls|parquet)"
)
COMMAND_PREFIXES = ("python ", "pytest", "uv ", "npm ", "pnpm ", "bun ", "powershell", "Get-", "git ")
ERROR_MARKERS = ("error", "failed", "exception", "traceback", "报错", "失败", "异常")
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
DECISION_MARKERS = ("建议", "结论", "下一步", "计划", "Conclusion:")
ENGLISH_RESULT_MARKERS = (
    "conclusion:",
    "data source:",
    "result:",
    "correction:",
    "corrected",
    "updated result:",
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
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)password\s*[:=]\s*\S+"),
    re.compile(r"(?i)token\s*[:=]\s*[A-Za-z0-9._-]{8,}"),
)
WARM_CONTEXT_CHAR_BUDGET = 960


@dataclass(slots=True)
class TurnProjectionSnapshot:
    cleaned_messages: list[Message]
    user_messages: list[Message]
    assistant_messages: list[Message]
    turn_trace: list[TurnUnderstanding]
    active_goal: str
    active_goal_turn_type: str
    last_turn_type: str


class TurnProjectionBuilder:
    """Projects conversation text into memory facts without deciding task intent."""

    def project(
        self,
        messages: list[Message],
        previous_state: DialogueState,
    ) -> TurnProjectionSnapshot:
        cleaned_messages = self._clean_messages(messages)
        user_messages = [msg for msg in cleaned_messages if msg.role == "user"]
        assistant_messages = [msg for msg in cleaned_messages if msg.role == "assistant"]
        turn_trace = self._project_turns(cleaned_messages)
        active_goal = self._latest_user_excerpt(turn_trace) or previous_state.active_goal.strip()
        active_goal_turn_type = "user_message" if active_goal else "unknown"
        last_turn_type = turn_trace[-1].turn_type if turn_trace else "unknown"
        return TurnProjectionSnapshot(
            cleaned_messages=cleaned_messages,
            user_messages=user_messages,
            assistant_messages=assistant_messages,
            turn_trace=turn_trace,
            active_goal=active_goal,
            active_goal_turn_type=active_goal_turn_type,
            last_turn_type=last_turn_type,
        )

    def _clean_messages(self, messages: list[Message]) -> list[Message]:
        cleaned: list[Message] = []
        for msg in messages[-30:]:
            if msg.role not in {"user", "assistant"}:
                continue
            content = self._sanitize_message_content(msg.content)
            if content:
                cleaned.append(Message(role=msg.role, content=content, meta=msg.meta))
        return cleaned

    def _sanitize_message_content(self, content: str) -> str:
        normalized = normalize_storage_text(content)
        if not normalized or self._looks_like_noise(normalized):
            return ""
        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        return self._shorten(" ".join(lines), 320)

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
        return len(text) > 900

    def _project_turns(self, messages: list[Message]) -> list[TurnUnderstanding]:
        return [
            TurnUnderstanding(
                role=message.role,
                turn_type=f"{message.role}_message",
                excerpt=self._shorten(message.content, 180),
                intent="not_decided",
                modality="not_decided",
                target_object="",
                flow_hint="not_decided",
                constraints=[],
            )
            for message in messages
        ]

    def _latest_user_excerpt(self, turn_trace: list[TurnUnderstanding]) -> str:
        for turn in reversed(turn_trace):
            if turn.role == "user":
                return turn.excerpt
        return ""

    def _shorten(self, text: str, limit: int) -> str:
        compact = " ".join(normalize_storage_text(text).split())
        return compact[:limit] + ("..." if len(compact) > limit else "")

    def _slugify(self, text: str) -> str:
        normalized = normalize_storage_text(text).lower()
        ascii_slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if ascii_slug:
            return ascii_slug[:48]
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,12}", normalized):
            if chunk:
                return chunk[:12]
        return "active"
