from __future__ import annotations

from .text_utils import normalize_storage_text

SYNTHETIC_WRITE_MARKERS = (
    "已写入长期记忆",
    "写入长期记忆",
    "已存在长期记忆中",
    "正在写入记忆文件",
    "saved to durable memory",
    "stored in durable memory",
    "write to durable memory",
)

ASSISTANT_ACK_MARKERS = (
    "收到，岩",
    "已记住",
    "这条偏好已在长期记忆中有记录",
    "这条项目主线已在长期记忆中记录",
    "后续相关讨论和决策我会围绕",
    "我会持续遵循",
    "结论：** 已记住",
    "结论： 已记住",
    "conclusion:** remembered",
    "i've remembered",
    "i will keep following",
)

INSTRUCTION_PREFIXES = (
    "记住：",
    "记住:",
    "记住",
    "请记住：",
    "请记住:",
    "请记住",
    "remember that ",
    "remember ",
    "please remember that ",
    "please remember ",
)


def normalize_runtime_text(*parts: str) -> str:
    combined = " ".join(normalize_storage_text(part) for part in parts if normalize_storage_text(part))
    return normalize_storage_text(combined).lower()


def looks_like_synthetic_memory_text(*parts: str) -> bool:
    normalized = normalize_runtime_text(*parts)
    if not normalized:
        return False
    return any(marker in normalized for marker in SYNTHETIC_WRITE_MARKERS)


def looks_like_assistant_ack_text(*parts: str) -> bool:
    normalized = normalize_runtime_text(*parts)
    if not normalized:
        return False
    return any(marker in normalized for marker in ASSISTANT_ACK_MARKERS)


def normalize_durable_fact_text(text: str) -> str:
    cleaned = normalize_storage_text(text).strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for prefix in INSTRUCTION_PREFIXES:
        normalized_prefix = normalize_storage_text(prefix).strip()
        if not normalized_prefix:
            continue
        prefix_lower = normalized_prefix.lower()
        if lowered.startswith(prefix_lower):
            cleaned = cleaned[len(normalized_prefix) :].strip()
            break
    cleaned = cleaned.lstrip("：:,- ").strip()
    return cleaned


def is_runtime_noise_note(
    *,
    source_role: str,
    created_by: str,
    title: str,
    summary: str,
    canonical_statement: str,
    source_message_excerpt: str,
) -> bool:
    if looks_like_synthetic_memory_text(title, summary, canonical_statement):
        return True

    normalized_role = normalize_storage_text(source_role).lower()
    if normalized_role != "assistant":
        return False

    if looks_like_synthetic_memory_text(source_message_excerpt):
        return True

    if normalize_storage_text(created_by).lower() in {"session_state_extractor", "memory_extractor"}:
        return True

    return looks_like_assistant_ack_text(title, summary, canonical_statement, source_message_excerpt)


