from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


TestLayer = Literal["chain", "functional", "system", "scenario"]
TestCaseStatus = Literal["active", "legacy", "quarantined", "candidate"]
TestRunner = Literal["pytest", "python", "harness"]


@dataclass(frozen=True, slots=True)
class TestCaseDefinition:
    case_id: str
    title: str
    layer: TestLayer
    path: str
    owner_system: str
    runner: TestRunner = "pytest"
    status: TestCaseStatus = "active"
    profiles: tuple[str, ...] = ()
    description: str = ""
    assertions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    replaces: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profiles"] = list(self.profiles)
        payload["assertions"] = list(self.assertions)
        payload["tags"] = list(self.tags)
        payload["replaces"] = list(self.replaces)
        return payload


ACTIVE_CASES: tuple[TestCaseDefinition, ...] = (
    TestCaseDefinition(
        case_id="chain.runtime_loop.contract",
        title="RuntimeLoop 事件与监控合同",
        layer="chain",
        path="tests/test_system_runtime_loop_regression.py",
        owner_system="test_system",
        profiles=("chain", "functional", "system", "stable"),
        assertions=("loop.event=tool_result_received", "tool.pairing_ok", "loop.completed"),
        tags=("runtime_loop", "monitor", "assertion"),
    ),
    TestCaseDefinition(
        case_id="chain.test_case_registry.contract",
        title="测试用例登记表合同",
        layer="chain",
        path="tests/test_system_case_registry_regression.py",
        owner_system="test_system",
        profiles=("chain", "functional", "system", "stable"),
        tags=("test_registry", "profile", "governance"),
    ),
    TestCaseDefinition(
        case_id="chain.test_agent.governance",
        title="测试 Agent 治理报告合同",
        layer="chain",
        path="tests/test_system_agent_regression.py",
        owner_system="test_system",
        profiles=("chain", "functional", "system", "stable"),
        tags=("test_agent", "governance", "registry"),
    ),
    TestCaseDefinition(
        case_id="chain.query_runtime.adapter",
        title="QueryRuntime 只作为 RuntimeLoop adapter",
        layer="chain",
        path="tests/query_runtime_runtime_loop_regression.py",
        owner_system="query_runtime",
        profiles=("chain", "system", "stable"),
        tags=("query_runtime", "adapter_only", "runtime_loop"),
    ),
    TestCaseDefinition(
        case_id="chain.task_runtime.contract",
        title="任务运行时合同",
        layer="chain",
        path="tests/task_runtime_contract_regression.py",
        owner_system="task_system",
        profiles=("chain", "system", "stable"),
        tags=("task", "operation", "runtime"),
    ),
    TestCaseDefinition(
        case_id="functional.operation.preview",
        title="操作系统 preview 与 OperationGate 合同",
        layer="functional",
        path="tests/operation_system_preview_regression.py",
        owner_system="operation_system",
        profiles=("functional", "system"),
        tags=("operation_gate", "resource_policy"),
    ),
    TestCaseDefinition(
        case_id="functional.operation.api",
        title="操作系统 API 目录合同",
        layer="functional",
        path="tests/operation_system_api_regression.py",
        owner_system="operation_system",
        profiles=("functional", "system"),
        tags=("operation_catalog", "api"),
    ),
    TestCaseDefinition(
        case_id="functional.tool.contract_gate",
        title="工具合同门禁",
        layer="functional",
        path="tests/tool_contract_gate_regression.py",
        owner_system="operation_system",
        profiles=("functional", "system"),
        tags=("tool", "contract", "operation_gate"),
    ),
    TestCaseDefinition(
        case_id="functional.tool.scope_contract",
        title="工具作用域合同",
        layer="functional",
        path="tests/tool_scope_contract_regression.py",
        owner_system="operation_system",
        profiles=("functional", "system"),
        tags=("tool", "scope", "contract"),
    ),
    TestCaseDefinition(
        case_id="functional.memory.contracts",
        title="记忆系统合同",
        layer="functional",
        path="tests/memory_system_contracts_regression.py",
        owner_system="memory_system",
        profiles=("functional",),
        tags=("memory", "contracts"),
    ),
    TestCaseDefinition(
        case_id="functional.memory.state_context",
        title="状态记忆与上下文策略",
        layer="functional",
        path="tests/state_memory_context_policy_regression.py",
        owner_system="memory_system",
        profiles=("functional",),
        tags=("state_memory", "context_policy"),
    ),
    TestCaseDefinition(
        case_id="functional.soul.api",
        title="灵魂系统 API 合同",
        layer="functional",
        path="tests/soul_system_api_regression.py",
        owner_system="soul_system",
        profiles=("functional",),
        tags=("soul", "api"),
    ),
    TestCaseDefinition(
        case_id="functional.soul.projection_boundary",
        title="灵魂投影资源边界",
        layer="functional",
        path="tests/soul_projection_resource_boundary_regression.py",
        owner_system="soul_system",
        profiles=("functional", "system"),
        tags=("soul", "projection", "operation_boundary"),
    ),
    TestCaseDefinition(
        case_id="functional.tool.registry",
        title="工具注册表合同",
        layer="functional",
        path="tests/tool_registry_regression.py",
        owner_system="operation_system",
        profiles=("functional",),
        tags=("tool", "registry"),
    ),
    TestCaseDefinition(
        case_id="functional.skill.contract",
        title="技能系统合同",
        layer="functional",
        path="tests/skill_contract_regression.py",
        owner_system="skill_system",
        profiles=("functional", "system"),
        tags=("skill", "contract"),
    ),
    TestCaseDefinition(
        case_id="functional.skill.policy",
        title="技能策略解析合同",
        layer="functional",
        path="tests/skill_policy_resolver_regression.py",
        owner_system="skill_system",
        profiles=("functional", "system"),
        tags=("skill", "policy"),
    ),
    TestCaseDefinition(
        case_id="functional.skill.registry",
        title="技能注册表合同",
        layer="functional",
        path="tests/skills_registry_regression.py",
        owner_system="skill_system",
        profiles=("functional", "system"),
        tags=("skill", "registry"),
    ),
    TestCaseDefinition(
        case_id="functional.task.understanding",
        title="任务理解合同",
        layer="functional",
        path="tests/task_understanding_regression.py",
        owner_system="task_system",
        profiles=("functional", "system"),
        tags=("task", "understanding"),
    ),
    TestCaseDefinition(
        case_id="functional.task.runtime_contract_trace",
        title="任务运行时合同 trace",
        layer="functional",
        path="tests/task_runtime_contract_trace_regression.py",
        owner_system="task_system",
        profiles=("functional", "system"),
        tags=("task", "operation", "runtime", "trace"),
    ),
    TestCaseDefinition(
        case_id="functional.permission.service",
        title="权限服务合同",
        layer="functional",
        path="tests/permission_service_regression.py",
        owner_system="operation_system",
        profiles=("functional",),
        tags=("permission", "operation_gate"),
    ),
    TestCaseDefinition(
        case_id="system.config.runtime",
        title="运行时配置合同",
        layer="system",
        path="tests/config_runtime_regression.py",
        owner_system="runtime",
        profiles=("system", "stable"),
        tags=("runtime", "config"),
    ),
    TestCaseDefinition(
        case_id="system.model.runtime",
        title="模型运行时合同",
        layer="system",
        path="tests/model_runtime_regression.py",
        owner_system="model_system",
        profiles=("system", "stable"),
        tags=("model", "runtime"),
    ),
    TestCaseDefinition(
        case_id="system.skill.runtime",
        title="技能运行时合同",
        layer="system",
        path="tests/skill_runtime_regression.py",
        owner_system="skill_system",
        profiles=("system",),
        tags=("skill", "runtime"),
    ),
    TestCaseDefinition(
        case_id="system.app.smoke",
        title="后端应用 smoke",
        layer="system",
        path="tests/app_smoke_regression.py",
        owner_system="runtime",
        profiles=("system", "stable"),
        tags=("api", "sse", "smoke"),
    ),
    TestCaseDefinition(
        case_id="system.harness.persistence",
        title="测试产物持久化合同",
        layer="system",
        path="tests/harness/persistence_report_regression.py",
        owner_system="test_system",
        profiles=("system",),
        tags=("harness", "artifact"),
    ),
    TestCaseDefinition(
        case_id="system.harness.gate",
        title="回归门禁合同",
        layer="system",
        path="tests/harness/regression_gate_regression.py",
        owner_system="test_system",
        profiles=("system",),
        tags=("harness", "profile"),
    ),
    TestCaseDefinition(
        case_id="scenario.long.catalog",
        title="长场景目录合同",
        layer="scenario",
        path="tests/system_eval/long_scenarios_regression.py",
        owner_system="test_system",
        profiles=("scenario",),
        tags=("scenario", "catalog"),
    ),
    TestCaseDefinition(
        case_id="scenario.long.runner.warning",
        title="长场景 warning 报告合同",
        layer="scenario",
        path="tests/system_eval/long_runner_warning_regression.py",
        owner_system="test_system",
        profiles=("scenario",),
        tags=("scenario", "report"),
    ),
)


