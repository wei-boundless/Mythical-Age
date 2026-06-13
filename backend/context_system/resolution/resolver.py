from __future__ import annotations

from typing import Any

import re

from request_intent.frame_access import capability_needs, explicit_paths, material_kinds, turn_signals
from context_system.current_turn.turn_binding import BundleItem, TurnBinding, ResolvedBinding


_ORDER_SPLIT_RE = re.compile(r"(?:(?<!优)先|再|然后|最后|并且|以及|，|,|；|;)")
_ORDINAL_FOLLOWUP_RE = re.compile(r"(?:第\s*([一二三四五六七八九十\d]+)\s*个?\s*子任务|([一二三四五六七八九十\d]+)\s*号\s*子任务|(?:展开|只展开|处理|继续)\s*第?\s*([一二三四五六七八九十\d]+)\s*个)")
_ORDINAL_MULTI_FOLLOWUP_RE = re.compile(r"第\s*([一二三四五六七八九十\d]+)\s*个?\s*(?:和|、|,|，)\s*第?\s*([一二三四五六七八九十\d]+)\s*个?\s*子任务")


class ContextResolver:
    """Resolves current-turn truth from explicit input plus candidate-only state."""

    def resolve(
        self,
        *,
        session_id: str,
        task_id: str,
        user_message: str,
        memory_runtime_view: dict[str, Any] | None = None,
        query_understanding: dict[str, Any] | None = None,
        task_goal_spec: dict[str, Any] | None = None,
        continuation_candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        continuation_decision: dict[str, Any] | None = None,
    ) -> TurnBinding:
        memory_view = dict(memory_runtime_view or {})
        understanding = dict(query_understanding or {})
        legacy_task_goal_spec_payload = dict(task_goal_spec or understanding.get("task_goal_spec") or {})
        continuation_candidate_payloads = [
            dict(item)
            for item in list(continuation_candidates or [])
            if isinstance(item, dict)
        ]
        continuation_decision_payload = dict(continuation_decision or understanding.get("continuation_decision") or {})
        explicit_inputs = self._explicit_inputs(understanding)
        ordinal_followups = _ordinal_followups(user_message)
        bundle_bindings = self._bundle_followup_bindings(
            memory_runtime_view=memory_view,
            ordinals=ordinal_followups,
        )
        structural_signals = turn_signals(understanding)
        if legacy_task_goal_spec_payload:
            structural_signals["legacy_task_goal_spec_candidate"] = {
                "present": True,
                "runtime_authority": "ignored",
                "migration_target": "model_action_request.task_contract_seed",
                "authority": "context.current_turn.legacy_goal_diagnostics",
            }
        bindings = self._resolved_bindings(
            explicit_inputs=explicit_inputs,
            structural_signals=structural_signals,
        )
        if bundle_bindings:
            bindings = [*bundle_bindings, *bindings]
        context_recall_candidates = _context_recall_candidates(
            continuation_candidates=continuation_candidate_payloads,
            continuation_decision=continuation_decision_payload,
            memory_runtime_view=memory_view,
        )
        bundle_items = self._bundle_items(
            task_id=task_id,
            user_message=user_message,
            explicit_inputs=explicit_inputs,
            bindings=bindings,
            bundle_bindings=bundle_bindings,
        )
        bundle_id = _bundle_id_for_context(task_id=task_id, bundle_items=bundle_items, bundle_bindings=bundle_bindings)
        execution_mode = "bundle" if len(bundle_items) > 1 else "single"
        intent = str(understanding.get("intent") or "")
        if bundle_bindings:
            explicit_inputs["ordinal_followup"] = ordinal_followups
            intent = "bundle_followup"
        followup_target_kind = str(
            explicit_inputs.get("followup_target_kind")
            or continuation_decision_payload.get("followup_target_kind")
            or ""
        ).strip()
        followup_target_refs = tuple(
            _dedupe_text(
                [
                    *(item.followup_target_ref for item in bundle_items if str(item.followup_target_ref or "").strip()),
                    *(
                        str(binding.result_handle_id or binding.owner_task_id or binding.identity or "").strip()
                        for binding in bundle_bindings
                    ),
                    *(
                        str(item or "").strip()
                        for item in list(continuation_decision_payload.get("followup_target_refs") or [])
                        if str(item or "").strip()
                    ),
                    *_followup_target_refs_for_kind(followup_target_kind, bindings),
                ]
            )
        )
        restore_candidate_refs = tuple(
            str(item.get("candidate_id") or "")
            for item in list(memory_view.get("restore_candidates") or [])
            if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
        )
        return TurnBinding(
            session_id=session_id,
            task_id=task_id,
            user_message=user_message,
            intent=intent,
            execution_mode=execution_mode,
            bundle_id=bundle_id,
            explicit_inputs=explicit_inputs,
            resolved_bindings=tuple(bindings),
            bundle_items=tuple(bundle_items),
            followup_target_refs=followup_target_refs,
            restore_candidates_used=restore_candidate_refs,
            continuation_candidates=tuple(continuation_candidate_payloads),
            continuation_decision=continuation_decision_payload,
            context_recall_candidates=tuple(context_recall_candidates),
            structural_signals=structural_signals,
            confidence=float(understanding.get("confidence") or 0.0),
        )

    def _explicit_inputs(self, understanding: dict[str, Any]) -> dict[str, Any]:
        signals = {
            **dict(understanding.get("structural_signals") or {}),
            **turn_signals(understanding),
        }
        paths = explicit_paths(understanding)
        kinds = material_kinds(understanding)
        result: dict[str, Any] = {}
        if paths:
            result["explicit_paths"] = paths
            primary_path = paths[0]
            if "pdf" in kinds:
                result["explicit_pdf_path"] = primary_path
            elif "dataset" in kinds:
                result["explicit_dataset_path"] = primary_path
            else:
                result["explicit_workspace_path"] = primary_path
        for key in (
            "explicit_dataset_path",
            "explicit_pdf_path",
            "explicit_workspace_path",
            "followup_target_kind",
            "followup_scope",
        ):
            value = signals.get(key)
            if value not in ("", [], {}, None):
                result[key] = value
        if signals.get("followup_ordinals"):
            result["followup_ordinals"] = list(signals.get("followup_ordinals") or [])
        capability_requests = [
            str(item).strip()
            for item in sorted(capability_needs(understanding))
            if str(item).strip()
        ]
        if capability_requests:
            result["capability_requests"] = capability_requests
        return result

    def _resolved_bindings(
        self,
        *,
        explicit_inputs: dict[str, Any],
        structural_signals: dict[str, Any],
    ) -> list[ResolvedBinding]:
        bindings: list[ResolvedBinding] = []
        explicit_pdf = str(explicit_inputs.get("explicit_pdf_path") or "").strip()
        explicit_dataset = str(explicit_inputs.get("explicit_dataset_path") or "").strip()
        if explicit_pdf:
            bindings.append(
                ResolvedBinding(
                    binding_id=f"binding:explicit:pdf:{_slug(explicit_pdf)}",
                    binding_kind="source_file",
                    identity=_identity(explicit_pdf),
                    file_kind="pdf",
                    source="explicit_user_input",
                    confidence=0.98,
                    metadata={"path": explicit_pdf},
                )
            )
        if explicit_dataset:
            bindings.append(
                ResolvedBinding(
                    binding_id=f"binding:explicit:dataset:{_slug(explicit_dataset)}",
                    binding_kind="source_file",
                    identity=_identity(explicit_dataset),
                    file_kind="dataset",
                    source="explicit_user_input",
                    confidence=0.98,
                    metadata={"path": explicit_dataset},
                )
            )
        return _dedupe_bindings(bindings)

    def _bundle_followup_bindings(
        self,
        *,
        memory_runtime_view: dict[str, Any],
        ordinals: list[int],
    ) -> list[ResolvedBinding]:
        if not ordinals:
            return []
        state_snapshot = dict(memory_runtime_view.get("state_snapshot") or {})
        bundle_refs = [
            dict(item)
            for item in list(state_snapshot.get("bundle_result_refs") or [])
            if isinstance(item, dict)
        ]
        if not bundle_refs:
            for candidate in list(memory_runtime_view.get("restore_candidates") or []):
                if not isinstance(candidate, dict) or str(candidate.get("restore_kind") or "") != "bundle_ref":
                    continue
                value = candidate.get("value")
                if isinstance(value, dict):
                    bundle_refs.append(dict(value))
        by_ordinal = {_safe_int(item.get("ordinal")): item for item in bundle_refs if _safe_int(item.get("ordinal")) > 0}
        bindings: list[ResolvedBinding] = []
        for ordinal in ordinals:
            ref = by_ordinal.get(ordinal)
            if not ref:
                continue
            task_id = str(ref.get("task_id") or "").strip()
            task_kind = str(ref.get("task_kind") or ref.get("capability_kind") or "").strip()
            bindings.append(
                ResolvedBinding(
                    binding_id=f"binding:bundle:{ordinal}:{_slug(task_id or ref.get('query') or '')}",
                    binding_kind="task_ref",
                    identity=task_id or f"bundle:{ordinal}",
                    file_kind="pdf" if task_kind == "pdf" else "dataset" if task_kind == "structured_data" else task_kind,
                    result_handle_id=task_id,
                    owner_task_id=task_id,
                    confidence=0.9,
                    source="task_ref",
                    metadata={
                        "bundle_id": str(ref.get("bundle_id") or "").strip(),
                        "item_id": str(ref.get("item_id") or "").strip(),
                        "ordinal": ordinal,
                        "query": str(ref.get("query") or "").strip(),
                        "summary": str(ref.get("summary") or "").strip(),
                        "task_kind": task_kind,
                        "capability_kind": str(ref.get("capability_kind") or "").strip(),
                        "required_tool": str(ref.get("required_tool") or "").strip(),
                        "source_kind": _source_kind_for_capability(str(ref.get("capability_kind") or "").strip()),
                        "key_points": list(ref.get("key_points") or []),
                    },
                )
            )
        return bindings

    def _bundle_items(
        self,
        *,
        task_id: str,
        user_message: str,
        explicit_inputs: dict[str, Any],
        bindings: list[ResolvedBinding],
        bundle_bindings: list[ResolvedBinding],
    ) -> list[BundleItem]:
        followup_items = _bundle_items_from_followup_bindings(task_id=task_id, bindings=bundle_bindings)
        if followup_items:
            return followup_items
        message = str(user_message or "").strip()
        if not _looks_compound(message):
            return []
        bundle_id = f"bundle:{task_id}"
        parts = [part.strip(" ，,；;") for part in _ORDER_SPLIT_RE.split(message) if part.strip(" ，,；;")]
        items: list[BundleItem] = []
        for part in parts:
            capability, tool = _capability_for_text(part)
            if not capability:
                continue
            binding = _binding_for_capability(capability, bindings)
            source_kind = _source_kind_for_capability(capability)
            target_ref = ""
            if binding is not None:
                target_ref = str(binding.result_handle_id or binding.source_handle_id or binding.identity or "").strip()
            items.append(
                BundleItem(
                    item_id=f"{bundle_id}:item:{len(items) + 1}",
                    ordinal=len(items) + 1,
                    user_text=part,
                    bundle_id=bundle_id,
                    recipe_id="",
                    capability_kind=capability,
                    required_tool=tool,
                    requested_outputs=tuple(_requested_outputs_for_capability(capability)),
                    inherited_binding_refs=tuple(
                        _dedupe_text([binding.binding_id] if binding is not None and binding.binding_id else [])
                    ),
                    followup_target_ref=target_ref,
                    target_ref=target_ref,
                    target_binding=binding,
                    output_requirement="answer_part",
                    metadata={"source": "compound_user_message", "bundle_id": bundle_id, "source_kind": source_kind},
                )
            )
        return items if len(items) > 1 else []


