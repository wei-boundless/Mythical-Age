from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from .write_models import DurableCandidateDraft, DurableExtractionBundle
from understanding.memory_policy import evaluate_memory_write


MessageInvoker = Callable[[list[dict[str, str]]], Awaitable[object]]


class DurableWriteExtractorAgent:
    def __init__(self, *, message_invoker: MessageInvoker | None = None) -> None:
        self._message_invoker = message_invoker

    def set_message_invoker(self, message_invoker: MessageInvoker | None) -> None:
        self._message_invoker = message_invoker

    async def extract(self, bundle: DurableExtractionBundle) -> list[DurableCandidateDraft]:
        if self._message_invoker is not None:
            drafts = await self._extract_with_model(bundle)
            if drafts:
                return drafts[:3]
        return self._extract_with_fallback(bundle)[:3]

    async def _extract_with_model(self, bundle: DurableExtractionBundle) -> list[DurableCandidateDraft]:
        assert self._message_invoker is not None
        system_prompt = (
            "You are the durable memory extraction subagent. "
            "Given a turn bundle, extract only stable, cross-session, non-obvious durable memory candidates. "
            "Never store task-local steps, tool outputs, temporary workflow bindings, or derivable repo facts. "
            "Return JSON with a top-level key `drafts`."
        )
        user_prompt = json.dumps(bundle.model_dump(), ensure_ascii=False)
        try:
            response = await self._message_invoker(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            content = getattr(response, "content", "")
            if isinstance(content, list):
                text = "".join(
                    str(block.get("text", ""))
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                text = str(content or "")
            payload = self._extract_json(text)
            drafts = payload.get("drafts", [])
            return [DurableCandidateDraft.model_validate(item) for item in drafts]
        except Exception:
            return []

    def _extract_with_fallback(self, bundle: DurableExtractionBundle) -> list[DurableCandidateDraft]:
        statements = self._candidate_statements(bundle)
        drafts: list[DurableCandidateDraft] = []
        for statement in statements:
            decision = evaluate_memory_write(statement)
            if decision.action != "durable_fact" or decision.memory_type is None or decision.memory_class is None:
                continue
            title = self._make_title(statement)
            drafts.append(
                DurableCandidateDraft(
                    draft_id=f"draft:{title[:32]}",
                    memory_type=decision.memory_type,
                    memory_class=decision.memory_class,
                    title=title,
                    canonical_statement=statement,
                    why=decision.reason,
                    how_to_apply="Apply this only when the same user/project context clearly recurs.",
                    stability="stable",
                    non_obvious_value=statement[:120],
                    source_scope="private",
                    evidence_excerpt=statement[:160],
                    proposed_action="create",
                )
            )
        deduped: dict[tuple[str, str, str], DurableCandidateDraft] = {}
        for draft in drafts:
            key = (draft.memory_type, draft.memory_class, draft.canonical_statement)
            deduped[key] = draft
        return list(deduped.values())

    def _candidate_statements(self, bundle: DurableExtractionBundle) -> list[str]:
        candidates: list[str] = []
        main_context = dict(bundle.main_context or {})
        for key in ("active_goal", "latest_correction"):
            value = str(main_context.get(key, "") or "").strip()
            if value:
                candidates.append(value)
        for item in bundle.corrections:
            value = str(item or "").strip()
            if value:
                candidates.append(value)
        for summary in bundle.task_summaries:
            for key in ("summary", "query"):
                value = str(summary.get(key, "") or "").strip()
                if value:
                    candidates.append(value)
        for message in bundle.message_slice[-8:]:
            if str(message.get("role", "") or "") != "user":
                continue
            value = str(message.get("content", "") or "").strip()
            if value:
                candidates.append(value)
        filtered: list[str] = []
        for item in candidates:
            normalized = " ".join(item.split()).strip()
            if not normalized or normalized.endswith(("?", "？")):
                continue
            filtered.append(normalized)
        return filtered

    def _make_title(self, text: str) -> str:
        compact = " ".join(str(text or "").split()).strip()
        if any("\u4e00" <= char <= "\u9fff" for char in compact):
            return compact[:24]
        return " ".join(compact.split()[:8]) or "Memory Note"

    def _extract_json(self, text: str) -> dict[str, object]:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise ValueError("No JSON object found in model response")
