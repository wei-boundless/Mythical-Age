from __future__ import annotations

from typing import Any

from output_boundary import sanitize_visible_assistant_content
from .legacy_types import Message


class MemoryMessageAdapter:
    CONTROL_PLANE_MARKERS = (
        "Runtime Stage Projection",
        "Runtime Context Package",
        "OperationGate",
        "ResourcePolicy",
        "ResourceRuntimeView",
        "当前投影",
        "任务契约",
        "资源边界",
        "护栏",
        "共同契约",
        "身份锚点",
    )
    CONTROL_PLANE_INLINE_MARKERS = (
        "runtime_view_only",
        "runtime_executable=false",
        "runtime_executable: false",
        "authorization_owner=ResourcePolicy",
    )

    def looks_like_skill_document(self, content: str) -> bool:
        normalized = content.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if "/skills/" in lowered and "/skill.md" in lowered:
            return True
        has_skill_frontmatter = (
            (normalized.startswith("---") or lowered.startswith("name:"))
            and "metadata:" in lowered
            and "description:" in lowered
        )
        heading_hits = sum(
            1
            for marker in (
                "## execution steps",
                "## lessons learned",
                "## troubleshooting",
                "## output format",
                "目标",
                "执行步骤",
                "输出格式",
                "故障排查",
                "查询策略",
            )
            if marker in normalized or marker in lowered
        )
        if has_skill_frontmatter and heading_hits >= 1:
            return True
        if "display_name:" in lowered and heading_hits >= 1:
            return True
        return False

    def looks_like_control_plane_contract(self, content: str) -> bool:
        normalized = str(content or "").strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if any(marker.lower() in lowered for marker in self.CONTROL_PLANE_INLINE_MARKERS):
            return True
        marker_hits = sum(1 for marker in self.CONTROL_PLANE_MARKERS if marker.lower() in lowered)
        if marker_hits >= 2:
            return True
        if "# 当前风格" in normalized and "# 共同契约" in normalized:
            return True
        if "## Runtime Stage Projection" in normalized or "## Runtime Context Package" in normalized:
            return True
        return False

    def sanitize_memory_content(self, role: str, content: str) -> str:
        if role in {"assistant", "tool"}:
            content = sanitize_visible_assistant_content(content)
        if self.looks_like_control_plane_contract(content):
            return ""
        return content.strip()

    def should_skip_message(self, role: str, content: str, item: dict[str, Any] | None = None) -> bool:
        if role == "system":
            return True
        if self.looks_like_control_plane_contract(content):
            return True
        if role == "tool":
            return self.looks_like_skill_document(content)
        if role == "assistant":
            canonical_state = str((item or {}).get("answer_canonical_state", "") or "").strip()
            if canonical_state and canonical_state not in {"stable_answer", "tool_summary"}:
                return True
        if role == "assistant" and self.looks_like_skill_document(content):
            return True
        return False

    def to_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
    ) -> list[Message]:
        converted: list[Message] = []
        for item in messages:
            role = str(item.get("role", "") or "")
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            content = str(item.get("content", "") or "")
            content = self.sanitize_memory_content(role, content)
            if self.should_skip_message(role, content, item):
                continue
            if not content.strip():
                continue
            meta = dict(item.get("meta", {}) or {})
            for key in (
                "answer_channel",
                "answer_source",
                "answer_canonical_state",
                "answer_persist_policy",
                "answer_finalization_policy",
                "answer_fallback_reason",
            ):
                value = item.get(key)
                if value is None:
                    continue
                normalized = str(value or "").strip()
                if normalized:
                    meta[key] = normalized
            if session_id:
                meta["session_id"] = session_id
            converted.append(Message(role=role, content=content, meta=meta))
        return converted
