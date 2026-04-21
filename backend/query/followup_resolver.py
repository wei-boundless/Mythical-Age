from __future__ import annotations

import re

from query.followup_models import FollowupResolution
from tasks import TaskCoordinator


class QueryFollowupResolver:
    def __init__(self, task_coordinator: TaskCoordinator) -> None:
        self.task_coordinator = task_coordinator

    def resolve(self, *, session_id: str, message: str) -> FollowupResolution:
        normalized = (message or "").strip()
        if not normalized:
            return FollowupResolution()
        if self._looks_explicit(normalized):
            return FollowupResolution()

        tasks = self.task_coordinator.list_tasks(session_id=session_id)
        if not tasks:
            return FollowupResolution()

        ordinal_targets = self._resolve_ordinal_tasks(normalized, tasks)
        if ordinal_targets:
            if len(ordinal_targets) > 1:
                return FollowupResolution(
                    mode="compound_subset",
                    task_id=ordinal_targets[0].task_id,
                    confidence=0.95,
                    reason="ordinal_task_subset_reference",
                    source_query=" | ".join(task.query for task in ordinal_targets),
                    task_ids=[task.task_id for task in ordinal_targets],
                )
            return FollowupResolution(
                mode="task_ref",
                task_id=ordinal_targets[0].task_id,
                confidence=0.95,
                reason="ordinal_task_reference",
                source_query=ordinal_targets[0].query,
                task_ids=[ordinal_targets[0].task_id],
            )

        binding_target = self._resolve_binding_task(normalized, tasks)
        if binding_target is not None:
            binding_key = self._binding_key(binding_target)
            return FollowupResolution(
                mode="binding_ref",
                task_id=binding_target.task_id,
                binding_owner_task_id=binding_target.task_id,
                binding_key=binding_key,
                confidence=0.9,
                reason="binding_reference",
                source_query=binding_target.query,
                task_ids=[binding_target.task_id],
            )

        return FollowupResolution()

    def _looks_explicit(self, message: str) -> bool:
        lowered = message.lower()
        return any(
            marker in lowered
            for marker in (".pdf", ".xlsx", ".csv", ".xls", "inventory.xlsx", "report.pdf")
        )

    def _resolve_ordinal_tasks(self, message: str, tasks: list) -> list[object]:
        ordinals = self._extract_ordinals(message)
        if not ordinals:
            return []
        indexed = {
            int(task.metadata.get("subtask_index", 0) or 0): task
            for task in tasks
            if task.task_type == "query" and int(task.metadata.get("subtask_index", 0) or 0) > 0
        }
        return [indexed[ordinal] for ordinal in ordinals if ordinal in indexed]

    def _extract_ordinals(self, message: str) -> list[int]:
        if "子任务" not in message:
            return []
        mapping = {"1": 1, "2": 2, "3": 3, "一": 1, "二": 2, "三": 3}
        primary_clause = re.split(r"(?:不要重复|不包括|排除|除了)", message, maxsplit=1)[0]
        matches = re.findall(r"第\s*([123一二三])\s*个?", primary_clause)
        if not matches:
            matches = re.findall(r"第\s*([123一二三])\s*个?", message)
        seen: list[int] = []
        for token in matches:
            ordinal = mapping.get(token)
            if ordinal is not None and ordinal not in seen:
                seen.append(ordinal)
        return seen

    def _resolve_binding_task(self, message: str, tasks: list) -> object | None:
        candidates = list(reversed(tasks))
        if any(
            marker in message
            for marker in ("刚才 PDF", "刚才的 PDF", "回到刚才 PDF", "那份报告", "这份 PDF", "这份pdf", "这个 PDF")
        ):
            for task in candidates:
                if task.context_ref and task.context_ref.bindings.active_pdf:
                    return task
        if any(marker in message for marker in ("刚才那个表", "那个表", "那张表", "刚才的数据表", "这个表", "这张表")):
            for task in candidates:
                if task.context_ref and task.context_ref.bindings.active_dataset:
                    return task
        return None

    def _binding_key(self, task) -> str:
        if task.context_ref is None:
            return ""
        if task.context_ref.bindings.active_pdf:
            return "active_pdf"
        if task.context_ref.bindings.active_dataset:
            return "active_dataset"
        return ""
