from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from graph_system.revision_signal_registry import RevisionRejectionSignalHandler, RevisionRequeuePatchHandler
from task_system.runtime_semantics.review_gate_verdict import (
    extract_review_verdict,
    review_verdict_is_rejected,
)


def register_revision_rejection_signal_handlers(register) -> None:
    register(
        RevisionRejectionSignalHandler(
            handler_id="writing_review_verdict_revision_signal",
            source_result_requests_revision=source_result_requests_writing_revision,
            priority=200,
        )
    )


def register_revision_requeue_patch_handlers(register) -> None:
    register(
        RevisionRequeuePatchHandler(
            handler_id="writing_chapter_revision_requeue_patch",
            build_revision_requeue_patch=build_writing_chapter_revision_requeue_patch,
            priority=200,
        )
    )


def source_result_requests_writing_revision(*, source_result: dict[str, Any]) -> dict[str, Any] | None:
    text = str(dict(source_result or {}).get("handoff_summary") or "").strip()
    if not text:
        return None
    verdict = extract_review_verdict(text)
    if not verdict:
        return None
    return {
        "requests_revision": review_verdict_is_rejected(verdict),
        "verdict": verdict,
        "authority": "task_system.writing_graphs.revision_signal.review_verdict",
    }


def build_writing_chapter_revision_requeue_patch(
    *,
    graph_config: Any,
    state: Any,
    target_node_ids: tuple[str, ...],
    revision_sources: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    if not _targets_require_chapter_revision(graph_config=graph_config, target_node_ids=target_node_ids):
        return None
    affected_indexes: list[int] = []
    revision_plan_text = ""
    for source in revision_sources:
        route = _revision_route_from_source(source)
        review_text = _revision_source_text(dict(source.get("source_result") or {}))
        indexes = _revision_route_chapter_indexes(route, state=state) if route else _revision_affected_chapter_indexes(review_text)
        indexes = _revision_indexes_within_current_batch(indexes, state=state)
        if not indexes:
            continue
        if not revision_plan_text:
            revision_plan_text = _revision_route_plan_text(route=route, review_text=review_text) if route else _revision_plan_excerpt(review_text)
        for index in indexes:
            if index not in affected_indexes:
                affected_indexes.append(index)
    queue = sorted(affected_indexes)
    if not queue:
        return None
    affected_start = int(queue[0])
    initial_inputs = dict(getattr(state, "initial_inputs", {}) or {})
    parent_start = _numeric_value(
        initial_inputs.get("batch_start_index")
        or initial_inputs.get("active_chapter_start_index"),
        None,
    )
    parent_end = _numeric_value(
        initial_inputs.get("batch_end_index")
        or initial_inputs.get("active_chapter_end_index"),
        parent_start,
    )
    patch: dict[str, Any] = {
        **_single_chapter_cursor_patch(affected_start),
        "revision_active": True,
        "revision_cursor_key": "chapter_index",
        "revision_cursor_values": queue,
        "revision_cursor_start": affected_start,
        "revision_cursor_end": int(queue[-1]),
        "revision_parent_start": parent_start,
        "revision_parent_end": parent_end,
        "revision_queue_chapter_indexes": queue,
        "revision_queue_position": 0,
        "revision_current_chapter_index": affected_start,
        "revision_execution_range": _revision_execution_range_label(queue),
        "authority": "task_system.writing_graphs.revision_requeue_patch.chapter_queue",
    }
    if revision_plan_text:
        patch["revision_plan_text"] = revision_plan_text
        patch["chapter_revision_requirements"] = _revision_requirements_for_chapter(
            revision_plan_text,
            affected_start,
        )
    return patch


def _targets_require_chapter_revision(*, graph_config: Any, target_node_ids: tuple[str, ...]) -> bool:
    for node_id in target_node_ids:
        node = _node_by_id(graph_config, str(node_id)) or {}
        node_tail = str(node.get("node_id") or "").split("::")[-1]
        if node_tail == "chapter_draft":
            return True
        retry_policy = dict(node.get("retry") or {})
        if str(retry_policy.get("requirements_input_key") or "").strip() == "chapter_revision_requirements":
            return True
    return False


def _node_by_id(graph_config: Any, node_id: str) -> dict[str, Any]:
    for raw in list(getattr(graph_config, "nodes", ()) or ()):
        node = dict(raw or {})
        if str(node.get("node_id") or "").strip() == str(node_id or "").strip():
            return node
    return {}


def _revision_route_from_source(source: dict[str, Any]) -> dict[str, Any]:
    route = _normalize_revision_route(source.get("revision_route"))
    if route:
        return route
    return _revision_route_from_result_summary(dict(source.get("source_result") or {}))


def _revision_route_from_result_summary(summary: dict[str, Any]) -> dict[str, Any]:
    outputs = dict(dict(summary or {}).get("outputs") or {})
    candidates: list[Any] = [
        dict(summary or {}).get("revision_route"),
        outputs.get("revision_route"),
    ]
    for key in ("structured_output", "node_output"):
        payload = outputs.get(key)
        if isinstance(payload, dict):
            candidates.extend(
                [
                    payload.get("revision_route"),
                    payload.get("review_revision_route"),
                    payload.get("revision"),
                ]
            )
    for candidate in candidates:
        route = _normalize_revision_route(candidate)
        if route:
            return route
    return {}


def _normalize_revision_route(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    route = dict(candidate or {})
    action = str(route.get("action") or route.get("decision") or route.get("route") or "").strip().lower()
    if action and action not in {
        "revise",
        "revision",
        "request_revision",
        "rewrite",
        "return_to_writer",
        "reject",
        "rejected",
        "返修",
        "拒绝",
    }:
        return {}
    if not action and not any(
        key in route
        for key in (
            "chapter_indexes",
            "affected_chapter_indexes",
            "revision_chapter_indexes",
            "rewrite_chapter_indexes",
            "scope",
            "full_batch",
        )
    ):
        return {}
    route["action"] = action or "revise"
    route["authority"] = str(route.get("authority") or "task_system.writing_graphs.chapter_review.revision_route")
    return route


def _revision_route_chapter_indexes(route: dict[str, Any], *, state: Any) -> list[int]:
    if not route:
        return []
    scope = str(route.get("scope") or route.get("revision_scope") or "").strip().lower()
    full_batch = bool(route.get("full_batch") is True) or scope in {
        "full_batch",
        "batch",
        "all_batch",
        "entire_batch",
        "all",
        "整批",
        "全批",
    }
    if full_batch:
        initial_inputs = dict(getattr(state, "initial_inputs", {}) or {})
        start = _numeric_value(route.get("batch_start_index"), None)
        end = _numeric_value(route.get("batch_end_index"), None)
        if start is None:
            start = _numeric_value(initial_inputs.get("batch_start_index"), None)
        if end is None:
            end = _numeric_value(initial_inputs.get("batch_end_index"), start)
        return _revision_indexes_from_range_values(start, end)
    indexes: list[int] = []
    for key in (
        "chapter_indexes",
        "affected_chapter_indexes",
        "revision_chapter_indexes",
        "rewrite_chapter_indexes",
        "chapters",
        "affected_chapters",
    ):
        indexes.extend(_revision_route_indexes_from_value(route.get(key)))
    if indexes:
        return sorted(dict.fromkeys(indexes))
    start = _numeric_value(
        route.get("revision_start_index")
        or route.get("start_chapter_index")
        or route.get("chapter_start_index"),
        None,
    )
    end = _numeric_value(
        route.get("revision_end_index")
        or route.get("end_chapter_index")
        or route.get("chapter_end_index"),
        start,
    )
    return _revision_indexes_from_range_values(start, end)


def _revision_route_indexes_from_value(value: Any) -> list[int]:
    raw_items = value if isinstance(value, list) else ([value] if value is not None else [])
    indexes: list[int] = []
    for item in raw_items:
        if isinstance(item, dict):
            number = _numeric_value(item.get("chapter_index") or item.get("index") or item.get("chapter"), None)
        else:
            number = _numeric_value(item, None)
        if number is None:
            continue
        chapter = int(number)
        if chapter > 0 and chapter not in indexes:
            indexes.append(chapter)
    return indexes


def _revision_indexes_from_range_values(start_value: Any, end_value: Any) -> list[int]:
    start = _numeric_value(start_value, None)
    end = _numeric_value(end_value, start)
    if start is None or end is None:
        return []
    start_index = int(start)
    end_index = int(end)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    if start_index <= 0 or end_index - start_index > 100:
        return []
    return list(range(start_index, end_index + 1))


def _revision_route_plan_text(*, route: dict[str, Any], review_text: str) -> str:
    route_text = json.dumps(route, ensure_ascii=False, indent=2) if route else ""
    requirements = (
        route.get("requirements")
        or route.get("revision_requirements")
        or route.get("instructions")
        or route.get("reason")
        or route.get("issue_summary")
    )
    if isinstance(requirements, (dict, list)):
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
    else:
        requirements_text = str(requirements or "").strip()
    sections = []
    if route_text:
        sections.append(f"## 返修路由\n\n```json\n{route_text}\n```")
    if requirements_text:
        sections.append(f"## 返修要求\n\n{requirements_text}")
    excerpt = _revision_plan_excerpt(review_text)
    if excerpt:
        sections.append(excerpt)
    return "\n\n".join(sections).strip()[:16000]


def _revision_source_text(summary: dict[str, Any]) -> str:
    for ref in list(dict(summary or {}).get("artifact_refs") or []):
        path = _artifact_ref_path(ref)
        if not path:
            continue
        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            if candidate.exists() and candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
                if text.strip():
                    return text
        except Exception:
            continue
    return str(dict(summary or {}).get("handoff_summary") or "")


def _revision_plan_excerpt(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    sections: list[str] = []
    for heading in ("返修要求", "必须修改项", "阻塞问题", "阻塞性问题", "问题清单", "语义连续性与矛盾点检查", "层级一致性检查"):
        match = re.search(rf"(?m)^(#{{1,4}})\s*{heading}\b.*$", normalized)
        if not match:
            continue
        section = _markdown_heading_section(normalized, start=match.start(), level=len(match.group(1)))
        if section.strip():
            sections.append(section.strip())
    return "\n\n".join(dict.fromkeys(sections)).strip()[:16000] or normalized[:16000]


def _markdown_heading_section(text: str, *, start: int, level: int) -> str:
    tail = str(text or "")[start:]
    first_newline = tail.find("\n")
    if first_newline < 0:
        return tail
    search_tail = tail[first_newline + 1 :]
    next_heading = re.search(rf"(?m)^#{{1,{max(1, int(level))}}}\s+", search_tail)
    if not next_heading:
        return tail
    return tail[: first_newline + 1 + next_heading.start()]


def _revision_requirements_for_chapter(plan_text: str, chapter: int) -> str:
    normalized = str(plan_text or "").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    selected: list[str] = []
    chapter_pattern = re.compile(rf"第\s*0*{chapter}\s*章")
    any_chapter_pattern = re.compile(r"第\s*0*\d{1,4}\s*章")
    capture = False
    for line in lines:
        if chapter_pattern.search(line):
            capture = True
            selected.append(line)
            continue
        if capture and any_chapter_pattern.search(line) and not chapter_pattern.search(line):
            break
        if capture:
            selected.append(line)
    body = "\n".join(selected).strip() if selected else normalized[:6000]
    if len(body) < 200:
        body = normalized[:6000]
    return (
        f"当前返修章：第{chapter}章。以下要求只用于当前章重写；"
        "返修队列中的其他章节由图循环逐章调度。\n\n"
        f"{body}"
    ).strip()[:8000]


def _revision_affected_chapter_indexes(text: str) -> list[int]:
    normalized = str(text or "")
    if not normalized:
        return []
    explicit_patterns = (
        r"(?:重写|返修|修改|修正)[^。\n]{0,30}?第\s*0*(\d{1,4})\s*[-至到~—－]\s*0*(\d{1,4})\s*章",
        r"(?:重写|返修|修改|修正)[^。\n]{0,30}?第\s*0*(\d{1,4})\s*章",
    )
    requirement_section = _revision_requirement_section(normalized)
    if requirement_section:
        requirement_indexes = _revision_chapter_indexes_from_section(requirement_section, explicit_patterns)
        if requirement_indexes:
            return requirement_indexes
    blocking_section = _revision_blocking_section(normalized)
    if blocking_section:
        blocking_indexes = _revision_chapter_indexes_from_section(blocking_section, explicit_patterns)
        if blocking_indexes:
            return blocking_indexes
    explicit_candidates = _revision_range_candidates(normalized, explicit_patterns)
    if explicit_candidates:
        return _revision_indexes_from_ranges(explicit_candidates)
    return []


def _revision_chapter_indexes_from_section(text: str, patterns: tuple[str, ...]) -> list[int]:
    indexes = _revision_indexes_from_ranges(_revision_range_candidates(text, patterns))
    for line in str(text or "").splitlines():
        if not re.search(r"第\s*0*\d{1,4}\s*章", line):
            continue
        if _revision_line_is_scope_description(line):
            continue
        if not _revision_line_is_issue(line):
            continue
        for match in re.finditer(r"第\s*0*(\d{1,4})\s*章", line):
            chapter = int(match.group(1))
            if chapter > 0 and chapter not in indexes:
                indexes.append(chapter)
    return sorted(indexes)


def _revision_line_is_scope_description(line: str) -> bool:
    text = str(line or "")
    if re.search(r"(?:返修|重写|修改|修正|阻塞|问题|矛盾|缺失|不达标|偏离|必须|需要|不足)", text):
        return False
    return bool(re.search(r"(?:汇总范围|审核范围|当前批次|允许范围|章节引用索引)", text))


def _revision_line_is_issue(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    if re.search(r"(?:返修|重写|修改|修正|阻塞|问题|矛盾|缺失|不达标|偏离|必须|需要|不足|不允许|不能通过)", text):
        return True
    return bool(re.match(r"^(?:[-*+]\s*)?(?:B-\d+|R-\d+|问题\s*\d+|第\s*0*\d{1,4}\s*章)[：:、.\s]", text))


def _revision_range_candidates(text: str, patterns: tuple[str, ...]) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = int(match.group(1))
            end = int(match.group(2)) if len(match.groups()) >= 2 and match.group(2) else start
            if start > end:
                start, end = end, start
            candidates.append((start, end))
    return candidates


def _revision_indexes_from_ranges(candidates: list[tuple[int, int]]) -> list[int]:
    indexes: list[int] = []
    for start, end in candidates:
        if start > end:
            start, end = end, start
        if end - start > 100:
            continue
        for chapter in range(start, end + 1):
            if chapter > 0 and chapter not in indexes:
                indexes.append(chapter)
    return sorted(indexes)


def _revision_requirement_section(text: str) -> str:
    match = re.search(r"(?m)^#{1,4}\s*返修要求\s*$", text)
    if not match:
        return ""
    tail = text[match.end() :]
    next_heading = re.search(r"(?m)^#{1,4}\s+", tail)
    return tail[: next_heading.start()] if next_heading else tail


def _revision_blocking_section(text: str) -> str:
    match = re.search(r"(?m)^#{1,4}\s*(?:必须修改项|阻塞问题|阻塞性问题|问题清单)\b.*$", text)
    if not match:
        return ""
    tail = text[match.end() :]
    next_nonblocking = re.search(r"(?m)^#{1,4}\s*(?:非阻塞|备注)", tail)
    if next_nonblocking:
        tail = tail[: next_nonblocking.start()]
    next_major = re.search(r"(?m)^##\s+(?:是否允许|下游|输入继承|当前节点|禁止)", tail)
    return tail[: next_major.start()] if next_major else tail


def _revision_indexes_within_current_batch(indexes: list[int], *, state: Any) -> list[int]:
    if not indexes:
        return []
    initial_inputs = dict(getattr(state, "initial_inputs", {}) or {})
    start = _numeric_value(
        initial_inputs.get("batch_start_index")
        or initial_inputs.get("active_chapter_start_index"),
        None,
    )
    end = _numeric_value(
        initial_inputs.get("batch_end_index")
        or initial_inputs.get("active_chapter_end_index"),
        None,
    )
    if start is None or end is None:
        return sorted(dict.fromkeys(index for index in indexes if int(index) > 0))
    start_index = int(start)
    end_index = int(end)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    return sorted(
        dict.fromkeys(
            int(index)
            for index in indexes
            if int(index) >= start_index and int(index) <= end_index
        )
    )


def _single_chapter_cursor_patch(chapter: int) -> dict[str, Any]:
    return {
        "chapter_index": chapter,
        "chapter_index_padded": f"{chapter:03d}",
        "chapter_file_prefix": f"chapter_{chapter:03d}",
        "active_chapter_start_index": chapter,
        "active_chapter_end_index": chapter,
        "active_chapter_count": 1,
        "active_chapter_range": f"{chapter:03d}-{chapter:03d}",
    }


def _revision_execution_range_label(indexes: list[int]) -> str:
    ordered = sorted({int(item) for item in indexes if int(item) > 0})
    if not ordered:
        return ""
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0]:03d}-{ordered[-1]:03d}"
    return ",".join(f"{item:03d}" for item in ordered)


def _artifact_ref_path(ref: Any) -> str:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        for key in ("path", "artifact_path", "ref", "artifact_ref"):
            value = str(ref.get(key) or "").strip()
            if value:
                return value
    return ""


def _numeric_value(value: Any, default: Any = 0) -> Any:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default
