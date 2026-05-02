from __future__ import annotations

import re
from typing import Any

from .current_turn import BundleItem, CurrentTurnContext, ResolvedBinding


_ORDER_SPLIT_RE = re.compile(r"(?:先|再|然后|最后|并且|以及|，|,|；|;)")
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
    ) -> CurrentTurnContext:
        memory_view = dict(memory_runtime_view or {})
        understanding = dict(query_understanding or {})
        explicit_inputs = self._explicit_inputs(understanding)
        ordinal_followups = _ordinal_followups(user_message)
        bundle_bindings = self._bundle_followup_bindings(
            memory_runtime_view=memory_view,
            ordinals=ordinal_followups,
        )
        bindings = self._resolved_bindings(
            explicit_inputs=explicit_inputs,
            memory_runtime_view=memory_view,
        )
        if bundle_bindings:
            bindings = [*bundle_bindings, *bindings]
        bundle_items = self._bundle_items(
            user_message=user_message,
            explicit_inputs=explicit_inputs,
            bindings=bindings,
        )
        execution_mode = "bundle" if len(bundle_items) > 1 else "single"
        intent = str(understanding.get("intent") or "")
        if bundle_bindings:
            explicit_inputs["ordinal_followup"] = ordinal_followups
            intent = "bundle_followup"
        restore_candidate_refs = tuple(
            str(item.get("candidate_id") or "")
            for item in list(memory_view.get("restore_candidates") or [])
            if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
        )
        return CurrentTurnContext(
            session_id=session_id,
            task_id=task_id,
            user_message=user_message,
            intent=intent,
            execution_mode=execution_mode,
            explicit_inputs=explicit_inputs,
            resolved_bindings=tuple(bindings),
            bundle_items=tuple(bundle_items),
            restore_candidates_used=restore_candidate_refs,
            confidence=float(understanding.get("confidence") or 0.0),
        )

    def _explicit_inputs(self, understanding: dict[str, Any]) -> dict[str, Any]:
        signals = dict(understanding.get("structural_signals") or {})
        tool_input = dict(understanding.get("tool_input") or {})
        result: dict[str, Any] = {}
        for key in (
            "explicit_dataset_path",
            "explicit_pdf_path",
            "explicit_workspace_path",
            "bound_dataset_path",
            "bound_pdf_path",
            "bound_pdf_mode",
            "bound_pdf_section",
        ):
            value = signals.get(key)
            if value not in ("", [], {}, None):
                result[key] = value
        if signals.get("bound_pdf_pages"):
            result["bound_pdf_pages"] = list(signals.get("bound_pdf_pages") or [])
        if tool_input:
            result["tool_input"] = tool_input
        capability_requests = [
            str(item).strip()
            for item in list(understanding.get("capability_requests") or [])
            if str(item).strip()
        ]
        if capability_requests:
            result["capability_requests"] = capability_requests
        return result

    def _resolved_bindings(
        self,
        *,
        explicit_inputs: dict[str, Any],
        memory_runtime_view: dict[str, Any],
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
        if bindings:
            return bindings

        state_snapshot = dict(memory_runtime_view.get("state_snapshot") or {})
        context_slots = dict(state_snapshot.get("context_slots") or {})
        active_handles = dict(state_snapshot.get("active_handles") or {})
        for key, file_kind in (("active_pdf", "pdf"), ("committed_pdf", "pdf"), ("active_dataset", "dataset"), ("committed_dataset", "dataset")):
            path = str(context_slots.get(key) or "").strip()
            if not path:
                continue
            bindings.append(
                ResolvedBinding(
                    binding_id=f"binding:state:{key}:{_slug(path)}",
                    binding_kind="source_file",
                    identity=_identity(path),
                    file_kind=file_kind,
                    source_handle_id=str(active_handles.get("active_object_handle_id") or context_slots.get("active_object_handle_id") or ""),
                    result_handle_id=str(active_handles.get("active_result_handle_id") or context_slots.get("active_result_handle_id") or ""),
                    subset_handle_id=str(active_handles.get("active_subset_handle_id") or context_slots.get("active_subset_handle_id") or ""),
                    owner_task_id=str(context_slots.get("active_binding_owner_task_id") or context_slots.get(f"{key}_owner_task_id") or ""),
                    source="session_state",
                    confidence=0.72 if key.startswith("committed_") else 0.82,
                    metadata={"slot_name": key, "path": path},
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
                    source="session_state",
                    metadata={
                        "ordinal": ordinal,
                        "query": str(ref.get("query") or "").strip(),
                        "summary": str(ref.get("summary") or "").strip(),
                        "task_kind": task_kind,
                        "capability_kind": str(ref.get("capability_kind") or "").strip(),
                        "required_tool": str(ref.get("required_tool") or "").strip(),
                        "key_points": list(ref.get("key_points") or []),
                    },
                )
            )
        return bindings

    def _bundle_items(
        self,
        *,
        user_message: str,
        explicit_inputs: dict[str, Any],
        bindings: list[ResolvedBinding],
    ) -> list[BundleItem]:
        message = str(user_message or "").strip()
        if not _looks_compound(message):
            return []
        parts = [part.strip(" ，,；;") for part in _ORDER_SPLIT_RE.split(message) if part.strip(" ，,；;")]
        items: list[BundleItem] = []
        for part in parts:
            capability, tool = _capability_for_text(part)
            if not capability:
                continue
            binding = _binding_for_capability(capability, bindings)
            items.append(
                BundleItem(
                    item_id=f"bundle:{len(items) + 1}:{_slug(part)}",
                    ordinal=len(items) + 1,
                    user_text=part,
                    capability_kind=capability,
                    required_tool=tool,
                    target_binding=binding,
                    output_requirement="answer_part",
                    metadata={"source": "compound_user_message"},
                )
            )
        return items if len(items) > 1 else []


def _looks_compound(message: str) -> bool:
    lowered = message.lower()
    markers = sum(1 for item in ("先", "再", "然后", "最后", "并且", "以及") if item in lowered)
    domains = sum(
        1
        for matched in (
            any(item in lowered for item in ("pdf", ".pdf", "报告", "第")),
            any(item in lowered for item in (".xlsx", ".csv", "表", "仓库", "缺货")),
            any(item in lowered for item in ("天气", "weather")),
            any(item in lowered for item in ("黄金", "金价", "gold")),
        )
        if matched
    )
    return markers >= 2 or domains >= 2


def _capability_for_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(item in lowered for item in ("pdf", ".pdf", "报告", "第")) and not any(item in lowered for item in ("天气", "黄金", "金价")):
        return "pdf", "pdf_analysis"
    if any(item in lowered for item in (".xlsx", ".csv", "表", "仓库", "缺货", "库存")):
        return "structured_data", "structured_data_analysis"
    if any(item in lowered for item in ("天气", "weather")):
        return "weather", "get_weather"
    if any(item in lowered for item in ("黄金", "金价", "gold")):
        return "gold_price", "get_gold_price"
    return "", ""


def _binding_for_capability(capability: str, bindings: list[ResolvedBinding]) -> ResolvedBinding | None:
    desired = "pdf" if capability == "pdf" else "dataset" if capability == "structured_data" else ""
    if not desired:
        return None
    return next((item for item in bindings if item.file_kind == desired), None)


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
