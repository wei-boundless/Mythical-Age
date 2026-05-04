from __future__ import annotations

from pathlib import Path
from typing import Any

from health_system.maintenance.experiments.artifacts import read_json_file
from health_system.maintenance.experiments.prompt_manifest import extract_prompt_manifest_from_turn


MEMORY_SECTION_NAMES = {
    "active_process_context": "状态流程",
    "hot_truth_window": "热事实窗口",
    "warm_snapshots": "暖启动快照",
    "exact_durable_context": "精确长期记忆",
    "relevant_durable_context": "相关长期记忆",
    "debug_session_trace": "调试会话轨迹",
}


def get_turn_memory_trace(output_dir: Path, turn_id: str) -> dict[str, Any]:
    turn_path = _find_turn_path(output_dir, turn_id)
    if turn_path is None:
        return {
            "status": "missing_trace",
            "reason": "没有找到对应 turn artifact。",
            "memory_trace": None,
        }
    payload = read_json_file(turn_path, {})
    if not isinstance(payload, dict):
        return {
            "status": "missing_trace",
            "reason": "turn artifact 不是合法 JSON 对象。",
            "memory_trace": None,
        }
    trace = build_memory_trace_from_turn(payload, run_id=output_dir.name, turn_id=turn_id)
    if not trace["has_memory_signal"]:
        return {
            "status": "missing_trace",
            "reason": "此 turn 没有记录 memory_context，也没有可见的记忆注入片段。",
            "memory_trace": trace,
        }
    return {
        "status": "available",
        "reason": "",
        "memory_trace": trace,
    }


def build_memory_trace_from_turn(payload: dict[str, Any], *, run_id: str = "", turn_id: str = "") -> dict[str, Any]:
    context = _latest_context_management(payload)
    memory_context = _latest_memory_context(payload)
    prompt_manifest = extract_prompt_manifest_from_turn(payload)
    turn_payload = _dict(payload.get("turn"))
    result_payload = _dict(payload.get("result"))
    prompt_sections = _memory_prompt_sections(prompt_manifest)
    model_sections = _sections_payload(_dict(context.get("model_visible_sections")))
    debug_sections = _sections_payload(_dict(context.get("debug_sections")))
    selected_sections = list(context.get("selected_sections") or [])
    debug_selected_sections = list(context.get("debug_selected_sections") or [])
    token_accounting = _dict(context.get("token_accounting"))
    memory_payload = _dict(memory_context.get("memory"))
    durable_payload = _dict(memory_payload.get("durable_memory"))
    session_payload = _dict(memory_payload.get("session_memory"))

    exact_count = _section_item_count(model_sections, "exact_durable_context") or len(durable_payload.get("exact_matches") or [])
    relevant_count = _section_item_count(model_sections, "relevant_durable_context") or len(durable_payload.get("relevant_notes") or [])
    session_count = (
        _section_item_count(model_sections, "active_process_context")
        + _section_item_count(model_sections, "hot_truth_window")
        + _section_item_count(model_sections, "warm_snapshots")
    )
    prompt_memory_chars = sum(int(section.get("chars") or 0) for section in prompt_sections)
    has_memory_signal = bool(
        memory_context
        or prompt_sections
        or exact_count
        or relevant_count
        or session_count
        or selected_sections
        or debug_selected_sections
    )

    return {
        "run_id": run_id,
        "turn_id": turn_id,
        "has_memory_signal": has_memory_signal,
        "turn_context": {
            "index": int(result_payload.get("index") or 0),
            "session_alias": str(result_payload.get("session_alias") or turn_payload.get("session") or ""),
            "speaker": str(turn_payload.get("speaker") or ""),
            "user_input": str(turn_payload.get("content") or result_payload.get("message") or ""),
            "assistant_output": str(result_payload.get("response_text") or result_payload.get("persisted_assistant_text") or ""),
            "status": "passed" if result_payload.get("passed") is True else "failed" if result_payload.get("passed") is False else "",
            "failed_checks": [str(item) for item in list(result_payload.get("failed_checks") or [])],
            "artifact_path": str(result_payload.get("artifact_path") or ""),
        },
        "summary": _summary_text(
            exact_count=exact_count,
            relevant_count=relevant_count,
            session_count=session_count,
            prompt_memory_chars=prompt_memory_chars,
        ),
        "context_management": {
            "pressure_level": str(context.get("pressure_level") or "unknown"),
            "strategy": str(context.get("strategy") or context.get("compaction_strategy") or "unknown"),
            "selected_sections": [str(item) for item in selected_sections],
            "debug_selected_sections": [str(item) for item in debug_selected_sections],
            "dropped_sections": [str(item) for item in list(context.get("dropped_sections") or [])],
            "token_accounting": {
                "durable_tokens": int(token_accounting.get("durable_tokens") or 0),
                "exact_durable_tokens": int(token_accounting.get("exact_durable_tokens") or 0),
                "relevant_durable_tokens": int(token_accounting.get("relevant_durable_tokens") or 0),
                "estimated_tokens_after": int(token_accounting.get("estimated_tokens_after") or 0),
            },
        },
        "session_memory": {
            "section_count": session_count,
            "model_sections": _only_memory_sections(model_sections, include_durable=False),
            "debug_sections": _only_memory_sections(debug_sections, include_durable=False),
            "active_goal": str(session_payload.get("active_goal") or ""),
            "flow_state": _dict(session_payload.get("flow_state")),
            "task_state": _dict(session_payload.get("task_state")),
            "context_slots": _dict(session_payload.get("context_slots")),
        },
        "durable_memory": {
            "exact_count": exact_count,
            "relevant_count": relevant_count,
            "exact_matches": list(durable_payload.get("exact_matches") or [])[:8],
            "relevant_notes": list(durable_payload.get("relevant_notes") or [])[:8],
            "model_sections": _only_durable_sections(model_sections),
            "debug_sections": _only_durable_sections(debug_sections),
        },
        "prompt_injection": {
            "section_count": len(prompt_sections),
            "total_chars": prompt_memory_chars,
            "sections": prompt_sections,
        },
    }


