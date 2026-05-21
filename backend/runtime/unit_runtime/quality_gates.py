from __future__ import annotations

import re
from typing import Any

from text_metric import count_text_units

from ..contracts.deliverable_validator import _protocol_leak_detected
from ..coordination_runtime.review_gate_verdict import (
    extract_explicit_review_verdict as _shared_extract_explicit_review_verdict,
    extract_review_verdict as _shared_extract_review_verdict,
    review_verdict_is_accepted,
    review_verdict_is_rejected,
)
from .artifact_materializer import extract_markdown_section_content


def _model_stream_policy_from_task_execution_assembly(
    task_execution_assembly: dict[str, Any],
    *,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly_payload = dict(task_execution_assembly or {})
    assembly_metadata = dict(assembly_payload.get("metadata") or {})
    assembly_diagnostics = dict(assembly_payload.get("diagnostics") or {})
    turn_context = dict(current_turn_context or {})
    stage_request = dict(turn_context.get("stage_execution_request") or {})
    policy: dict[str, Any] = {}
    for candidate in (
        assembly_metadata.get("stream_policy"),
        assembly_diagnostics.get("stream_policy"),
        stage_request.get("stream_policy"),
        turn_context.get("stream_policy"),
    ):
        candidate_dict = dict(candidate or {})
        if candidate_dict:
            policy = {**policy, **candidate_dict}
    return {
        "enabled": bool(policy.get("enabled") is True),
        "mode": str(policy.get("mode") or "disabled"),
        "monitor_visibility": str(policy.get("monitor_visibility") or "none"),
        "chunk_event_type": str(policy.get("chunk_event_type") or ""),
        "emit_text_preview": bool(policy.get("emit_text_preview") is True),
        "preview_char_limit": _safe_int(policy.get("preview_char_limit")),
        "persist_full_stream_text": bool(policy.get("persist_full_stream_text") is True),
        "fallback_to_non_stream_on_error": bool(policy.get("fallback_to_non_stream_on_error", True) is not False),
        "model_response_timeout_seconds": float(policy.get("model_response_timeout_seconds") or 0),
        "non_stream_fallback_timeout_seconds": float(policy.get("non_stream_fallback_timeout_seconds") or 0),
        "stream_recovery_timeout_seconds": float(policy.get("stream_recovery_timeout_seconds") or 0),
        "fallback_timeout_seconds": float(policy.get("fallback_timeout_seconds") or 0),
        "authority": "orchestration.task_stream_policy",
    }


def _artifact_policy_from_task_execution_assembly(
    *,
    selected_recipe_payload: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly_payload = dict(task_execution_assembly or {})
    assembly_metadata = dict(assembly_payload.get("metadata") or {})
    assembly_diagnostics = dict(assembly_payload.get("diagnostics") or {})
    turn_context = dict(current_turn_context or {})
    stage_request = dict(turn_context.get("stage_execution_request") or {})
    policy: dict[str, Any] = {}
    for candidate in (
        selected_recipe_payload.get("artifact_policy"),
        assembly_metadata.get("artifact_policy"),
        assembly_diagnostics.get("artifact_policy"),
        stage_request.get("artifact_policy"),
        turn_context.get("artifact_policy"),
    ):
        candidate_dict = dict(candidate or {})
        if candidate_dict:
            policy = {**policy, **candidate_dict}
    return policy


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count_text_units(content: str) -> int:
    return count_text_units(content)


def _quality_gate_metric_text(content: str, policy: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    text = str(content or "").strip()
    if not text:
        return "", {"metric_content_source": "empty"}
    section_keys = tuple(
        str(item).strip()
        for item in list(policy.get("metric_section_keys") or policy.get("body_section_keys") or [])
        if str(item).strip()
    )
    stop_section_keys = tuple(
        str(item).strip()
        for item in list(policy.get("metric_stop_section_keys") or policy.get("body_stop_section_keys") or [])
        if str(item).strip()
    )
    if section_keys:
        section_text = extract_markdown_section_content(
            text,
            section_keys,
            stop_section_keys=stop_section_keys,
            include_heading=True,
        )
        if section_text.strip():
            return section_text.strip(), {
                "metric_content_source": "section",
                "metric_section_keys": list(section_keys),
                "metric_stop_section_keys": list(stop_section_keys),
            }
    if stop_section_keys:
        truncated = _truncate_text_at_quality_sections(text, stop_section_keys)
        if truncated.strip() != text:
            return truncated.strip(), {
                "metric_content_source": "truncated_full_content",
                "metric_section_keys": list(section_keys),
                "metric_stop_section_keys": list(stop_section_keys),
            }
    return text, {
        "metric_content_source": "full_content",
        "metric_section_keys": list(section_keys),
        "metric_stop_section_keys": list(stop_section_keys),
    }


def _truncate_text_at_quality_sections(content: str, section_keys: tuple[str, ...]) -> str:
    text = str(content or "")
    if not text.strip() or not section_keys:
        return text
    stop_positions: list[int] = []
    for match in re.finditer(r"^(?:#{1,6}\s+)?【(?P<title>[^】]{1,80})】\s*$", text, flags=re.MULTILINE):
        title = str(match.group("title") or "").strip()
        if any(_quality_section_title_matches(title, key) for key in section_keys):
            stop_positions.append(int(match.start()))
    if not stop_positions:
        return text
    return text[: min(stop_positions)]


def _quality_section_title_matches(title: str, key: str) -> bool:
    title_norm = re.sub(r"\s+", "", str(title or "").strip().strip("#").strip("【】[]（）()")).lower()
    key_norm = re.sub(r"\s+", "", str(key or "").strip().strip("#").strip("【】[]（）()")).lower()
    if not title_norm or not key_norm:
        return False
    return title_norm == key_norm or key_norm in title_norm or title_norm in key_norm


def _stage_business_acceptance(
    *,
    stage_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any] | None = None,
    final_content: str,
    output_refs: list[str],
    terminal_status: str,
    requires_file_artifact_refs: bool,
) -> dict[str, Any]:
    artifact_ok = bool(output_refs) if requires_file_artifact_refs else True
    base_accepted = str(terminal_status or "") == "completed" and artifact_ok
    protocol_leak = _protocol_leak_detected(final_content)
    if protocol_leak:
        return {
            "accepted": False,
            "base_accepted": base_accepted,
            "business_accepted": False,
            "artifact_ok": artifact_ok,
            "stage_id": stage_id,
            "policy": "protocol_boundary",
            "issues": ["protocol_boundary:pseudo_tool_output"],
            "protocol_leak_detected": True,
            "authority": "orchestration.stage_business_acceptance",
        }
    length_budget = dict(contract.get("length_budget") or {})
    quality_policy = dict(contract.get("quality_retry_policy") or {})
    accepted_policies = {str(item) for item in list(quality_policy.get("acceptance_policies") or []) if str(item)}
    if length_budget and length_budget.get("configured") is True:
        content_quality = _length_budget_quality_gate(
            final_content,
            explicit_inputs=dict(explicit_inputs or {}),
            length_budget=length_budget,
        )
        return {
            "accepted": bool(base_accepted and content_quality["accepted"]),
            "base_accepted": base_accepted,
            "business_accepted": bool(content_quality["accepted"]),
            "artifact_ok": artifact_ok,
            "stage_id": stage_id,
            "policy": "length_budget",
            **content_quality,
            "authority": "orchestration.stage_business_acceptance",
        }
    if "sectioned_text_batch_quality" in accepted_policies:
        content_quality = _sectioned_text_batch_quality_gate(
            final_content,
            explicit_inputs=dict(explicit_inputs or {}),
            policy=quality_policy,
        )
        return {
            "accepted": bool(base_accepted and content_quality["accepted"]),
            "base_accepted": base_accepted,
            "business_accepted": bool(content_quality["accepted"]),
            "artifact_ok": artifact_ok,
            "stage_id": stage_id,
            "policy": "sectioned_text_batch_quality",
            **content_quality,
            "authority": "orchestration.stage_business_acceptance",
        }
    node_type = str(contract.get("node_type") or "").strip()
    review_policy = dict(contract.get("review_gate_policy") or {})
    gate_policy = str(contract.get("gate_policy") or "").strip()
    is_review_gate = node_type == "review_gate" or gate_policy == "review_gate" or bool(review_policy)
    if not is_review_gate:
        if str(stage_id or "").strip() == "project_brief":
            return {
                "accepted": base_accepted,
                "base_accepted": base_accepted,
                "artifact_ok": artifact_ok,
                "stage_id": stage_id,
                "policy": "technical_completion",
                "authority": "orchestration.stage_business_acceptance",
            }
        return {
            "accepted": base_accepted,
            "base_accepted": base_accepted,
            "artifact_ok": artifact_ok,
            "stage_id": stage_id,
            "policy": "technical_completion",
            "authority": "orchestration.stage_business_acceptance",
        }
    verdict = _extract_review_verdict(final_content)
    allowed_to_commit = _extract_review_commit_permission(final_content)
    if review_verdict_is_accepted(verdict):
        business_accepted = True
    elif review_verdict_is_rejected(verdict):
        business_accepted = False
    elif allowed_to_commit is not None:
        business_accepted = allowed_to_commit
    else:
        business_accepted = False
    return {
        "accepted": bool(base_accepted and business_accepted),
        "base_accepted": base_accepted,
        "business_accepted": business_accepted,
        "artifact_ok": artifact_ok,
        "stage_id": stage_id,
        "policy": "review_gate_verdict",
        "verdict": verdict,
        "allowed_to_commit": allowed_to_commit,
        "authority": "orchestration.stage_business_acceptance",
    }


def _length_budget_quality_gate(
    content: str,
    *,
    explicit_inputs: dict[str, Any],
    length_budget: dict[str, Any],
) -> dict[str, Any]:
    text = str(content or "").strip()
    metric_text, metric_text_diagnostics = _quality_gate_metric_text(text, length_budget)
    measurement_mode = str(length_budget.get("measurement_mode") or "text_units").strip() or "text_units"
    raw_content_metric_total = _count_text_units(text)
    content_metric_total = _count_text_units(metric_text)
    measurement_diagnostics: dict[str, Any] = {"measurement_mode": measurement_mode}
    if measurement_mode in {"tokens", "hybrid"}:
        measurement_diagnostics["measurement_fallback"] = (
            "text_units_counter_used_for_length_budget_until_token_meter_is_bound"
        )
    target_units = _safe_int(length_budget.get("target_units"))
    min_units = _safe_int(length_budget.get("min_units"))
    max_units = _safe_int(length_budget.get("max_units"))
    batch_unit_count = _safe_int(length_budget.get("batch_unit_count"))
    if batch_unit_count <= 0:
        batch_unit_count = max(_safe_int(explicit_inputs.get("chapters_per_round")), 1)
    if target_units <= 0 and min_units > 0:
        target_units = min_units
    if max_units > 0 and target_units > max_units:
        target_units = max_units
    issues: list[str] = []
    if not text:
        issues.append("empty_content")
    if min_units > 0 and content_metric_total < min_units:
        issues.append(f"insufficient_metric:{content_metric_total}<{min_units}")
    if max_units > 0 and content_metric_total > max_units:
        issues.append(f"exceeds_metric:{content_metric_total}>{max_units}")
    if target_units > 0 and content_metric_total < target_units:
        issues.append(f"below_target:{content_metric_total}<{target_units}")
    accepted = not issues
    return {
        "accepted": accepted,
        "content_metric_total": content_metric_total,
        "raw_content_metric_total": raw_content_metric_total,
        "target_units": target_units,
        "min_required_metric_total": min_units,
        "max_allowed_metric_total": max_units,
        "batch_unit_count": batch_unit_count,
        "issues": issues,
        **measurement_diagnostics,
        **metric_text_diagnostics,
    }


def _extract_review_verdict(content: str) -> str:
    return _shared_extract_review_verdict(content)


def _extract_explicit_review_verdict(text: str) -> str:
    return _shared_extract_explicit_review_verdict(text)


def _extract_review_commit_permission(content: str) -> bool | None:
    text = str(content or "")
    if not text.strip():
        return None
    if re.search(r"是否允许批次写入记忆\s*[:：]\s*(是|允许|yes|true|pass)", text, re.IGNORECASE):
        return True
    if re.search(r"是否允许批次写入记忆\s*[:：]\s*(否|不允许|no|false)", text, re.IGNORECASE):
        return False
    if "不允许写入" in text or "不允许批次写入" in text:
        return False
    if "允许批次写入记忆" in text and "否" not in text:
        return True
    return None


def _sectioned_text_batch_quality_gate(
    content: str,
    *,
    explicit_inputs: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    text = str(content or "").strip()
    metric_text, metric_text_diagnostics = _quality_gate_metric_text(text, policy)
    raw_content_metric_total = _count_text_units(text)
    content_metric_total = _count_text_units(metric_text)
    unit_count_key = str(policy.get("unit_count_key") or "unit_count")
    unit_start_key = str(policy.get("unit_start_key") or "unit_start_index")
    unit_end_key = str(policy.get("unit_end_key") or "unit_end_index")
    unit_index_key = str(policy.get("unit_index_key") or unit_start_key)
    target_metric_key = str(policy.get("target_metric_key") or "target_metric_total")
    unit_target_metric_key = str(policy.get("unit_target_metric_key") or "")
    units_per_batch = max(
        _safe_int(explicit_inputs.get(unit_count_key)) or 1,
        1,
    )
    start_index = _safe_int(explicit_inputs.get(unit_start_key) or explicit_inputs.get(unit_index_key)) or 1
    end_index = _safe_int(explicit_inputs.get(unit_end_key)) or (start_index + units_per_batch - 1)
    expected_indexes = list(range(start_index, end_index + 1)) if end_index >= start_index else [start_index]
    expected_index_set = set(expected_indexes)
    heading_patterns = tuple(str(item).strip() for item in list(policy.get("required_heading_patterns") or []) if str(item).strip())
    heading_match_scope = str(policy.get("heading_match_scope") or policy.get("unit_heading_scope") or "anywhere").strip()
    ignored_heading_parent_keywords = tuple(
        str(item).strip()
        for item in list(policy.get("ignored_heading_parent_keywords") or [])
        if str(item).strip()
    )
    section_ranges = _extract_indexed_section_ranges(
        text,
        heading_patterns,
        heading_match_scope=heading_match_scope,
        ignored_parent_keywords=ignored_heading_parent_keywords,
    )
    found_indexes = set(section_ranges)
    missing_indexes = [index for index in expected_indexes if index not in found_indexes] if heading_patterns else []
    unexpected_indexes = (
        sorted(index for index in found_indexes if index not in expected_index_set)
        if bool(policy.get("forbid_unexpected_unit_indexes"))
        else []
    )
    unexpected_ranges = (
        _unexpected_unit_range_declarations(
            text,
            expected_start=start_index,
            expected_end=end_index,
            expected_indexes=expected_index_set,
        )
        if bool(policy.get("forbid_unexpected_unit_ranges"))
        else []
    )
    target_metric_total = _safe_int(explicit_inputs.get(target_metric_key)) or (
        (_safe_int(explicit_inputs.get(unit_target_metric_key)) or 0) * units_per_batch
    )
    min_ratio = float(policy.get("minimum_metric_ratio") or 0.0)
    min_per_unit = _safe_int(policy.get("minimum_metric_per_unit"))
    min_metric_total = max(min_per_unit * units_per_batch, int(target_metric_total * min_ratio))
    unit_metric_counts = {
        str(index): _count_text_units(metric_text[start:end])
        for index, (start, end) in sorted(
            _extract_indexed_section_ranges(
                metric_text,
                heading_patterns,
                heading_match_scope=heading_match_scope,
                ignored_parent_keywords=ignored_heading_parent_keywords,
            ).items()
        )
        if index in expected_indexes
    }
    insufficient_unit_metrics = [
        {
            "unit_index": index,
            "metric_value": int(unit_metric_counts.get(str(index)) or 0),
            "min_required_metric": min_per_unit,
            "deficit": max(min_per_unit - int(unit_metric_counts.get(str(index)) or 0), 0),
        }
        for index in expected_indexes
        if min_per_unit > 0
        and index in found_indexes
        and int(unit_metric_counts.get(str(index)) or 0) < min_per_unit
    ]
    refusal_markers = tuple(str(item) for item in list(policy.get("refusal_markers") or [])) or (
        "抱歉，我无法",
        "无法执行这个请求",
        "请先提供",
        "缺少前置资产",
        "我没有读取到",
        "当前可推进步骤",
        "不能直接产出",
    )
    refusal_detected = any(marker in text for marker in refusal_markers)
    issues: list[str] = []
    if not text:
        issues.append("empty_content")
    if refusal_detected:
        issues.append("refusal_or_process_text_detected")
    if min_metric_total > 0 and content_metric_total < min_metric_total:
        issues.append(f"insufficient_metric:{content_metric_total}<{min_metric_total}")
    for item in insufficient_unit_metrics:
        issues.append(
            "insufficient_unit_metric:"
            f"{item['unit_index']}:{item['metric_value']}<{item['min_required_metric']}"
        )
    if unexpected_indexes:
        issues.append("unexpected_unit_indexes:" + ",".join(str(index) for index in unexpected_indexes))
    for item in unexpected_ranges[:5]:
        issues.append(
            "unexpected_unit_range:"
            f"{item['start_index']}-{item['end_index']}!=expected:{start_index}-{end_index}"
        )
    if missing_indexes:
        issues.append("missing_required_sections:" + ",".join(str(index) for index in missing_indexes))
    return {
        "accepted": not issues,
        "content_metric_total": content_metric_total,
        "raw_content_metric_total": raw_content_metric_total,
        "min_required_metric_total": min_metric_total,
        **metric_text_diagnostics,
        "expected_unit_indexes": expected_indexes,
        "found_unit_indexes": sorted(found_indexes),
        "missing_unit_indexes": missing_indexes,
        "unexpected_unit_indexes": unexpected_indexes,
        "unexpected_unit_ranges": unexpected_ranges,
        "minimum_metric_per_unit": min_per_unit,
        "unit_metric_counts": unit_metric_counts,
        "insufficient_unit_metrics": insufficient_unit_metrics,
        "unit_metric_summary": _unit_metric_summary(
            expected_indexes=expected_indexes,
            unit_metric_counts=unit_metric_counts,
            min_per_unit=min_per_unit,
            insufficient_unit_metrics=insufficient_unit_metrics,
            missing_indexes=missing_indexes,
        ),
        "issues": issues,
    }


def _extract_indexed_markers(content: str, patterns: tuple[str, ...]) -> set[int]:
    return set(_extract_indexed_section_ranges(content, patterns))


def _extract_indexed_section_ranges(
    content: str,
    patterns: tuple[str, ...],
    *,
    heading_match_scope: str = "anywhere",
    ignored_parent_keywords: tuple[str, ...] = (),
) -> dict[int, tuple[int, int]]:
    text = str(content or "")
    scope = str(heading_match_scope or "anywhere").strip().lower()
    ignored_ranges = _ignored_parent_section_ranges(text, ignored_parent_keywords)
    markers: list[tuple[int, int]] = []
    for pattern in patterns:
        try:
            matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
        except re.error:
            continue
        for match in matches:
            if scope in {"formal_heading", "heading", "markdown_heading"} and not _is_formal_indexed_heading_match(
                text,
                match,
                require_markdown=scope == "markdown_heading",
            ):
                continue
            if _position_in_ranges(match.start(), ignored_ranges):
                continue
            value = ""
            if "index" in match.groupdict():
                value = str(match.groupdict().get("index") or "")
            elif match.groups():
                value = str(match.group(1) or "")
            parsed = _parse_index_number(value)
            if parsed > 0:
                markers.append((match.start(), parsed))
    if not markers:
        return {}
    ranges: dict[int, tuple[int, int]] = {}
    ordered = sorted(markers, key=lambda item: item[0])
    for position, (start, parsed) in enumerate(ordered):
        end = ordered[position + 1][0] if position + 1 < len(ordered) else len(text)
        ranges.setdefault(parsed, (start, end))
    return ranges


def _is_formal_indexed_heading_match(text: str, match: re.Match[str], *, require_markdown: bool = False) -> bool:
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    prefix = line[: match.start() - line_start]
    if require_markdown:
        if not re.fullmatch(r"\s{0,3}#{1,6}\s+", prefix):
            return False
    elif not re.fullmatch(r"\s{0,3}(?:#{1,6}\s+)?", prefix):
        return False
    suffix = line[match.end() - line_start :].lstrip()
    if suffix.startswith(("至", "到", "-", "—", "~", "～")):
        return False
    return True


def _ignored_parent_section_ranges(text: str, keywords: tuple[str, ...]) -> list[tuple[int, int]]:
    if not keywords:
        return []
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    ranges: list[tuple[int, int]] = []
    active_start: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        is_boundary = _is_quality_gate_section_boundary(stripped)
        has_keyword = any(keyword in stripped for keyword in keywords)
        if has_keyword and is_boundary:
            if active_start is None:
                active_start = starts[idx]
            continue
        if active_start is not None and is_boundary and not has_keyword:
            ranges.append((active_start, starts[idx]))
            active_start = None
    if active_start is not None:
        ranges.append((active_start, len(text)))
    return ranges


def _is_quality_gate_section_boundary(stripped_line: str) -> bool:
    if re.match(r"^#{1,6}\s+\S", stripped_line):
        return True
    if re.match(r"^【[^】]{1,60}】\s*$", stripped_line):
        return True
    if re.match(r"^[^：:\n]{1,40}[：:]\s*$", stripped_line):
        return True
    return False


def _position_in_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _unexpected_unit_range_declarations(
    content: str,
    *,
    expected_start: int,
    expected_end: int,
    expected_indexes: set[int],
) -> list[dict[str, Any]]:
    text = str(content or "")
    if not text.strip() or expected_start <= 0 or expected_end <= 0:
        return []
    exact_range_keywords = (
        "当前批次",
        "当前章批次",
        "本批允许范围",
        "本批允许章号",
        "允许范围",
        "批次目标",
        "批次摘要",
        "当前批次细纲",
        "当前批次正文",
    )
    broad_batch_keywords = ("本批", "本轮")
    unexpected: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        is_exact_declaration = any(keyword in stripped for keyword in exact_range_keywords) or bool(
            re.search(r"第\s*[0-9一二三四五六七八九十百零〇两]+\s*(?:[-—~～]|至|到)\s*第?\s*[0-9一二三四五六七八九十百零〇两]+\s*章\s*批次摘要", stripped)
        )
        is_batch_line = is_exact_declaration or any(keyword in stripped for keyword in broad_batch_keywords)
        if not is_batch_line:
            continue
        line_ranges = _chapter_range_mentions_in_text(stripped)
        line_indexes = _chapter_indexes_in_text(stripped)
        for range_mention in line_ranges:
            start_index = int(range_mention.get("start_index") or 0)
            end_index = int(range_mention.get("end_index") or 0)
            if (
                not is_exact_declaration
                and _is_future_unit_range_reference(
                    stripped,
                    range_mention=range_mention,
                    expected_end=expected_end,
                )
            ):
                continue
            exact_mismatch = is_exact_declaration and (start_index != expected_start or end_index != expected_end)
            subset_mismatch = not is_exact_declaration and not (
                start_index >= expected_start and end_index <= expected_end
            )
            if exact_mismatch or subset_mismatch:
                unexpected.append(
                    {
                        "line_number": line_number,
                        "line_preview": stripped[:160],
                        "start_index": start_index,
                        "end_index": end_index,
                        "expected_start_index": expected_start,
                        "expected_end_index": expected_end,
                    }
                )
        if is_exact_declaration:
            outside_indexes = sorted(index for index in line_indexes if index not in expected_indexes)
            if outside_indexes:
                unexpected.append(
                    {
                        "line_number": line_number,
                        "line_preview": stripped[:160],
                        "start_index": outside_indexes[0],
                        "end_index": outside_indexes[-1],
                        "expected_start_index": expected_start,
                        "expected_end_index": expected_end,
                        "outside_indexes": outside_indexes,
                    }
                )
    return unexpected


def _chapter_ranges_in_text(content: str) -> list[tuple[int, int]]:
    return [
        (int(item["start_index"]), int(item["end_index"]))
        for item in _chapter_range_mentions_in_text(content)
    ]


def _chapter_range_mentions_in_text(content: str) -> list[dict[str, int]]:
    text = str(content or "")
    pattern = re.compile(
        r"第\s*(?P<start>[0-9一二三四五六七八九十百零〇两]+)\s*章?\s*(?:至|到|[-—~～])\s*第?\s*(?P<end>[0-9一二三四五六七八九十百零〇两]+)\s*章"
    )
    ranges: list[dict[str, int]] = []
    for match in pattern.finditer(text):
        start_index = _parse_index_number(str(match.group("start") or ""))
        end_index = _parse_index_number(str(match.group("end") or ""))
        if start_index > 0 and end_index > 0:
            if start_index <= end_index:
                normalized_start, normalized_end = start_index, end_index
            else:
                normalized_start, normalized_end = end_index, start_index
            ranges.append(
                {
                    "start_index": normalized_start,
                    "end_index": normalized_end,
                    "match_start": int(match.start()),
                    "match_end": int(match.end()),
                }
            )
    return ranges


def _is_future_unit_range_reference(
    line: str,
    *,
    range_mention: dict[str, int],
    expected_end: int,
) -> bool:
    start_index = int(range_mention.get("start_index") or 0)
    end_index = int(range_mention.get("end_index") or 0)
    if start_index <= expected_end and end_index <= expected_end:
        return False
    future_keywords = (
        "下一批",
        "下批",
        "下一轮",
        "下轮",
        "后续批次",
        "后续章节",
        "后续章",
        "后续承接",
        "承接点",
        "下一阶段",
    )
    match_start = int(range_mention.get("match_start") or 0)
    prefix = str(line or "")[:match_start]
    suffix = str(line or "")[match_start : int(range_mention.get("match_end") or match_start)]
    nearby = str(line or "")[max(match_start - 36, 0) : min(int(range_mention.get("match_end") or match_start) + 36, len(str(line or "")))]
    return any(keyword in prefix or keyword in suffix or keyword in nearby for keyword in future_keywords)


def _chapter_indexes_in_text(content: str) -> set[int]:
    indexes: set[int] = set()
    for match in re.finditer(r"第\s*([0-9一二三四五六七八九十百零〇两]+)\s*章", str(content or "")):
        parsed = _parse_index_number(str(match.group(1) or ""))
        if parsed > 0:
            indexes.add(parsed)
    return indexes


def _unit_metric_summary(
    *,
    expected_indexes: list[int],
    unit_metric_counts: dict[str, int],
    min_per_unit: int,
    insufficient_unit_metrics: list[dict[str, int]],
    missing_indexes: list[int],
) -> str:
    if not expected_indexes:
        return ""
    insufficient_by_index = {
        int(item.get("unit_index") or 0): item for item in insufficient_unit_metrics
    }
    parts: list[str] = []
    for index in expected_indexes:
        if index in missing_indexes:
            parts.append(f"第{index}章缺失")
            continue
        count = int(unit_metric_counts.get(str(index)) or 0)
        if index in insufficient_by_index and min_per_unit > 0:
            deficit = int(insufficient_by_index[index].get("deficit") or 0)
            parts.append(f"第{index}章约{count}字，低于{min_per_unit}字，需补约{deficit}字")
        else:
            parts.append(f"第{index}章约{count}字")
    return "；".join(parts)


def _parse_index_number(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = 0
    current = 0
    for char in raw:
        if char in digits:
            current = digits[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    return total + current


def _match_bundle_ordinal_for_tool_observation(
    *,
    bundle_items: list[dict[str, Any]],
    tool_name: str,
    tool_args: dict[str, Any],
    executed_ordinals: list[int],
) -> int:
    normalized_tool = str(tool_name or "").strip()
    if not normalized_tool or not bundle_items:
        return 0
    normalized_path = str(tool_args.get("path") or "").strip()
    normalized_query = str(tool_args.get("query") or "").strip().lower()
    matching_items = [
        dict(item)
        for item in bundle_items
        if str(item.get("required_tool") or "").strip() == normalized_tool
    ]
    if not matching_items:
        return 0
    if normalized_path:
        for item in matching_items:
            binding = item.get("target_binding")
            if not isinstance(binding, dict):
                continue
            binding_path = str(dict(binding.get("metadata") or {}).get("path") or "").strip()
            if binding_path and binding_path == normalized_path:
                return _safe_int(item.get("ordinal"))
    if normalized_query:
        for item in matching_items:
            user_text = str(item.get("user_text") or "").strip().lower()
            if user_text and (user_text in normalized_query or normalized_query in user_text):
                return _safe_int(item.get("ordinal"))
    executed = {value for value in executed_ordinals if _safe_int(value) > 0}
    for item in matching_items:
        ordinal = _safe_int(item.get("ordinal"))
        if ordinal > 0 and ordinal not in executed:
            return ordinal
    return _safe_int(matching_items[0].get("ordinal"))