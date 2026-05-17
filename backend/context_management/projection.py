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
    summaries = [dict(item) for item in list(task_summary_refs or []) if isinstance(item, dict)]
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
        summary = str(existing.get("summary") or sections.get(ordinal) or "").strip()
        if not summary and ordinal == single_allowed_ordinal:
            summary = str(content or "").strip()
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


def projection_from_bound_answer(
    *,
    content: str,
    current_turn_context: dict[str, Any] | None,
    existing_task_summary_refs: list[dict[str, Any]] | None = None,
    existing_main_context: dict[str, Any] | None = None,
) -> ContextProjection:
    context = dict(current_turn_context or {})
    current_file_kind = _current_turn_file_work_kind(context)
    if current_file_kind not in {"pdf", "dataset"}:
        return ContextProjection()
    bindings = [dict(item) for item in list(context.get("resolved_bindings") or []) if isinstance(item, dict)]
    binding = _select_source_binding(bindings, context)
    if not binding:
        return ContextProjection()
    file_kind = str(binding.get("file_kind") or "").strip()
    if file_kind != current_file_kind:
        kind_matched = _binding_by_kind(
            [
                item
                for item in bindings
                if str(item.get("binding_kind") or "") == "source_file"
                and str(item.get("file_kind") or "") in {"pdf", "dataset"}
            ],
            current_file_kind,
        )
        if not kind_matched:
            return ContextProjection()
        binding = kind_matched
        file_kind = current_file_kind
    metadata = dict(binding.get("metadata") or {})
    path = str(metadata.get("path") or binding.get("identity") or "").strip()
    answer = _compact(str(content or ""), 420)
    if file_kind not in {"pdf", "dataset"} or not path or not answer:
        return ContextProjection()

    explicit_inputs = dict(context.get("explicit_inputs") or {})
    tool_input = dict(explicit_inputs.get("tool_input") or {})
    query = str(tool_input.get("query") or context.get("user_message") or "").strip()
    task_kind = "pdf" if file_kind == "pdf" else "structured_data"
    source_prefix = "source:pdf" if file_kind == "pdf" else "source:dataset"
    result_prefix = "result:pdf_answer" if file_kind == "pdf" else "result:structured_answer"
    object_handle_id = str(binding.get("source_handle_id") or _stable_file_work_id(source_prefix, path)).strip()
    result_handle_id = str(
        binding.get("result_handle_id")
        or binding.get("owner_task_id")
        or _stable_file_work_id(result_prefix, f"{path}:{query}:{answer[:160]}")
    ).strip()
    subset_handle_id = str(binding.get("subset_handle_id") or "").strip()

    main_context = dict(existing_main_context or {})
    active_constraints = dict(main_context.get("active_constraints") or {})
    if file_kind == "pdf":
        mode = str(tool_input.get("mode") or active_constraints.get("active_pdf_mode") or "document").strip()
        active_constraints.update({"active_pdf": path, "active_pdf_mode": mode, "source_kind": "pdf"})
        active_work_item = "pdf"
        followup_binding_key = "active_pdf"
        key_points = [f"pdf={path}", f"pdf_mode={mode}", f"artifact={path}#analysis"]
    else:
        active_constraints.update({"active_dataset": path, "source_kind": "dataset"})
        active_work_item = "structured_data"
        followup_binding_key = "active_dataset"
        key_points = [f"dataset={path}", f"artifact={path}#analysis"]

    main_context.update(
        {
            "active_goal": query,
            "active_work_item": active_work_item,
            "active_binding_identity": _binding_identity(path),
            "active_object_handle_id": object_handle_id,
            "active_result_handle_id": result_handle_id,
            "active_subset_handle_id": subset_handle_id,
            "followup_mode": "binding_ref",
            "followup_resolution_source": "bound_answer_projection",
            "followup_target_task_id": result_handle_id,
            "followup_target_task_ids": _dedupe(
                [*list(main_context.get("followup_target_task_ids") or []), result_handle_id]
            ),
            "followup_binding_key": followup_binding_key,
            "followup_binding_identity": _binding_identity(path),
            "active_constraints": active_constraints,
        }
    )
    existing_refs = [dict(item) for item in list(existing_task_summary_refs or []) if isinstance(item, dict)]
    task_summary = {
        "task_id": result_handle_id,
        "query": query,
        "summary": answer,
        "task_kind": task_kind,
        "key_points": key_points,
        "source": "bound_answer_projection",
    }
    return ContextProjection(
        main_context=main_context,
        task_summary_refs=_dedupe_dicts([*existing_refs, task_summary], "task_id"),
        object_handle_ids=_present([object_handle_id]),
        result_handle_ids=_present([result_handle_id]),
        subset_handle_ids=_present([subset_handle_id]),
        prompt_visibility={
            "active_work_item": active_work_item,
            "source_kind": file_kind,
            "task_summary_count": len(existing_refs) + 1,
        },
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


def _select_source_binding(bindings: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    source_bindings = [
        item
        for item in bindings
        if str(item.get("binding_kind") or "") == "source_file"
        and str(item.get("file_kind") or "") in {"pdf", "dataset"}
    ]
    if not source_bindings:
        return {}

    explicit_inputs = dict(context.get("explicit_inputs") or {})
    tool_input = dict(explicit_inputs.get("tool_input") or {})
    preferred_path = _first_present(
        tool_input.get("path"),
        tool_input.get("file_path"),
        tool_input.get("active_dataset"),
        tool_input.get("active_pdf"),
        explicit_inputs.get("explicit_dataset_path"),
        explicit_inputs.get("explicit_pdf_path"),
    )
    if preferred_path:
        matched = _binding_by_path(source_bindings, preferred_path)
        if matched:
            return matched

    preferred_kind = _preferred_file_kind(context)
    if preferred_kind:
        kind_matched = _binding_by_kind(source_bindings, preferred_kind)
        if kind_matched:
            return kind_matched

    return source_bindings[0] if source_bindings else {}


def _preferred_file_kind(context: dict[str, Any]) -> str:
    current_turn_kind = _current_turn_file_work_kind(context)
    if current_turn_kind:
        return current_turn_kind

    explicit_inputs = dict(context.get("explicit_inputs") or {})
    path_hint = _first_present(
        explicit_inputs.get("explicit_dataset_path"),
        explicit_inputs.get("explicit_pdf_path"),
    )
    suffix = _normalized_suffix(path_hint)
    if suffix in {".xlsx", ".xls", ".csv", ".tsv", ".jsonl", ".parquet"}:
        return "dataset"
    if suffix == ".pdf":
        return "pdf"

    return ""


def _current_turn_file_work_kind(context: dict[str, Any]) -> str:
    explicit_inputs = dict(context.get("explicit_inputs") or {})
    tool_input = dict(explicit_inputs.get("tool_input") or {})
    source_kind = str(
        context.get("source_kind")
        or context.get("selected_source_kind")
        or explicit_inputs.get("source_kind")
        or dict(context.get("active_constraints") or {}).get("source_kind")
        or ""
    ).lower()
    if source_kind in {"dataset", "structured_data"}:
        return "dataset"
    if source_kind in {"pdf", "document"}:
        return "pdf"

    path_hint = _first_present(
        tool_input.get("path"),
        tool_input.get("file_path"),
        tool_input.get("active_dataset"),
        tool_input.get("active_pdf"),
        explicit_inputs.get("explicit_dataset_path"),
        explicit_inputs.get("explicit_pdf_path"),
    )
    suffix = _normalized_suffix(path_hint)
    if suffix in {".xlsx", ".xls", ".csv", ".tsv", ".jsonl", ".parquet"}:
        return "dataset"
    if suffix == ".pdf":
        return "pdf"

    capability_requests = " ".join(str(item or "").lower() for item in list(context.get("capability_requests") or []))
    if any(token in capability_requests for token in ("dataset", "structured", "table", "spreadsheet")):
        return "dataset"
    if "pdf" in capability_requests or "document" in capability_requests:
        return "pdf"

    intent = str(context.get("intent") or "").lower()
    if "pdf" in intent:
        return "pdf"
    if any(token in intent for token in ("structured", "dataset", "table", "spreadsheet")):
        return "dataset"
    return ""


def _binding_by_kind(bindings: list[dict[str, Any]], file_kind: str) -> dict[str, Any]:
    expected = str(file_kind or "").strip()
    if expected not in {"pdf", "dataset"}:
        return {}
    for item in bindings:
        if str(item.get("file_kind") or "").strip() == expected:
            return item
    return {}


def _binding_by_path(bindings: list[dict[str, Any]], path: str) -> dict[str, Any]:
    wanted = _binding_path_key(path)
    wanted_name = _binding_basename_key(path)
    if not wanted and not wanted_name:
        return {}
    for item in bindings:
        metadata = dict(item.get("metadata") or {})
        candidates = [
            metadata.get("path"),
            item.get("identity"),
            metadata.get("source"),
            metadata.get("file_path"),
        ]
        for candidate in candidates:
            key = _binding_path_key(candidate)
            name = _binding_basename_key(candidate)
            if wanted and key and (wanted == key or wanted.endswith("/" + key) or key.endswith("/" + wanted)):
                return item
            if wanted_name and name and wanted_name == name:
                return item
    return {}


def _first_present(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _binding_path_key(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _binding_basename_key(value: Any) -> str:
    normalized = _binding_path_key(value)
    return normalized.rsplit("/", 1)[-1] if normalized else ""


def _normalized_suffix(value: Any) -> str:
    basename = _binding_basename_key(value)
    if "." not in basename:
        return ""
    return "." + basename.rsplit(".", 1)[-1].lower()


def _stable_file_work_id(prefix: str, value: str) -> str:
    import hashlib

    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _binding_identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


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
