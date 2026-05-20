from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True, slots=True)
class MaterializedTaskArtifacts:
    enabled: bool
    artifact_root: str = ""
    artifact_refs: tuple[str, ...] = ()
    created_files: tuple[str, ...] = ()
    skipped_files: tuple[str, ...] = ()
    diagnostics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "artifact_root": self.artifact_root,
            "artifact_refs": list(self.artifact_refs),
            "created_files": list(self.created_files),
            "skipped_files": list(self.skipped_files),
            "diagnostics": dict(self.diagnostics or {}),
        }


def materialize_task_artifacts(
    *,
    workspace_root: Path,
    task_run_id: str,
    session_id: str,
    task_ref: str,
    coordination_run_id: str,
    final_content: str,
    user_message: str,
    explicit_inputs: dict[str, Any],
    task_policy: dict[str, Any],
    task_status: str = "",
    terminal_reason: str = "",
    task_diagnostics: dict[str, Any] | None = None,
    acceptance_status: str = "",
    stage_id: str = "",
    request_id: str = "",
) -> MaterializedTaskArtifacts:
    artifact_policy = dict(task_policy.get("artifact_policy") or {})
    if not artifact_policy.get("enabled"):
        return MaterializedTaskArtifacts(enabled=False)

    root_value = str(
        explicit_inputs.get("artifact_root")
        or artifact_policy.get("artifact_root")
        or artifact_policy.get("default_artifact_root")
        or ""
    ).strip()
    if not root_value:
        return MaterializedTaskArtifacts(
            enabled=True,
            diagnostics={"status": "skipped", "reason": "artifact_policy root is empty"},
        )

    workspace = Path(workspace_root).resolve()
    subdir_template = str(artifact_policy.get("subdir_template") or "").strip()
    if subdir_template:
        root_value = _join_artifact_root(
            root_value,
            _render_subdir_template(
                subdir_template,
                task_run_id=task_run_id,
                session_id=session_id,
                task_ref=task_ref,
                explicit_inputs=explicit_inputs,
            ),
        )
    artifact_root = _resolve_artifact_root(workspace, root_value)
    rejected_output = str(acceptance_status or "").strip().lower() == "rejected"
    visible_artifact_root = artifact_root
    if rejected_output:
        artifact_root = _rejected_artifact_root(
            artifact_root,
            stage_id=stage_id or _safe_slug(task_ref or task_run_id),
            explicit_inputs=explicit_inputs,
            request_id=request_id or task_run_id,
        )
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "debug").mkdir(parents=True, exist_ok=True)

    sections = _split_markdown_sections(final_content)
    diagnostics_payload = dict(task_diagnostics or {})
    failed_empty_run = str(task_status or "").strip().lower() == "failed" and not str(final_content or "").strip()
    created: list[str] = []
    skipped: list[str] = []

    artifact_specs = _artifact_specs(artifact_policy)
    if _should_materialize_project_brief(task_ref=task_ref, artifact_specs=artifact_specs):
        project_brief = _project_brief_markdown(explicit_inputs=explicit_inputs, user_message=user_message)
        if project_brief.strip():
            target = _write_text_preserving_existing(artifact_root / "00_project_brief.md", project_brief)
            created.append(_relative_or_absolute(target, artifact_root))
        else:
            skipped.append("00_project_brief.md")

    for spec in artifact_specs:
        relative_path = _render_artifact_path(str(spec.get("path") or "").strip(), explicit_inputs)
        if not relative_path or relative_path == "00_project_brief.md":
            continue
        if _required_markers_missing(spec, final_content, sections):
            skipped.append(relative_path)
            continue
        content = _content_for_artifact_spec(spec, sections, final_content, explicit_inputs)
        if not content.strip():
            if spec.get("required") and not failed_empty_run:
                content = _required_missing_content(relative_path, final_content)
            else:
                skipped.append(relative_path)
                continue
        target = (artifact_root / relative_path).resolve()
        try:
            target.relative_to(artifact_root.resolve())
        except ValueError:
            skipped.append(relative_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target = _write_text_preserving_existing(target, content)
        created.append(_relative_or_absolute(target, artifact_root))

    report = _run_report(
        task_run_id=task_run_id,
        session_id=session_id,
        task_ref=task_ref,
        coordination_run_id=coordination_run_id,
        artifact_root=_relative_or_absolute(artifact_root, workspace),
        created_files=created,
        skipped_files=skipped,
        task_status=task_status,
        terminal_reason=terminal_reason,
        task_diagnostics=diagnostics_payload,
    )
    report_path = _write_text_preserving_existing(
        artifact_root / "debug" / f"run_report_{_safe_slug(task_ref or task_run_id)}.md",
        report,
    )
    report_relative_path = _relative_or_absolute(report_path, artifact_root)
    if report_relative_path not in created:
        created.append(report_relative_path)

    artifact_refs = tuple(f"artifact:{_relative_or_absolute(artifact_root / item, workspace)}" for item in created)
    return MaterializedTaskArtifacts(
        enabled=True,
        artifact_root=_relative_or_absolute(artifact_root, workspace),
        artifact_refs=artifact_refs,
        created_files=tuple(_created_files_public_view(created)),
        skipped_files=tuple(skipped),
        diagnostics={
            "status": "created",
            "created_count": len(created),
            "skipped_count": len(skipped),
            "task_status": task_status,
            "terminal_reason": terminal_reason,
            "acceptance_status": acceptance_status,
            "visible_artifact_root": _relative_or_absolute(visible_artifact_root, workspace),
            "source": "task_policy.artifact_policy",
        },
    )


def _created_files_public_view(created_files: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in created_files:
        value = str(item or "").replace("\\", "/").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
        leaf = Path(value).name if value else ""
        if leaf and leaf not in seen:
            seen.add(leaf)
            result.append(leaf)
    return result


def _artifact_specs(policy: dict[str, Any]) -> list[dict[str, Any]]:
    specs = [dict(item) for item in list(policy.get("artifacts") or []) if isinstance(item, dict)]
    if specs:
        return specs
    artifact_target = str(policy.get("artifact_target") or policy.get("output_path") or "").strip()
    if artifact_target:
        return [
            {
                "path": artifact_target,
                "required": bool(policy.get("required", True)),
                "content_source": "final_content",
                "fallback_to_full_content": True,
            }
        ]
    return []


def _should_materialize_project_brief(*, task_ref: str, artifact_specs: list[dict[str, Any]]) -> bool:
    normalized_task_ref = str(task_ref or "").strip().lower()
    if normalized_task_ref.endswith("project_brief"):
        return True
    for spec in artifact_specs:
        normalized_path = str(spec.get("path") or "").replace("\\", "/").strip().lower()
        if normalized_path in {"project_brief.md", "00_project_brief.md"}:
            return True
    return False


def _resolve_artifact_root(workspace: Path, value: str) -> Path:
    raw = Path(str(value).replace("\\", "/"))
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (workspace / str(value).replace("\\", "/").strip("/")).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"artifact_root must stay inside workspace: {value}") from exc
    return resolved


def _join_artifact_root(root_value: str, subdir: str) -> str:
    clean_root = str(root_value or "").replace("\\", "/").rstrip("/")
    clean_subdir = str(subdir or "").replace("\\", "/").strip("/")
    if not clean_subdir:
        return clean_root
    if clean_root == clean_subdir or clean_root.endswith(f"/{clean_subdir}"):
        return clean_root
    return f"{clean_root}/{clean_subdir}" if clean_root else clean_subdir


def _render_subdir_template(
    template: str,
    *,
    task_run_id: str,
    session_id: str,
    task_ref: str,
    explicit_inputs: dict[str, Any],
) -> str:
    title = str(explicit_inputs.get("title") or explicit_inputs.get("project_title") or "").strip()
    values = {
        "task_slug": _safe_slug(task_ref or "task"),
        "task_id": _safe_slug(task_ref or "task"),
        "run_slug": _safe_slug(task_run_id.split(":")[-1] or task_run_id or str(int(time.time()))),
        "task_run_id": _safe_slug(task_run_id),
        "session_id": _safe_slug(session_id),
        "title": _safe_slug(title or task_ref or "task"),
    }
    rendered = str(template or "")
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _render_artifact_path(path_template: str, explicit_inputs: dict[str, Any]) -> str:
    template = str(path_template or "").strip()
    if not template:
        return ""
    chapter_index = _safe_int(explicit_inputs.get("chapter_index"), 1)
    volume_index = _safe_int(explicit_inputs.get("volume_index"), 1)
    chapters_per_round = max(
        _safe_int(explicit_inputs.get("chapters_per_round") or explicit_inputs.get("chapter_batch_size"), 1),
        1,
    )
    batch_start_index = _safe_int(explicit_inputs.get("batch_start_index"), chapter_index)
    batch_end_index = _safe_int(explicit_inputs.get("batch_end_index"), batch_start_index + chapters_per_round - 1)
    batch_index = _safe_int(explicit_inputs.get("batch_index"), ((chapter_index - 1) // chapters_per_round) + 1)
    values = {
        "volume_index": volume_index,
        "volume_index_padded": f"{volume_index:03d}",
        "volume_label": str(explicit_inputs.get("volume_label") or f"第{volume_index}卷"),
        "volume_current_words": _safe_int(explicit_inputs.get("volume_current_words"), 0),
        "volume_target_words": _safe_int(explicit_inputs.get("volume_target_words"), 0),
        "chapters_per_volume": _safe_int(explicit_inputs.get("chapters_per_volume"), 0),
        "chapter_index": chapter_index,
        "chapter_index_padded": f"{chapter_index:03d}",
        "chapter_file_prefix": str(explicit_inputs.get("chapter_file_prefix") or f"chapter_{chapter_index:03d}"),
        "chapters_per_round": chapters_per_round,
        "chapter_batch_size": chapters_per_round,
        "batch_index": batch_index,
        "batch_index_padded": f"{batch_index:03d}",
        "batch_start_index": batch_start_index,
        "batch_start_index_padded": f"{batch_start_index:03d}",
        "batch_end_index": batch_end_index,
        "batch_end_index_padded": f"{batch_end_index:03d}",
        "batch_chapter_range": f"{batch_start_index:03d}-{batch_end_index:03d}",
        "round_index": _safe_int(
            explicit_inputs.get("round_index")
            or explicit_inputs.get("revision_round")
            or explicit_inputs.get("attempt_index"),
            1,
        ),
    }
    rendered = template
    for key, value in values.items():
        padded_value = f"{int(value):03d}" if isinstance(value, int) else str(value)
        rendered = rendered.replace("{" + key + ":03d}", padded_value)
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def _rejected_artifact_root(
    artifact_root: Path,
    *,
    stage_id: str,
    explicit_inputs: dict[str, Any],
    request_id: str,
) -> Path:
    batch_start = _safe_int(explicit_inputs.get("batch_start_index"), _safe_int(explicit_inputs.get("chapter_index"), 0))
    batch_end = _safe_int(explicit_inputs.get("batch_end_index"), batch_start)
    round_index = _safe_int(
        explicit_inputs.get("round_index")
        or explicit_inputs.get("revision_round")
        or explicit_inputs.get("attempt_index"),
        1,
    )
    batch_slug = (
        f"chapter_{batch_start:03d}_{batch_end:03d}_round_{round_index:03d}"
        if batch_start and batch_end
        else f"round_{round_index:03d}"
    )
    return artifact_root / "rejected" / _safe_slug(stage_id) / batch_slug / _safe_slug(request_id)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_slug(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "task"


def _split_markdown_sections(content: str) -> dict[str, str]:
    text = str(content or "").strip()
    if not text:
        return {}
    matches = list(re.finditer(r"^(#{1,4})\s+(.+?)\s*$", text, flags=re.MULTILINE))
    if not matches:
        return {"__all__": text}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(2).strip().strip("#").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections[title] = f"## {title}\n\n{body}".strip()
    sections["__all__"] = text
    return sections


def extract_markdown_section_content(
    content: str,
    section_keys: tuple[str, ...] | list[str],
    *,
    stop_section_keys: tuple[str, ...] | list[str] | None = None,
    include_heading: bool = True,
) -> str:
    text = str(content or "").strip()
    keys = tuple(str(item).strip() for item in list(section_keys or []) if str(item).strip())
    if not text or not keys:
        return ""
    boundaries = _markdown_section_boundaries(text)
    if not boundaries:
        return ""
    stop_keys = tuple(
        dict.fromkeys(
            [
                *[str(item).strip() for item in list(stop_section_keys or []) if str(item).strip()],
            ]
        )
    )
    chunks: list[str] = []
    for index, boundary in enumerate(boundaries):
        title = str(boundary.get("title") or "")
        if not any(_section_title_matches(title, key) for key in keys):
            continue
        end = len(text)
        for next_boundary in boundaries[index + 1 :]:
            next_title = str(next_boundary.get("title") or "")
            if any(_section_title_matches(next_title, stop_key) for stop_key in stop_keys):
                end = int(next_boundary.get("start") or end)
                break
        start = int(boundary.get("start") if include_heading else boundary.get("end") or 0)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    return "\n\n".join(chunks).strip()


def _markdown_section_boundaries(text: str) -> list[dict[str, Any]]:
    boundaries: list[dict[str, Any]] = []
    offset = 0
    for line in str(text or "").splitlines(keepends=True):
        stripped = line.strip()
        markdown_match = re.match(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$", stripped)
        bracket_match = re.match(r"^【(?P<title>[^】]{1,80})】\s*$", stripped)
        if markdown_match:
            title = str(markdown_match.group("title") or "").strip().strip("#").strip()
            boundaries.append(
                {
                    "start": offset,
                    "end": offset + len(line),
                    "level": len(str(markdown_match.group("hashes") or "")),
                    "title": title,
                }
            )
        elif bracket_match:
            title = str(bracket_match.group("title") or "").strip()
            boundaries.append(
                {
                    "start": offset,
                    "end": offset + len(line),
                    "level": 1,
                    "title": title,
                }
            )
        offset += len(line)
    return boundaries


def _normalize_section_title(value: str) -> str:
    text = str(value or "").strip().strip("#").strip()
    text = re.sub(r"^[【\[\(（]+", "", text)
    text = re.sub(r"[】\]\)）]+$", "", text)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _section_title_matches(title: str, key: str) -> bool:
    normalized_title = _normalize_section_title(title)
    normalized_key = _normalize_section_title(key)
    if not normalized_title or not normalized_key:
        return False
    return normalized_title == normalized_key or normalized_key in normalized_title or normalized_title in normalized_key


def _content_for_artifact_spec(
    spec: dict[str, Any],
    sections: dict[str, str],
    final_content: str,
    explicit_inputs: dict[str, Any] | None = None,
) -> str:
    keys = [
        _render_artifact_path(str(item).strip(), dict(explicit_inputs or {}))
        for item in list(spec.get("section_keys") or [])
        if str(item).strip()
    ]
    path = str(spec.get("path") or "")
    if str(spec.get("content_source") or "").strip() == "final_content":
        return str(final_content or "").strip()
    section_content = extract_markdown_section_content(
        final_content,
        keys,
        stop_section_keys=[
            str(item).strip()
            for item in list(spec.get("stop_section_keys") or spec.get("section_stop_keys") or [])
            if str(item).strip()
        ],
        include_heading=True,
    )
    if section_content.strip():
        return section_content
    for key in keys:
        for title, content in sections.items():
            if key == title or key.lower() in title.lower() or title.lower() in key.lower():
                return content
    if spec.get("fallback_to_full_content"):
        return str(final_content or "").strip()
    if str(spec.get("path") or "") == "01_project_bible.md":
        return str(final_content or "").strip()
    return ""


def _project_brief_markdown(*, explicit_inputs: dict[str, Any], user_message: str) -> str:
    title = str(explicit_inputs.get("title") or "未命名项目").strip()
    payload = {
        key: value
        for key, value in explicit_inputs.items()
        if key not in {"artifact_root", "workspace_root"} and value not in ("", None, [], {})
    }
    lines = [f"# {title}", "", "## 用户原始要求", "", str(user_message or "").strip()]
    if payload:
        lines.extend(["", "## 显式输入", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines).strip() + "\n"


def _required_missing_content(relative_path: str, final_content: str) -> str:
    return (
        f"# {relative_path}\n\n"
        "本文件由任务产物规则创建，但本轮模型输出中没有可独立拆分的对应内容。\n\n"
        "## 本轮真实输出\n\n"
        f"{str(final_content or '').strip()}\n"
    )


def _required_markers_missing(spec: dict[str, Any], final_content: str, sections: dict[str, str]) -> bool:
    markers = tuple(str(item).strip() for item in list(spec.get("required_content_markers") or []) if str(item).strip())
    if not markers:
        return False
    return not _has_section(final_content, sections, markers)


def _has_section(final_content: str, sections: dict[str, str], markers: tuple[str, ...]) -> bool:
    text = str(final_content or "")
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers) or any(
        any(marker.lower() in str(title).lower() for marker in markers)
        for title in sections
    )


def _run_report(
    *,
    task_run_id: str,
    session_id: str,
    task_ref: str,
    coordination_run_id: str,
    artifact_root: str,
    created_files: list[str],
    skipped_files: list[str],
    task_status: str,
    terminal_reason: str,
    task_diagnostics: dict[str, Any],
) -> str:
    last_error = dict(task_diagnostics.get("last_error") or {})
    lines = [
        "# 任务产物运行报告",
        "",
        f"- task_run_id: `{task_run_id}`",
        f"- session_id: `{session_id}`",
        f"- task_ref: `{task_ref}`",
        f"- coordination_run_id: `{coordination_run_id or '无'}`",
        f"- task_status: `{task_status or 'unknown'}`",
        f"- terminal_reason: `{terminal_reason or 'none'}`",
        f"- artifact_root: `{artifact_root}`",
        f"- generated_at: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        "",
    ]
    if last_error:
        lines.extend([
            "## 失败诊断",
            "",
            f"- message: `{str(last_error.get('message') or '')}`",
            f"- code: `{str(last_error.get('code') or '') or 'unknown'}`",
            f"- provider: `{str(last_error.get('provider') or '') or 'unknown'}`",
            f"- model: `{str(last_error.get('model') or '') or 'unknown'}`",
            f"- step_id: `{str(last_error.get('step_id') or '') or 'unknown'}`",
        ])
        detail = str(last_error.get("detail") or "").strip()
        if detail:
            lines.extend(["", "```text", detail, "```", ""])
    lines.extend([
        "## 已生成产物",
        "",
    ])
    lines.extend(f"- `{item}`" for item in created_files)
    if skipped_files:
        lines.extend(["", "## 未生成或跳过", ""])
        lines.extend(f"- `{item}`" for item in skipped_files)
    skipped_required = [item for item in skipped_files if item]
    if skipped_required:
        lines.extend(["", "说明：本轮没有生成这些必需产物，因此没有伪造文件内容。"])
    return "\n".join(lines).strip() + "\n"


def _write_text(path: Path, content: str) -> None:
    path.write_text(str(content or "").strip() + "\n", encoding="utf-8")


def _write_text_preserving_existing(path: Path, content: str) -> Path:
    normalized = str(content or "").strip() + "\n"
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == normalized:
                return path
        except OSError:
            pass
        path = _versioned_path(path)
    path.write_text(normalized, encoding="utf-8")
    return path


def _versioned_path(path: Path) -> Path:
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10000):
        candidate = parent / f"{stem}_v{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many artifact versions for {path}")


def _relative_or_absolute(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
