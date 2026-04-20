from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from memory.read_models import MemoryRecallRequest, MemoryRecallSelection


MessageInvoker = Callable[[list[dict[str, str]]], Awaitable[object]]


class MemoryReadAgent:
    def __init__(self, *, message_invoker: MessageInvoker | None = None) -> None:
        self._message_invoker = message_invoker

    def set_message_invoker(self, message_invoker: MessageInvoker | None) -> None:
        self._message_invoker = message_invoker

    async def select_relevant(self, request: MemoryRecallRequest) -> MemoryRecallSelection:
        if request.ignore_memory:
            return MemoryRecallSelection(
                should_recall=False,
                reason="ignore_memory",
                confidence=1.0,
                ignore_memory=True,
            )

        headers = list(request.manifest_headers)
        if not headers:
            return MemoryRecallSelection(
                should_recall=False,
                reason="no_manifest_headers",
                confidence=1.0,
            )

        if request.explicit_memory_mode == "inventory":
            return MemoryRecallSelection(
                should_recall=False,
                reason="explicit_memory_inventory",
                confidence=1.0,
                manifest_only=True,
            )

        if self._message_invoker is not None:
            selection = await self._select_with_model(request)
            if selection is not None:
                return selection

        return self._select_with_fallback(request)

    async def _select_with_model(self, request: MemoryRecallRequest) -> MemoryRecallSelection | None:
        assert self._message_invoker is not None
        headers = request.manifest_headers[:80]
        manifest = "\n".join(
            f"- {header.get('note_id', '')} | {header.get('memory_type', '')}/{header.get('memory_class', '')} | "
            f"{header.get('title', '')} | {header.get('description', '')}"
            for header in headers
        )
        system_prompt = (
            "You are the durable memory recall subagent. "
            "Given a user query, main working context, and a manifest of available durable memory headers, "
            "select only the memory note ids that are clearly useful for answering the current query. "
            "Be strict. If nothing is clearly useful, return an empty selection. "
            "Never answer the user directly. Return JSON with keys: should_recall, selected_note_ids, reason, confidence, "
            "needs_verification, manifest_only, ignore_memory."
        )
        user_prompt = json.dumps(
            {
                "query": request.query,
                "main_context": request.main_context,
                "task_summaries": request.task_summaries[:4],
                "session_summary": request.session_summary[:600],
                "explicit_memory_mode": request.explicit_memory_mode,
                "ignore_memory": request.ignore_memory,
                "preferred_types": request.preferred_types,
                "preferred_memory_classes": request.preferred_memory_classes,
                "recent_tools": request.recent_tools[:8],
                "recently_surfaced_note_ids": request.recently_surfaced_note_ids[:12],
                "manifest": manifest,
            },
            ensure_ascii=False,
        )
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
            selection = MemoryRecallSelection.model_validate(payload)
            valid_ids = {str(header.get("note_id", "") or "") for header in request.manifest_headers}
            selection.selected_note_ids = [
                note_id for note_id in selection.selected_note_ids if note_id in valid_ids
            ][:5]
            if not selection.selected_note_ids and not selection.manifest_only:
                selection.should_recall = False
            return selection
        except Exception:
            return None

    def _select_with_fallback(self, request: MemoryRecallRequest) -> MemoryRecallSelection:
        query_terms = _extract_terms(request.query)
        if not query_terms:
            return MemoryRecallSelection(
                should_recall=False,
                reason="empty_query_terms",
                confidence=0.0,
            )

        preferred_types = set(request.preferred_types)
        preferred_classes = set(request.preferred_memory_classes)
        seen = set(request.recently_surfaced_note_ids)
        scored: list[tuple[float, str]] = []
        for header in request.manifest_headers:
            note_id = str(header.get("note_id", "") or "")
            if not note_id or note_id in seen:
                continue
            score = _score_header(
                header=header,
                query_terms=query_terms,
                preferred_types=preferred_types,
                preferred_classes=preferred_classes,
            )
            if score <= 0:
                continue
            scored.append((score, note_id))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [note_id for _, note_id in scored[:3]]
        if not selected:
            return MemoryRecallSelection(
                should_recall=False,
                reason="no_clear_manifest_match",
                confidence=0.2,
            )
        return MemoryRecallSelection(
            should_recall=True,
            selected_note_ids=selected,
            reason="manifest_overlap_fallback",
            confidence=0.45,
            needs_verification=bool(re.search(r"(当前|现在|最近|latest|current)", request.query, flags=re.IGNORECASE)),
        )

    def _extract_json(self, text: str) -> dict[str, object]:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise ValueError("No JSON object found in model response")


def _extract_terms(text: str) -> set[str]:
    normalized = str(text or "").lower()
    parts = re.findall(r"[a-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", normalized)
    terms: set[str] = set()
    for part in parts:
        if part in {"什么", "一下", "一个", "默认", "memory"}:
            continue
        terms.add(part)
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", part):
            for size in (2, 3):
                if len(part) < size:
                    continue
                for index in range(0, len(part) - size + 1):
                    chunk = part[index : index + size]
                    if chunk not in {"什么", "一下", "一个"}:
                        terms.add(chunk)
    return terms


def _score_header(
    *,
    header: dict[str, object],
    query_terms: set[str],
    preferred_types: set[str],
    preferred_classes: set[str],
) -> float:
    haystacks = [
        str(header.get("title", "") or ""),
        str(header.get("description", "") or ""),
        str(header.get("canonical_statement", "") or ""),
        " ".join(str(item) for item in list(header.get("retrieval_hints", []) or [])),
    ]
    combined = " ".join(haystacks).lower()
    if not combined.strip():
        return 0.0

    matches = sum(1.0 for term in query_terms if term in combined)
    score = matches
    memory_type = str(header.get("memory_type", "") or "")
    memory_class = str(header.get("memory_class", "") or "")
    preferred_bonus = 0.0
    if preferred_types and memory_type in preferred_types:
        preferred_bonus += 1.5
    if preferred_classes and memory_class in preferred_classes:
        preferred_bonus += 1.0
    if matches == 0 and preferred_bonus < 1.0:
        return 0.0
    score += preferred_bonus
    if str(header.get("status", "") or "") not in {"active", ""}:
        score -= 1.0
    if not bool(header.get("eligible_for_injection", True)):
        score -= 2.0
    return score
