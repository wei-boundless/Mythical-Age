from __future__ import annotations

import re
from typing import Any

from capability_system.local_mcp_registry import get_local_mcp_primary_template

from .current_turn import BundleItem, CurrentTurnContext, ResolvedBinding


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
        followup_target_refs = tuple(
            _dedupe_text(
                [
                    *(item.followup_target_ref for item in bundle_items if str(item.followup_target_ref or "").strip()),
                    *(
                        str(binding.result_handle_id or binding.owner_task_id or binding.identity or "").strip()
                        for binding in bundle_bindings
                    ),
                ]
            )
        )
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
            bundle_id=bundle_id,
            explicit_inputs=explicit_inputs,
            resolved_bindings=tuple(bindings),
            bundle_items=tuple(bundle_items),
            followup_target_refs=followup_target_refs,
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
        bound_pdf = str(explicit_inputs.get("bound_pdf_path") or "").strip()
        bound_dataset = str(explicit_inputs.get("bound_dataset_path") or "").strip()
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
        if bound_pdf:
            bindings.append(
                ResolvedBinding(
                    binding_id=f"binding:bound:pdf:{_slug(bound_pdf)}",
                    binding_kind="source_file",
                    identity=_identity(bound_pdf),
                    file_kind="pdf",
                    source="session_state",
                    confidence=0.9,
                    metadata={"path": bound_pdf, "slot_name": "bound_pdf_path"},
                )
            )
        if bound_dataset:
            bindings.append(
                ResolvedBinding(
                    binding_id=f"binding:bound:dataset:{_slug(bound_dataset)}",
                    binding_kind="source_file",
                    identity=_identity(bound_dataset),
                    file_kind="dataset",
                    source="session_state",
                    confidence=0.9,
                    metadata={"path": bound_dataset, "slot_name": "bound_dataset_path"},
                )
            )

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
                        "bundle_id": str(ref.get("bundle_id") or "").strip(),
                        "item_id": str(ref.get("item_id") or "").strip(),
                        "ordinal": ordinal,
                        "query": str(ref.get("query") or "").strip(),
                        "summary": str(ref.get("summary") or "").strip(),
                        "task_kind": task_kind,
                        "capability_kind": str(ref.get("capability_kind") or "").strip(),
                        "required_tool": str(ref.get("required_tool") or "").strip(),
                        "template_id": str(ref.get("template_id") or _template_id_for_capability(str(ref.get("capability_kind") or "").strip())).strip(),
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
            template_id = _template_id_for_capability(capability)
            target_ref = ""
            if binding is not None:
                target_ref = str(binding.result_handle_id or binding.source_handle_id or binding.identity or "").strip()
            items.append(
                BundleItem(
                    item_id=f"{bundle_id}:item:{len(items) + 1}",
                    ordinal=len(items) + 1,
                    user_text=part,
                    bundle_id=bundle_id,
                    template_id=template_id,
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
                    metadata={"source": "compound_user_message", "bundle_id": bundle_id},
                )
            )
        return items if len(items) > 1 else []


def _looks_compound(message: str) -> bool:
    lowered = message.lower()
    markers = len(re.findall(r"(?<!优)先|再|然后|最后|并且|以及", lowered))
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
        return "pdf", ""
    if any(item in lowered for item in (".xlsx", ".csv", "表", "仓库", "缺货", "库存")):
        return "structured_data", ""
    if any(item in lowered for item in ("天气", "weather")):
        return "realtime_network", "web_search"
    if any(item in lowered for item in ("黄金", "金价", "gold")):
        return "realtime_network", "web_search"
    return "", ""


def _template_id_for_capability(capability: str) -> str:
    template_id = get_local_mcp_primary_template(capability)
    if template_id:
        return template_id
    if capability == "realtime_network":
        return "template.search.information_search"
    return "template.chat.general_response"


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
        template_id = str(metadata.get("template_id") or _template_id_for_capability(capability)).strip()
        followup_target_ref = str(binding.result_handle_id or binding.owner_task_id or binding.identity or "").strip()
        items.append(
            BundleItem(
                item_id=item_id,
                ordinal=ordinal or len(items) + 1,
                user_text=user_text,
                bundle_id=bundle_id,
                template_id=template_id,
                capability_kind=capability,
                required_tool=required_tool,
                requested_outputs=tuple(_requested_outputs_for_capability(capability)),
                inherited_binding_refs=(binding.binding_id,) if binding.binding_id else (),
                followup_target_ref=followup_target_ref,
                target_ref=followup_target_ref,
                target_binding=binding,
                output_requirement="answer_part",
                metadata={"source": "bundle_followup_binding", **metadata},
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
