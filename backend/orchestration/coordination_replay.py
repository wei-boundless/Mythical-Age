from __future__ import annotations

import time
from pathlib import Path
from typing import Any

def _sanitize_replayed_writing_stage_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean stale chapter revision fields before replaying a persisted stage request."""
    if str(payload.get("stage_id") or payload.get("node_id") or "").strip() != "chapter_draft":
        return payload
    explicit_inputs = dict(payload.get("explicit_inputs") or {})
    if explicit_inputs.get("revision_required") is not True and "chapter_revision_requirements" not in explicit_inputs:
        return payload

    sanitized_inputs = _sanitize_writing_chapter_revision_inputs(explicit_inputs)
    sanitized = dict(payload)
    sanitized["explicit_inputs"] = sanitized_inputs
    sanitized["request_id"] = ""
    sanitized["idempotency_key"] = ""
    sanitized["a2a_payload"] = _replace_nested_explicit_inputs(
        dict(sanitized.get("a2a_payload") or {}),
        sanitized_inputs,
    )
    sanitized["runtime_assembly"] = _replace_nested_explicit_inputs(
        dict(sanitized.get("runtime_assembly") or {}),
        sanitized_inputs,
    )
    return sanitized


def _sanitize_writing_chapter_revision_inputs(explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    inputs = dict(explicit_inputs)
    artifact_root = Path(str(inputs.get("artifact_root") or ""))
    batch_dir_name = _writing_batch_dir_name(inputs)

    latest_review_ref = _latest_artifact_ref(
        artifact_root / "reviews" / "chapters" / batch_dir_name,
        "review_round_*.md",
    )
    latest_draft_ref = _latest_artifact_ref(
        artifact_root / "chapters" / batch_dir_name,
        "draft_round_*.md",
    )
    if latest_review_ref:
        inputs["previous_chapter_review_ref"] = latest_review_ref
    if latest_draft_ref:
        inputs["previous_chapter_draft_ref"] = latest_draft_ref

    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    chapters_per_round = _safe_int(inputs.get("chapters_per_round") or inputs.get("chapter_batch_size"), 10)
    chapter_target_words = _safe_int(inputs.get("chapter_target_words"), 2000)
    batch_chapter_numbers = list(range(batch_start, batch_end + 1))
    inputs["batch_chapter_numbers"] = batch_chapter_numbers
    inputs["batch_chapter_list"] = "、".join(f"第{i}章" for i in batch_chapter_numbers)
    review_hint = ""
    review_text = _read_artifact_text(latest_review_ref)
    if review_text:
        review_hint = "\n最新审核意见摘要：\n" + _compact_review_text(review_text, max_chars=6000)
    inputs["chapter_revision_requirements"] = (
        f"第{batch_start}章至第{batch_end}章上一轮审核未通过。"
        f"本轮必须严格依据最新审核意见重写完整批次，共{chapters_per_round}章；"
        f"每章约{chapter_target_words}字，只输出完整正文，不要输出摘要、提纲、解释、拒绝、等待补充或工作说明。"
        f"{review_hint}"
    )
    inputs["revision_required"] = True
    inputs["force_replay"] = True
    inputs["force_replay_after"] = time.time()
    for key in list(inputs):
        if str(key).endswith(":artifact_refs") and "chapter_draft" in str(key):
            inputs.pop(key, None)
    inputs.pop("previous_quality_failure_stage_id", None)
    return inputs


def _replace_nested_explicit_inputs(value: Any, explicit_inputs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        replaced: dict[str, Any] = {}
        for key, child in value.items():
            if key == "explicit_inputs" and isinstance(child, dict):
                replaced[key] = dict(explicit_inputs)
            else:
                replaced[key] = _replace_nested_explicit_inputs(child, explicit_inputs)
        return replaced
    if isinstance(value, list):
        return [_replace_nested_explicit_inputs(item, explicit_inputs) for item in value]
    return value


def _writing_batch_dir_name(inputs: dict[str, Any]) -> str:
    batch_index = _safe_int(inputs.get("batch_index"), 1)
    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    return f"batch_{batch_index:03d}_chapters_{batch_start:03d}_{batch_end:03d}"


def _latest_artifact_ref(directory: Path, pattern: str) -> str:
    if not directory.exists() or not directory.is_dir():
        return ""
    files = [path for path in directory.glob(pattern) if path.is_file()]
    if not files:
        return ""
    latest = max(files, key=lambda path: path.stat().st_mtime)
    return f"artifact:{latest.as_posix()}"


def _read_artifact_text(artifact_ref: str, *, max_chars: int = 8000) -> str:
    path_text = str(artifact_ref or "")
    if path_text.startswith("artifact:"):
        path_text = path_text[len("artifact:") :]
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _compact_review_text(text: str, *, max_chars: int = 3000) -> str:
    raw = str(text or "").strip()
    sections = _extract_named_review_sections(
        raw,
        section_names=(
            "裁决",
            "裁决理由",
            "阻塞问题",
            "非阻塞问题",
            "下一轮修改要求",
            "canon一致性检查",
            "承接与推进检查",
            "商业阅读体验检查",
            "爽点与章末追读检查",
        ),
    )
    if sections:
        compact = "\n\n".join(sections)
    else:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        important = [
            line
            for line in lines
            if any(
                marker in line
                for marker in (
                    "阻塞",
                    "修改",
                    "问题",
                    "必须",
                    "裁决",
                    "verdict",
                    "revise",
                    "未通过",
                    "断裂",
                    "失衡",
                    "过于简单",
                    "不允许",
                )
            )
        ]
        compact = "\n".join(important or lines)
    return compact[:max_chars]


def _extract_named_review_sections(text: str, *, section_names: tuple[str, ...]) -> list[str]:
    sections: list[tuple[str, list[str]]] = []
    current_name = ""
    current_lines: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        matched_name = ""
        for name in section_names:
            if stripped.startswith(f"【{name}】"):
                matched_name = name
                break
        if matched_name:
            if current_name and current_lines:
                sections.append((current_name, current_lines))
            current_name = matched_name
            current_lines = [stripped]
            continue
        if current_name:
            if stripped.startswith("【") and stripped.endswith("】"):
                if current_lines:
                    sections.append((current_name, current_lines))
                current_name = ""
                current_lines = []
            else:
                current_lines.append(line)
    if current_name and current_lines:
        sections.append((current_name, current_lines))
    wanted = set(section_names)
    return ["\n".join(lines).strip() for name, lines in sections if name in wanted and "\n".join(lines).strip()]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

