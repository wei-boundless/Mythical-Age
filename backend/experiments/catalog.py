from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ExperimentProfile:
    id: str
    title: str
    description: str
    command_preview: str
    risk: str
    estimated_duration: str
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PROFILES: dict[str, ExperimentProfile] = {
    "smoke": ExperimentProfile(
        id="smoke",
        title="冒烟测试",
        description="验证后端聊天流、SSE 事件和前端事件 reducer，适合每次小改后快速跑。",
        command_preview="python -m harness.run --profile smoke",
        risk="低风险",
        estimated_duration="约 1-3 分钟",
    ),
    "stable": ExperimentProfile(
        id="stable",
        title="稳定门禁",
        description="在冒烟测试基础上追加 core regression gate，适合功能改完后确认主链没断。",
        command_preview="python -m harness.run --profile stable",
        risk="中风险",
        estimated_duration="约 3-8 分钟",
    ),
    "long": ExperimentProfile(
        id="long",
        title="长场景测试",
        description="运行真实用户长链场景，重点检查 follow-up、状态漂移、记忆和工具续写。",
        command_preview="python -m harness.run --profile long",
        risk="高耗时",
        estimated_duration="约 8-20 分钟",
        requires_confirmation=True,
    ),
}


def list_profiles() -> list[ExperimentProfile]:
    return list(PROFILES.values())


def get_profile(profile_id: str) -> ExperimentProfile | None:
    return PROFILES.get(str(profile_id or "").strip())
