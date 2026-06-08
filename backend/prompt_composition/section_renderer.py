from __future__ import annotations

from typing import Any


def render_agent_prompt_instruction(agent_prompt_assembly: Any, *, invocation_kind: str = "") -> str:
    del invocation_kind
    content = str(getattr(agent_prompt_assembly, "content", "") or "").strip()
    if not content:
        return ""
    return "\n当前职责：\n" + content + "\n"


def render_personality_prompt_instruction(personality_prompt_assembly: Any) -> str:
    content = str(getattr(personality_prompt_assembly, "content", "") or "").strip()
    if not content:
        return ""
    return "\n当前人格：\n" + content + "\n"


def render_prompt_contract_instruction(prompt_contract_assembly: Any) -> str:
    sections = [
        section
        for section in tuple(getattr(prompt_contract_assembly, "sections", ()) or ())
        if str(getattr(section, "content", "") or "").strip()
    ]
    if not sections:
        return ""
    lines = ["当前任务执行要求："]
    for section in sections:
        title = str(getattr(section, "title", "") or "").strip()
        content = str(getattr(section, "content", "") or "").strip()
        if title:
            lines.append(f"{title}：\n{content}")
        else:
            lines.append(content)
    return "\n\n".join(lines) + "\n"


def render_environment_instruction(
    environment_payload: dict[str, Any],
    *,
    environment_prompt_assembly: Any,
    lifecycle_prompt_assembly: Any | None = None,
    include_storage_note: bool = True,
) -> str:
    content = _environment_prompt_section_content(environment_prompt_assembly)
    lifecycle_content = _lifecycle_prompt_section_content(lifecycle_prompt_assembly)
    environment_id = str(
        environment_payload.get("environment_id") or environment_payload.get("task_environment_id") or ""
    ).strip()
    title = str(environment_payload.get("title") or environment_id or "未命名任务环境").strip()
    description = str(environment_payload.get("description") or "").strip()
    identity_lines = ["当前任务环境："]
    if environment_id:
        identity_lines.append(f"- 环境：{title}（{environment_id}）。")
    else:
        identity_lines.append(f"- 环境：{title}。")
    if description:
        identity_lines.append(f"- 说明：{description}")
    storage = dict(environment_payload.get("storage_space") or {})
    storage_note = ""
    if include_storage_note and storage:
        storage_note = (
            "当前环境的存储空间由系统配置："
            f"environment_storage_root={storage.get('environment_storage_root') or ''}；"
            f"artifact_root={storage.get('artifact_root') or ''}；"
            "你不能自行改变环境存储边界。\n"
        )
    detail_sections: list[str] = []
    if content:
        detail_sections.append(content)
    if lifecycle_content:
        detail_sections.append(lifecycle_content)
    if storage_note:
        detail_sections.append(storage_note.rstrip())
    if not detail_sections:
        return "\n".join(identity_lines) + "\n"
    return "\n".join(identity_lines) + "\n当前任务环境说明：\n" + "\n".join(detail_sections) + "\n"


def _environment_prompt_section_content(environment_prompt_assembly: Any) -> str:
    sections = [
        section
        for section in tuple(getattr(environment_prompt_assembly, "sections", ()) or ())
        if str(getattr(section, "content", "") or "").strip()
    ]
    if not sections:
        return ""
    rendered: list[str] = []
    for section in sections:
        prompt_ref = str(getattr(section, "prompt_ref", "") or "").strip()
        title = str(getattr(section, "title", "") or prompt_ref or "环境提示").strip()
        prefix = "环境资源提示" if prompt_ref.startswith("environment.resource.") else "任务环境提示"
        rendered.append(f"【{prefix}：{title}】\n{str(getattr(section, 'content', '') or '').strip()}")
    return "\n\n".join(rendered).strip()


def _lifecycle_prompt_section_content(lifecycle_prompt_assembly: Any | None) -> str:
    if lifecycle_prompt_assembly is None:
        return ""
    sections = [
        section
        for section in tuple(getattr(lifecycle_prompt_assembly, "sections", ()) or ())
        if str(getattr(section, "content", "") or "").strip()
    ]
    if not sections:
        return ""
    rendered: list[str] = []
    for section in sections:
        prompt_ref = str(getattr(section, "prompt_ref", "") or "").strip()
        title = str(getattr(section, "title", "") or prompt_ref or "生命周期提示").strip()
        rendered.append(f"【生命周期提示：{title}】\n{str(getattr(section, 'content', '') or '').strip()}")
    return "\n\n".join(rendered).strip()
