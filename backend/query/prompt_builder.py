from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from config import get_settings
from query.long_term_context import build_long_term_context_bundle

if TYPE_CHECKING:
    from context_management import ContextPackage

STATIC_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("Skills Snapshot", "SKILLS_SNAPSHOT.md"),
)

STATIC_PROMPT_ASSEMBLY_ORDER: tuple[str, ...] = (
    "capability_summary",
    "soul_static_context",
    "retrieval_grounding_guard",
    "static_prompt_concealment_guard",
)

SYSTEM_PROMPT_ASSEMBLY_ORDER: tuple[str, ...] = (
    "static_prompt",
    "session_prompt",
    "turn_prompt",
)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _read_component(base_dir: Path, relative_path: str, limit: int) -> str:
    path = base_dir / relative_path
    if not path.exists():
        return f"[missing component: {relative_path}]"
    return _truncate(path.read_text(encoding="utf-8"), limit)


def _render_context_package_block(
    package: ContextPackage,
    *,
    include_durable_context: bool,
    include_runtime_context: bool = True,
    mode: str = "model",
) -> str:
    section_order = [
        ("static_context", None),
        ("active_process_context", None),
        ("hot_truth_window", "## Hot Truth Window"),
        ("retrieval_evidence", "## Retrieval Evidence"),
        ("warm_snapshots", "## Warm Flow Snapshots"),
        ("exact_durable_context", "## Exact Durable Context"),
        ("relevant_durable_context", "## Relevant Durable Context"),
    ]
    lines: list[str] = []
    sections = _sections_for_package(package, mode=mode)
    for section_name, heading in section_order:
        if not include_runtime_context and section_name in {
            "static_context",
            "active_process_context",
            "hot_truth_window",
            "retrieval_evidence",
            "warm_snapshots",
        }:
            continue
        if not include_durable_context and section_name in {
            "exact_durable_context",
            "relevant_durable_context",
        }:
            continue
        items = list(sections.get(section_name, []))
        if not items:
            continue
        if heading is not None:
            if lines:
                lines.append("")
            lines.append(heading)
        for item in items:
            stripped = str(item).strip()
            if not stripped:
                continue
            if section_name in {"static_context", "active_process_context"}:
                if lines:
                    lines.append("")
                lines.append(stripped)
            else:
                lines.append(f"- {stripped}")
    return "\n".join(lines).strip()


def _sections_for_package(
    package: ContextPackage,
    *,
    mode: str,
) -> dict[str, list[str]]:
    if hasattr(package, "sections_for"):
        return package.sections_for("debug" if mode == "debug" else "model")
    if mode == "debug" and hasattr(package, "debug_sections"):
        return getattr(package, "debug_sections")
    if hasattr(package, "model_visible_sections"):
        return getattr(package, "model_visible_sections")
    return package.sections


def build_static_prompt(
    base_dir: Path,
    rag_mode: bool,
    *,
    long_term_context_bundle=None,
) -> str:
    settings = get_settings()
    parts: list[str] = []

    for label, relative_path in STATIC_COMPONENTS:
        content = _read_component(base_dir, relative_path, settings.component_char_limit)
        parts.append(f"## 当前可用能力摘要\n{content}")

    long_term_context = long_term_context_bundle or build_long_term_context_bundle(base_dir)
    static_context = long_term_context.render(
        truncate=_truncate,
        limit=settings.component_char_limit,
        include_memory_block=False,
    )
    if static_context:
        parts.append(static_context)

    if rag_mode:
        parts.append(
            "当检索证据可用时，应把它当作当前问题的直接依据。"
            "你已经记得的设定和长期事实用于保持稳定性，不替代当前检索到的资料。"
        )

    parts.append(
        "你当前读到的稳定原则、持续生效的偏好和长期事实，都应被当作你记得的内容，而不是对用户暴露的系统结构。"
        "不要在回答中提及 internal file paths, directory names, filenames, schema labels, storage layout，"
        "也不要复述实现层标签、分层命名或配置文件叫法。"
        "如果用户追问你为什么知道某件事，应优先用“我记得”“我当前的设定是”“我目前延续使用的偏好是”这类自然表述。"
        "不要把短期情绪、临时口头禅或偶发说法提升为长期记忆。"
    )
    return "\n\n".join(parts)


def build_session_memoized_prompt(
    *,
    context_package: ContextPackage | None = None,
    session_memory: str | None = None,
    active_skill: str | None = None,
) -> str:
    settings = get_settings()
    parts: list[str] = []
    if active_skill:
        parts.append(f"## 当前工作指引\n{_truncate(active_skill, settings.component_char_limit)}")

    rendered_session_memory = (
        _render_context_package_block(context_package, include_durable_context=False)
        if context_package is not None
        else (session_memory or "").strip()
    )
    if rendered_session_memory:
        parts.append(f"## 当前情境\n{_truncate(rendered_session_memory, settings.component_char_limit)}")
    return "\n\n".join(parts)


def build_turn_prompt(
    *,
    persistent_memory: str | None = None,
    context_package: ContextPackage | None = None,
    long_term_context_bundle=None,
) -> str:
    settings = get_settings()
    long_term_context = long_term_context_bundle or build_long_term_context_bundle(
        settings.backend_dir,
        persistent_memory=persistent_memory,
    )
    parts: list[str] = []
    package_durable_memory = (
        _render_context_package_block(
            context_package,
            include_durable_context=True,
            include_runtime_context=False,
        )
        if context_package is not None
        else ""
    )
    durable_memory_block = (
        persistent_memory
        if persistent_memory is not None
        else package_durable_memory
        if package_durable_memory
        else long_term_context.memory_block
    ).strip()
    if durable_memory_block:
        parts.append(
            f"## 当前最相关的已记住事实\n{_truncate(durable_memory_block, settings.component_char_limit)}"
        )
    return "\n\n".join(parts)


def build_system_prompt(
    base_dir: Path,
    rag_mode: bool,
    persistent_memory: str | None = None,
    session_memory: str | None = None,
    context_package: ContextPackage | None = None,
    active_skill: str | None = None,
) -> str:
    long_term_context = build_long_term_context_bundle(
        base_dir,
        persistent_memory=persistent_memory,
    )
    parts = [
        build_static_prompt(
            base_dir,
            rag_mode,
            long_term_context_bundle=long_term_context,
        ),
        build_session_memoized_prompt(
            context_package=context_package,
            session_memory=session_memory,
            active_skill=active_skill,
        ),
        build_turn_prompt(
            persistent_memory=persistent_memory,
            context_package=context_package,
            long_term_context_bundle=long_term_context,
        ),
    ]
    return "\n\n".join(part for part in parts if part.strip())