def _looks_compound(message: str) -> bool:
    lowered = message.lower()
    if _looks_like_creative_writing_runtime_packet(lowered):
        return False
    markers = len(re.findall(r"(?<!优)先|再|然后|最后|并且|以及", lowered))
    domains = sum(
        1
        for matched in (
            any(item in lowered for item in ("pdf", ".pdf", "报告")) or _looks_like_document_scope(lowered),
            any(item in lowered for item in (".xlsx", ".csv", "表", "仓库", "缺货")),
            any(item in lowered for item in ("天气", "weather")),
            any(item in lowered for item in ("黄金", "金价", "gold")),
        )
        if matched
    )
    return markers >= 2 or domains >= 2


def _capability_for_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if (
        (any(item in lowered for item in ("pdf", ".pdf", "报告")) or _looks_like_document_scope(lowered))
        and not any(item in lowered for item in ("天气", "黄金", "金价"))
    ):
        return "pdf", ""
    if any(item in lowered for item in (".xlsx", ".csv", "表", "仓库", "缺货", "库存")):
        return "structured_data", ""
    if any(item in lowered for item in ("天气", "weather")):
        return "realtime_network", "web_search"
    if any(item in lowered for item in ("黄金", "金价", "gold")):
        return "realtime_network", "web_search"
    return "", ""


