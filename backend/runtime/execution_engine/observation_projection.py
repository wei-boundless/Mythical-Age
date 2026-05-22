from __future__ import annotations

from typing import Any

from .delegation_context import classify_delegation_goal_alignment, clean_text


def project_file_work_context_from_tool_observation(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tool_name = clean_text(payload.get("tool_name"))
    tool_args = dict(payload.get("tool_args") or {})
    result_text = clean_text(payload.get("result"))
    if not result_text or str(payload.get("truncated") or "").lower() == "true":
        return {}, []
    if tool_name == "delegate_to_agent":
        return _project_delegated_file_work_context(tool_args=tool_args, result_text=result_text)
    if tool_name in {"mcp_pdf", "pdf"}:
        return _project_pdf_tool_context(tool_args=tool_args, result_text=result_text)
    if tool_name in {"mcp_structured_data", "structured_data"}:
        return _project_structured_data_tool_context(tool_args=tool_args, result_text=result_text)
    return {}, []


def _project_pdf_tool_context(*, tool_args: dict[str, Any], result_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = clean_text(tool_args.get("path"))
    query = clean_text(tool_args.get("query"))
    if not path:
        path = _extract_tool_output_field(result_text, ("PDF", "文件", "path", "source"))
    canonical_payload = _parse_tool_canonical_payload(result_text, "PDF_CANONICAL_RESULT::")
    if not path and canonical_payload:
        path = clean_text(canonical_payload.get("source"))
    if not path or _looks_like_failed_tool_result(result_text):
        return {}, []

    object_handle_id = _stable_file_work_id("source:pdf", path)
    result_handle_id = _stable_file_work_id("result:pdf_answer", f"{path}:{query}:{result_text[:160]}")
    pages = _extract_page_numbers(result_text)
    if not pages and canonical_payload:
        pages = [
            int(page)
            for page in list(canonical_payload.get("pages") or [])
            if _safe_positive_int(page) is not None
        ][:12]
    if not pages and canonical_payload:
        metadata = dict(canonical_payload.get("metadata") or {})
        target_page = _safe_positive_int(metadata.get("target_page"))
        if target_page is not None:
            pages = [target_page]
    subset_handle_id = (
        _stable_file_work_id("subset:pdf_pages", f"{path}:{','.join(str(page) for page in pages)}")
        if pages
        else ""
    )
    mode = clean_text(tool_args.get("mode")) or ("page" if pages else "document")
    active_constraints: dict[str, Any] = {
        "active_pdf": path,
        "active_pdf_mode": mode,
        "source_kind": "pdf",
    }
    if pages:
        active_constraints["active_pdf_pages"] = pages
    main_context = {
        "active_goal": query,
        "active_work_item": "pdf",
        "active_binding_identity": _binding_identity(path),
        "active_object_handle_id": object_handle_id,
        "active_result_handle_id": result_handle_id,
        "active_subset_handle_id": subset_handle_id,
        "followup_mode": "binding_ref",
        "followup_resolution_source": "tool_observation_projection",
        "followup_target_task_id": result_handle_id,
        "followup_target_task_ids": [result_handle_id],
        "followup_binding_key": "active_pdf",
        "followup_binding_identity": _binding_identity(path),
        "active_constraints": active_constraints,
    }
    summary_source = clean_text(canonical_payload.get("summary")) if canonical_payload else ""
    degraded_reason = clean_text(canonical_payload.get("degraded_reason")) if canonical_payload else ""
    summary = _compact_summary(summary_source or result_text)
    if degraded_reason and degraded_reason not in summary:
        summary = _compact_summary(f"{summary} degraded_reason={degraded_reason}")
    task_summary = {
        "task_id": result_handle_id,
        "query": query,
        "summary": summary,
        "task_kind": "pdf",
        "key_points": [
            f"pdf={path}",
            f"pdf_mode={mode}",
            *([f"pdf_pages={','.join(str(page) for page in pages)}"] if pages else []),
            f"artifact={path}#analysis",
        ],
    }
    return main_context, [task_summary]


def _project_structured_data_tool_context(
    *,
    tool_args: dict[str, Any],
    result_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context_writeback_hints = dict(tool_args.get("context_writeback_hints") or {})
    path = clean_text(tool_args.get("path"))
    query = clean_text(tool_args.get("query"))
    if not path:
        path = clean_text(context_writeback_hints.get("source_path")) or _extract_tool_output_field(
            result_text,
            ("数据集", "文件", "path", "source"),
        )
    if not path or _looks_like_failed_tool_result(result_text):
        return {}, []
    object_handle_id = clean_text(context_writeback_hints.get("active_object_handle_id")) or _stable_file_work_id("source:dataset", path)
    result_handle_id = clean_text(context_writeback_hints.get("active_result_handle_id")) or _stable_file_work_id(
        "result:structured_answer",
        f"{path}:{query}:{result_text[:160]}",
    )
    subset_labels = [
        clean_text(item)
        for item in list(context_writeback_hints.get("subset_labels") or [])
        if clean_text(item)
    ]
    subset_filter_column = clean_text(context_writeback_hints.get("subset_filter_column"))
    subset_handle_id = clean_text(context_writeback_hints.get("active_subset_handle_id"))
    active_constraints: dict[str, Any] = {
        "active_dataset": path,
        "source_kind": "dataset",
    }
    if subset_labels:
        active_constraints["subset_labels"] = subset_labels
    if subset_filter_column:
        active_constraints["subset_filter_column"] = subset_filter_column
    main_context = {
        "active_goal": query,
        "active_work_item": "structured_data",
        "active_binding_identity": _binding_identity(path),
        "active_object_handle_id": object_handle_id,
        "active_result_handle_id": result_handle_id,
        "active_subset_handle_id": subset_handle_id,
        "followup_mode": "binding_ref",
        "followup_resolution_source": "tool_observation_projection",
        "followup_target_task_id": result_handle_id,
        "followup_target_task_ids": [result_handle_id],
        "followup_binding_key": "active_dataset",
        "followup_binding_identity": _binding_identity(path),
        "active_constraints": active_constraints,
    }
    task_summary = {
        "task_id": result_handle_id,
        "query": query,
        "summary": _compact_summary(result_text),
        "task_kind": "structured_data",
        "active_object_handle_id": object_handle_id,
        "active_result_handle_id": result_handle_id,
        "active_subset_handle_id": subset_handle_id,
        **({"subset_labels": subset_labels} if subset_labels else {}),
        **({"subset_filter_column": subset_filter_column} if subset_filter_column else {}),
        "key_points": [
            f"dataset={path}",
            f"artifact={path}#analysis",
        ],
    }
    return main_context, [task_summary]


def _project_delegated_file_work_context(
    *,
    tool_args: dict[str, Any],
    result_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result_payload = _parse_json_object(result_text)
    if not result_payload or str(result_payload.get("status") or "") not in {"completed", "failed"}:
        return {}, []
    input_payload = dict(tool_args.get("input_payload") or {})
    context_writeback_hints = dict(result_payload.get("context_writeback_hints") or {})
    kind = _infer_delegated_file_work_kind(
        tool_args=tool_args,
        result_payload=result_payload,
        context_writeback_hints=context_writeback_hints,
    )
    path = clean_text(
        input_payload.get("file_path")
        or input_payload.get("path")
        or input_payload.get("active_dataset")
        or input_payload.get("active_pdf")
    )
    goal_alignment = classify_delegation_goal_alignment(
        user_message=clean_text(tool_args.get("current_user_message")),
        instruction=clean_text(tool_args.get("instruction")),
        input_payload=input_payload,
    )
    if goal_alignment == "offtopic":
        return {}, []
    if not path:
        path = clean_text(
            context_writeback_hints.get("source_path")
            or result_payload.get("source")
            or result_payload.get("path")
        )
    summary = clean_text(result_payload.get("summary") or result_payload.get("answer_candidate") or result_text)
    if not path and kind in {"retrieval", "evidence_lookup", "knowledge_retrieval"}:
        task_id = _stable_file_work_id(
            "result:delegated_retrieval",
            f"{tool_args.get('instruction')}:{summary[:160]}",
        )
        main_context = {
            "active_goal": clean_text(tool_args.get("instruction")),
            "active_work_item": "delegated_retrieval",
            "followup_mode": "summary_ref",
            "followup_resolution_source": "tool_observation_projection",
            "followup_target_task_id": task_id,
            "followup_target_task_ids": [task_id],
        }
        task_summary = {
            "task_id": task_id,
            "query": clean_text(tool_args.get("instruction")),
            "summary": _compact_summary(summary),
            "task_kind": "delegated_retrieval",
            "key_points": [
                "source=delegated_retrieval",
                f"target_agent={clean_text(result_payload.get('target_agent_id')) or 'delegated_agent'}",
            ],
        }
        return main_context, [task_summary]
    if not path:
        return {}, []

    delegated_tool_args = {
        "path": path,
        "query": clean_text(input_payload.get("query") or tool_args.get("instruction")),
        **({"context_writeback_hints": context_writeback_hints} if context_writeback_hints else {}),
    }
    if kind in {"structured_data", "table_analysis", "structured_data_lookup"}:
        return _project_structured_data_tool_context(tool_args=delegated_tool_args, result_text=summary)
    if kind in {"pdf", "pdf_reading", "document_reading"}:
        mode = clean_text(input_payload.get("mode") or input_payload.get("extract_mode"))
        if mode:
            delegated_tool_args["mode"] = mode
        return _project_pdf_tool_context(tool_args=delegated_tool_args, result_text=summary)
    return {}, []


def _infer_delegated_file_work_kind(
    *,
    tool_args: dict[str, Any],
    result_payload: dict[str, Any],
    context_writeback_hints: dict[str, Any],
) -> str:
    explicit_kind = clean_text(tool_args.get("delegation_kind"))
    if explicit_kind:
        return explicit_kind

    result_metadata = dict(result_payload.get("metadata") or {})
    source_kind = clean_text(
        context_writeback_hints.get("source_kind")
        or result_payload.get("source_kind")
        or result_metadata.get("source_kind")
    ).lower()
    if source_kind in {"dataset", "structured_data", "table", "spreadsheet", "csv", "xlsx"}:
        return "table_analysis"
    if source_kind in {"pdf", "document"}:
        return "pdf_reading"
    if source_kind in {"retrieval", "knowledge", "knowledge_base", "rag"}:
        return "evidence_lookup"

    target_agent_id = clean_text(result_payload.get("target_agent_id")).lower()
    if any(token in target_agent_id for token in ("table", "structured", "data_analyst", "dataset")):
        return "table_analysis"
    if any(token in target_agent_id for token in ("pdf", "document")):
        return "pdf_reading"
    if any(token in target_agent_id for token in ("rag", "retrieval", "search", "knowledge")):
        return "evidence_lookup"
    return ""


def _stable_file_work_id(prefix: str, value: str) -> str:
    import hashlib

    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _parse_tool_canonical_payload(value: str, marker: str) -> dict[str, Any]:
    import json

    text = clean_text(value)
    if marker not in text:
        return {}
    raw = text.split(marker, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_json_object(value: str) -> dict[str, Any]:
    import json

    text = clean_text(value)
    if not text.startswith("{"):
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _binding_identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _compact_summary(value: str, max_chars: int = 280) -> str:
    return " ".join(str(value or "").split()).strip()[:max_chars]


def _safe_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _looks_like_failed_tool_result(value: str) -> bool:
    text = clean_text(value).lower()
    failure_markers = (
        "failed:",
        "分析失败",
        "explicit path is required",
        "file does not exist",
        "文件不存在",
        "unavailable",
    )
    return any(marker in text for marker in failure_markers)


def _extract_page_numbers(value: str) -> list[int]:
    import re

    pages: list[int] = []
    for match in re.finditer(r"(?:第\s*|page\s*|p\.?\s*)(\d{1,4})\s*(?:页)?", str(value or ""), flags=re.IGNORECASE):
        try:
            page = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if page > 0 and page not in pages:
            pages.append(page)
    return pages[:12]


def _extract_tool_output_field(value: str, labels: tuple[str, ...]) -> str:
    import re

    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = rf"(?:{label_pattern})\s*[:：]\s*([^\s,，;；]+)"
    match = re.search(pattern, str(value or ""), flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""
