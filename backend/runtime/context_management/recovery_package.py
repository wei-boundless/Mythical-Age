from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any


CONTEXT_RECOVERY_PACKAGE_SCHEMA_VERSION = "runtime-context-recovery-package.v1"


CONTEXT_RECOVERY_LIST_FIELDS: tuple[str, ...] = (
    "key_user_constraints",
    "progress_so_far",
    "important_findings",
    "key_decisions",
    "files_artifacts_refs",
    "errors_and_corrections",
    "environment_state",
    "dirty_worktree",
    "validation_state",
    "open_questions",
    "next_steps",
    "do_not_touch",
)


CONTEXT_RECOVERY_MARKDOWN_SECTIONS: tuple[tuple[str, str], ...] = (
    ("current_task", "当前任务"),
    ("key_user_constraints", "关键用户约束"),
    ("progress_so_far", "进展"),
    ("important_findings", "重要发现"),
    ("key_decisions", "关键决策"),
    ("files_artifacts_refs", "文件与产物引用"),
    ("errors_and_corrections", "错误与纠正"),
    ("environment_state", "环境状态"),
    ("dirty_worktree", "工作区状态"),
    ("validation_state", "验证状态"),
    ("open_questions", "未解决问题"),
    ("next_steps", "下一步"),
    ("do_not_touch", "不要触碰"),
)


SESSION_SECTION_MAP: dict[str, str] = {
    "# Active Goal": "current_task",
    "# Key User Requests": "key_user_constraints",
    "# Conventions and Constraints": "key_user_constraints",
    "# Flow State": "progress_so_far",
    "# Context Slots": "progress_so_far",
    "# Current Task State": "progress_so_far",
    "# Warm Context": "progress_so_far",
    "# Worklog": "progress_so_far",
    "# Decisions and Learnings": "key_decisions",
    "# Key Results": "important_findings",
    "# Historical Results": "important_findings",
    "# Files and Functions": "files_artifacts_refs",
    "# Errors and Corrections": "errors_and_corrections",
    "# Risk Watch": "validation_state",
    "# Next Step": "next_steps",
}


STRUCTURED_SUMMARY_TO_CONTEXT_RECOVERY: dict[str, str] = {
    "current_goal": "current_task",
    "active_constraints": "key_user_constraints",
    "verified_facts": "important_findings",
    "decisions": "key_decisions",
    "artifacts": "files_artifacts_refs",
    "invalidated_items": "errors_and_corrections",
    "open_questions": "open_questions",
    "next_actions": "next_steps",
    "recovery_notes": "progress_so_far",
}


@dataclass(slots=True)
class ContextRecoveryCoverage:
    covered_message_count: int = 0
    covered_message_ids: list[str] = field(default_factory=list)
    covered_event_run_id: str = ""
    covered_event_offset_start: int | None = None
    covered_event_offset_end: int | None = None
    summary_hash: str = ""
    source_summary_hash: str = ""
    created_at: float = 0.0
    stale_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered_message_count": max(0, int(self.covered_message_count or 0)),
            "covered_message_ids": [str(item) for item in list(self.covered_message_ids or []) if str(item)],
            "covered_event_run_id": str(self.covered_event_run_id or ""),
            "covered_event_offset_start": self.covered_event_offset_start,
            "covered_event_offset_end": self.covered_event_offset_end,
            "summary_hash": str(self.summary_hash or ""),
            "source_summary_hash": str(self.source_summary_hash or ""),
            "created_at": float(self.created_at or 0.0),
            "stale_reason": str(self.stale_reason or ""),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContextRecoveryCoverage":
        data = dict(payload or {})
        return cls(
            covered_message_count=_safe_int(data.get("covered_message_count")),
            covered_message_ids=_text_list(data.get("covered_message_ids")),
            covered_event_run_id=_text(data.get("covered_event_run_id")),
            covered_event_offset_start=_optional_int(data.get("covered_event_offset_start")),
            covered_event_offset_end=_optional_int(data.get("covered_event_offset_end")),
            summary_hash=_text(data.get("summary_hash")),
            source_summary_hash=_text(data.get("source_summary_hash")),
            created_at=_safe_float(data.get("created_at")),
            stale_reason=_text(data.get("stale_reason")),
        )


@dataclass(slots=True)
class ContextRecoveryFreshness:
    status: str = "unknown"
    stale_reason: str = ""
    checked_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status or "unknown"),
            "stale_reason": str(self.stale_reason or ""),
            "checked_at": float(self.checked_at or 0.0),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContextRecoveryFreshness":
        data = dict(payload or {})
        return cls(
            status=_text(data.get("status")) or "unknown",
            stale_reason=_text(data.get("stale_reason")),
            checked_at=_safe_float(data.get("checked_at")),
        )


