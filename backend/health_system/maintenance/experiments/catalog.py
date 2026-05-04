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
    harness_profile: str = ""
    extra_args: tuple[str, ...] = ()
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["extra_args"] = list(self.extra_args)
        payload["harness_profile"] = self.harness_profile or self.id
        return payload


PROFILES: dict[str, ExperimentProfile] = {
    "smoke": ExperimentProfile(
        id="smoke",
        title="冒烟测试",
        description="验证后端聊天流、SSE 事件和前端事件 reducer，适合每次小改后快速跑。",
        command_preview="python -m health_system.maintenance.harness.run --profile smoke",
        risk="低风险",
        estimated_duration="约 1-3 分钟",
    ),
    "stable": ExperimentProfile(
        id="stable",
        title="稳定门禁",
        description="在冒烟测试基础上追加新测试体系 stable regression gate 和前端构建，适合功能改完后确认主链没断。",
        command_preview="python -m health_system.maintenance.harness.run --profile stable",
        risk="中风险",
        estimated_duration="约 3-10 分钟",
    ),
    "chain": ExperimentProfile(
        id="chain",
        title="链路级测试",
        description="验证单 Agent RuntimeLoop 主链、QueryRuntime adapter、任务-操作接线，适合每次主链改动后快速跑。",
        command_preview="python -m health_system.maintenance.harness.run --profile chain",
        risk="低风险",
        estimated_duration="约 1-3 分钟",
    ),
    "functional": ExperimentProfile(
        id="functional",
        title="功能级测试",
        description="覆盖操作、记忆、灵魂、工具等系统级功能合同，不跑长场景。",
        command_preview="python -m health_system.maintenance.harness.run --profile functional",
        risk="中风险",
        estimated_duration="约 3-8 分钟",
    ),
    "system": ExperimentProfile(
        id="system",
        title="系统级测试",
        description="覆盖链路级、功能级与后端应用 smoke、测试产物、门禁合同。",
        command_preview="python -m health_system.maintenance.harness.run --profile system",
        risk="中风险",
        estimated_duration="约 5-12 分钟",
    ),
    "scenario": ExperimentProfile(
        id="scenario",
        title="场景合同测试",
        description="只验证长场景目录、报告和场景测试基础设施，不直接跑真实长链。",
        command_preview="python -m health_system.maintenance.harness.run --profile scenario",
        risk="低风险",
        estimated_duration="约 1-3 分钟",
    ),
    "long_core": ExperimentProfile(
        id="long_core",
        title="长场景核心",
        description="运行三条核心长场景，覆盖 RAG、结构化数据、跨会话记忆和 follow-up，是日常长链回归的默认档。",
        command_preview="python -m health_system.maintenance.harness.run --profile long --scenario-set core",
        risk="高耗时",
        estimated_duration="约 8-20 分钟",
        harness_profile="long",
        extra_args=("--scenario-set", "core"),
        requires_confirmation=True,
    ),
    "long_batches": ExperimentProfile(
        id="long_batches",
        title="长场景批量",
        description="运行六条中长场景，追加复合任务、权限边界和多会话隔离，适合较大改动后的深度排查。",
        command_preview="python -m health_system.maintenance.harness.run --profile long --scenario-set batches",
        risk="高耗时",
        estimated_duration="约 15-35 分钟",
        harness_profile="long",
        extra_args=("--scenario-set", "batches"),
        requires_confirmation=True,
    ),
    "marathon": ExperimentProfile(
        id="marathon",
        title="六十轮长跑",
        description="运行 60 turn 真实用户马拉松，专门压测状态漂移、follow-up、记忆召回和恢复能力。",
        command_preview="python -m health_system.maintenance.harness.run --profile long --scenario-set mega",
        risk="最高耗时",
        estimated_duration="约 20-60 分钟",
        harness_profile="long",
        extra_args=("--scenario-set", "mega"),
        requires_confirmation=True,
    ),
}


def list_profiles() -> list[ExperimentProfile]:
    return list(PROFILES.values())


def get_profile(profile_id: str) -> ExperimentProfile | None:
    return PROFILES.get(str(profile_id or "").strip())
