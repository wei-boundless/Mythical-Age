from __future__ import annotations

from typing import Any


def merge_task_spec_binding_into_delegation_payload(
    payload: dict[str, Any],
    *,
    task_spec_payload: dict[str, Any] | None,
    current_turn_context: dict[str, Any] | None = None,
    user_message: str,
) -> dict[str, Any]:
    merged = dict(payload or {})
    inputs = dict(dict(task_spec_payload or {}).get("inputs") or {})
    tool_input = dict(inputs.get("tool_input") or {})
    if user_message:
        merged.setdefault("query", clean_text(user_message))
    for key in ("query", "mode", "extract_mode", "section", "page", "pages", "max_chunks"):
        value = tool_input.get(key)
        if value not in ("", [], {}, None):
            merged.setdefault(key, value)

    explicit_dataset = clean_text(
        inputs.get("explicit_dataset_path")
        or tool_input.get("active_dataset")
        or tool_input.get("path")
        or tool_input.get("file_path")
        or _path_from_context_recall(current_turn_context, source_kind="dataset", binding_key="active_dataset")
    )
    explicit_pdf = clean_text(
        inputs.get("explicit_pdf_path")
        or tool_input.get("active_pdf")
        or tool_input.get("path")
        or tool_input.get("file_path")
        or _path_from_context_recall(current_turn_context, source_kind="pdf", binding_key="active_pdf")
    )
    source_kind = _task_spec_source_kind(task_spec_payload or {})
    if source_kind == "dataset" and explicit_dataset:
        _set_file_binding_defaults(merged, active_key="active_dataset", path=explicit_dataset)
    elif source_kind == "pdf" and explicit_pdf:
        _set_file_binding_defaults(merged, active_key="active_pdf", path=explicit_pdf)
    elif explicit_dataset and not explicit_pdf:
        _set_file_binding_defaults(merged, active_key="active_dataset", path=explicit_dataset)
    elif explicit_pdf:
        _set_file_binding_defaults(merged, active_key="active_pdf", path=explicit_pdf)
    return merged


def classify_delegation_goal_alignment(
    *,
    user_message: str,
    instruction: str,
    input_payload: dict[str, Any],
) -> str:
    user_text = clean_text(user_message)
    instruction_text = clean_text(instruction)
    path = clean_text(
        input_payload.get("file_path")
        or input_payload.get("path")
        or input_payload.get("active_pdf")
        or input_payload.get("active_dataset")
    )
    if not user_text or not instruction_text:
        return "unknown"

    user_lower = user_text.lower()
    instruction_lower = instruction_text.lower()
    if path:
        normalized_path = path.replace("\\", "/").lower()
        if normalized_path and normalized_path in user_lower:
            return "aligned"
        file_name = normalized_path.split("/")[-1]
        if file_name and file_name in user_lower:
            return "aligned"

    user_tokens = set(_alignment_tokens(user_text))
    instruction_tokens = set(_alignment_tokens(instruction_text))
    if not user_tokens or not instruction_tokens:
        return "unknown"
    if len(user_tokens & instruction_tokens) >= 2:
        return "aligned"

    strong_user = any(token in user_lower for token in ("pdf", ".pdf", "第3页", "第三页", "第4页", "第四页", "第二部分", "章节"))
    strong_instruction = any(
        token in instruction_lower for token in ("pdf", ".pdf", "页", "第二部分", "章节", "全文", "目录页", "正文页")
    )
    if strong_user and strong_instruction:
        return "aligned"
    if strong_user != strong_instruction and not user_tokens & instruction_tokens:
        return "offtopic"
    if any(token in user_lower for token in ("表格", "excel", ".xlsx", ".csv")) and not any(
        token in instruction_lower for token in ("表格", "excel", ".xlsx", ".csv", "数据表", "数据集")
    ):
        return "offtopic"
    if any(token in user_lower for token in ("黄金", "金价", "xau", "天气")) and not any(
        token in instruction_lower for token in ("黄金", "金价", "xau", "天气")
    ):
        return "offtopic"
    return "unknown"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def _set_file_binding_defaults(payload: dict[str, Any], *, active_key: str, path: str) -> None:
    payload.setdefault(active_key, path)
    payload.setdefault("path", path)
    payload.setdefault("file_path", path)


def _task_spec_source_kind(task_spec_payload: dict[str, Any]) -> str:
    recipe_id = clean_text(task_spec_payload.get("recipe_id"))
    if "structured_data" in recipe_id:
        return "dataset"
    if "pdf" in recipe_id:
        return "pdf"
    bindings = dict(task_spec_payload.get("bindings") or {})
    for item in list(bindings.get("resolved_bindings") or []):
        if not isinstance(item, dict):
            continue
        file_kind = clean_text(item.get("file_kind"))
        if file_kind == "dataset":
            return "dataset"
        if file_kind == "pdf":
            return "pdf"
    return ""


def _path_from_context_recall(
    current_turn_context: dict[str, Any] | None,
    *,
    source_kind: str,
    binding_key: str,
) -> str:
    target_source = clean_text(source_kind)
    target_binding = clean_text(binding_key)
    for candidate in list(dict(current_turn_context or {}).get("context_recall_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if clean_text(candidate.get("source_kind")) != target_source:
            continue
        payload = dict(candidate.get("recall_payload") or {})
        constraints = dict(payload.get("active_constraints") or {})
        for key in (target_binding, "path", "file_path"):
            value = clean_text(payload.get(key) or constraints.get(key))
            if value:
                return value
    return ""


def _alignment_tokens(value: str) -> list[str]:
    import re

    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9_.:/\\-]{2,}|[\u4e00-\u9fff]{2,8}", str(value or "")):
        token = match.group(0).strip().lower()
        if not token or token in {"当前", "继续", "直接", "告诉我", "给我", "分析", "文件", "内容", "结果"}:
            continue
        tokens.append(token)
    return tokens
