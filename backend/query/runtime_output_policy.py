from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any, Callable

from query.answer_finalizer import (
    RAGEvidencePack,
    answer_looks_like_snippet_dump,
    build_rag_answer_finalization_messages,
    build_rag_evidence_pack,
    normalize_finalized_answer,
    total_compact_chars,
)
from query.models import QueryExecutionPlan
from query.output_boundary import (
    AssistantOutputResponse,
    contains_internal_protocol,
    sanitize_visible_assistant_content,
)
from query.output_classifier import looks_like_progress_text
from runtime.model_runtime import ModelRuntime, ModelRuntimeError, stringify_content

logger = logging.getLogger(__name__)


class RuntimeOutputPolicy:
    def __init__(
        self,
        *,
        model_runtime: ModelRuntime,
        stringify_tool_output: Callable[[Any], str],
    ) -> None:
        self.model_runtime = model_runtime
        self._stringify_tool_output = stringify_tool_output

    async def maybe_finalize_rag_output(
        self,
        *,
        execution: QueryExecutionPlan,
        retrieval_results: list[dict[str, Any]] | None,
        output_response: AssistantOutputResponse,
    ) -> AssistantOutputResponse:
        if str(execution.query_understanding.route or "") != "rag":
            return output_response
        if str(getattr(output_response, "finalization_policy", "none") or "none") != "route_required":
            return output_response
        fallback_reason = str(getattr(output_response, "fallback_reason", "") or "")
        preserve_no_receipt_fallback = fallback_reason in {"no_receipt_tool_claim", "no_receipt_query_promise"}
        evidence_pack = build_rag_evidence_pack(
            user_query=execution.message,
            retrieval_results=retrieval_results,
            max_items=3,
        )
        if not self.rag_evidence_pack_can_finalize(evidence_pack):
            return output_response if preserve_no_receipt_fallback else self.fallback_rag_output_response(output_response)
        finalized = await self.rewrite_rag_answer_with_model(evidence_pack=evidence_pack)
        if not finalized:
            return self.fallback_rag_output_response(output_response)
        return replace(
            output_response,
            canonical_answer=finalized,
            selected_channel="answer_candidate",
            selected_source="rag_answer_finalization",
            canonical_state="stable_answer",
            persist_policy="persist_canonical",
            finalization_policy="none",
            fallback_reason="",
        )

    async def rewrite_rag_answer_with_model(
        self,
        *,
        evidence_pack: RAGEvidencePack,
    ) -> str:
        messages = build_rag_answer_finalization_messages(evidence_pack=evidence_pack)
        try:
            response = await self.model_runtime.invoke_messages(messages)
        except ModelRuntimeError:
            return ""
        except Exception:
            logger.exception("RAG answer finalization failed")
            return ""
        content = normalize_finalized_answer(stringify_content(getattr(response, "content", response)))
        if (
            not content
            or contains_internal_protocol(content)
            or self.looks_like_rag_procedural_answer(content)
            or answer_looks_like_snippet_dump(content, evidence_pack)
        ):
            return ""
        return content

    def rag_evidence_pack_can_finalize(self, evidence_pack: RAGEvidencePack | None) -> bool:
        if evidence_pack is None:
            return False
        if len(list(evidence_pack.items or [])) < 2:
            return False
        return total_compact_chars(evidence_pack) >= 60

    def fallback_rag_output_response(self, output_response: AssistantOutputResponse) -> AssistantOutputResponse:
        return replace(
            output_response,
            canonical_answer="已检索到相关资料，但当前模型尚未产出可直接展示的结论。",
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="route_required",
            fallback_reason="rag_missing_answer",
        )

    def maybe_gate_memory_output(
        self,
        *,
        execution: QueryExecutionPlan,
        output_response: AssistantOutputResponse,
    ) -> AssistantOutputResponse:
        if str(execution.query_understanding.route or "") != "memory":
            return output_response
        if str(getattr(output_response, "selected_channel", "") or "") == "fallback_answer":
            return output_response
        if str(getattr(output_response, "canonical_state", "") or "") == "progress_only":
            return self.fallback_memory_output_response(output_response)
        if not self.memory_output_needs_gate(output_response):
            return output_response
        return self.fallback_memory_output_response(output_response)

    def memory_output_needs_gate(self, output_response: AssistantOutputResponse) -> bool:
        selected_source = str(getattr(output_response, "selected_source", "") or "")
        if not selected_source.startswith("segment."):
            return False
        answer = sanitize_visible_assistant_content(
            str(getattr(output_response, "canonical_answer", "") or "")
        ).strip()
        if not answer:
            return False
        if looks_like_progress_text(answer):
            return True
        leak_flags = {str(flag or "").strip() for flag in list(getattr(output_response, "leak_flags", []) or [])}
        if not leak_flags:
            return False
        compact = re.sub(r"\s+", "", answer)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in answer
            for token in (
                "检查",
                "查看",
                "读取",
                "分析",
                "确认",
                "整理",
                "梳理",
                "回顾",
                "回忆",
                "目录结构",
                "知识库",
            )
        )

    def fallback_memory_output_response(self, output_response: AssistantOutputResponse) -> AssistantOutputResponse:
        return replace(
            output_response,
            canonical_answer="当前没有足够稳定的会话内容可直接回答这个问题。",
            selected_channel="fallback_answer",
            selected_source="fallback_policy",
            canonical_state="missing_answer",
            persist_policy="do_not_persist",
            finalization_policy="none",
            fallback_reason="memory_visible_pollution",
        )

    def looks_like_rag_procedural_answer(self, answer: str) -> bool:
        normalized = sanitize_visible_assistant_content(str(answer or "")).strip()
        if not normalized:
            return False
        normalized = re.sub(r"^(?:岩[，,\s]*)+", "", normalized).strip()
        if not normalized:
            return False
        if looks_like_progress_text(normalized):
            return True
        compact = re.sub(r"\s+", "", normalized)
        if not compact.startswith(("我来先", "我先来", "我先", "我来", "我将", "我会", "让我", "接下来我")):
            return False
        return any(
            token in normalized
            for token in (
                "检索",
                "搜索",
                "查看",
                "检查",
                "读取",
                "分析",
                "确认",
                "整理",
                "改写",
                "根据这些证据",
                "整理答案",
            )
        )

    def merge_summary_key_points(
        self,
        existing: list[str],
        *,
        pdf_path: str = "",
        page: int | None = None,
        pdf_mode: str = "",
        pdf_section: str = "",
        pdf_pages: list[int] | None = None,
        readable_pages: int | None = None,
        usable_pages: int | None = None,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()

        def add(item: str) -> None:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            merged.append(normalized)

        for item in existing:
            add(str(item or ""))
        if page is not None:
            add(f"page={page}")
        if pdf_mode:
            add(f"pdf_mode={pdf_mode}")
        if pdf_section:
            add(f"pdf_section={pdf_section}")
        normalized_pages = [int(page_item) for page_item in list(pdf_pages or []) if int(page_item) > 0]
        if normalized_pages:
            add("pdf_pages=" + ",".join(str(page_item) for page_item in normalized_pages))
        if readable_pages is not None:
            add(f"readable_pages={readable_pages}")
        if usable_pages is not None:
            add(f"usable_pages={usable_pages}")
        if pdf_path:
            add(f"pdf={pdf_path}")
        return merged

    def pdf_task_kind_from_mode(self, mode: str) -> str:
        normalized = self.normalize_pdf_scope(str(mode or ""))
        if normalized == "page":
            return "document_page"
        if normalized == "section":
            return "document_section"
        return "document_read"

    def normalize_pdf_scope(self, mode: str) -> str:
        normalized = str(mode or "").strip().lower()
        if normalized in {"page", "page-read", "page_read"}:
            return "page"
        if normalized in {"section", "section-read", "section_read"}:
            return "section"
        return "document"