def _looks_like_creative_writing_runtime_packet(text: str) -> bool:
    return any(marker in text for marker in ("网文", "小说", "章节", "正文", "细纲", "大纲", "第1章", "第 1 章")) and any(
        marker in text for marker in ("本轮工作", "当前批次", "本节点", "产物政策", "卷")
    )


def _looks_like_document_scope(text: str) -> bool:
    if re.search(r"page\s*\d+", text, re.I):
        return True
    if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:页|部分)", text):
        return True
    if not re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*(?:章|节)", text):
        return False
    if _looks_like_creative_writing_runtime_packet(text):
        return False
    return any(marker in text for marker in ("pdf", ".pdf", "报告", "文档", "文件", "材料", "阅读", "抽取", "页码", "目录"))


def _source_kind_for_capability(capability: str) -> str:
    if capability == "pdf":
        return "pdf"
    if capability == "structured_data":
        return "dataset"
    if capability == "realtime_network":
        return "external_web"
    if capability in {"retrieval", "rag"}:
        return "knowledge"
    return "knowledge_base"


def _requested_outputs_for_capability(capability: str) -> list[str]:
    if capability in {"pdf", "structured_data"}:
        return ["final_answer", "task_summary_refs"]
    return ["final_answer"]


def _binding_for_capability(capability: str, bindings: list[ResolvedBinding]) -> ResolvedBinding | None:
    desired = "pdf" if capability == "pdf" else "dataset" if capability == "structured_data" else ""
    if not desired:
        return None
    return next((item for item in bindings if item.file_kind == desired), None)


