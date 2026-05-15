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
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "chapters").mkdir(parents=True, exist_ok=True)
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
        if _is_narrative_required_artifact(relative_path) and not _has_required_narrative_artifact(relative_path, final_content, sections):
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
        created_files=tuple(created),
        skipped_files=tuple(skipped),
        diagnostics={
            "status": "created",
            "created_count": len(created),
            "skipped_count": len(skipped),
            "task_status": task_status,
            "terminal_reason": terminal_reason,
            "source": "task_policy.artifact_policy",
        },
    )


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
    return [
        {"path": "01_project_bible.md", "section_keys": ["项目总纲", "Project Brief"], "required": True},
        {"path": "02_world_bible.md", "section_keys": ["世界规则", "World Rules"], "required": True},
        {"path": "03_character_bible.md", "section_keys": ["主角设定", "人物设定", "角色设定", "Protagonist"], "required": True},
        {"path": "04_volume_plan.md", "section_keys": ["分卷规划", "Volume Plan"], "required": True},
        {
            "path": "chapters/chapter_{chapter_index:03d}_plan.md",
            "section_keys": ["{chapter_label}写作准备", "{chapter_label}规划", "写作准备", "章节规划", "Chapter Plan"],
            "required": True,
        },
        {
            "path": "chapters/chapter_{chapter_index:03d}_draft.md",
            "section_keys": ["{chapter_label}正文", "章正文", "正文初稿", "章节正文", "Chapter Draft"],
            "required": True,
        },
        {
            "path": "chapters/chapter_{chapter_index:03d}_revised.md",
            "section_keys": ["{chapter_label}综合修订稿", "综合修订稿", "修订稿", "Chapter Revised"],
            "required": True,
        },
        {
            "path": "chapters/chapter_{chapter_index:03d}_final.md",
            "section_keys": ["{chapter_label}风格终稿", "风格终稿", "章节终稿", "Chapter Final"],
            "required": True,
        },
        {
            "path": "memory/memory_candidates_{chapter_index:03d}.md",
            "section_keys": ["{chapter_label}创作资产整理", "创作资产整理", "记忆候选", "记忆候选批次"],
            "required": True,
        },
    ]


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
    values = {
        "chapter_index": chapter_index,
        "chapter_index_padded": f"{chapter_index:03d}",
        "chapter_file_prefix": str(explicit_inputs.get("chapter_file_prefix") or f"chapter_{chapter_index:03d}"),
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
    if "chapter_" in path:
        if path.endswith("_plan.md"):
            keys.extend(["写作准备", "章节规划", "章节准备", "Chapter Plan"])
        elif path.endswith("_draft.md"):
            keys.extend(["章正文", "正文初稿", "章节正文", "Chapter Draft"])
        elif path.endswith("_progression.md"):
            keys.extend(["推进检查", "章节推进", "Chapter Progression"])
        elif path.endswith("_revised.md"):
            keys.extend(["综合修订稿", "修订稿", "Chapter Revised"])
        elif path.endswith("_final.md"):
            keys.extend(["风格终稿", "章节终稿", "Chapter Final"])
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
        "本文件由任务产物规则创建，但本轮模型输出中没有可独立拆分的对应章节。\n\n"
        "## 本轮真实输出\n\n"
        f"{str(final_content or '').strip()}\n"
    )


def _is_narrative_required_artifact(relative_path: str) -> bool:
    normalized = str(relative_path or "").replace("\\", "/")
    return normalized.startswith("chapters/chapter_") and normalized.endswith(("_draft.md", "_revised.md", "_final.md"))


def _has_required_narrative_artifact(relative_path: str, final_content: str, sections: dict[str, str]) -> bool:
    normalized = str(relative_path or "").replace("\\", "/")
    if normalized.endswith("_revised.md"):
        return _has_section(final_content, sections, ("综合修订稿", "chapter revised", "revised"))
    if normalized.endswith("_final.md"):
        return _has_section(final_content, sections, ("风格终稿", "chapter final", "final"))
    return _has_chapter_draft(final_content, sections)


def _has_section(final_content: str, sections: dict[str, str], markers: tuple[str, ...]) -> bool:
    text = str(final_content or "")
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers) or any(
        any(marker.lower() in str(title).lower() for marker in markers)
        for title in sections
    )


def _has_chapter_draft(final_content: str, sections: dict[str, str]) -> bool:
    text = str(final_content or "")
    markers = ("章正文", "chapter draft", "正文初稿")
    return any(marker.lower() in text.lower() for marker in markers) or any(
        "draft" in title.lower() and ("chapter" in title.lower() or "章" in title)
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
        "# 长篇小说任务运行报告",
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
    if any(item.startswith("chapters/chapter_") and item.endswith("_draft.md") for item in skipped_files):
        lines.extend(["", "说明：本轮没有生成章节正文，因此没有伪造正文文件。"])
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
