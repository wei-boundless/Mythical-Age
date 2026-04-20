from __future__ import annotations

from understanding import QueryUnderstanding, split_compound_query


class QuerySubtaskPlanner:
    def plan(self, *, message: str, understanding: QueryUnderstanding) -> list[str]:
        normalized = (message or "").strip()
        if not normalized:
            return []
        parts = split_compound_query(normalized)
        if not self._should_fan_out(understanding, parts):
            return [normalized]
        return parts

    def _should_fan_out(
        self,
        understanding: QueryUnderstanding,
        parts: list[str],
    ) -> bool:
        if len(parts) < 2:
            return False
        if understanding.route == "memory":
            return False
        return True
