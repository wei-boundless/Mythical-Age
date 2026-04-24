from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from pdf_analysis.catalog import PdfAnalysisCatalog
from query.models import BundleItemPlan, BundlePlan
from understanding import QueryUnderstanding


_DATASET_REF_RE = re.compile(
    r"([^\s,，;；:：\"'“”‘’]+?\.(?:xlsx|csv|xls|json|parquet))",
    flags=re.IGNORECASE,
)
_PAGE_RE = re.compile(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页")
_SECTION_RE = re.compile(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:部分|章|节)")
_WEATHER_MARKERS = ("weather", "forecast", "天气", "气温", "温度", "预报")
_GOLD_MARKERS = ("gold price", "spot gold", "xau", "黄金", "金价", "现货黄金")
_KNOWLEDGE_MARKERS = ("知识库", "本地资料", "报告", "白皮书")
_CLAUSE_BREAK_RE = re.compile(r"[，,。；;\n]")


@dataclass(slots=True)
class _AnchorCandidate:
    position: int
    item: BundleItemPlan


class BundlePlanner:
    def plan(
        self,
        *,
        session_id: str,
        message: str,
        understanding: QueryUnderstanding,
        authority_context: dict[str, Any] | None = None,
    ) -> BundlePlan | None:
        normalized = (message or "").strip()
        if not normalized:
            return None
        if understanding.task_kind != "multi_capability_request":
            return None

        anchors: list[_AnchorCandidate] = []
        pdf_candidate = self._build_pdf_item(normalized)
        if pdf_candidate is not None:
            anchors.append(pdf_candidate)
        dataset_candidate = self._build_dataset_item(normalized)
        if dataset_candidate is not None:
            anchors.append(dataset_candidate)
        weather_candidate = self._build_weather_item(normalized)
        if weather_candidate is not None:
            anchors.append(weather_candidate)
        gold_candidate = self._build_gold_item(normalized)
        if gold_candidate is not None:
            anchors.append(gold_candidate)
        knowledge_candidate = self._build_knowledge_item(
            normalized,
            authority_context=authority_context,
            existing_capabilities={anchor.item.capability for anchor in anchors},
        )
        if knowledge_candidate is not None:
            anchors.append(knowledge_candidate)

        deduped: list[_AnchorCandidate] = []
        seen_keys: set[tuple[str, str]] = set()
        for anchor in sorted(anchors, key=lambda item: item.position):
            key = (anchor.item.capability, anchor.item.execution_message.strip().lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(anchor)

        if len(deduped) < 2:
            return None

        bundle_id = self._bundle_id(session_id=session_id, message=normalized)
        items = [
            BundleItemPlan(
                item_id=f"{bundle_id}-item-{index}",
                index=index,
                goal=anchor.item.goal,
                user_visible_title=anchor.item.user_visible_title,
                execution_message=anchor.item.execution_message,
                source_kind=anchor.item.source_kind,
                capability=anchor.item.capability,
                execution_kind=anchor.item.execution_kind,
                explicit_refs=dict(anchor.item.explicit_refs),
                constraints=dict(anchor.item.constraints),
                followup_aliases=list(anchor.item.followup_aliases),
                origin=anchor.item.origin,
            )
            for index, anchor in enumerate(deduped, start=1)
        ]
        return BundlePlan(
            bundle_id=bundle_id,
            parent_query_id=f"{session_id}-bundle-parent",
            items=items,
            origin="strong_anchor_bundle",
        )

    def _build_pdf_item(self, message: str) -> _AnchorCandidate | None:
        explicit_refs = PdfAnalysisCatalog.extract_explicit_pdf_references(message)
        page_match = _PAGE_RE.search(message)
        section_match = _SECTION_RE.search(message)
        if not explicit_refs and page_match is None and section_match is None:
            return None

        position_candidates = [
            match.start()
            for match in (page_match, section_match)
            if match is not None
        ]
        if explicit_refs:
            first_ref = explicit_refs[0]
            ref_position = message.lower().find(first_ref.lower())
            if ref_position >= 0:
                position_candidates.append(ref_position)
        position = min(position_candidates) if position_candidates else 0
        clause = self._extract_clause(message, position)
        execution_message = clause
        if explicit_refs and explicit_refs[0] not in execution_message:
            execution_message = f"{explicit_refs[0]} {clause}".strip()
        if not execution_message:
            execution_message = clause or "总结 PDF 相关内容"
        title = "PDF 内容"
        if page_match is not None:
            title = page_match.group(0)
        elif section_match is not None:
            title = section_match.group(0)
        return _AnchorCandidate(
            position=position,
            item=BundleItemPlan(
                item_id="",
                index=0,
                goal=execution_message,
                user_visible_title=title,
                execution_message=execution_message,
                source_kind="document",
                capability="pdf_analysis",
                execution_kind="direct_tool",
                explicit_refs={"path": explicit_refs[0]} if explicit_refs else {},
                followup_aliases=["第一个子任务", "PDF", "文档"],
            ),
        )

    def _build_dataset_item(self, message: str) -> _AnchorCandidate | None:
        match = _DATASET_REF_RE.search(message)
        if match is None:
            return None
        dataset_path = match.group(1).strip()
        clause = self._extract_clause(message, match.start())
        execution_message = clause if dataset_path in clause else f"{clause} {dataset_path}".strip()
        return _AnchorCandidate(
            position=match.start(),
            item=BundleItemPlan(
                item_id="",
                index=0,
                goal=execution_message,
                user_visible_title=dataset_path.rsplit("/", 1)[-1],
                execution_message=execution_message,
                source_kind="dataset",
                capability="structured_data_analysis",
                execution_kind="direct_tool",
                explicit_refs={"path": dataset_path},
                followup_aliases=["第二个子任务", "表格", "数据表", dataset_path.rsplit("/", 1)[-1]],
            ),
        )

    def _build_weather_item(self, message: str) -> _AnchorCandidate | None:
        match_position = self._first_marker_position(message, _WEATHER_MARKERS)
        if match_position < 0:
            return None
        clause = self._extract_clause(message, match_position)
        return _AnchorCandidate(
            position=match_position,
            item=BundleItemPlan(
                item_id="",
                index=0,
                goal=clause,
                user_visible_title="天气",
                execution_message=clause,
                source_kind="external_web",
                capability="get_weather",
                execution_kind="direct_tool",
                followup_aliases=["天气", "实时查询", "第三个子任务"],
            ),
        )

    def _build_gold_item(self, message: str) -> _AnchorCandidate | None:
        match_position = self._first_marker_position(message, _GOLD_MARKERS)
        if match_position < 0:
            return None
        clause = self._extract_clause(message, match_position)
        return _AnchorCandidate(
            position=match_position,
            item=BundleItemPlan(
                item_id="",
                index=0,
                goal=clause,
                user_visible_title="黄金价格",
                execution_message=clause,
                source_kind="external_web",
                capability="get_gold_price",
                execution_kind="direct_tool",
                followup_aliases=["黄金", "金价", "实时查询"],
            ),
        )

    def _build_knowledge_item(
        self,
        message: str,
        *,
        authority_context: dict[str, Any] | None,
        existing_capabilities: set[str],
    ) -> _AnchorCandidate | None:
        if "search_knowledge" in existing_capabilities:
            return None
        if PdfAnalysisCatalog.extract_explicit_pdf_references(message):
            return None
        if _PAGE_RE.search(message) is not None or _SECTION_RE.search(message) is not None:
            return None
        if not any(marker in message for marker in _KNOWLEDGE_MARKERS):
            return None
        position = self._first_marker_position(message, _KNOWLEDGE_MARKERS)
        if position < 0:
            return None
        clause = self._extract_clause(message, position)
        if authority_context and str(authority_context.get("active_pdf", "") or "").strip():
            return None
        return _AnchorCandidate(
            position=position,
            item=BundleItemPlan(
                item_id="",
                index=0,
                goal=clause,
                user_visible_title="知识检索",
                execution_message=clause,
                source_kind="knowledge_base",
                capability="search_knowledge",
                execution_kind="direct_rag",
                followup_aliases=["知识库", "资料"],
            ),
        )

    def _extract_clause(self, message: str, position: int) -> str:
        if position < 0:
            return message.strip()
        start = 0
        for match in _CLAUSE_BREAK_RE.finditer(message):
            if match.start() >= position:
                break
            start = match.end()
        end = len(message)
        for match in _CLAUSE_BREAK_RE.finditer(message[position:]):
            end = position + match.start()
            break
        clause = message[start:end].strip(" ，,。；;:：")
        return clause or message.strip()

    def _first_marker_position(self, message: str, markers: tuple[str, ...]) -> int:
        lowered = message.lower()
        positions = [lowered.find(marker.lower()) for marker in markers if lowered.find(marker.lower()) >= 0]
        return min(positions) if positions else -1

    def _bundle_id(self, *, session_id: str, message: str) -> str:
        digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:10]
        return f"{session_id}-bundle-{digest}"
