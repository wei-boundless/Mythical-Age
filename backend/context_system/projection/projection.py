from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ContextProjection:
    main_context: dict[str, Any] = field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = field(default_factory=list)
    bundle_summary_refs: list[dict[str, Any]] = field(default_factory=list)
    object_handle_ids: list[str] = field(default_factory=list)
    result_handle_ids: list[str] = field(default_factory=list)
    subset_handle_ids: list[str] = field(default_factory=list)
    memory_policy: str = "session_context_only"
    prompt_visibility: dict[str, Any] = field(default_factory=dict)
    authority: str = "context.execution_projection"

    def __post_init__(self) -> None:
        if self.authority != "context.execution_projection":
            raise ValueError("ContextProjection authority must be context.execution_projection")

    def merge(self, other: "ContextProjection") -> "ContextProjection":
        main_context = _merge_main_context(self.main_context, other.main_context)
        return ContextProjection(
            main_context=main_context,
            task_summary_refs=_dedupe_dicts([*self.task_summary_refs, *other.task_summary_refs], "task_id"),
            bundle_summary_refs=_dedupe_dicts([*self.bundle_summary_refs, *other.bundle_summary_refs], "task_id"),
            object_handle_ids=_dedupe([*self.object_handle_ids, *other.object_handle_ids]),
            result_handle_ids=_dedupe([*self.result_handle_ids, *other.result_handle_ids]),
            subset_handle_ids=_dedupe([*self.subset_handle_ids, *other.subset_handle_ids]),
            memory_policy=other.memory_policy or self.memory_policy,
            prompt_visibility={**self.prompt_visibility, **other.prompt_visibility},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def projection_from_file_work(
    main_context: dict[str, Any] | None,
    task_summary_refs: list[dict[str, Any]] | None,
    *,
    bundle_items: list[dict[str, Any]] | None = None,
) -> ContextProjection:
    context = dict(main_context or {})
    summaries = [_normalize_task_summary_ref(item) for item in list(task_summary_refs or []) if isinstance(item, dict)]
    bundle_refs = _bundle_refs_from_summaries(summaries, bundle_items=bundle_items)
    active_constraints = dict(context.get("active_constraints") or {})
    return ContextProjection(
        main_context=context,
        task_summary_refs=summaries,
        bundle_summary_refs=bundle_refs,
        object_handle_ids=_present([context.get("active_object_handle_id")]),
        result_handle_ids=_present([context.get("active_result_handle_id")]),
        subset_handle_ids=_present([context.get("active_subset_handle_id")]),
        prompt_visibility={
            "active_work_item": str(context.get("active_work_item") or ""),
            "source_kind": str(active_constraints.get("source_kind") or ""),
            "task_summary_count": len(summaries),
        },
    )


def projection_from_bundle_answer(
    *,
    content: str,
    bundle_items: list[dict[str, Any]] | None,
    existing_task_summary_refs: list[dict[str, Any]] | None = None,
    existing_main_context: dict[str, Any] | None = None,
    executed_ordinals: list[int] | None = None,
) -> ContextProjection:
    items = [dict(item) for item in list(bundle_items or []) if isinstance(item, dict)]
    if not items:
        return ContextProjection()
    sections = _extract_answer_sections(content, len(items))
    allowed_ordinals = {value for value in list(executed_ordinals or []) if _safe_int(value) > 0}
    single_allowed_ordinal = next(iter(allowed_ordinals)) if len(allowed_ordinals) == 1 else 0
    existing_by_kind = {
        str(item.get("task_kind") or "").strip(): dict(item)
        for item in list(existing_task_summary_refs or [])
        if isinstance(item, dict) and str(item.get("task_kind") or "").strip()
    }
    refs: list[dict[str, Any]] = []
    for item in items:
        ordinal = _safe_int(item.get("ordinal"))
        if ordinal <= 0:
            continue
        capability = str(item.get("capability_kind") or "").strip()
        task_kind = _task_kind_from_capability(capability)
        existing = existing_by_kind.get(task_kind, {})
        has_existing = bool(existing)
        if allowed_ordinals and ordinal not in allowed_ordinals and not has_existing:
            continue
        if not allowed_ordinals and not has_existing and ordinal not in sections:
            continue
        task_id = str(existing.get("task_id") or f"bundle:{ordinal}:{_slug(item.get('user_text') or capability)}").strip()
        answer = str(existing.get("answer") or sections.get(ordinal) or "").strip()
        summary = str(existing.get("summary") or answer or "").strip()
        if not summary and ordinal == single_allowed_ordinal:
            summary = _compact(str(content or "").strip(), 120)
        if not summary:
            summary = str(item.get("user_text") or "").strip()
        query = str(existing.get("query") or item.get("user_text") or "").strip()
        refs.append(
            {
                "task_id": task_id,
                "bundle_id": str(item.get("bundle_id") or "").strip(),
                "item_id": str(item.get("item_id") or "").strip(),
                "ordinal": ordinal,
                "query": query,
                "answer": answer,
                "summary": _compact(summary, 420),
                "task_kind": task_kind,
                "recipe_id": str(item.get("recipe_id") or "").strip(),
                "capability_kind": capability,
                "required_tool": str(item.get("required_tool") or "").strip(),
                "source": "bundle_answer_projection",
                "key_points": _key_points_for_bundle_item(item, existing),
            }
        )
    main_context = dict(existing_main_context or {})
    if refs:
        main_context["active_work_item"] = "bundle"
        main_context["followup_mode"] = "bundle_ref"
        main_context["followup_resolution_source"] = "bundle_answer_projection"
        main_context["active_bundle_id"] = str(refs[0].get("bundle_id") or "").strip()
        main_context["followup_target_task_ids"] = [str(item.get("task_id") or "") for item in refs if item.get("task_id")]
        main_context["active_constraints"] = {
            **dict(main_context.get("active_constraints") or {}),
            "bundle_item_count": len(refs),
        }
    return ContextProjection(
        main_context=main_context,
        task_summary_refs=[*list(existing_task_summary_refs or []), *refs],
        bundle_summary_refs=refs,
        object_handle_ids=_present([main_context.get("active_object_handle_id")]),
        result_handle_ids=_present([main_context.get("active_result_handle_id")]),
        subset_handle_ids=_present([main_context.get("active_subset_handle_id")]),
        prompt_visibility={"bundle_item_count": len(refs)},
    )


def _merge_main_context(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return dict(right)
    if not right:
        return dict(left)
    result = dict(left)
    for key, value in right.items():
        if value in ("", None, [], {}):
            continue
        if key == "active_constraints":
            result[key] = {**dict(result.get(key) or {}), **dict(value or {})}
            continue
        if key == "followup_target_task_ids":
            result[key] = _dedupe([*list(result.get(key) or []), *list(value or [])])
            continue
        result[key] = value
    return result


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_dicts(values: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        item_key = str(value.get(key) or value.get("query") or repr(value)).strip()
        if not item_key or item_key in seen:
            continue
        seen.add(item_key)
        result.append(dict(value))
    return result


def _normalize_task_summary_ref(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    answer = str(result.get("answer") or result.get("summary") or result.get("response") or "").strip()
    summary = str(result.get("summary") or "").strip()
    if answer and not summary:
        summary = _compact(answer, 120)
    result["answer"] = answer
    result["summary"] = summary
    return result


def _bundle_refs_from_summaries(
    summaries: list[dict[str, Any]],
    *,
    bundle_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    items = [dict(item) for item in list(bundle_items or []) if isinstance(item, dict)]
    if not items:
        return [dict(item) for item in summaries]
    refs: list[dict[str, Any]] = []
    used_summary_ids: set[str] = set()
    for item in items:
        capability = str(item.get("capability_kind") or "").strip()
        task_kind = _task_kind_from_capability(capability)
        summary = next(
            (
                dict(candidate)
                for candidate in summaries
                if _summary_matches_bundle_item(candidate, item, task_kind=task_kind)
                and str(candidate.get("task_id") or "").strip() not in used_summary_ids
            ),
            {},
        )
        if not summary:
            continue
        used_summary_ids.add(str(summary.get("task_id") or "").strip())
        refs.append(
            {
                **summary,
                "task_id": str(summary.get("task_id") or f"bundle:{item.get('ordinal')}:{_slug(item.get('user_text'))}"),
                "bundle_id": str(item.get("bundle_id") or "").strip(),
                "item_id": str(item.get("item_id") or "").strip(),
                "ordinal": _safe_int(item.get("ordinal")),
                "query": str(summary.get("query") or item.get("user_text") or "").strip(),
                "summary": str(summary.get("summary") or item.get("user_text") or "").strip(),
                "task_kind": task_kind,
                "recipe_id": str(item.get("recipe_id") or "").strip(),
                "capability_kind": capability,
                "required_tool": str(item.get("required_tool") or "").strip(),
                "source": str(summary.get("source") or "tool_projection"),
            }
        )
    return [item for item in refs if _safe_int(item.get("ordinal")) > 0]


def _summary_matches_bundle_item(
    summary: dict[str, Any],
    bundle_item: dict[str, Any],
    *,
    task_kind: str,
) -> bool:
    if str(summary.get("task_kind") or "").strip() != task_kind:
        return False
    binding = bundle_item.get("target_binding")
    if not isinstance(binding, dict):
        return True
    binding_metadata = dict(binding.get("metadata") or {})
    binding_path = str(binding_metadata.get("path") or "").strip()
    binding_kind = str(binding.get("file_kind") or "").strip()
    if not binding_path or binding_kind not in {"pdf", "dataset"}:
        return True
    prefix = f"{binding_kind}="
    for item in list(summary.get("key_points") or []):
        text = str(item or "").strip()
        if text.startswith(prefix) and text[len(prefix):].strip() == binding_path:
            return True
    return False


def _extract_answer_sections(content: str, expected_count: int) -> dict[int, str]:
    import re

    text = str(content or "").strip()
    if not text:
        return {}
    marker_re = re.compile(r"(?m)^(?:#+\s*)?(?:[一二三四五六七八九十]+|\d+)[、.．]\s*")
    matches = list(marker_re.finditer(text))
    sections: dict[int, str] = {}
    if len(matches) >= 2:
        for index, match in enumerate(matches[:expected_count]):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[index + 1] = text[start:end].strip()
        return sections
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*---+\s*\n", text) if chunk.strip()]
    for index, chunk in enumerate(chunks[:expected_count], start=1):
        sections[index] = chunk
    return sections


def _task_kind_from_capability(value: str) -> str:
    capability = str(value or "").strip()
    if capability == "pdf":
        return "pdf"
    if capability == "structured_data":
        return "structured_data"
    if capability in {"weather", "gold_price", "realtime_network"}:
        return "realtime_network"
    return capability or "general"


def _key_points_for_bundle_item(item: dict[str, Any], existing: dict[str, Any]) -> list[str]:
    points = [str(value).strip() for value in list(existing.get("key_points") or []) if str(value).strip()]
    capability = str(item.get("capability_kind") or "").strip()
    if capability:
        points.append(f"capability={capability}")
    required_tool = str(item.get("required_tool") or "").strip()
    if required_tool:
        points.append(f"tool={required_tool}")
    target = item.get("target_binding")
    if isinstance(target, dict):
        path = str(dict(target.get("metadata") or {}).get("path") or "").strip()
        file_kind = str(target.get("file_kind") or "").strip()
        if path and file_kind in {"pdf", "dataset"}:
            points.append(f"{file_kind}={path}")
    return _dedupe(points)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _slug(value: Any) -> str:
    import re

    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", str(value or "").lower()).strip("-")
    return compact[:48] or "item"


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _present(values: list[Any]) -> list[str]:
    return _dedupe(values)
