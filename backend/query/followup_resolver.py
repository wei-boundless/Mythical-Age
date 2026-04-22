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
            return FollowupResolution(resolution_source="explicit_input", reason="explicit_reference_present")

        tasks = self.task_coordinator.list_tasks(session_id=session_id)
        if not tasks:
            return FollowupResolution()

        ordinal_targets = self._resolve_ordinal_tasks(normalized, tasks)
        if ordinal_targets:
            if len(ordinal_targets) > 1:
                return FollowupResolution(
                    mode="compound_subset",
                    target_kind="task_subset",
                    resolved_target_kind="task_subset",
                    task_id=ordinal_targets[0].task_id,
                    resolved_task_id=ordinal_targets[0].task_id,
                    resolved_task_kind=self._task_kind(ordinal_targets[0]),
                    resolution_source="task_registry_ordinal",
                    confidence=0.95,
                    reason="ordinal_task_subset_reference",
                    source_query=" | ".join(task.query for task in ordinal_targets),
                    task_ids=[task.task_id for task in ordinal_targets],
                    resolved_task_ids=[task.task_id for task in ordinal_targets],
                )
            return FollowupResolution(
                mode="task_ref",
                target_kind="task",
                resolved_target_kind="task",
                task_id=ordinal_targets[0].task_id,
                resolved_task_id=ordinal_targets[0].task_id,
                resolved_task_kind=self._task_kind(ordinal_targets[0]),
                resolution_source="task_registry_ordinal",
                confidence=0.95,
                reason="ordinal_task_reference",
                source_query=ordinal_targets[0].query,
                task_ids=[ordinal_targets[0].task_id],
                resolved_task_ids=[ordinal_targets[0].task_id],
            )

        binding_targets = self._resolve_binding_tasks(normalized, tasks)
        if len(binding_targets) == 1:
            binding_target = binding_targets[0]
            binding_key = self._binding_key(binding_target)
            binding_identity = self._binding_identity(binding_target)
            return FollowupResolution(
                mode="binding_ref",
                target_kind="binding",
                resolved_target_kind="binding",
                task_id=binding_target.task_id,
                resolved_task_id=binding_target.task_id,
                resolved_task_kind=self._task_kind(binding_target),
                binding_owner_task_id=binding_target.task_id,
                resolved_binding_owner_task_id=binding_target.task_id,
                binding_key=binding_key,
                binding_kind=binding_key,
                resolved_binding_kind=binding_key,
                binding_identity=binding_identity,
                resolved_binding_identity=binding_identity,
                resolved_binding_ref=binding_identity,
                resolution_source="task_registry_binding",
                confidence=0.9,
                reason="binding_reference",
                source_query=binding_target.query,
                task_ids=[binding_target.task_id],
                resolved_task_ids=[binding_target.task_id],
            )
        if len(binding_targets) > 1:
            return FollowupResolution(
                mode="clarify",
                target_kind="binding",
                resolved_target_kind="binding",
                resolution_source="task_registry_binding",
                confidence=0.0,
                reason="ambiguous_binding_reference",
                requires_clarification=True,
                clarification_prompt="你提到的是哪一个对象？请直接说文件名、任务名，或显式路径。",
                task_ids=[task.task_id for task in binding_targets],
                resolved_task_ids=[task.task_id for task in binding_targets],
                source_query=" | ".join(task.query for task in binding_targets),
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

    def _resolve_binding_tasks(self, message: str, tasks: list) -> list[object]:
        candidates = self._binding_owner_candidates(tasks)
        if not candidates:
            return []

        explicit_matches = self._match_explicit_binding_candidates(message, candidates)
        if explicit_matches:
            return [candidate["task"] for candidate in explicit_matches]

        binding_kind = self._binding_hint_kind(message)
        if binding_kind:
            filtered = [
                candidate
                for candidate in candidates
                if str(candidate.get("binding_kind", "") or "") == binding_kind
            ]
            if len(filtered) == 1:
                return [filtered[0]["task"]]
            if len(filtered) > 1:
                if self._contains_generic_object_reference(message):
                    return [candidate["task"] for candidate in filtered]
                return [filtered[0]["task"]]
            return []

        if self._looks_like_generic_followup_hint(message):
            if len(candidates) == 1:
                return [candidates[0]["task"]]
            return []
        return []

    def _binding_owner_candidates(self, tasks: list) -> list[dict[str, object]]:
        collapsed: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for task in reversed(tasks):
            binding_kind = self._binding_key(task)
            if not binding_kind:
                continue
            binding_identity = self._binding_identity(task)
            if not binding_identity:
                continue
            dedupe_key = (binding_kind, binding_identity)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            collapsed.append(
                {
                    "task": task,
                    "binding_kind": binding_kind,
                    "binding_identity": binding_identity,
                }
            )
        return collapsed

    def _match_explicit_binding_candidates(
        self,
        message: str,
        candidates: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        explicit_refs = self._extract_explicit_binding_references(message)
        if not explicit_refs:
            return []
        matches: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            identity = str(candidate.get("binding_identity", "") or "")
            normalized_identity = identity.replace("\\", "/").lower()
            filename = normalized_identity.rsplit("/", 1)[-1]
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            for reference in explicit_refs:
                normalized_reference = reference.replace("\\", "/").lower()
                reference_name = normalized_reference.rsplit("/", 1)[-1]
                reference_stem = reference_name.rsplit(".", 1)[0] if "." in reference_name else reference_name
                if (
                    normalized_identity.endswith(normalized_reference)
                    or filename == reference_name
                    or stem == reference_stem
                ):
                    dedupe_key = (
                        str(candidate.get("binding_kind", "") or ""),
                        identity,
                    )
                    if dedupe_key in seen:
                        break
                    seen.add(dedupe_key)
                    matches.append(candidate)
                    break
        return matches

    def _extract_explicit_binding_references(self, message: str) -> list[str]:
        normalized = (message or "").strip()
        if not normalized:
            return []
        matches = re.findall(
            r"([^\s,，;；:：\"'“”‘’]+?\.(?:pdf|xlsx|csv|xls|json|parquet))",
            normalized,
            flags=re.IGNORECASE,
        )
        seen: set[str] = set()
        references: list[str] = []
        for matched in matches:
            candidate = str(matched or "").strip()
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            references.append(candidate)
        return references

    def _binding_hint_kind(self, message: str) -> str:
        if self._looks_like_pdf_binding_followup(message):
            return "active_pdf"
        if self._looks_like_dataset_binding_followup(message):
            return "active_dataset"
        return ""

    def _looks_like_generic_followup_hint(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if self._looks_like_summary_or_rewrite_request(message):
            return False
        starter_markers = ("再", "继续", "然后", "接着", "那", "把", "按", "回到刚才", "刚才那个")
        generic_reference_markers = (
            "这个",
            "那个",
            "这份",
            "那份",
            "刚才",
            "前面",
        )
        return normalized.startswith(starter_markers) or any(marker in message for marker in generic_reference_markers)

    def _contains_generic_object_reference(self, message: str) -> bool:
        return any(
            marker in message
            for marker in (
                "这个表",
                "这张表",
                "那个表",
                "那张表",
                "这份表格",
                "那个文件",
                "那份文件",
                "这个文件",
                "刚才那个表",
                "前面那个表",
                "这份 PDF",
                "那个 PDF",
            )
        )

    def _looks_like_pdf_binding_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if ".pdf" in normalized:
            return True
        if re.search(r"第\s*\d+\s*页", message):
            return True
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            return True
        if re.search(r"page\s*\d+", normalized):
            return True
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)", message):
            return True

        document_nouns = ("pdf", "这一页", "那一页", "这页", "那页", "这一章", "那一章")
        document_actions = (
            "结论",
            "行动建议",
            "约束重点",
            "重点",
            "解读",
            "分析",
            "总结",
            "压成",
            "改写",
        )
        return any(noun in normalized or noun in message for noun in document_nouns) and any(
            action in message for action in document_actions
        )

    def _looks_like_dataset_binding_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if self._looks_like_summary_or_rewrite_request(message):
            return False
        if any(ext in normalized for ext in (".xlsx", ".csv", ".xls", ".json", ".parquet")):
            return True
        dataset_nouns = ("表", "数据表", "表格", "工作簿", "sheet", "dataset")
        structured_actions = (
            "按仓库",
            "按地区",
            "按部门",
            "按品类",
            "展开",
            "汇总",
            "统计",
            "分组",
            "筛选",
            "排序",
            "缺货",
            "补货",
            "均值",
            "平均",
            "总计",
            "总和",
        )
        if any(noun in message for noun in dataset_nouns):
            return any(action in message for action in structured_actions)
        return any(action in message for action in structured_actions)

    def _looks_like_summary_or_rewrite_request(self, message: str) -> bool:
        return any(
            marker in message
            for marker in (
                "总结",
                "概括",
                "归纳",
                "梳理",
                "整理成",
                "压成",
                "改写",
                "改成",
                "润色",
                "适合管理层",
                "汇报版本",
            )
        )

    def _has_committed_pdf_binding(self, task) -> bool:
        if task.context_ref is None:
            return False
        active_pdf = str(task.context_ref.bindings.active_pdf or "").strip()
        return active_pdf.lower().endswith(".pdf")

    def _has_committed_dataset_binding(self, task) -> bool:
        if task.context_ref is None:
            return False
        active_dataset = str(task.context_ref.bindings.active_dataset or "").strip()
        return active_dataset.lower().endswith((".xlsx", ".xls", ".csv", ".json", ".parquet"))

    def _binding_key(self, task) -> str:
        if task.context_ref is None:
            return ""
        if self._has_committed_pdf_binding(task):
            return "active_pdf"
        if self._has_committed_dataset_binding(task):
            return "active_dataset"
        return ""

    def _binding_identity(self, task) -> str:
        if task.context_ref is None:
            return ""
        if self._has_committed_pdf_binding(task):
            return str(task.context_ref.bindings.active_pdf or "").replace("\\", "/").strip().lower()
        if self._has_committed_dataset_binding(task):
            return str(task.context_ref.bindings.active_dataset or "").replace("\\", "/").strip().lower()
        return ""

    def _task_kind(self, task) -> str:
        context_ref = getattr(task, "context_ref", None)
        if context_ref is None:
            return ""
        return str(getattr(context_ref, "task_kind", "") or "").strip()
