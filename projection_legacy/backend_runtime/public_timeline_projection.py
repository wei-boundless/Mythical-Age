from __future__ import annotations

import json
import re
from hashlib import sha1
from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary


SUPPRESSED_TEXT = {
    "",
    "assistant_message",
    "done",
    "completed",
    "running",
    "working",
    "ready_to_finish",
    "开始处理",
    "处理完成",
    "处理已完成",
    "处理结束",
    "正在处理",
    "正在处理当前请求",
    "正在处理当前请求。",
    "正在处理任务",
    "正在建立任务运行",
    "正在建立任务运行。",
    "已开始处理当前请求",
    "已开始处理当前请求。",
    "true",
    "false",
    "null",
    "none",
    "回答已生成并写回会话",
    "会话输出完成",
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
}

INTERNAL_EVENT_TOKENS = {
    "agent_turn_terminal",
    "runtime_invocation_packet_compiled",
    "task_execution_packet_compiled",
    "task_model_action_wait_heartbeat",
    "task_run_executor_scheduled",
    "task_run_executor_claimed",
    "step_summary_recorded",
}

STRUCTURED_PAYLOAD_TOKENS = {
    "action_type",
    "authority",
    "completion_status",
    "diagnostics",
    "model_action",
    "matched_version_count",
    "candidate_version_count",
    "public_action_state",
    "public_progress_note",
    "result_envelope",
    "structured_payload",
    "tool_call",
}

TOOL_NAME_TOKENS = {
    "agent_todo",
    "apply_patch",
    "edit_file",
    "glob_paths",
    "image_asset",
    "image_generate",
    "image_generation",
    "list_dir",
    "memory_search",
    "path_exists",
    "read_file",
    "read_path",
    "search_files",
    "search_text",
    "stat_path",
    "terminal",
    "write_file",
}


def public_text(value: Any, *, limit: int = 220) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    text = " ".join(text.split()).strip()
    lowered = text.lower()
    if text in SUPPRESSED_TEXT or lowered in SUPPRESSED_TEXT:
        return ""
    if _looks_like_generic_tool_wait(text):
        return ""
    if _looks_internal(text) or looks_structured_payload(text):
        return ""
    if limit > 0 and len(text) > limit:
        return text[: max(1, limit - 1)] + "..."
    return text


def public_work_action_item(
    *,
    item_id: str,
    tool_name: str = "",
    raw_target: Any = "",
    summary: Any = "",
    observation: Any = "",
    state: str = "running",
    trace_refs: list[str] | None = None,
    recovery_hint: Any = "",
    action_kind: str = "",
) -> dict[str, Any]:
    normalized_state = public_state(state)
    kind = action_kind or public_action_kind(tool_name, raw_target)
    subject = public_subject_label(tool_name=tool_name, raw_target=raw_target, action_kind=kind)
    phase = "adjusting" if normalized_state == "error" else "done" if normalized_state == "done" else "running"
    title = public_action_title(action_kind=kind, phase=phase)
    summary_text = public_action_summary(action_kind=kind, phase=phase, subject_label=subject, fallback=summary)
    observation_text = public_observation_text(
        action_kind=kind,
        phase=phase,
        subject_label=subject,
        value=observation or summary,
    )
    recovery_text = public_text(recovery_hint, limit=180)
    if not subject and summary_text == title and not observation_text and not recovery_text:
        return {}
    return compact(
        {
            "item_id": item_id or stable_id("work-action", ",".join(trace_refs or []), kind, subject),
            "kind": "work_action",
            "slot": "tool",
            "surface": "tool_window",
            "source_authority": "tool",
            "action_kind": kind,
            "phase": phase,
            "title": title,
            "subject_label": subject,
            "public_summary": summary_text,
            "observation": observation_text,
            "recovery_hint": recovery_text,
            "state": normalized_state,
            "stream_state": "streaming" if normalized_state == "running" else "done",
            "trace_refs": trace_refs or [],
        }
    )


def public_observation_report_item(
    *,
    item_id: str,
    detail: Any,
    state: str = "done",
    trace_refs: list[str] | None = None,
    implication: Any = "",
    title: str = "处理反馈",
) -> dict[str, Any]:
    visible_detail = public_text(detail, limit=220)
    if not visible_detail:
        return {}
    return compact(
        {
            "item_id": item_id or stable_id("observation", ",".join(trace_refs or []), title, visible_detail),
            "kind": "observation_report",
            "slot": "body",
            "surface": "assistant_body",
            "source_authority": "model",
            "title": title,
            "detail": visible_detail,
            "implication": public_text(implication, limit=180),
            "state": public_state(state),
            "trace_refs": trace_refs or [],
        }
    )