LEGACY_CASES: tuple[TestCaseDefinition, ...] = ()


PROFILE_ORDER: dict[str, tuple[str, ...]] = {
    "chain": ("chain",),
    "functional": ("chain", "functional"),
    "system": ("chain", "functional", "system"),
    "scenario": ("scenario",),
    "stable": ("chain", "system"),
    "full": ("chain", "functional", "system", "scenario"),
}


def all_cases(*, include_legacy: bool = False, include_candidates: bool = False) -> list[TestCaseDefinition]:
    cases = list(ACTIVE_CASES)
    if include_legacy:
        cases.extend(LEGACY_CASES)
    if include_candidates:
        cases.extend(candidate_cases())
    return cases


def active_cases() -> list[TestCaseDefinition]:
    return list(ACTIVE_CASES)


def legacy_cases() -> list[TestCaseDefinition]:
    return list(LEGACY_CASES)


def candidate_cases() -> list[TestCaseDefinition]:
    registered = {case.path.replace("\\", "/") for case in list(ACTIVE_CASES) + list(LEGACY_CASES)}
    tests_root = _backend_root() / "tests"
    if not tests_root.exists():
        return []
    result: list[TestCaseDefinition] = []
    for path in _discover_test_files(tests_root):
        if path in registered:
            continue
        result.append(
            TestCaseDefinition(
                case_id=f"candidate.{_slug(path)}",
                title=f"候选测试：{Path(path).name}",
                layer=_guess_layer(path),
                path=path,
                owner_system=_guess_owner(path),
                status="candidate",
                tags=("candidate", _guess_owner(path)),
                reason="尚未重写到新测试体系或尚未确认是否进入 curated gate。",
            )
        )
    return result