@dataclass(slots=True)
class ContextRecoveryPackage:
    current_task: str = ""
    key_user_constraints: list[str] = field(default_factory=list)
    progress_so_far: list[str] = field(default_factory=list)
    important_findings: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    files_artifacts_refs: list[str] = field(default_factory=list)
    errors_and_corrections: list[str] = field(default_factory=list)
    environment_state: list[str] = field(default_factory=list)
    dirty_worktree: list[str] = field(default_factory=list)
    validation_state: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    do_not_touch: list[str] = field(default_factory=list)
    coverage: ContextRecoveryCoverage = field(default_factory=ContextRecoveryCoverage)
    freshness: ContextRecoveryFreshness = field(default_factory=ContextRecoveryFreshness)
    source: str = ""
    schema_version: str = CONTEXT_RECOVERY_PACKAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version or CONTEXT_RECOVERY_PACKAGE_SCHEMA_VERSION,
            "current_task": _text(self.current_task),
            "coverage": self.coverage.to_dict(),
            "freshness": self.freshness.to_dict(),
            "source": _text(self.source),
            "authority": "runtime.context_management.context_recovery_package",
        }
        for field_name in CONTEXT_RECOVERY_LIST_FIELDS:
            payload[field_name] = _text_list(getattr(self, field_name))
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContextRecoveryPackage":
        data = dict(payload or {})
        kwargs: dict[str, Any] = {
            "schema_version": _text(data.get("schema_version")) or CONTEXT_RECOVERY_PACKAGE_SCHEMA_VERSION,
            "current_task": _text(data.get("current_task")),
            "coverage": ContextRecoveryCoverage.from_dict(data.get("coverage") if isinstance(data.get("coverage"), dict) else {}),
            "freshness": ContextRecoveryFreshness.from_dict(data.get("freshness") if isinstance(data.get("freshness"), dict) else {}),
            "source": _text(data.get("source")),
        }
        for field_name in CONTEXT_RECOVERY_LIST_FIELDS:
            kwargs[field_name] = _text_list(data.get(field_name))
        return cls(**kwargs)

    def is_material(self) -> bool:
        if _text(self.current_task):
            return True
        return any(_text_list(getattr(self, field_name)) for field_name in CONTEXT_RECOVERY_LIST_FIELDS)


def context_recovery_package_from_session_memory(
    content: str,
    *,
    compaction_state: dict[str, Any] | None = None,
    source: str = "session_memory",
) -> ContextRecoveryPackage:
    sections = _parse_markdown_sections(content)
    values: dict[str, Any] = {field_name: [] for field_name in CONTEXT_RECOVERY_LIST_FIELDS}
    current_task = ""
    for section, target in SESSION_SECTION_MAP.items():
        items = _text_list(sections.get(section))
        if not items:
            continue
        if target == "current_task" and not current_task:
            current_task = items[0]
            continue
        values[target] = _dedupe([*list(values.get(target) or []), *items])
    do_not_touch = _do_not_touch_candidates(
        [
            *list(values.get("key_user_constraints") or []),
            *list(values.get("errors_and_corrections") or []),
        ]
    )
    values["do_not_touch"] = _dedupe([*list(values.get("do_not_touch") or []), *do_not_touch])
    coverage = _coverage_from_compaction_state(compaction_state, source_summary=content)
    freshness = ContextRecoveryFreshness(
        status="fresh" if coverage.covered_message_count > 0 and not coverage.stale_reason else "unknown",
        stale_reason=coverage.stale_reason,
        checked_at=time.time(),
    )
    summary = ContextRecoveryPackage(
        current_task=current_task,
        coverage=coverage,
        freshness=freshness,
        source=source,
        **values,
    )
    summary.coverage.summary_hash = stable_json_hash(_summary_to_dict_without_hash(summary))
    return summary


def context_recovery_package_from_structured_summary(
    structured_summary: dict[str, Any],
    *,
    fallback_summary: str = "",
    source: str = "semantic_compactor",
) -> ContextRecoveryPackage:
    normalized = dict(structured_summary or {})
    values: dict[str, Any] = {field_name: [] for field_name in CONTEXT_RECOVERY_LIST_FIELDS}
    current_task = _text(normalized.get("current_task"))
    if not current_task:
        current_task = _first_text(normalized.get("current_goal"))
    for key, target in STRUCTURED_SUMMARY_TO_CONTEXT_RECOVERY.items():
        items = _text_list(normalized.get(key))
        if not items:
            continue
        if target == "current_task":
            if not current_task:
                current_task = items[0]
            continue
        values[target] = _dedupe([*list(values.get(target) or []), *items])
    for field_name in CONTEXT_RECOVERY_LIST_FIELDS:
        values[field_name] = _dedupe([*list(values.get(field_name) or []), *_text_list(normalized.get(field_name))])
    if fallback_summary and not any(values.values()):
        values["progress_so_far"] = [_text(fallback_summary)]
    summary = ContextRecoveryPackage(
        current_task=current_task,
        coverage=ContextRecoveryCoverage(created_at=time.time()),
        freshness=ContextRecoveryFreshness(status="fresh", checked_at=time.time()),
        source=source,
        **values,
    )
    summary.coverage.summary_hash = stable_json_hash(_summary_to_dict_without_hash(summary))
    return summary


