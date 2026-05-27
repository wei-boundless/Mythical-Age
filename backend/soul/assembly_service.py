from __future__ import annotations

from pathlib import Path
from .registry import SoulRegistry


class SoulAssemblyService:
    """Role-prompt-only soul assembly boundary."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.registry = SoulRegistry(self.base_dir)

    def build_role_prompt(self, *, soul_id: str) -> dict[str, Any]:
        profile = self.registry.get_profile(soul_id)
        if profile is None:
            raise KeyError(soul_id)
        traits = list(profile.personality_traits or profile.soul_traits or ())
        style = list(profile.expression_style or ())
        guardrails = list(profile.guardrails or ())
        lines = [
            f"你正在以“{profile.display_name or profile.name}”的角色气质与用户交流。",
            "这只是角色表达锚点，不授予任何工作职责、工具权限、运行时权限或任务裁决权。",
        ]
        if profile.description:
            lines.append(f"角色概述：{profile.description}")
        if traits:
            lines.append("性格锚点：" + "、".join(traits) + "。")
        if style:
            lines.append("表达风格：" + "、".join(style) + "。")
        if guardrails:
            lines.append("角色边界：" + "、".join(guardrails) + "。")
        return {
            "resource_type": "role_prompt",
            "role_prompt_id": f"soul.role_prompt.{profile.soul_id}",
            "soul_id": profile.soul_id,
            "title": f"{profile.display_name or profile.name}角色表达锚点",
            "content": "\n".join(line for line in lines if line.strip()),
            "authority": "soul.role_prompt",
        }