def cases_for_profile(profile: str) -> list[TestCaseDefinition]:
    normalized = str(profile or "").strip() or "chain"
    if normalized not in PROFILE_ORDER:
        raise ValueError(f"Unsupported test profile: {profile}")
    profile_layers = set(PROFILE_ORDER[normalized])
    return [
        case
        for case in ACTIVE_CASES
        if case.status == "active"
        and (normalized in case.profiles or case.layer in profile_layers)
    ]


def case_registry_payload(*, include_legacy: bool = True) -> dict[str, Any]:
    candidates = candidate_cases()
    cases = all_cases(include_legacy=include_legacy) + candidates
    return {
        "profiles": {
            profile: {
                "layers": list(layers),
                "case_count": len(cases_for_profile(profile)),
            }
            for profile, layers in PROFILE_ORDER.items()
        },
        "layers": ("chain", "functional", "system", "scenario"),
        "active_cases": [case.to_dict() for case in ACTIVE_CASES],
        "legacy_cases": [case.to_dict() for case in LEGACY_CASES] if include_legacy else [],
        "candidate_cases": [case.to_dict() for case in candidates],
        "case_count": len(cases),
        "authority": "test_system.case_registry",
    }


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _discover_test_files(tests_root: Path) -> list[str]:
    backend_root = tests_root.parent
    result: list[str] = []
    for pattern in ("*_regression.py", "*_eval.py", "*_experiment.py", "*_smoke.py"):
        for path in tests_root.rglob(pattern):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                result.append(path.relative_to(backend_root).as_posix())
            except ValueError:
                continue
    return sorted(set(result))


def _guess_layer(path: str) -> TestLayer:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    if "/system_eval/" in normalized or name.endswith("_eval.py") or name.endswith("_experiment.py"):
        return "scenario"
    if "app_" in name or "/harness/" in normalized or "runtime" in name or "orchestration" in name:
        return "system"
    return "functional"


def _guess_owner(path: str) -> str:
    name = Path(path.replace("\\", "/")).name
    prefixes = (
        "memory",
        "retrieval",
        "pdf",
        "tool",
        "skill",
        "soul",
        "task",
        "operation",
        "orchestration",
        "query",
        "model",
        "document",
        "permission",
        "search",
        "harness",
    )
    for prefix in prefixes:
        if name.startswith(prefix):
            return f"{prefix}_system"
    if "system_eval/" in path.replace("\\", "/"):
        return "test_system"
    return "unknown"


def _slug(value: str) -> str:
    chars: list[str] = []
    for char in value.replace("\\", "/"):
        if char.isalnum():
            chars.append(char.lower())
        else:
            chars.append("_")
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "case"