def render_context_recovery_markdown(summary: ContextRecoveryPackage | dict[str, Any], *, include_metadata: bool = True) -> str:
    package = summary if isinstance(summary, ContextRecoveryPackage) else ContextRecoveryPackage.from_dict(summary)
    if not package.is_material():
        return ""
    lines: list[str] = ["# Context Recovery Package", ""]
    for key, title in CONTEXT_RECOVERY_MARKDOWN_SECTIONS:
        value = getattr(package, key)
        items = [_text(value)] if isinstance(value, str) and _text(value) else _text_list(value)
        if not items:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    if include_metadata:
        coverage = package.coverage.to_dict()
        metadata_lines = [
            f"source: {package.source}" if package.source else "",
            f"covered_message_count: {coverage.get('covered_message_count', 0)}",
            f"covered_event_run_id: {coverage.get('covered_event_run_id')}" if coverage.get("covered_event_run_id") else "",
            f"covered_event_offset_end: {coverage.get('covered_event_offset_end')}" if coverage.get("covered_event_offset_end") is not None else "",
            f"freshness: {package.freshness.status}",
            f"stale_reason: {package.freshness.stale_reason}" if package.freshness.stale_reason else "",
        ]
        metadata_lines = [line for line in metadata_lines if line]
        if metadata_lines:
            lines.append("## 覆盖元数据")
            lines.extend(f"- {line}" for line in metadata_lines)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(_stable_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _summary_to_dict_without_hash(summary: ContextRecoveryPackage) -> dict[str, Any]:
    payload = summary.to_dict()
    coverage = dict(payload.get("coverage") or {})
    coverage["summary_hash"] = ""
    payload["coverage"] = coverage
    return payload


def _parse_markdown_sections(content: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_header = ""
    current_lines: list[str] = []
    for line in str(content or "").splitlines():
        if line.startswith("# "):
            if current_header:
                sections[current_header] = _text_list(current_lines)
            current_header = line.strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_header:
        sections[current_header] = _text_list(current_lines)
    return sections


def _coverage_from_compaction_state(compaction_state: dict[str, Any] | None, *, source_summary: str) -> ContextRecoveryCoverage:
    state = dict(compaction_state or {})
    return ContextRecoveryCoverage(
        covered_message_count=_safe_int(state.get("covered_message_count")),
        covered_message_ids=_text_list(state.get("covered_message_ids")),
        covered_event_run_id=_text(state.get("covered_event_run_id") or state.get("run_id")),
        covered_event_offset_start=_optional_int(state.get("covered_event_offset_start")),
        covered_event_offset_end=_optional_int(state.get("covered_event_offset_end")),
        source_summary_hash=(
            _text(state.get("summary_sha256"))
            or hashlib.sha256(str(source_summary or "").encode("utf-8", errors="ignore")).hexdigest()
        ),
        created_at=time.time(),
        stale_reason=_text(state.get("stale_reason") or ""),
    )


def _do_not_touch_candidates(items: list[str]) -> list[str]:
    result: list[str] = []
    markers = ("不要", "不能", "禁止", "严禁", "do not", "must not", "不要触碰", "不要修改")
    for item in items:
        lower = item.lower()
        if any(marker in item or marker in lower for marker in markers):
            result.append(item)
    return _dedupe(result)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = _text(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _text_list(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [
            item
            for item in (
                _text(line.strip(" -\t"))
                for line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines()
            )
            if item
        ]
    if isinstance(value, dict):
        preferred = value.get("content") or value.get("text") or value.get("summary") or value.get("title") or value.get("path") or value.get("ref")
        if preferred:
            return [_text(preferred)] if _text(preferred) else []
        return [_text(json.dumps(_stable_json(value), ensure_ascii=False, sort_keys=True))]
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_text_list(item))
        return _dedupe(result)
    text = _text(value)
    return [text] if text else []


def _first_text(value: Any) -> str:
    items = _text_list(value)
    return items[0] if items else ""


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r\n", "\n").replace("\r", "\n").split())


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _stable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _stable_json(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_stable_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
