from __future__ import annotations

import re

from output_boundary.answer_models import AnswerAssemblyPlan, AnswerDroppedSegment, AnswerSegment, StyleConstraints
from context_policy.runtime_models import MainContextState


class AnswerAssembler:
    def build_plan(
        self,
        *,
        results: list[dict[str, object]],
        main_context: MainContextState,
    ) -> AnswerAssemblyPlan:
        style_constraints = StyleConstraints(
            dedupe=bool(main_context.active_constraints.get("dedupe")),
            append_mode=str(main_context.active_constraints.get("append_mode", "") or ""),
            default_style=str(main_context.active_constraints.get("response_style", "") or ""),
        )
        segments: list[AnswerSegment] = []
        dropped_segments: list[AnswerDroppedSegment] = []
        dedupe_targets: list[str] = []
        source_refs: list[str] = []
        seen_bodies: set[str] = set()
        selected_task_ids = [
            str(task_id)
            for task_id in list(main_context.followup_target_task_ids or [])
            if str(task_id).strip()
        ]
        selected_task_id = str(main_context.followup_target_task_id or "").strip()
        if selected_task_id and selected_task_id not in selected_task_ids:
            selected_task_ids.insert(0, selected_task_id)
        selected_task_set = set(selected_task_ids)
        for item in results:
            index = int(item.get("index", len(segments) + 1) or len(segments) + 1)
            query = str(item.get("query", "") or "")
            task_id = str(item.get("task_id", "") or "")
            if selected_task_set and task_id not in selected_task_set:
                dropped_segments.append(
                    AnswerDroppedSegment(
                        index=index,
                        task_id=task_id,
                        title=query,
                        reason="not_selected_by_followup_context",
                        detail="当前 follow-up 上下文只选择指定 task。",
                    )
                )
                continue
            summary_payload = item.get("summary")
            body = ""
            response_style = style_constraints.default_style
            answer_source = ""
            answer_ref = ""
            if isinstance(summary_payload, dict):
                body = str(summary_payload.get("response", "") or "").strip()
                response_style = str(summary_payload.get("response_style", "") or response_style)
                if body:
                    answer_source = "canonical_summary"
            result_ref_payload = item.get("result_ref")
            if not body:
                body, answer_source, answer_ref = self._fallback_from_result_ref(result_ref_payload)
            body = self._apply_style(body, response_style=response_style) if answer_source == "canonical_summary" else body
            if not body:
                body = "任务已执行，但当前尚未形成可直接展示的摘要。"
                answer_source = "missing_summary"
            dedupe_key = re.sub(r"\s+", " ", body).strip()
            if style_constraints.dedupe and dedupe_key in seen_bodies:
                dedupe_targets.append(task_id or query)
                dropped_segments.append(
                    AnswerDroppedSegment(
                        index=index,
                        task_id=task_id,
                        title=query,
                        reason="dedupe_duplicate_body",
                        detail="启用 dedupe 后，该分支正文与已选分支重复。",
                    )
                )
                continue
            seen_bodies.add(dedupe_key)
            if answer_ref and answer_ref not in source_refs:
                source_refs.append(answer_ref)
            segments.append(
                AnswerSegment(
                    index=index,
                    task_id=task_id,
                    title=query,
                    body=body,
                    response_style=response_style,
                    answer_source=answer_source,
                    answer_ref=answer_ref,
                )
            )
        return AnswerAssemblyPlan(
            segments=segments,
            dropped_segments=dropped_segments,
            style_constraints=style_constraints,
            dedupe_targets=dedupe_targets,
            source_refs=source_refs,
        )

    def render(self, plan: AnswerAssemblyPlan) -> str:
        if not plan.segments:
            return ""
        if len(plan.segments) == 1:
            return plan.segments[0].body.strip()
        sections: list[str] = []
        for segment in plan.segments:
            sections.append(f"{segment.index}. {segment.title}\n{segment.body}")
        return "\n\n".join(sections).strip()

    def _apply_style(self, body: str, *, response_style: str) -> str:
        normalized = body.strip()
        if not normalized:
            return ""
        if response_style == "one_sentence":
            parts = re.split(r"(?<=[。！？!?\.])\s*", normalized, maxsplit=1)
            return parts[0].strip()
        if response_style == "brief":
            return normalized[:140].rstrip()
        return normalized

    def _fallback_from_result_ref(self, result_ref_payload: object) -> tuple[str, str, str]:
        if not isinstance(result_ref_payload, dict):
            return ("任务已执行，但当前尚未形成可直接展示的摘要。", "missing_summary", "")
        result_id = str(result_ref_payload.get("result_id", "") or "").strip()
        storage_path = str(result_ref_payload.get("storage_path", "") or "").strip()
        if result_id or storage_path:
            return (
                "任务已执行，结果已保存，但当前尚未形成可直接展示的摘要。",
                "result_ref_placeholder",
                result_id or storage_path,
            )
        return ("任务已执行，但当前尚未形成可直接展示的摘要。", "missing_summary", "")
