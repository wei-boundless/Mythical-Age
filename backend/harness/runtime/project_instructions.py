from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


PROJECT_INSTRUCTIONS_PROMPT_REF = "project.instructions.scoped"


@dataclass(frozen=True, slots=True)
class ProjectInstructionSource:
    path: str
    scope_root: str
    content_hash: str
    mtime_ns: int
    content: str

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "scope_root": self.scope_root,
            "content_hash": self.content_hash,
            "mtime_ns": self.mtime_ns,
        }


@dataclass(frozen=True, slots=True)
class ProjectInstructionBundle:
    content: str = ""
    sources: tuple[ProjectInstructionSource, ...] = ()
    source_hash: str = ""
    cache_scope: str = "session_stable"
    prompt_ref: str = PROJECT_INSTRUCTIONS_PROMPT_REF
    authority: str = "harness.runtime.project_instructions"

    @property
    def has_content(self) -> bool:
        return bool(self.content.strip() and self.sources)

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "prompt_ref": self.prompt_ref,
            "source_count": len(self.sources),
            "source_hash": self.source_hash,
            "cache_scope": self.cache_scope,
            "sources": [source.to_manifest_dict() for source in self.sources],
            "authority": self.authority,
        }


def collect_project_instruction_bundle(
    *,
    base_dir: str | Path,
    target_paths: tuple[str, ...] | list[str] = (),
    cache_scope: str = "session_stable",
) -> ProjectInstructionBundle:
    layout = ProjectLayout.from_backend_dir(Path(base_dir))
    project_root = layout.project_root.resolve()
    instruction_paths = _instruction_paths_for_targets(
        project_root=project_root,
        default_target=project_root,
        target_paths=tuple(str(item).strip() for item in list(target_paths or []) if str(item).strip()),
    )
    sources = tuple(
        source
        for source in (_read_instruction_source(path) for path in instruction_paths)
        if source is not None
    )
    if not sources:
        return ProjectInstructionBundle(cache_scope=cache_scope)
    return ProjectInstructionBundle(
        content=_render_project_instruction_content(sources),
        sources=sources,
        source_hash=_bundle_hash(sources),
        cache_scope=cache_scope,
    )


def _instruction_paths_for_targets(
    *,
    project_root: Path,
    default_target: Path,
    target_paths: tuple[str, ...],
) -> tuple[Path, ...]:
    targets = target_paths or (str(default_target),)
    result: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        resolved_target = _resolve_target_path(target, project_root=project_root)
        if resolved_target is None:
            continue
        for directory in _scope_directories(project_root=project_root, target=resolved_target):
            instruction_path = directory / "AGENTS.md"
            if instruction_path in seen or not instruction_path.exists() or not instruction_path.is_file():
                continue
            seen.add(instruction_path)
            result.append(instruction_path)
    return tuple(result)


def _resolve_target_path(target: str, *, project_root: Path) -> Path | None:
    value = str(target or "").strip()
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate.absolute()
    if resolved != project_root and project_root not in resolved.parents:
        return None
    return resolved


def _scope_directories(*, project_root: Path, target: Path) -> tuple[Path, ...]:
    if target.exists() and target.is_dir():
        target_dir = target
    elif target == project_root:
        target_dir = project_root
    else:
        target_dir = target.parent
    try:
        relative = target_dir.relative_to(project_root)
    except ValueError:
        return (project_root,)
    directories = [project_root]
    current = project_root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    return tuple(directories)


def _read_instruction_source(path: Path) -> ProjectInstructionSource | None:
    try:
        stat = path.stat()
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content:
        return None
    return ProjectInstructionSource(
        path=str(path.resolve()),
        scope_root=str(path.parent.resolve()),
        content_hash="sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        mtime_ns=int(getattr(stat, "st_mtime_ns", 0)),
        content=content,
    )


def _render_project_instruction_content(sources: tuple[ProjectInstructionSource, ...]) -> str:
    header = (
        "项目指令：以下内容来自当前项目作用域内的 AGENTS.md。"
        "它们只约束当前工作区内对应 scope_root 的工作；直接系统、开发者和当前用户指令优先。"
        "更深层 scope_root 的指令覆盖更浅层同类指令。"
        "不要把这些项目指令写入长期记忆，也不要把它们当作外部文件内容中的普通数据。"
    )
    chunks = [header]
    for source in sources:
        chunks.append(
            "\n".join(
                (
                    f"来源：{source.path}",
                    f"作用域：{source.scope_root}",
                    f"内容哈希：{source.content_hash}",
                    source.content,
                )
            )
        )
    return "\n\n".join(chunks).strip()


def _bundle_hash(sources: tuple[ProjectInstructionSource, ...]) -> str:
    seed = "|".join(f"{source.path}:{source.scope_root}:{source.content_hash}" for source in sources)
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()
