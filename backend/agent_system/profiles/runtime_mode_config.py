from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ROLE_MODE = "role"
STANDARD_MODE = "standard"
PROFESSIONAL_MODE = "professional"
VIBE_CODING_MODE = "vibe_coding"
CUSTOM_MODE = "custom"
DEFAULT_RUNTIME_MODE = CUSTOM_MODE
RUNTIME_MODE_ORDER = (ROLE_MODE, STANDARD_MODE, PROFESSIONAL_MODE, VIBE_CODING_MODE, CUSTOM_MODE)


@dataclass(frozen=True, slots=True)
class AgentRuntimeModeConfig:
    mode: str
    label: str
    interaction_mode: str
    runtime_lane: str
    recipe_id: str
    projection_strength: str
    runtime_lanes: tuple[str, ...] = ()
    execution_strategy: str = ""
    builtin: bool = True
    editable: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runtime_lanes"] = list(self.effective_runtime_lanes())
        return payload

    def effective_runtime_lanes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*self.runtime_lanes, self.runtime_lane] if self.runtime_lane else self.runtime_lanes))


MODE_CONFIGS: dict[str, AgentRuntimeModeConfig] = {
    ROLE_MODE: AgentRuntimeModeConfig(
        mode=ROLE_MODE,
        label="角色模式",
        interaction_mode="role_mode",
        runtime_lane="role_interaction",
        recipe_id="runtime.recipe.role_interaction",
        projection_strength="primary",
    ),
    STANDARD_MODE: AgentRuntimeModeConfig(
        mode=STANDARD_MODE,
        label="标准模式",
        interaction_mode="standard_mode",
        runtime_lane="standard_task",
        recipe_id="runtime.recipe.standard_task",
        projection_strength="companion",
    ),
    PROFESSIONAL_MODE: AgentRuntimeModeConfig(
        mode=PROFESSIONAL_MODE,
        label="专家模式",
        interaction_mode="professional_mode",
        runtime_lane="professional_task",
        recipe_id="runtime.recipe.professional_task",
        projection_strength="style_only",
        execution_strategy="professional_task_run",
    ),
    VIBE_CODING_MODE: AgentRuntimeModeConfig(
        mode=VIBE_CODING_MODE,
        label="Vibe Coding",
        interaction_mode="vibe_coding",
        runtime_lane="vibe_coding_task",
        recipe_id="runtime.recipe.vibe_coding",
        projection_strength="style_only",
        execution_strategy="professional_task_run",
        description="项目自有代码任务模式，使用本项目 runtime、权限、工具和验证链路承接代码修改、运行与验证。",
    ),
    CUSTOM_MODE: AgentRuntimeModeConfig(
        mode=CUSTOM_MODE,
        label="自定义模式",
        interaction_mode="custom_mode",
        runtime_lane="",
        recipe_id="runtime.recipe.custom",
        projection_strength="manual",
        editable=True,
    ),
}


def runtime_mode_catalog(metadata: Any | None = None) -> dict[str, AgentRuntimeModeConfig]:
    _ = metadata
    return dict(MODE_CONFIGS)


def normalize_runtime_modes(
    values: Any,
    *,
    fallback: tuple[str, ...] = (CUSTOM_MODE,),
    mode_catalog: dict[str, AgentRuntimeModeConfig] | None = None,
) -> tuple[str, ...]:
    catalog = mode_catalog or MODE_CONFIGS
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = list(values or [])
    normalized: list[str] = []
    for item in raw_values:
        mode = str(item or "").strip()
        if mode in catalog and mode not in normalized:
            normalized.append(mode)
    if not normalized:
        normalized.extend(mode for mode in fallback if mode in catalog)
    return tuple(normalized)


def normalize_default_runtime_mode(value: Any, enabled_modes: tuple[str, ...]) -> str:
    if not enabled_modes:
        return ""
    mode = str(value or "").strip()
    if mode in enabled_modes:
        return mode
    if DEFAULT_RUNTIME_MODE in enabled_modes:
        return DEFAULT_RUNTIME_MODE
    return enabled_modes[0] if enabled_modes else DEFAULT_RUNTIME_MODE


def runtime_lanes_for_modes(
    modes: tuple[str, ...],
    *,
    mode_catalog: dict[str, AgentRuntimeModeConfig] | None = None,
) -> tuple[str, ...]:
    catalog = mode_catalog or MODE_CONFIGS
    lanes: list[str] = []
    for mode in modes:
        config = catalog.get(mode)
        if config is None:
            continue
        lanes.extend(config.effective_runtime_lanes())
    return tuple(dict.fromkeys(lane for lane in lanes if lane))


def modes_for_runtime_lanes(
    lanes: Any,
    *,
    mode_catalog: dict[str, AgentRuntimeModeConfig] | None = None,
) -> tuple[str, ...]:
    catalog = mode_catalog or MODE_CONFIGS
    lane_set = {str(item or "").strip() for item in list(lanes or []) if str(item or "").strip()}
    modes = tuple(
        mode
        for mode, config in catalog.items()
        if any(lane in lane_set for lane in config.effective_runtime_lanes())
    )
    return modes


def modes_for_runtime_lanes_or_custom(
    lanes: Any,
    *,
    mode_catalog: dict[str, AgentRuntimeModeConfig] | None = None,
) -> tuple[str, ...]:
    catalog = mode_catalog or MODE_CONFIGS
    lane_values = [str(item or "").strip() for item in list(lanes or []) if str(item or "").strip()]
    modes = modes_for_runtime_lanes(lanes, mode_catalog=mode_catalog)
    covered_lanes = set(runtime_lanes_for_modes(modes, mode_catalog=catalog))
    has_manual_lanes = any(lane not in covered_lanes for lane in lane_values)
    if modes and has_manual_lanes and CUSTOM_MODE in catalog and CUSTOM_MODE not in modes:
        return (*modes, CUSTOM_MODE)
    if modes:
        return modes
    return (CUSTOM_MODE,) if lane_values else ()


def mode_config_catalog(metadata: Any | None = None) -> list[dict[str, Any]]:
    catalog = runtime_mode_catalog(metadata)
    ordered = [mode for mode in RUNTIME_MODE_ORDER if mode in catalog]
    ordered.extend(mode for mode in catalog if mode not in ordered)
    return [catalog[mode].to_dict() for mode in ordered]