def public_action_kind(tool_name: str, raw_target: Any = "") -> str:
    normalized = str(tool_name or "").strip().lower()
    target = str(raw_target or "").strip().lower()
    if normalized == "memory_search":
        return "memory"
    if normalized in {"image_generate", "image_generation", "generate_image", "image_asset"}:
        return "image"
    if normalized in {"path_exists", "stat_path", "list_dir"}:
        return "inspect"
    if normalized in {"read_file", "read_path"} or "read" in normalized:
        return "read"
    if normalized in {"search_text", "search_files", "glob_paths"} or any(token in normalized for token in ("search", "grep", "glob")):
        return "search"
    if normalized in {"write_file", "edit_file", "apply_patch"} or any(token in normalized for token in ("write", "edit", "patch")):
        return "edit"
    if any(token in normalized for token in ("terminal", "shell", "command", "powershell")):
        if _looks_like_verification_command(target):
            return "verify"
        if _looks_like_prepare_command(target):
            return "prepare"
        return "run"
    return "work"


def public_subject_label(*, tool_name: str, raw_target: Any, action_kind: str) -> str:
    text = public_text(raw_target, limit=180)
    if not text:
        if action_kind == "memory":
            return "相关记忆"
        if action_kind == "verify":
            return "验证结果"
        if action_kind == "prepare":
            return "输出准备"
        return ""
    if looks_structured_payload(text) or _looks_like_raw_command(text) or _is_tool_token(text):
        if action_kind == "prepare":
            return _prepare_subject_from_command(text)
        if action_kind == "verify":
            return _verification_subject_from_command(text)
        if action_kind == "memory":
            return "相关记忆"
        return ""
    if action_kind == "memory":
        return "相关记忆"
    if action_kind in {"read", "edit", "inspect"}:
        return compact_path_label(text)
    if action_kind == "search":
        return _search_subject(text)
    if action_kind == "verify":
        return _verification_subject_from_command(text)
    if action_kind == "prepare":
        return _prepare_subject_from_command(text)
    return compact_path_label(text) if looks_like_path(text) else public_text(text, limit=80)


def public_action_title(*, action_kind: str, phase: str) -> str:
    labels = {
        "inspect": ("正在确认目标", "已确认目标", "确认目标未完成"),
        "read": ("正在读取上下文", "已读取上下文", "读取上下文未完成"),
        "search": ("正在搜索引用", "已搜索引用", "搜索未完成"),
        "edit": ("正在更新文件", "已更新文件", "更新未完成"),
        "run": ("正在运行命令", "命令已返回", "命令未完成"),
        "verify": ("正在运行验证", "验证已返回", "验证未完成"),
        "memory": ("正在检索相关记忆", "记忆检索已返回", "记忆检索未完成"),
        "prepare": ("正在准备输出", "输出准备完成", "输出准备未完成"),
        "image": ("正在生成图像", "图像已生成", "图像生成未完成"),
        "artifact": ("产物就绪", "产物就绪", "产物未完成"),
    }
    running, done, adjusting = labels.get(action_kind, ("正在调用工具", "工具结果已返回", "步骤未完成"))
    if phase == "done":
        return done
    if phase == "adjusting":
        return adjusting
    return running


def public_action_summary(*, action_kind: str, phase: str, subject_label: str, fallback: Any = "") -> str:
    title = public_action_title(action_kind=action_kind, phase=phase)
    subject = public_text(subject_label, limit=100)
    if subject:
        return f"{title} {subject}"
    fallback_text = public_text(fallback, limit=120)
    if fallback_text and not _looks_like_raw_command(fallback_text) and not _is_tool_token(fallback_text):
        return fallback_text
    return title


def public_observation_text(*, action_kind: str, phase: str, subject_label: str, value: Any = "") -> str:
    if phase == "running":
        return ""
    text = public_text(value, limit=180)
    if text and text != subject_label and not _looks_like_raw_command(text) and not _is_tool_token(text):
        if action_kind == "verify":
            return f"验证已返回，{text}"
        if action_kind == "prepare":
            return f"输出准备已返回，{text}"
        return text
    return ""


