from __future__ import annotations

import re

from query.answer_models import AnswerAssemblyPlan, AnswerSegment, StyleConstraints
from query.context_models import MainContextState


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
        dedupe_targets: list[str] = []
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
                continue
            summary_payload = item.get("summary")
            body = ""
            response_style = style_constraints.default_style
            if isinstance(summary_payload, dict):
                body = str(summary_payload.get("response", "") or "").strip()
                response_style = str(summary_payload.get("response_style", "") or response_style)
            if not body:
                body = str(item.get("content", "") or "").strip()
            body = self._apply_style(body, response_style=response_style)
            if not body:
                body = "未能生成结果。"
            dedupe_key = re.sub(r"\s+", " ", body).strip()
            if style_constraints.dedupe and dedupe_key in seen_bodies:
                dedupe_targets.append(task_id or query)
                continue
            seen_bodies.add(dedupe_key)
            segments.append(
                AnswerSegment(
                    index=index,
                    task_id=task_id,
                    title=query,
                    body=body,
                    response_style=response_style,
                )
            )
        return AnswerAssemblyPlan(
            segments=segments,
            style_constraints=style_constraints,
            dedupe_targets=dedupe_targets,
        )

    def render(self, plan: AnswerAssemblyPlan) -> str:
        if not plan.segments:
            return ""
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
