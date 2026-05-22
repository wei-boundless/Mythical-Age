from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def sanitize_replayed_stage_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean stale revision fields before replaying a persisted stage request.

    The replay policy is contract driven: task-specific behavior belongs in the
    request's explicit inputs, not in orchestration hardcoded node names.
    """

    explicit_inputs = dict(payload.get("explicit_inputs") or {})
    replay_policy = _replay_sanitization_policy(payload=payload, explicit_inputs=explicit_inputs)
    if not replay_policy:
        return payload
    trigger_keys = [str(item).strip() for item in list(replay_policy.get("trigger_input_keys") or ["revision_required"]) if str(item).strip()]
    if trigger_keys and not any(explicit_inputs.get(key) in {True, "true", "1"} or key in explicit_inputs for key in trigger_keys):
        return payload

    sanitized_inputs = _sanitize_revision_inputs(explicit_inputs, replay_policy=replay_policy)
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


def _replay_sanitization_policy(*, payload: dict[str, Any], explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    for source in (
        explicit_inputs.get("replay_sanitization_policy"),
        dict(payload.get("runtime_assembly") or {}).get("replay_sanitization_policy"),
        dict(dict(payload.get("runtime_assembly") or {}).get("metadata") or {}).get("replay_sanitization_policy"),
    ):
        if isinstance(source, dict) and source:
            return dict(source)
    return {}


def _sanitize_revision_inputs(explicit_inputs: dict[str, Any], *, replay_policy: dict[str, Any]) -> dict[str, Any]:
    inputs = dict(explicit_inputs)
    artifact_root = Path(str(inputs.get("artifact_root") or ""))
    batch_dir_name = _batch_dir_name(inputs, replay_policy=replay_policy)

    artifact_sources = [dict(item) for item in list(replay_policy.get("latest_artifact_sources") or []) if isinstance(item, dict)]
    for source in artifact_sources:
        input_key = str(source.get("input_key") or "").strip()
        directory_template = str(source.get("directory_template") or "").strip()
        pattern = str(source.get("pattern") or "").strip()
        if not input_key or not directory_template or not pattern:
            continue
        latest_ref = _latest_artifact_ref(
            artifact_root / _render_template(directory_template, {**inputs, "batch_dir_name": batch_dir_name}),
            pattern,
        )
        if latest_ref:
            inputs[input_key] = latest_ref

    review_ref_key = str(replay_policy.get("review_ref_key") or "previous_review_ref").strip()
    review_hint = ""
    review_text = _read_artifact_text(str(inputs.get(review_ref_key) or ""))
    if review_text:
        review_hint = "\n最新审核意见摘要：\n" + _compact_review_text(
            review_text,
            max_chars=_safe_int(replay_policy.get("review_hint_max_chars"), 6000),
            section_names=tuple(str(item) for item in list(replay_policy.get("review_section_names") or ()) if str(item)),
        )

    start = _safe_int(inputs.get(str(replay_policy.get("unit_start_key") or "batch_start_index")), 1)
    end = _safe_int(inputs.get(str(replay_policy.get("unit_end_key") or "batch_end_index")), start)
    count = _safe_int(inputs.get(str(replay_policy.get("unit_count_key") or "unit_batch_size")), max(end - start + 1, 1))
    unit_target = _safe_int(inputs.get(str(replay_policy.get("unit_target_metric_key") or "unit_target_metric")), 0)
    unit_label = str(replay_policy.get("unit_label") or "单元").strip()
    unit_prefix = str(replay_policy.get("unit_label_prefix") or "").strip()
    unit_suffix = str(replay_policy.get("unit_label_suffix") or unit_label).strip()
    unit_numbers = list(range(start, end + 1))
    list_key = str(replay_policy.get("unit_list_key") or "").strip()
    if list_key:
        inputs[list_key] = "、".join(f"{unit_prefix}{index}{unit_suffix}" for index in unit_numbers)

    requirements_key = str(replay_policy.get("requirements_key") or "revision_requirements").strip()
    template = str(
        replay_policy.get("requirements_template")
        or "{unit_prefix}{start}{unit_suffix}至{unit_prefix}{end}{unit_suffix}上一轮审核未通过。"
        "本轮必须严格依据最新审核意见重写完整批次，共{count}{unit_label}；"
        "每个单元目标工作量约{unit_target}，只输出完整产物，不要输出摘要、提纲、解释、拒绝、等待补充或工作说明。"
        "{review_hint}"
    )
    inputs[requirements_key] = _render_template(
        template,
        {
            **inputs,
            "start": start,
            "end": end,
            "count": count,
            "unit_target": unit_target,
            "unit_label": unit_label,
            "unit_prefix": unit_prefix,
            "unit_suffix": unit_suffix,
            "review_hint": review_hint,
        },
    )
    inputs["revision_required"] = True
    inputs["force_replay"] = True
    inputs["force_replay_after"] = time.time()

    for pattern in list(replay_policy.get("clear_input_key_contains") or []):
        token = str(pattern or "")
        if not token:
            continue
        for key in list(inputs):
            if token in str(key):
                inputs.pop(key, None)
    for key in list(replay_policy.get("clear_input_keys") or ["previous_quality_failure_stage_id"]):
        inputs.pop(str(key), None)
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


def _batch_dir_name(inputs: dict[str, Any], *, replay_policy: dict[str, Any]) -> str:
    template = str(replay_policy.get("batch_dir_template") or "").strip()
    if template:
        return _render_template(template, inputs)
    batch_index = _safe_int(inputs.get("batch_index"), 1)
    batch_start = _safe_int(inputs.get("batch_start_index"), 1)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    return f"batch_{batch_index:03d}_{batch_start:03d}_{batch_end:03d}"


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


def _compact_review_text(
    text: str,
    *,
    max_chars: int = 3000,
    section_names: tuple[str, ...] = (),
) -> str:
    raw = str(text or "").strip()
    sections = _extract_named_review_sections(raw, section_names=section_names)
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
    if not section_names:
        return []
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


def _render_template(template: str, values: dict[str, Any]) -> str:
    try:
        return str(template or "").format_map(_SafeFormatValues(values))
    except (KeyError, ValueError, IndexError):
        rendered = str(template or "")
        for key, value in dict(values or {}).items():
            rendered = rendered.replace("{" + str(key) + "}", str(value))
        return rendered


class _SafeFormatValues(dict):
    def __init__(self, values: dict[str, Any]) -> None:
        super().__init__({str(key): value for key, value in dict(values or {}).items()})

    def __missing__(self, key: str) -> str:
        return "{" + str(key) + "}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