def memory_search_observation_detail(value: Any) -> str:
    payload = _json_record(value)
    result_count = _safe_int(payload.get("result_count"))
    results = payload.get("results")
    if result_count is None and isinstance(results, list):
        result_count = len(results)
    if result_count is None:
        return "记忆检索已返回，结果会纳入当前判断"
    if result_count > 0:
        return f"记忆检索命中 {result_count} 条相关记录"
    return "记忆检索未找到相关记录"


def path_exists_observation_detail(value: Any) -> str:
    data = _record(value)
    exists = data.get("exists")
    if exists is True:
        return "目标路径存在"
    if exists is False:
        return "目标路径不存在"
    return ""


def public_state(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"done", "ready", "passed", "success", "completed"}:
        return "done"
    if text in {"error", "failed", "blocked", "missing", "aborted", "cancelled", "canceled"}:
        return "error"
    return "running"


def stable_id(prefix: str, left: str, middle: str = "", right: str = "") -> str:
    digest = sha1("|".join([prefix, left, middle, right]).encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def compact(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value not in ("", None, [], {})}


def looks_structured_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        return True
    lowered = text.lower()
    return any(token in lowered for token in STRUCTURED_PAYLOAD_TOKENS)


def looks_like_path(value: str) -> bool:
    return bool(re.search(r"[\\/]", value) or re.search(r"\.[a-z0-9]{1,8}(?:\s|$)", value, flags=re.IGNORECASE))


def compact_path_label(value: Any, *, limit: int = 90) -> str:
    text = public_text(value, limit=240)
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) <= 2 or not looks_like_path(text):
        return public_text(text, limit=limit)
    tail = parts[-1]
    parent = parts[-2] if len(parts) >= 2 else ""
    return public_text(f"{parent}/{tail}" if parent else tail, limit=limit)


def _search_subject(value: str) -> str:
    text = public_text(value, limit=90)
    if not text or _looks_like_raw_command(text) or _is_tool_token(text):
        return "相关引用"
    return compact_path_label(text, limit=90) if looks_like_path(text) else text


def _prepare_subject_from_command(value: str) -> str:
    text = str(value or "")
    if re.search(r"\b(New-Item|mkdir)\b", text, flags=re.IGNORECASE):
        if re.search(r"\b(ItemType\s+Directory|mkdir)\b", text, flags=re.IGNORECASE):
            return "输出目录"
        return "输出文件"
    return "输出准备"


def _verification_subject_from_command(value: str) -> str:
    text = str(value or "").lower()
    if "vitest" in text or "npm test" in text or "pnpm test" in text or "yarn test" in text:
        return "前端测试"
    if "pytest" in text:
        return "后端测试"
    if "ruff" in text or "mypy" in text or "tsc" in text or "eslint" in text:
        return "代码校验"
    return "验证结果"


def _looks_like_raw_command(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"\b(New-Item|Set-Content|Get-Content|Remove-Item|Move-Item|Copy-Item|npm|pnpm|yarn|pytest|python|powershell|cmd\s*/c|git|rg|grep|mkdir|touch)\b", text, flags=re.IGNORECASE)
        or re.search(r"\s-(?:ItemType|Path|Recurse|Force|Filter|Pattern|Command)\b", text, flags=re.IGNORECASE)
        or re.search(r"[;&|]{1,2}", text)
    )


def _looks_like_generic_tool_wait(value: str) -> bool:
    return bool(re.match(r"^(已发起工具调用|已经过工具调用)，正在等待工具返回", str(value or "").strip()))


def _looks_like_prepare_command(value: str) -> bool:
    return bool(re.search(r"\b(New-Item|mkdir)\b", str(value or ""), flags=re.IGNORECASE))


def _looks_like_verification_command(value: str) -> bool:
    return bool(re.search(r"\b(npm\s+test|pnpm\s+test|yarn\s+test|vitest|pytest|ruff|mypy|tsc|eslint)\b", str(value or ""), flags=re.IGNORECASE))


def _looks_internal(text: str) -> bool:
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    if any(token in lowered for token in INTERNAL_EVENT_TOKENS):
        return True
    return lowered.startswith(("rtevt:", "taskrun:", "turnrun:", "toolobs:", "toolinv:", "rtpacket:", "harness.", "runtime.", "backend.", "agent_system.", "task_system."))


def _is_tool_token(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text in TOOL_NAME_TOKENS or text in {"tool", "工具"}


def _json_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
