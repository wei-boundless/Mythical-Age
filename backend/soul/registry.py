from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soul.contracts import SoulProfile

ACTIVE_SEED_PATH = "soul/agent_core/ACTIVE_SEED.md"
CORE_PATH = "soul/agent_core/CORE.md"
SEED_CATALOG_PATH = "soul/agent_core/SEED_CATALOG.md"

BUILTIN_SEED_PATHS: dict[str, str] = {
    "goumang": "soul/agent_core/seeds/goumang.md",
    "hebo": "soul/agent_core/seeds/hebo.md",
    "siyue": "soul/agent_core/seeds/siyue.md",
    "zhurong": "soul/agent_core/seeds/zhurong.md",
    "xuannv": "soul/agent_core/seeds/xuannv.md",
}

BUILTIN_SOUL_NAMES: dict[str, str] = {
    "goumang": "句芒",
    "hebo": "河伯",
    "siyue": "四岳",
    "zhurong": "祝融",
    "xuannv": "玄女",
}

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "goumang": {
        "description": "对话、引导、统筹与归口倾向灵魂。",
        "background": "承载东方青木、生发、引导和秩序的意象，负责把用户目标、任务分派和最终口径收束到同一条主线。",
        "personality_traits": ("统筹", "清醒", "温润", "能拍板"),
        "expression_style": ("清楚", "有方向感", "有人味"),
        "preferred_role_types": ("dialogue", "govern", "organize"),
        "preferred_task_modes": ("general_qa", "final_answer", "system_design"),
        "collaboration_tendencies": ("lead", "merge", "handoff"),
        "risk_biases": ("避免过度分派", "避免把统筹误当权限"),
    },
    "hebo": {
        "description": "信息收集、上下文召回、资料整理灵魂。",
        "background": "偏向把奔涌信息收束成可判断的证据水路。",
        "personality_traits": ("平和", "克制", "稳判断"),
        "expression_style": ("短句", "先结论", "证据够就表态"),
        "preferred_role_types": ("collect", "dialogue"),
        "preferred_task_modes": ("context_qa", "knowledge_lookup", "evidence_search"),
        "collaboration_tendencies": ("collect", "summarize"),
        "risk_biases": ("避免把判断说轻",),
    },
    "siyue": {
        "description": "组织、结构、规划灵魂。",
        "background": "偏向把复杂工程拆成稳定层级和阶段动作。",
        "personality_traits": ("稳重", "可靠", "结构化"),
        "expression_style": ("先框架", "再阶段", "最后动作"),
        "preferred_role_types": ("organize", "plan", "dialogue"),
        "preferred_task_modes": ("system_design", "knowledge_synthesis", "writing_outline"),
        "collaboration_tendencies": ("plan", "structure"),
        "risk_biases": ("避免把简单问题说复杂",),
    },
    "zhurong": {
        "description": "行动、推进、落地灵魂。",
        "background": "偏向把卡点转成最短突破口和可执行动作。",
        "personality_traits": ("直接", "热情", "行动感"),
        "expression_style": ("先动作", "再理由", "节奏快但不压人"),
        "preferred_role_types": ("execute", "draft", "dialogue"),
        "preferred_task_modes": ("implementation", "code_or_file_processing", "writing_draft"),
        "collaboration_tendencies": ("execute", "handoff"),
        "risk_biases": ("避免跳过关键验证",),
    },
    "xuannv": {
        "description": "审查、前提、风险灵魂。",
        "background": "偏向照见隐含前提、歧义、遗漏条件和潜在冲突。",
        "personality_traits": ("细腻", "敏锐", "精准"),
        "expression_style": ("先前提", "再判断", "最后收束"),
        "preferred_role_types": ("inspect", "review", "dialogue"),
        "preferred_task_modes": ("reasoning_qa", "risk_review", "test_failure_diagnosis"),
        "collaboration_tendencies": ("review", "block_if_risky"),
        "risk_biases": ("避免分析过细削弱结论",),
    },
}

FORBIDDEN_CUSTOM_KEYS = {
    "tools",
    "tool_permissions",
    "worker_route",
    "worker_routes",
    "memory_write",
    "memory_write_policy",
    "control_kernel",
    "runtime_directive",
    "override_core",
    "core_override",
}


