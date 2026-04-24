from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from agents import EXPLORER_AGENT, WORKER_AGENT
from query.binding_models import StructuredDatasetBinding
from tasks.context_models import TaskBindings, TaskConstraints, TaskContextRef, TaskResultRef, TaskSummary
from tasks.models import TaskRecord


class TaskCoordinator:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._base_dir = base_dir
        self._result_store_dir = (
            base_dir.parent / "output" / "task_results" if base_dir is not None else None
        )

    @property
    def tasks(self) -> list[TaskRecord]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def list_tasks(self, *, session_id: str | None = None) -> list[TaskRecord]:
        tasks = list(self._tasks.values())
        if session_id is not None:
            tasks = [
                task
                for task in tasks
                if str(task.metadata.get("session_id", "")) == session_id
            ]
        return sorted(tasks, key=lambda task: task.created_at)

    def _register(self, task: TaskRecord) -> TaskRecord:
        self._tasks[task.task_id] = task
        return task

    def _query_task(self, session_id: str, subquery: str, index: int, parent_query_id: str) -> TaskRecord:
        task_id = f"{session_id}-subtask-{index}"
        return self._register(
            TaskRecord(
                task_id=task_id,
                task_type="query",
                query=subquery,
                parent_query_id=parent_query_id,
                agent_type=EXPLORER_AGENT.agent_type,
                context_ref=self._build_task_context_ref(
                    task_id=task_id,
                    parent_query_id=parent_query_id,
                    query=subquery,
                ),
                metadata={"session_id": session_id, "subtask_index": index, "parent_query_id": parent_query_id},
            )
        )

    def _next_query_subtask_index(self, session_id: str) -> int:
        highest = 0
        for task in self._tasks.values():
            if task.task_type != "query":
                continue
            if str(task.metadata.get("session_id", "")) != session_id:
                continue
            highest = max(highest, int(task.metadata.get("subtask_index", 0) or 0))
        return highest + 1

    def _tool_task(
        self,
        session_id: str,
        tool_name: str,
        *,
        query: str,
        parent_query_id: str,
    ) -> TaskRecord:
        task_id = f"{session_id}-tool-{tool_name}-{len(self._tasks) + 1}"
        return self._register(
            TaskRecord(
                task_id=task_id,
                task_type="tool",
                query=query,
                parent_query_id=parent_query_id,
                agent_type=WORKER_AGENT.agent_type,
                context_ref=self._build_task_context_ref(
                    task_id=task_id,
                    parent_query_id=parent_query_id,
                    query=query,
                ),
                metadata={
                    "session_id": session_id,
                    "tool_name": tool_name,
                    "parent_query_id": parent_query_id,
                    "execution_kind": "direct_tool",
                },
            )
        )

    def _build_task_context_ref(
        self,
        *,
        task_id: str,
        parent_query_id: str,
        query: str,
    ) -> TaskContextRef:
        bindings = self._derive_task_bindings(query)
        constraints = self._derive_task_constraints(query)
        return TaskContextRef(
            task_id=task_id,
            parent_query_id=parent_query_id,
            task_kind=self._derive_task_kind(bindings),
            bindings=bindings,
            constraints=constraints,
        )

    def _derive_task_kind(self, bindings: TaskBindings) -> str:
        if bindings.active_pdf:
            return "pdf"
        if bindings.active_dataset:
            return "structured_data"
        return bindings.source_kind or "general"

    def _derive_task_bindings(self, query: str) -> TaskBindings:
        pdf_match = re.search(r"([^\s,，。；;:：]+\.pdf)", query, flags=re.IGNORECASE)
        dataset_match = re.search(r"([^\s,，。；;:：]+?\.(?:xlsx|csv|xls))", query, flags=re.IGNORECASE)
        active_pdf = pdf_match.group(1) if pdf_match else ""
        active_dataset = dataset_match.group(1) if dataset_match else ""
        active_binding_identity = ""
        if active_pdf:
            active_binding_identity = active_pdf.replace("\\", "/").strip().lower()
        elif active_dataset:
            active_binding_identity = active_dataset.replace("\\", "/").strip().lower()
        source_kind = ""
        if pdf_match:
            source_kind = "pdf"
        elif dataset_match:
            source_kind = "dataset"
        return TaskBindings(
            active_pdf=active_pdf,
            active_dataset=active_dataset,
            active_binding_identity=active_binding_identity,
            active_entity="",
            active_location="",
            source_kind=source_kind,
        )

    def _derive_task_constraints(self, query: str) -> TaskConstraints:
        top_n = self._extract_top_n(query)
        page = self._extract_page(query)
        group_by = ""
        if "按仓库" in query:
            group_by = "仓库"
        elif "按地区" in query:
            group_by = "地区"
        elif "按部门" in query:
            group_by = "部门"
        response_style = ""
        if "一句话" in query or "一句" in query:
            response_style = "one_sentence"
        elif "简要" in query or "简短" in query:
            response_style = "brief"
        return TaskConstraints(
            top_n=top_n,
            group_by=group_by,
            page=page,
            response_style=response_style,
        )

    def _extract_top_n(self, query: str) -> int | None:
        direct = re.search(r"(?:前|top\s*)(\d+)", query, flags=re.IGNORECASE)
        if direct:
            return int(direct.group(1))
        zh = re.search(r"前([一二三四五六七八九十两])", query)
        if not zh:
            return None
        mapping = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        return mapping.get(zh.group(1))

    def _extract_page(self, query: str) -> int | None:
        direct = re.search(r"第\s*(\d+)\s*页", query)
        if direct:
            return int(direct.group(1))
        zh = re.search(r"第\s*([一二三四五六七八九十两])\s*页", query)
        if not zh:
            return None
        mapping = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        return mapping.get(zh.group(1))

    def _build_task_summary(self, query: str, content: str, context_ref: TaskContextRef | None) -> TaskSummary:
        normalized = " ".join(str(content or "").split()).strip()
        if not normalized:
            normalized = "未能生成结果。"
        headline = query.strip()[:80]
        key_points: list[str] = []
        if context_ref is not None and context_ref.constraints.top_n is not None:
            key_points.append(f"top_n={context_ref.constraints.top_n}")
        if context_ref is not None and context_ref.constraints.page is not None:
            key_points.append(f"page={context_ref.constraints.page}")
        if context_ref is not None and context_ref.constraints.pdf_mode:
            key_points.append(f"pdf_mode={context_ref.constraints.pdf_mode}")
        if context_ref is not None and context_ref.constraints.pdf_section:
            key_points.append(f"pdf_section={context_ref.constraints.pdf_section}")
        if context_ref is not None and context_ref.constraints.pdf_focus_pages:
            pages = ",".join(str(page) for page in context_ref.constraints.pdf_focus_pages if int(page) > 0)
            if pages:
                key_points.append(f"pdf_pages={pages}")
        if context_ref is not None and context_ref.constraints.readable_pages is not None:
            key_points.append(f"readable_pages={context_ref.constraints.readable_pages}")
        if context_ref is not None and context_ref.constraints.usable_pages is not None:
            key_points.append(f"usable_pages={context_ref.constraints.usable_pages}")
        if context_ref is not None and context_ref.bindings.active_dataset:
            key_points.append(f"dataset={context_ref.bindings.active_dataset}")
        if context_ref is not None and context_ref.bindings.active_pdf:
            key_points.append(f"pdf={context_ref.bindings.active_pdf}")
        return TaskSummary(
            headline=headline,
            response=normalized[:280],
            key_points=key_points,
            response_style=context_ref.constraints.response_style if context_ref is not None else "",
        )

    def _apply_direct_tool_context(
        self,
        *,
        task: TaskRecord,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        structured_binding: StructuredDatasetBinding | None,
        task_kind: str = "",
        constraints: TaskConstraints | None = None,
    ) -> None:
        context_ref = task.context_ref
        if context_ref is None:
            return
        payload = dict(tool_input or {})
        if task_kind:
            context_ref.task_kind = task_kind
        if constraints is not None:
            context_ref.constraints = constraints
        if tool_name == "pdf_analysis":
            pdf_path = str(payload.get("path", "") or "").strip()
            if pdf_path:
                context_ref.bindings.active_pdf = pdf_path
                context_ref.bindings.active_binding_identity = pdf_path.replace("\\", "/").strip().lower()
                context_ref.bindings.source_kind = "pdf"
                if not context_ref.task_kind:
                    context_ref.task_kind = "pdf"
        elif tool_name == "structured_data_analysis":
            dataset_path = str(payload.get("path", "") or "").strip()
            if structured_binding is not None and structured_binding.dataset_path:
                dataset_path = structured_binding.dataset_path
                task.metadata["structured_binding"] = structured_binding.to_dict()
            if dataset_path:
                context_ref.bindings.active_dataset = dataset_path
                context_ref.bindings.active_binding_identity = dataset_path.replace("\\", "/").strip().lower()
                context_ref.bindings.source_kind = "dataset"
                if not context_ref.task_kind:
                    context_ref.task_kind = "structured_data"
            if structured_binding is not None and structured_binding.target_object:
                context_ref.bindings.active_entity = structured_binding.target_object
        elif tool_name == "get_weather":
            location = str(payload.get("location", "") or payload.get("query", "") or "").strip()
            if location:
                context_ref.bindings.active_location = location
                context_ref.bindings.source_kind = "weather"
                if not context_ref.task_kind:
                    context_ref.task_kind = "weather"
        elif tool_name == "get_gold_price":
            context_ref.bindings.active_entity = "黄金"
            context_ref.bindings.source_kind = "finance"
            if not context_ref.task_kind:
                context_ref.task_kind = "finance"

        if payload:
            task.metadata["tool_input"] = payload

    def _persist_result_ref(self, *, session_id: str, task_id: str, content: str) -> TaskResultRef:
        preview = " ".join(str(content or "").split()).strip()[:160]
        if self._result_store_dir is None:
            return TaskResultRef(
                result_id=f"{task_id}-result",
                task_id=task_id,
                storage_path="",
                content_preview=preview,
            )
        session_dir = self._result_store_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        result_path = session_dir / f"{task_id}.json"
        payload = {"task_id": task_id, "content": content}
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return TaskResultRef(
            result_id=f"{task_id}-result",
            task_id=task_id,
            storage_path=str(result_path),
            content_preview=preview,
        )

    async def run_query_tasks(
        self,
        session_id: str,
        executions: list[Any],
        runner: Callable[[Any], AsyncIterator[dict[str, object]]],
        *,
        subtasks: list[Any] | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        parent_query_id = f"{session_id}-query-{len(self._tasks) + 1}"
        start_index = self._next_query_subtask_index(session_id)
        for offset, execution in enumerate(executions):
            index = start_index + offset
            subquery = execution.message
            structured_binding = getattr(execution, "structured_binding", None)
            query_understanding = getattr(execution, "query_understanding", None)
            tool_name = str(getattr(query_understanding, "tool_name", "") or "").strip()
            task_kind = str(getattr(query_understanding, "task_kind", "") or "").strip()
            tool_input = dict(
                getattr(execution, "tool_input", {})
                or getattr(query_understanding, "tool_input", {})
                or {}
            )
            subtask = subtasks[offset] if subtasks is not None and offset < len(subtasks) else None
            subtask_metadata = {
                "subtask_plan_id": str(
                    getattr(subtask, "subtask_id", "")
                    or getattr(execution, "subtask_id", "")
                    or f"subtask-{index}"
                ),
                "goal": str(getattr(subtask, "goal", "") or getattr(execution, "subtask_goal", "") or subquery),
                "title": str(
                    getattr(subtask, "user_visible_title", "")
                    or getattr(execution, "subtask_title", "")
                    or subquery
                ),
                "refs": dict(getattr(subtask, "refs", None) or getattr(execution, "subtask_refs", {}) or {}),
                "depends_on": list(
                    getattr(subtask, "depends_on", None) or getattr(execution, "subtask_depends_on", []) or []
                ),
                "origin": str(getattr(subtask, "origin", "") or getattr(execution, "subtask_origin", "") or "planner"),
            }
            bundle_item_metadata = {
                "bundle_id": str(getattr(execution, "bundle_id", "") or "").strip(),
                "bundle_item_id": str(getattr(execution, "bundle_item_id", "") or "").strip(),
                "bundle_item_index": int(getattr(execution, "bundle_item_index", 0) or 0),
                "bundle_origin": str(getattr(execution, "bundle_origin", "") or "").strip(),
            }
            task = self._query_task(session_id, subquery, index, parent_query_id)
            task.metadata["subtask_plan"] = subtask_metadata
            if bundle_item_metadata["bundle_id"]:
                task.metadata["bundle_item"] = dict(bundle_item_metadata)
                task.metadata["bundle_id"] = bundle_item_metadata["bundle_id"]
                task.metadata["bundle_item_id"] = bundle_item_metadata["bundle_item_id"]
                task.metadata["bundle_item_index"] = bundle_item_metadata["bundle_item_index"]
            if task.context_ref is not None and bundle_item_metadata["bundle_id"]:
                task.context_ref.bundle_id = bundle_item_metadata["bundle_id"]
                task.context_ref.bundle_item_id = bundle_item_metadata["bundle_item_id"]
                task.context_ref.bundle_item_index = bundle_item_metadata["bundle_item_index"]
                task.context_ref.bundle_origin = bundle_item_metadata["bundle_origin"]
            if tool_name:
                task.metadata["tool_name"] = tool_name
                self._apply_direct_tool_context(
                    task=task,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    structured_binding=structured_binding,
                    task_kind=task_kind,
                    constraints=(task.context_ref.constraints if task.context_ref is not None else None),
                )
            if structured_binding is not None:
                task.metadata["structured_binding"] = structured_binding.to_dict()
                if task.context_ref is not None:
                    if structured_binding.dataset_path:
                        task.context_ref.bindings.active_dataset = structured_binding.dataset_path
                        task.context_ref.bindings.active_binding_identity = (
                            str(structured_binding.binding_identity or structured_binding.dataset_path)
                            .replace("\\", "/")
                            .strip()
                            .lower()
                        )
                    if structured_binding.target_object:
                        task.context_ref.bindings.active_entity = structured_binding.target_object
                    if task.context_ref.bindings.active_dataset:
                        task.context_ref.bindings.source_kind = "dataset"
            task.mark_running()
            if task.context_ref is not None:
                task.context_ref.status = "running"
            task.add_event("subtask_start", payload={"index": index, "query": subquery, **subtask_metadata})
            yield {
                "type": "subtask_start",
                "index": index,
                "query": subquery,
                "task_id": task.task_id,
                "subtask_plan": subtask_metadata,
                "bundle_item": dict(bundle_item_metadata) if bundle_item_metadata["bundle_id"] else None,
                "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
                "structured_binding": structured_binding.to_dict() if structured_binding is not None else None,
            }

            final_subcontent = ""
            try:
                async for event in runner(execution):
                    event_type = str(event.get("type", ""))
                    if event_type == "token":
                        continue
                    if event_type == "done":
                        final_subcontent = str(event.get("content", "") or "")
                        continue
                    forwarded = dict(event)
                    forwarded["subtask_index"] = index
                    forwarded["subtask_query"] = subquery
                    forwarded["task_id"] = task.task_id
                    forwarded["subtask_plan"] = subtask_metadata
                    if bundle_item_metadata["bundle_id"]:
                        forwarded["bundle_item"] = dict(bundle_item_metadata)
                    if structured_binding is not None:
                        forwarded["structured_binding"] = structured_binding.to_dict()
                    task.add_event(event_type or "event", payload=forwarded)
                    yield forwarded
            except Exception as exc:
                task.mark_failed(str(exc))
                if task.context_ref is not None:
                    task.context_ref.status = "failed"
                task.add_event("subtask_error", message=str(exc))
                raise

            task.mark_completed(final_subcontent)
            task.result_ref = self._persist_result_ref(
                session_id=session_id,
                task_id=task.task_id,
                content=final_subcontent,
            )
            task.summary = self._build_task_summary(subquery, final_subcontent, task.context_ref)
            if task.context_ref is not None:
                task.context_ref.status = "completed"
                task.context_ref.summary = task.summary.response
                task.context_ref.result_ref_id = task.result_ref.result_id
            task.add_event(
                "subtask_end",
                payload={
                    "index": index,
                    "query": subquery,
                    "content": final_subcontent,
                    "subtask_plan": subtask_metadata,
                    "bundle_item": dict(bundle_item_metadata) if bundle_item_metadata["bundle_id"] else None,
                    "summary": task.summary.to_dict() if task.summary is not None else None,
                    "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
                    "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
                    "structured_binding": structured_binding.to_dict() if structured_binding is not None else None,
                },
            )
            yield {
                "type": "subtask_end",
                "index": index,
                "query": subquery,
                "content": final_subcontent,
                "task_id": task.task_id,
                "subtask_plan": subtask_metadata,
                "bundle_item": dict(bundle_item_metadata) if bundle_item_metadata["bundle_id"] else None,
                "summary": task.summary.to_dict() if task.summary is not None else None,
                "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
                "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
                "structured_binding": structured_binding.to_dict() if structured_binding is not None else None,
            }

    async def run_tool_task(
        self,
        session_id: str,
        tool_name: str,
        runner: Callable[[], Awaitable[Any]],
        *,
        query: str = "",
        tool_input: dict[str, Any] | None = None,
        structured_binding: StructuredDatasetBinding | None = None,
        task_kind: str = "",
        constraints: TaskConstraints | None = None,
        render_content: Callable[[Any], str] | None = None,
    ) -> TaskRecord:
        parent_query_id = f"{session_id}-tool-parent-{len(self._tasks) + 1}"
        task = self._tool_task(
            session_id,
            tool_name,
            query=query or tool_name,
            parent_query_id=parent_query_id,
        )
        self._apply_direct_tool_context(
            task=task,
            tool_name=tool_name,
            tool_input=tool_input,
            structured_binding=structured_binding,
            task_kind=task_kind,
            constraints=constraints,
        )
        task.mark_running()
        if task.context_ref is not None:
            task.context_ref.status = "running"
        task.add_event("tool_task_start", payload={"tool_name": tool_name})
        try:
            raw_result = await runner()
        except Exception as exc:
            task.mark_failed(str(exc))
            if task.context_ref is not None:
                task.context_ref.status = "failed"
            task.add_event("tool_task_error", message=str(exc))
            raise
        visible_content = render_content(raw_result) if render_content is not None else str(raw_result)
        task.mark_completed(visible_content)
        task.result_ref = self._persist_result_ref(
            session_id=session_id,
            task_id=task.task_id,
            content=visible_content,
        )
        task.summary = self._build_task_summary(task.query, visible_content, task.context_ref)
        if task.context_ref is not None:
            task.context_ref.status = "completed"
            task.context_ref.summary = task.summary.response
            task.context_ref.result_ref_id = task.result_ref.result_id
        task.add_event(
            "tool_task_end",
            payload={
                "tool_name": tool_name,
                "summary": task.summary.to_dict() if task.summary is not None else None,
                "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
                "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
            },
        )
        return task

    def refresh_completed_tool_task(
        self,
        *,
        session_id: str,
        task: TaskRecord,
        content: str,
        event_name: str = "tool_task_finalize",
    ) -> TaskRecord:
        normalized = str(content or "")
        task.result = normalized
        task.result_ref = self._persist_result_ref(
            session_id=session_id,
            task_id=task.task_id,
            content=normalized,
        )
        task.summary = self._build_task_summary(task.query, normalized, task.context_ref)
        if task.context_ref is not None:
            task.context_ref.status = "completed"
            task.context_ref.summary = task.summary.response
            task.context_ref.result_ref_id = task.result_ref.result_id
        task.add_event(
            event_name,
            payload={
                "summary": task.summary.to_dict() if task.summary is not None else None,
                "context_ref": task.context_ref.to_dict() if task.context_ref is not None else None,
                "result_ref": task.result_ref.to_dict() if task.result_ref is not None else None,
            },
        )
        return task
