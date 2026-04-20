from __future__ import annotations

import re

from understanding import QueryUnderstanding, split_compound_query


RESOURCE_PATH_PATTERN = re.compile(
    r"(?i)(?:^|[\s:：'\"“”‘’(（])(?:[A-Za-z]:[\\/]|\.{0,2}[\\/]|knowledge[\\/])[^\s]+?\.(pdf|xlsx|csv|json|md|txt)\b"
)


class QuerySubtaskPlanner:
    def plan(self, *, message: str, understanding: QueryUnderstanding) -> list[str]:
        normalized = (message or "").strip()
        if not normalized:
            return []
        if not self._should_fan_out(normalized, understanding):
            return [normalized]
        parts = split_compound_query(normalized)
        return parts if len(parts) >= 2 else [normalized]

    def _should_fan_out(self, message: str, understanding: QueryUnderstanding) -> bool:
        if understanding.route in {"tool", "memory"}:
            return False
        if RESOURCE_PATH_PATTERN.search(message):
            return False
        return True
