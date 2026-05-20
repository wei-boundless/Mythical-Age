from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IntentDomainProfile:
    """Configurable signal profile for current-turn intent recognition."""

    domain_id: str
    target_domain_hint: str
    markers: tuple[str, ...] = ()
    explicit_markers: tuple[str, ...] = ()
    continuation_markers: tuple[str, ...] = ()
    scope_refinement_markers: tuple[str, ...] = ()
    delegation_markers: tuple[str, ...] = ()
    execution_strategy_candidates: tuple[str, ...] = ("single_react_loop",)
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "target_domain_hint": self.target_domain_hint,
            "markers": list(self.markers),
            "explicit_markers": list(self.explicit_markers),
            "continuation_markers": list(self.continuation_markers),
            "scope_refinement_markers": list(self.scope_refinement_markers),
            "delegation_markers": list(self.delegation_markers),
            "execution_strategy_candidates": list(self.execution_strategy_candidates),
            "metadata": dict(self.metadata or {}),
        }


@lru_cache(maxsize=1)
def default_intent_profiles() -> tuple[IntentDomainProfile, ...]:
    stored = _load_profiles_from_storage()
    return stored or _builtin_profiles()


def profile_by_domain() -> dict[str, IntentDomainProfile]:
    profiles = default_intent_profiles()
    result: dict[str, IntentDomainProfile] = {}
    for profile in profiles:
        result[profile.domain_id] = profile
        if profile.target_domain_hint and profile.target_domain_hint not in result:
            result.setdefault(profile.target_domain_hint, profile)
    return result


def marker_hits(text: str, markers: tuple[str, ...]) -> int:
    lowered = str(text or "").lower()
    return sum(1 for marker in markers if marker and str(marker).lower() in lowered)


def any_profile_marker(text: str, domain_id: str, marker_field: str = "markers") -> bool:
    profile = profile_by_domain().get(domain_id)
    if profile is None:
        return False
    markers = tuple(getattr(profile, marker_field, ()) or ())
    return marker_hits(text, markers) > 0


def _load_profiles_from_storage() -> tuple[IntentDomainProfile, ...]:
    path = _profiles_path()
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ()
    raw_profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(raw_profiles, list):
        return ()
    profiles: list[IntentDomainProfile] = []
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            continue
        profile = _profile_from_payload(raw)
        if profile is not None:
            profiles.append(profile)
    return tuple(profiles)


def _profile_from_payload(payload: dict[str, Any]) -> IntentDomainProfile | None:
    domain_id = str(payload.get("domain_id") or "").strip()
    target_domain_hint = str(payload.get("target_domain_hint") or payload.get("domain_hint") or domain_id).strip()
    if not domain_id or not target_domain_hint:
        return None
    return IntentDomainProfile(
        domain_id=domain_id,
        target_domain_hint=target_domain_hint,
        markers=_string_tuple(payload.get("markers")),
        explicit_markers=_string_tuple(payload.get("explicit_markers")),
        continuation_markers=_string_tuple(payload.get("continuation_markers")),
        scope_refinement_markers=_string_tuple(payload.get("scope_refinement_markers")),
        delegation_markers=_string_tuple(payload.get("delegation_markers")),
        execution_strategy_candidates=_string_tuple(payload.get("execution_strategy_candidates")) or ("single_react_loop",),
        metadata=dict(payload.get("metadata") or {}),
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _profiles_path() -> Path:
    return Path(__file__).resolve().parents[2] / "storage" / "orchestration" / "intent_domain_profiles.json"


def _builtin_profiles() -> tuple[IntentDomainProfile, ...]:
    return (
        IntentDomainProfile(
            domain_id="dataset",
            target_domain_hint="dataset",
            markers=("数据", "表格", "全表", "员工", "这些人", "这些员工", "前五", "前五名", "部门", "按部门", "仓库", "缺货", "薪资", "xlsx", "csv"),
            explicit_markers=("xlsx", "csv", "xls", "json", "parquet"),
            continuation_markers=("这些人", "这些员工", "这个表", "这张表", "全表", "刚才", "按部门", "按仓库", "再看"),
            scope_refinement_markers=("只", "仅", "不要扩展", "不要回到", "不要全表", "不要重算", "前五名", "前五", "这些人"),
            delegation_markers=("分析", "汇总", "统计", "查询", "找出", "处理", "总结"),
            execution_strategy_candidates=("specialist_handoff", "single_react_loop"),
        ),
        IntentDomainProfile(
            domain_id="pdf",
            target_domain_hint="pdf",
            markers=("pdf", "报告", "白皮书", "这一页", "那一页", "这份报告", "第三页", "第四页", "第二部分", "页面"),
            explicit_markers=(".pdf",),
            continuation_markers=("这份 pdf", "这个 pdf", "这份报告", "这个报告", "这一页", "那一页", "第二部分", "第三页", "第四页"),
            scope_refinement_markers=("只看", "只读", "这一页", "那一页", "这几页", "第三页", "第四页"),
            delegation_markers=("阅读", "总结", "摘读", "压成", "分析", "解读"),
            execution_strategy_candidates=("specialist_handoff", "single_react_loop"),
        ),
        IntentDomainProfile(
            domain_id="knowledge",
            target_domain_hint="knowledge",
            markers=("知识库", "资料库", "本地知识", "本地资料", "rag", "检索", "基于本地", "从库里"),
            explicit_markers=("知识库", "资料库", "本地知识", "本地资料"),
            delegation_markers=("检索", "查询", "查一下", "确认", "解释"),
            execution_strategy_candidates=("retrieval_augmented_answer", "single_react_loop"),
        ),
        IntentDomainProfile(
            domain_id="memory",
            target_domain_hint="memory",
            markers=("你记得", "还记得", "我让你", "我说过", "怎么称呼", "称呼我", "偏好", "约定"),
            execution_strategy_candidates=("single_react_loop",),
        ),
        IntentDomainProfile(
            domain_id="workflow_graph",
            target_domain_hint="workflow_graph",
            markers=("任务图", "图任务", "graph run", "多agent", "多个 agent", "规划、执行、审核", "按阶段协作", "节点", "handoff"),
            explicit_markers=("任务图", "图任务", "graph run"),
            delegation_markers=("协作", "按阶段", "编排", "调度"),
            execution_strategy_candidates=("graph_coordination_run", "single_agent_long_run"),
        ),
        IntentDomainProfile(
            domain_id="long_task",
            target_domain_hint="task",
            markers=("追踪", "排查", "修复", "执行计划", "落地", "一次性", "端到端", "重跑", "长跑", "六十轮", "测试报告"),
            delegation_markers=("追踪", "排查", "修复", "执行", "重跑", "检查"),
            execution_strategy_candidates=("single_agent_long_run", "single_react_loop"),
        ),
    )