def _bundle_items_from_followup_bindings(*, task_id: str, bindings: list[ResolvedBinding]) -> list[BundleItem]:
    items: list[BundleItem] = []
    for binding in bindings:
        if binding.binding_kind != "task_ref":
            continue
        metadata = dict(binding.metadata or {})
        capability = str(metadata.get("capability_kind") or "").strip()
        required_tool = str(metadata.get("required_tool") or "").strip()
        user_text = str(metadata.get("query") or metadata.get("summary") or binding.identity or "").strip()
        bundle_id = str(metadata.get("bundle_id") or f"bundle:{task_id}").strip()
        ordinal = _safe_int(metadata.get("ordinal"))
        item_id = str(metadata.get("item_id") or f"{bundle_id}:item:{ordinal or len(items) + 1}").strip()
        source_kind = str(metadata.get("source_kind") or _source_kind_for_capability(capability)).strip()
        followup_target_ref = str(binding.result_handle_id or binding.owner_task_id or binding.identity or "").strip()
        items.append(
            BundleItem(
                item_id=item_id,
                ordinal=ordinal or len(items) + 1,
                user_text=user_text,
                bundle_id=bundle_id,
                recipe_id="",
                capability_kind=capability,
                required_tool=required_tool,
                requested_outputs=tuple(_requested_outputs_for_capability(capability)),
                inherited_binding_refs=(binding.binding_id,) if binding.binding_id else (),
                followup_target_ref=followup_target_ref,
                target_ref=followup_target_ref,
                target_binding=binding,
                output_requirement="answer_part",
                metadata={"source": "bundle_followup_binding", "source_kind": source_kind, **metadata},
            )
        )
    return items


