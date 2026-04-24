from __future__ import annotations

from query.models import SubtaskPlan
from understanding import QueryUnderstanding


class InvalidSubtaskPlan(ValueError):
    pass


class QuerySubtaskPlanner:
    def plan_structured(
        self,
        *,
        message: str,
        understanding: QueryUnderstanding,
        explicit_subtasks: list[dict[str, object]] | None = None,
    ) -> list[SubtaskPlan]:
        normalized = (message or "").strip()
        if not normalized:
            return []
        if explicit_subtasks:
            return self._parse_explicit_subtasks(explicit_subtasks)
        return [SubtaskPlan.single(normalized)]

    def _parse_explicit_subtasks(self, items: list[dict[str, object]]) -> list[SubtaskPlan]:
        subtasks: list[SubtaskPlan] = []
        seen_ids: set[str] = set()
        for index, raw_item in enumerate(items, start=1):
            if not isinstance(raw_item, dict):
                raise InvalidSubtaskPlan("explicit subtask must be an object")
            subtask_id = str(raw_item.get("subtask_id") or raw_item.get("id") or f"task-{index}").strip()
            execution_message = str(raw_item.get("execution_message") or raw_item.get("message") or "").strip()
            goal = str(raw_item.get("goal") or execution_message).strip()
            title = str(raw_item.get("user_visible_title") or raw_item.get("title") or goal).strip()
            if not subtask_id or not execution_message or not goal:
                raise InvalidSubtaskPlan("explicit subtask requires id, goal, and execution_message")
            if subtask_id in seen_ids:
                raise InvalidSubtaskPlan(f"duplicate explicit subtask id: {subtask_id}")
            seen_ids.add(subtask_id)
            depends_on = raw_item.get("depends_on") or []
            refs = raw_item.get("refs") or {}
            constraints = raw_item.get("constraints") or {}
            if not isinstance(depends_on, list) or not isinstance(refs, dict) or not isinstance(constraints, dict):
                raise InvalidSubtaskPlan("depends_on must be list; refs and constraints must be objects")
            subtasks.append(
                SubtaskPlan(
                    subtask_id=subtask_id,
                    goal=goal,
                    user_visible_title=title,
                    execution_message=execution_message,
                    task_kind=str(raw_item.get("task_kind") or "query"),
                    owner=str(raw_item.get("owner") or "planner"),
                    depends_on=[str(item) for item in depends_on],
                    refs=dict(refs),
                    constraints=dict(constraints),
                    origin="explicit_structured_input",
                )
            )
        if not subtasks:
            raise InvalidSubtaskPlan("explicit subtasks cannot be empty")
        missing_dependencies = {
            dependency
            for subtask in subtasks
            for dependency in subtask.depends_on
            if dependency not in seen_ids
        }
        if missing_dependencies:
            raise InvalidSubtaskPlan(f"unknown explicit subtask dependencies: {', '.join(sorted(missing_dependencies))}")
        return subtasks
