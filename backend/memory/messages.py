from __future__ import annotations

from typing import Any

from structured_memory import Message


class MemoryMessageAdapter:
    def looks_like_skill_document(self, content: str) -> bool:
        normalized = content.strip()
        if not normalized:
            return False
        lowered = normalized.lower()
        if "skills/" in lowered and "/skill.md" in lowered:
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

    def should_skip_message(self, role: str, content: str) -> bool:
        if role == "tool":
            return self.looks_like_skill_document(content)
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
            if self.should_skip_message(role, content):
                continue
            meta = dict(item.get("meta", {}) or {})
            if session_id:
                meta["session_id"] = session_id
            converted.append(Message(role=role, content=content, meta=meta))
        return converted