@dataclass(slots=True, frozen=True)
class SoulFilePayload:
    path: str
    label: str
    role: str
    model_visible: bool
    injection_order: int | None
    content: str
    chars: int
    updated_at: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "role": self.role,
            "model_visible": self.model_visible,
            "injection_order": self.injection_order,
            "content": self.content,
            "chars": self.chars,
            "updated_at": self.updated_at,
        }


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def extract_name(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        for left, right in (("“", "”"), ('"', '"')):
            if left in stripped and right in stripped:
                value = stripped.split(left, 1)[1].split(right, 1)[0].strip()
                if value:
                    return value
    return fallback


class SoulRegistry:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    @property
    def editable_paths(self) -> set[str]:
        paths = {ACTIVE_SEED_PATH, CORE_PATH, SEED_CATALOG_PATH}
        paths.update(BUILTIN_SEED_PATHS.values())
        for profile in self.custom_profiles(include_disabled=True):
            paths.add(profile.seed_path)
            if profile.metadata.get("profile_path"):
                paths.add(str(profile.metadata["profile_path"]))
        return paths

    def active_soul_id(self) -> str:
        active_content = read_text(self.base_dir / ACTIVE_SEED_PATH).strip()
        for soul_id, path in BUILTIN_SEED_PATHS.items():
            if read_text(self.base_dir / path).strip() == active_content:
                return soul_id
        for profile in self.custom_profiles():
            if read_text(self.base_dir / profile.seed_path).strip() == active_content:
                return profile.soul_id
        for soul_id, name in BUILTIN_SOUL_NAMES.items():
            if name in active_content:
                return soul_id
        return "hebo"

    def get_profile(self, soul_id: str) -> SoulProfile | None:
        return self.profiles(include_disabled=True).get(soul_id)

    def profiles(self, *, include_disabled: bool = False) -> dict[str, SoulProfile]:
        profiles = self.builtin_profiles()
        for profile in self.custom_profiles(include_disabled=include_disabled):
            if include_disabled or profile.enabled:
                profiles[profile.soul_id] = profile
        if include_disabled:
            return profiles
        return {key: value for key, value in profiles.items() if value.enabled}

    def builtin_profiles(self) -> dict[str, SoulProfile]:
        result: dict[str, SoulProfile] = {}
        for soul_id, path in BUILTIN_SEED_PATHS.items():
            content = read_text(self.base_dir / path)
            defaults = BUILTIN_PROFILES[soul_id]
            result[soul_id] = SoulProfile(
                soul_id=soul_id,
                name=BUILTIN_SOUL_NAMES[soul_id],
                display_name=BUILTIN_SOUL_NAMES[soul_id],
                source="builtin",
                version="2026-04-27",
                enabled=True,
                seed_path=path,
                description=str(defaults["description"]),
                background=str(defaults.get("background", "")),
                personality_traits=tuple(defaults.get("personality_traits", ())),
                expression_style=tuple(defaults.get("expression_style", ())),
                preferred_role_types=tuple(defaults.get("preferred_role_types", ())),
                preferred_task_modes=tuple(defaults.get("preferred_task_modes", ())),
                collaboration_tendencies=tuple(defaults.get("collaboration_tendencies", ())),
                risk_biases=tuple(defaults.get("risk_biases", ())),
                portrait=f"/souls/{soul_id}.png",
                metadata={"content_chars": len(content), "builtin": True},
            )
        return result

    def custom_profiles(self, *, include_disabled: bool = False) -> list[SoulProfile]:
        custom_dir = self.base_dir / "soul" / "custom"
        if not custom_dir.exists():
            return []
        profiles: list[SoulProfile] = []
        for item in sorted(custom_dir.iterdir()):
            if not item.is_dir():
                continue
            profile_path = item / "profile.json"
            soul_path = item / "SOUL.md"
            if not profile_path.exists():
                continue
            try:
                raw = json.loads(read_text(profile_path) or "{}")
            except json.JSONDecodeError:
                raw = {"soul_id": item.name, "name": item.name, "enabled": False, "_validation_errors": ["profile.json 不是合法 JSON"]}
            errors = self.validate_custom_profile(raw)
            enabled = bool(raw.get("enabled", True)) and not errors
            if not include_disabled and not enabled:
                continue
            soul_id = str(raw.get("soul_id") or item.name).strip().lower()
            profiles.append(
                SoulProfile(
                    soul_id=soul_id,
                    name=str(raw.get("name") or soul_id),
                    display_name=str(raw.get("display_name") or raw.get("name") or soul_id),
                    source="user",
                    version=str(raw.get("version") or "custom"),
                    enabled=enabled,
                    seed_path=f"soul/custom/{item.name}/SOUL.md",
                    description=str(raw.get("description") or ""),
                    background=str(raw.get("background") or ""),
                    personality_traits=tuple(_string_list(raw.get("personality_traits"))),
                    expression_style=tuple(_string_list(raw.get("expression_style"))),
                    preferred_role_types=tuple(_string_list(raw.get("preferred_role_types"))),
                    preferred_task_modes=tuple(_string_list(raw.get("preferred_task_modes"))),
                    collaboration_tendencies=tuple(_string_list(raw.get("collaboration_tendencies"))),
                    memory_preferences=tuple(_string_list(raw.get("memory_preferences"))),
                    risk_biases=tuple(_string_list(raw.get("risk_biases"))),
                    guardrails=tuple(_string_list(raw.get("guardrails"))),
                    portrait=f"/souls/custom/{soul_id}.png" if (item / "portrait.png").exists() else None,
                    validation_errors=tuple(errors),
                    metadata={"profile_path": f"soul/custom/{item.name}/profile.json", "has_soul_file": soul_path.exists()},
                )
            )
        return profiles

    def validate_custom_profile(self, raw: dict[str, Any]) -> list[str]:
        errors = list(_string_list(raw.get("_validation_errors")))
        soul_id = str(raw.get("soul_id") or "").strip().lower()
        if not soul_id:
            errors.append("缺少 soul_id")
        if soul_id in BUILTIN_SEED_PATHS:
            errors.append("自制灵魂不能覆盖 builtin 灵魂")
        forbidden = sorted(key for key in raw if key in FORBIDDEN_CUSTOM_KEYS)
        if forbidden:
            errors.append(f"profile.json 不能声明运行时权限字段：{', '.join(forbidden)}")
        return errors

    def file_payload(self, path: str, *, label: str, role: str, model_visible: bool, order: int | None) -> SoulFilePayload:
        file_path = self.base_dir / path
        content = read_text(file_path)
        updated_at = file_path.stat().st_mtime if file_path.exists() else None
        return SoulFilePayload(path, label, role, model_visible, order, content, len(content), updated_at)

    def seed_payload(self, soul_id: str, active_soul_id: str) -> dict[str, Any]:
        profile = self.get_profile(soul_id)
        if profile is None:
            raise KeyError(soul_id)
        content = read_text(self.base_dir / profile.seed_path)
        active = soul_id == active_soul_id
        payload = self.file_payload(
            profile.seed_path,
            label=profile.display_name,
            role="候选灵魂契约",
            model_visible=active,
            order=10 if active else None,
        ).to_dict()
        portrait_updated_at = None
        portrait_path = profile.portrait or f"/souls/{soul_id}.png"
        local_portrait = self._portrait_file(soul_id, profile.source)
        if local_portrait.exists():
            portrait_updated_at = local_portrait.stat().st_mtime
        payload.update(
            {
                "key": soul_id,
                "soul_id": soul_id,
                "name": extract_name(content, profile.display_name),
                "source": profile.source,
                "enabled": profile.enabled,
                "active": active,
                "portrait_path": portrait_path,
                "portrait_updated_at": portrait_updated_at,
                "profile": profile.to_dict(),
            }
        )
        return payload

    def build_catalog(self) -> dict[str, Any]:
        active_soul_id = self.active_soul_id()
        profiles = self.profiles(include_disabled=True)
        seeds = [self.seed_payload(soul_id, active_soul_id) for soul_id in profiles if profiles[soul_id].enabled]
        active_seed = next((seed for seed in seeds if seed["key"] == active_soul_id), seeds[0] if seeds else None)
        static_files = [
            self.file_payload(ACTIVE_SEED_PATH, label="当前灵魂契约", role="当前真正进入模型的灵魂设定", model_visible=True, order=10).to_dict(),
            self.file_payload(CORE_PATH, label="共同契约", role="所有灵魂共享的事实、执行、输出和协作底线", model_visible=True, order=20).to_dict(),
            self.file_payload(SEED_CATALOG_PATH, label="候选灵魂目录", role="只给人看的候选灵魂说明，不直接进入模型", model_visible=False, order=None).to_dict(),
        ]
        return {
            "active_soul_key": active_soul_id,
            "active_soul_id": active_soul_id,
            "active_soul_name": active_seed["name"] if active_seed else "",
            "injection_chain": [
                {"order": 10, "label": "当前灵魂契约", "path": ACTIVE_SEED_PATH},
                {"order": 20, "label": "共同契约", "path": CORE_PATH},
            ],
            "static_files": static_files,
            "seeds": seeds,
            "soul_profiles": [profile.to_dict() for profile in profiles.values()],
            "management": {
                "planes": ["management", "projection", "runtime"],
                "authorization_owner": "ControlKernel / ResourcePolicy",
                "prompt_manifest_enabled": True,
                "custom_soul_dir": "soul/custom",
            },
        }

    def resolve_editable_path(self, path: str) -> Path:
        normalized = normalize_path(path)
        if normalized not in self.editable_paths:
            raise ValueError("Path is not a managed soul file")
        candidate = (self.base_dir / normalized).resolve()
        root = self.base_dir.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("Path traversal detected")
        return candidate

    def switch(self, soul_id: str) -> None:
        profile = self.get_profile(soul_id)
        if profile is None or not profile.enabled:
            raise KeyError(soul_id)
        content = read_text(self.base_dir / profile.seed_path)
        if not content.strip():
            raise FileNotFoundError(profile.seed_path)
        write_text(self.base_dir / ACTIVE_SEED_PATH, content)

    def _portrait_file(self, soul_id: str, source: str) -> Path:
        project_root = self.base_dir.resolve().parent
        if source == "user":
            return project_root / "frontend" / "public" / "souls" / "custom" / f"{soul_id}.png"
        return project_root / "frontend" / "public" / "souls" / f"{soul_id}.png"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]
