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
        items = list(package.sections.get(section_name, []))
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


def _render_context_package_operational_notes(package: ContextPackage) -> str:
    lines = [
        "## Context Management Runtime",
        f"- Pressure Level: {package.pressure_level}",
        f"- Rebuild Reason: {package.rebuild_reason}",
        f"- Compaction Strategy: {package.compaction_strategy}",
    ]
    if package.selected_sections:
        lines.append(f"- Selected Sections: {', '.join(package.selected_sections)}")
    if package.dropped_sections:
        lines.append(f"- Dropped Sections: {', '.join(package.dropped_sections)}")
    if package.compaction_decisions:
        lines.extend(f"- {decision}" for decision in package.compaction_decisions)
    return "\n".join(lines)


def build_system_prompt(
    base_dir: Path,
    rag_mode: bool,
    persistent_memory: str | None = None,
    session_memory: str | None = None,
    context_package: ContextPackage | None = None,
    active_skill: str | None = None,
) -> str:
    settings = get_settings()
    parts: list[str] = []

    for label, relative_path in STATIC_COMPONENTS:
        content = _read_component(base_dir, relative_path, settings.component_char_limit)
        parts.append(f"<!-- {label} -->\n{content}")

    long_term_context = build_long_term_context_bundle(
        base_dir,
        persistent_memory=persistent_memory,
    )
    static_context = long_term_context.render(
        truncate=_truncate,
        limit=settings.component_char_limit,
        include_memory_block=False,
    )
    if static_context:
        parts.append(f"<!-- Long-Term Context -->\n{static_context}")

    if rag_mode:
        parts.append(
            "<!-- Retrieval Mode -->\n"
            "RAG mode is enabled. When retrieved context is available, treat it as grounded evidence. "
            "Use long-term context for stable preferences, project conventions, and durable facts, not as a replacement "
            "for retrieved knowledge."
        )

    parts.append(
        "<!-- Memory Policy -->\n"
        "The long-term context system is layered: constitution for stable agent principles, profile for user/project defaults, "
        "and dynamic memory for durable facts and reusable conventions. Do not treat transient emotions, temporary moods, "
        "or user attachment to the agent as durable memory. Those can remain in session context without being promoted "
        "to the long-term context store."
    )

    if active_skill:
        parts.append(f"<!-- Active Skill -->\n{_truncate(active_skill, settings.component_char_limit)}")

    rendered_session_memory = (
        _render_context_package_block(context_package, include_durable_context=False)
        if context_package is not None
        else (session_memory or "").strip()
    )
    if rendered_session_memory:
        parts.append(
            "<!-- Session Memory -->\n"
            f"{_truncate(rendered_session_memory, settings.component_char_limit)}"
        )

    if context_package is not None:
        operational_notes = _render_context_package_operational_notes(context_package).strip()
        if operational_notes:
            parts.append(
                "<!-- Context Management -->\n"
                f"{_truncate(operational_notes, settings.component_char_limit)}"
            )

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
            "<!-- Durable Memory -->\n"
            f"## Dynamic Long-Term Memory\n{_truncate(durable_memory_block, settings.component_char_limit)}"
        )

    return "\n\n".join(parts)