def _dedupe_bindings(bindings: list[ResolvedBinding]) -> list[ResolvedBinding]:
    result: list[ResolvedBinding] = []
    seen: set[tuple[str, str]] = set()
    for item in bindings:
        key = (item.file_kind, item.identity)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _context_recall_candidates(
    *,
    continuation_candidates: list[dict[str, Any]],
    continuation_decision: dict[str, Any],
    memory_runtime_view: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    selected_id = str(continuation_decision.get("selected_candidate_id") or "").strip()
    for candidate in continuation_candidates:
        if not isinstance(candidate, dict):
            continue
        payload = dict(candidate)
        payload["recall_source"] = "continuation_candidate"
        if selected_id and str(payload.get("candidate_id") or "") == selected_id:
            payload["selected_by_context_recall"] = True
        results.append(_compact_recall_candidate(payload))
    for candidate in list(memory_runtime_view.get("restore_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        payload = dict(candidate)
        payload["recall_source"] = "restore_candidate"
        results.append(_compact_recall_candidate(payload))
    return [item for item in results if item]


def _compact_recall_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = (
        "candidate_id",
        "recall_source",
        "source",
        "source_kind",
        "file_kind",
        "target_kind",
        "identity",
        "value",
        "score",
        "confidence",
        "compatible",
        "selected_by_context_recall",
        "recall_payload",
        "metadata",
    )
    return {
        key: candidate.get(key)
        for key in allowed_keys
        if candidate.get(key) not in ("", None, [], {})
    }


def _bundle_id_for_context(
    *,
    task_id: str,
    bundle_items: list[BundleItem],
    bundle_bindings: list[ResolvedBinding],
) -> str:
    for item in bundle_items:
        if str(item.bundle_id or "").strip():
            return str(item.bundle_id or "").strip()
    for binding in bundle_bindings:
        bundle_id = str(dict(binding.metadata or {}).get("bundle_id") or "").strip()
        if bundle_id:
            return bundle_id
    return f"bundle:{task_id}" if bundle_items else ""


def _followup_target_refs_for_kind(kind: str, bindings: list[ResolvedBinding]) -> list[str]:
    target_kind = str(kind or "").strip()
    if target_kind == "active_subset":
        return [
            str(value or "").strip()
            for binding in bindings
            for value in (binding.subset_handle_id, binding.result_handle_id, binding.owner_task_id)
            if str(value or "").strip()
        ]
    if target_kind == "active_dataset":
        return [
            str(value or "").strip()
            for binding in bindings
            if binding.file_kind == "dataset"
            for value in (binding.result_handle_id, binding.owner_task_id, binding.identity)
            if str(value or "").strip()
        ]
    if target_kind == "active_pdf":
        return [
            str(value or "").strip()
            for binding in bindings
            if binding.file_kind == "pdf"
            for value in (binding.result_handle_id, binding.owner_task_id, binding.identity)
            if str(value or "").strip()
        ]
    return []


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _ordinal_followups(message: str) -> list[int]:
    text = str(message or "")
    ordinals: list[int] = []
    for match in _ORDINAL_MULTI_FOLLOWUP_RE.finditer(text):
        for group in match.groups():
            value = _parse_ordinal(group)
            if value > 0 and value not in ordinals:
                ordinals.append(value)
    for match in _ORDINAL_FOLLOWUP_RE.finditer(text):
        raw = match.group(1) or match.group(2) or match.group(3)
        value = _parse_ordinal(raw)
        if value > 0 and value not in ordinals:
            ordinals.append(value)
    return ordinals


def _parse_ordinal(value: str) -> int:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
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
    if text in mapping:
        return mapping[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + mapping.get(text[1:], 0)
    if text.endswith("十") and len(text) == 2:
        return mapping.get(text[:1], 0) * 10
    if "十" in text and len(text) == 3:
        left, right = text.split("十", 1)
        return mapping.get(left, 0) * 10 + mapping.get(right, 0)
    return 0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _slug(value: str) -> str:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", str(value or "").lower()).strip("-")
    return compact[:48] or "main"



