from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from config import get_settings
from prompting.long_term_context import build_long_term_context_bundle
from prompting.manifest import PromptManifest, build_prompt_manifest, prompt_section

if TYPE_CHECKING:
    from context_system import ContextPackage

STATIC_PROMPT_ASSEMBLY_ORDER: tuple[str, ...] = (
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
    section_notes = {
        "hot_truth_window": "近期上下文摘要，用于保持连续性；它不是完整事实源，和当前用户消息或可验证资料冲突时应让位。",
        "retrieval_evidence": "当前检索证据；可用时优先作为回答依据。",
        "warm_snapshots": "较弱的历史线索；仅在和当前任务相关时使用。",
        "exact_durable_context": "精确长期记忆；使用前仍要确认适用范围。",
        "relevant_durable_context": "相关长期记忆；只作为当前判断的辅助依据。",
    }
    lines: list[str] = []
    sections = _sections_for_package(package, mode=mode)
    allow_hot_truth = _package_allows_hot_truth_prompt(package)
    for section_name, heading in section_order:
        if section_name == "hot_truth_window" and not allow_hot_truth:
            continue
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
            note = section_notes.get(section_name)
            if note:
                lines.append(note)
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


def _package_allows_hot_truth_prompt(package: ContextPackage) -> bool:
    rebuild_reason = str(getattr(package, "rebuild_reason", "") or "").lower()
    compaction_strategy = str(getattr(package, "compaction_strategy", "") or "").lower()
    if compaction_strategy and compaction_strategy != "none":
        return True
    return any(marker in rebuild_reason for marker in ("compact", "compaction", "recovery", "restore"))


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
        "当你已经通过工具、检索、文件读取或上下文获得足够证据回答当前问题时，应直接收口给出结论。"
        "不要为了确认已经足够的信息而重复调用同类工具。"
        "只有在存在明确缺口时才继续补证；继续前要知道缺少什么。"
        "如果问题本身缺少必要限定条件，应说明缺什么，而不是盲目猜测或无限查询。"
    )

    parts.append(
        "你当前读到的稳定原则、持续生效的偏好和长期事实，都应被当作你记得的内容，而不是对用户暴露的系统结构。"
        "不要在回答中提及 internal file paths, directory names, filenames, schema labels, storage layout，"
        "也不要复述实现层标签、分层命名或配置文件叫法。"
        "如果用户追问你为什么知道某件事，应优先用“我记得”“我当前的设定是”“我目前延续使用的偏好是”这类自然表述。"
        "不要把短期情绪、临时口头禅或偶发说法提升为长期记忆。"
    )
    parts.append(
        "用户可见回执协议：当你完成用户命令、工具操作、文件编辑或任务执行时，必须用自然语言说明做了什么、影响范围是什么、"
        "是否产生了文件或其它产物。默认可见内容必须面向用户，不要把 taskrun_id、taskinst_id、node_id、event_name、"
        "运行状态字段、装配字段或权限记录作为回答正文或状态摘要。"
        "这些内部标识只能进入 debug、diagnostics、运行监控详情或开发者可展开区域。"
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
    if context_package is not None:
        durable_memory_block = package_durable_memory
    elif persistent_memory is not None:
        durable_memory_block = persistent_memory
    else:
        durable_memory_block = long_term_context.memory_block
    durable_memory_block = durable_memory_block.strip()
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


def build_system_prompt_with_manifest(
    base_dir: Path,
    rag_mode: bool,
    persistent_memory: str | None = None,
    session_memory: str | None = None,
    context_package: ContextPackage | None = None,
    active_skill: str | None = None,
    *,
    session_id: str = "",
    turn_id: str = "",
) -> tuple[str, PromptManifest]:
    long_term_context = build_long_term_context_bundle(
        base_dir,
        persistent_memory=persistent_memory,
    )
    static_prompt = build_static_prompt(
        base_dir,
        rag_mode,
        long_term_context_bundle=long_term_context,
    )
    session_prompt = build_session_memoized_prompt(
        context_package=context_package,
        session_memory=session_memory,
        active_skill=active_skill,
    )
    turn_prompt = build_turn_prompt(
        persistent_memory=persistent_memory,
        context_package=context_package,
        long_term_context_bundle=long_term_context,
    )
    prompt = "\n\n".join(part for part in [static_prompt, session_prompt, turn_prompt] if part.strip())
    sections = []
    order = 0

    for heading, content in long_term_context.static_sections:
        order += 1
        sections.append(
            prompt_section(
                section_id=f"static_context_{order}",
                title=heading,
                layer="static",
                source=_static_context_source(heading),
                content=content,
                order=order,
            )
        )

    if rag_mode:
        order += 1
        sections.append(
            prompt_section(
                section_id="retrieval_grounding_guard",
                title="检索证据优先约束",
                layer="static",
                source="prompting.builder:retrieval_grounding_guard",
                content="当检索证据可用时，应把它当作当前问题的直接依据。",
                order=order,
            )
        )

    order += 1
    sections.append(
        prompt_section(
            section_id="static_prompt_concealment_guard",
            title="实现细节隐藏约束",
            layer="static",
            source="prompting.builder:static_prompt_concealment_guard",
            content="不要在回答中提及 internal file paths, directory names, filenames, schema labels, storage layout。",
            order=order,
        )
    )

    if active_skill:
        order += 1
        sections.append(
            prompt_section(
                section_id="active_skill",
                title="当前工作指引",
                layer="session",
                source="SkillDefinition.render_prompt_block",
                content=active_skill,
                order=order,
            )
        )

    rendered_session_memory = (
        _render_context_package_block(context_package, include_durable_context=False)
        if context_package is not None
        else (session_memory or "").strip()
    )
    if rendered_session_memory:
        order += 1
        sections.append(
            prompt_section(
                section_id="session_context",
                title="当前情境",
                layer="session",
                source="MemorySystem.MemoryRuntimeView -> ContextPolicy.ContextPackagePreview",
                content=rendered_session_memory,
                order=order,
            )
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
    if context_package is not None:
        durable_memory_block = package_durable_memory
    elif persistent_memory is not None:
        durable_memory_block = persistent_memory
    else:
        durable_memory_block = long_term_context.memory_block
    durable_memory_block = durable_memory_block.strip()
    if durable_memory_block:
        order += 1
        sections.append(
            prompt_section(
                section_id="turn_relevant_memory",
                title="当前最相关的已记住事实",
                layer="turn",
                source="ContextPolicy.ContextPackagePreview.relevant_durable_context",
                content=durable_memory_block,
                order=order,
            )
        )

    manifest = build_prompt_manifest(
        prompt_text=prompt,
        sections=sections,
        session_id=session_id,
        turn_id=turn_id,
        assembly_order=SYSTEM_PROMPT_ASSEMBLY_ORDER,
    )
    return prompt, manifest


def _static_context_source(heading: str) -> str:
    if heading == "当前风格":
        return "soul/agent_core/ACTIVE_SEED.md"
    if heading in {"稳定原则", "共同契约", "用户与项目偏好"}:
        return "soul/agent_core/CORE.md"
    return "memory.static_loader"