def has_turn_memory_trace(payload: dict[str, Any]) -> bool:
    trace = build_memory_trace_from_turn(payload)
    return bool(trace.get("has_memory_signal"))


def _latest_context_management(payload: dict[str, Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for event in list(payload.get("events") or []):
        if not isinstance(event, dict) or event.get("event") != "context_management":
            continue
        data = _dict(event.get("data"))
        context = _dict(data.get("context"))
        if context:
            latest = context
    return latest


def _latest_memory_context(payload: dict[str, Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for event in list(payload.get("events") or []):
        if not isinstance(event, dict) or event.get("event") != "memory_context":
            continue
        data = _dict(event.get("data"))
        if data:
            latest = data
    return latest


def _memory_prompt_sections(prompt_manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section in list(_dict(prompt_manifest).get("sections") or []):
        if not isinstance(section, dict):
            continue
        blob = " ".join(
            str(section.get(key) or "")
            for key in ("id", "title", "source", "layer", "preview")
        ).lower()
        if not any(token in blob for token in ["memory", "记忆", "context", "durable", "session"]):
            continue
        sections.append(
            {
                "id": str(section.get("id") or ""),
                "title": str(section.get("title") or ""),
                "layer": str(section.get("layer") or ""),
                "source": str(section.get("source") or ""),
                "chars": int(section.get("chars") or 0),
                "preview": _compact_text(str(section.get("preview") or ""), 420),
                "order": int(section.get("order") or 0),
            }
        )
    return sections


def _sections_payload(sections: dict[str, Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for key, raw_items in sections.items():
        if key not in MEMORY_SECTION_NAMES:
            continue
        items = [str(item) for item in list(raw_items or []) if str(item).strip()]
        payload.append(
            {
                "id": key,
                "label": MEMORY_SECTION_NAMES.get(key, key),
                "items": [_compact_text(item, 420) for item in items[:8]],
                "count": len(items),
            }
        )
    return payload


def _only_memory_sections(sections: list[dict[str, Any]], *, include_durable: bool) -> list[dict[str, Any]]:
    durable_ids = {"exact_durable_context", "relevant_durable_context"}
    return [
        section
        for section in sections
        if (section.get("id") in durable_ids) == include_durable
    ]


def _only_durable_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _only_memory_sections(sections, include_durable=True)


def _section_item_count(sections: list[dict[str, Any]], section_id: str) -> int:
    for section in sections:
        if section.get("id") == section_id:
            return int(section.get("count") or 0)
    return 0


def _summary_text(*, exact_count: int, relevant_count: int, session_count: int, prompt_memory_chars: int) -> str:
    parts = [
        f"状态记忆 {session_count} 段",
        f"精确长期 {exact_count} 条",
        f"相关长期 {relevant_count} 条",
        f"Prompt 记忆片段 {prompt_memory_chars} chars",
    ]
    return " · ".join(parts)


def _find_turn_path(output_dir: Path, turn_id: str) -> Path | None:
    normalized = str(turn_id or "").strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized.startswith("."):
        return None
    for path in output_dir.glob("artifacts/**/turn-*.json"):
        if path.stem == normalized:
            return path
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact_text(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").replace("\r\n", "\n").replace("\r", "\n").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"
