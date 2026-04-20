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

        target = self._resolve_ordinal_task(normalized, tasks)
        if target is not None:
            rewritten = self._rewrite_message(normalized, target.query, target.context_ref.to_dict() if target.context_ref else {})
            return FollowupResolution(
                mode="task_ref",
                task_id=target.task_id,
                confidence=0.95,
                reason="ordinal_task_reference",
                rewritten_message=rewritten,
                source_query=target.query,
                task_ids=[target.task_id],
            )

        binding_target = self._resolve_binding_task(normalized, tasks)
        if binding_target is not None:
            binding_key = self._binding_key(binding_target)
            rewritten = self._rewrite_message(
                normalized,
                binding_target.query,
                binding_target.context_ref.to_dict() if binding_target.context_ref else {},
            )
            return FollowupResolution(
                mode="binding_ref",
                task_id=binding_target.task_id,
                binding_key=binding_key,
                confidence=0.9,
                reason="binding_reference",
                rewritten_message=rewritten,
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

    def _resolve_ordinal_task(self, message: str, tasks: list) -> object | None:
        ordinal = self._extract_ordinal(message)
        if ordinal is None:
            return None
        indexed = {
            int(task.metadata.get("subtask_index", 0) or 0): task
            for task in tasks
            if task.task_type == "query" and int(task.metadata.get("subtask_index", 0) or 0) > 0
        }
        return indexed.get(ordinal)

    def _extract_ordinal(self, message: str) -> int | None:
        direct = re.search(r"第\s*([123])\s*个子任务", message)
        if direct:
            return int(direct.group(1))
        zh = re.search(r"第([一二三])个子任务", message)
        if zh:
            return {"一": 1, "二": 2, "三": 3}[zh.group(1)]
        short = re.search(r"([第一第二第三])个子任务", message)
        if short:
            token = short.group(1)
            mapping = {"第一": 1, "第二": 2, "第三": 3, "第": None, "一": 1, "二": 2, "三": 3}
            return mapping.get(token)
        return None

    def _resolve_binding_task(self, message: str, tasks: list) -> object | None:
        candidates = list(reversed(tasks))
        if any(marker in message for marker in ("刚才 PDF", "刚才的 PDF", "回到刚才 PDF", "那份报告")):
            for task in candidates:
                if task.context_ref and task.context_ref.bindings.active_pdf:
                    return task
        if any(marker in message for marker in ("刚才那个表", "那个表", "那张表", "刚才的数据表")):
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

    def _rewrite_message(self, message: str, source_query: str, context_ref: dict[str, object]) -> str:
        constraint_parts: list[str] = []
        constraints = dict(context_ref.get("constraints", {}) or {})
        bindings = dict(context_ref.get("bindings", {}) or {})
        for key in ("top_n", "page", "group_by", "response_style"):
            value = constraints.get(key)
            if value not in ("", None, [], {}):
                constraint_parts.append(f"{key}={value}")
        for key in ("active_dataset", "active_pdf"):
            value = bindings.get(key)
            if value not in ("", None):
                constraint_parts.append(f"{key}={value}")
        if not constraint_parts:
            return f"延续之前的子任务“{source_query}”。当前要求：{message}"
        return (
            f"延续之前的子任务“{source_query}”，并保持这些约束：{', '.join(constraint_parts)}。"
            f"当前要求：{message}"
        )
