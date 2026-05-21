from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


@dataclass(frozen=True, slots=True)
class ContinuationDomainProfile:
    domain_id: str
    source_kind: str
    file_kind: str = ""
    state_slots: tuple[str, ...] = ()
    binding_key: str = ""
    followup_target_kind: str = ""
    subset_followup_target_kind: str = "active_subset"
    path_extensions: tuple[str, ...] = ()
    task_kinds: tuple[str, ...] = ()
    capability_kinds: tuple[str, ...] = ()
    compatible_markers: tuple[str, ...] = ()
    subset_markers: tuple[str, ...] = ()
    conflict_markers: tuple[str, ...] = ()
    handle_prefixes: tuple[str, ...] = ()
    delegation_kind: str = ""
    target_agent_id: str = ""
    return_contract: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "source_kind": self.source_kind,
            "file_kind": self.file_kind,
            "state_slots": list(self.state_slots),
            "binding_key": self.binding_key,
            "followup_target_kind": self.followup_target_kind,
            "subset_followup_target_kind": self.subset_followup_target_kind,
            "path_extensions": list(self.path_extensions),
            "task_kinds": list(self.task_kinds),
            "capability_kinds": list(self.capability_kinds),
            "compatible_markers": list(self.compatible_markers),
            "subset_markers": list(self.subset_markers),
            "conflict_markers": list(self.conflict_markers),
            "handle_prefixes": list(self.handle_prefixes),
            "delegation_kind": self.delegation_kind,
            "target_agent_id": self.target_agent_id,
            "return_contract": dict(self.return_contract or {}),
            "metadata": dict(self.metadata or {}),
        }


@lru_cache(maxsize=1)
def default_continuation_profiles() -> tuple[ContinuationDomainProfile, ...]:
    stored = _load_profiles_from_storage()
    return stored or _builtin_profiles()


def profile_by_domain() -> dict[str, ContinuationDomainProfile]:
    result: dict[str, ContinuationDomainProfile] = {}
    for profile in default_continuation_profiles():
        result[profile.domain_id] = profile
        if profile.source_kind not in result or profile.domain_id == profile.source_kind:
            result[profile.source_kind] = profile
    return result


def _load_profiles_from_storage() -> tuple[ContinuationDomainProfile, ...]:
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
    profiles: list[ContinuationDomainProfile] = []
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            continue
        profile = _profile_from_payload(raw)
        if profile is not None:
            profiles.append(profile)
    return tuple(profiles)


def _profile_from_payload(payload: dict[str, Any]) -> ContinuationDomainProfile | None:
    domain_id = str(payload.get("domain_id") or "").strip()
    source_kind = str(payload.get("source_kind") or "").strip()
    if not domain_id or not source_kind:
        return None
    return ContinuationDomainProfile(
        domain_id=domain_id,
        source_kind=source_kind,
        file_kind=str(payload.get("file_kind") or "").strip(),
        state_slots=_string_tuple(payload.get("state_slots")),
        binding_key=str(payload.get("binding_key") or "").strip(),
        followup_target_kind=str(payload.get("followup_target_kind") or "").strip(),
        subset_followup_target_kind=str(payload.get("subset_followup_target_kind") or "active_subset").strip(),
        path_extensions=_string_tuple(payload.get("path_extensions")),
        task_kinds=_string_tuple(payload.get("task_kinds")),
        capability_kinds=_string_tuple(payload.get("capability_kinds")),
        compatible_markers=_string_tuple(payload.get("compatible_markers")),
        subset_markers=_string_tuple(payload.get("subset_markers")),
        conflict_markers=_string_tuple(payload.get("conflict_markers")),
        handle_prefixes=_string_tuple(payload.get("handle_prefixes")),
        delegation_kind=str(payload.get("delegation_kind") or "").strip(),
        target_agent_id=str(payload.get("target_agent_id") or "").strip(),
        return_contract=dict(payload.get("return_contract") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return tuple(str(item).strip() for item in list(value or []) if str(item).strip())


def _profiles_path() -> Path:
    return ProjectLayout.from_backend_dir(Path(__file__).resolve().parents[1]).orchestration_dir / "continuation_domain_profiles.json"


def _builtin_profiles() -> tuple[ContinuationDomainProfile, ...]:
    return (
        ContinuationDomainProfile(
            domain_id="dataset",
            source_kind="dataset",
            file_kind="dataset",
            state_slots=("active_dataset", "committed_dataset"),
            binding_key="active_dataset",
            followup_target_kind="active_dataset",
            path_extensions=("xlsx", "csv", "xls", "json", "parquet"),
            task_kinds=("structured_data",),
            capability_kinds=("structured_data", "dataset_analysis"),
            compatible_markers=(
                "数据",
                "表",
                "表格",
                "全表",
                "员工",
                "这些人",
                "这些员工",
                "前五",
                "前五名",
                "部门",
                "按部门",
                "仓库",
                "缺货",
                "薪资",
                "xlsx",
                "csv",
            ),
            subset_markers=("只基于", "刚才这", "这前五", "这些人", "这些员工", "不要扩展", "不要回到全表", "不要全表", "不要重算"),
            conflict_markers=("pdf", "报告", "第几页", "第三页", "第四页", "这一页", "第二部分"),
            handle_prefixes=("result:structured", "subset:selection", "subset:structured"),
            delegation_kind="table_analysis",
            target_agent_id="agent:table_analyst",
            return_contract={
                "required": ["summary", "answer_candidate"],
                "optional": ["evidence_refs", "artifact_refs", "confidence", "limitations", "consumed_handles", "produced_handles"],
            },
        ),
        ContinuationDomainProfile(
            domain_id="pdf",
            source_kind="pdf",
            file_kind="pdf",
            state_slots=("active_pdf", "committed_pdf"),
            binding_key="active_pdf",
            followup_target_kind="active_pdf",
            path_extensions=("pdf",),
            task_kinds=("pdf", "document_analysis"),
            capability_kinds=("pdf", "document_analysis"),
            compatible_markers=("pdf", "报告", "白皮书", "第几页", "第三页", "第四页", "这一页", "那一页", "这份报告", "第二部分", "页面"),
            subset_markers=("这一页", "那一页", "这几页", "第三页", "第四页"),
            conflict_markers=("全表", "员工", "这些人", "这些员工", "按部门", "仓库", "缺货", "薪资", "xlsx", "csv"),
            handle_prefixes=("result:pdf", "subset:pdf"),
            delegation_kind="pdf_reading",
            target_agent_id="agent:pdf_reader",
            return_contract={
                "required": ["summary", "answer_candidate"],
                "optional": ["evidence_refs", "artifact_refs", "confidence", "limitations", "consumed_handles", "produced_handles"],
            },
        ),
        ContinuationDomainProfile(
            domain_id="task_bundle",
            source_kind="bundle_result",
            state_slots=(),
            followup_target_kind="bundle_ordinals",
            task_kinds=("bundle_result",),
            capability_kinds=("bundle", "task_bundle"),
            compatible_markers=("子任务", "第一个", "第二个", "第三个", "只展开", "压成一句话"),
            subset_markers=("只展开", "只要", "不要再提"),
            handle_prefixes=("bundle:", "result:bundle"),
            delegation_kind="bounded_analysis",
        ),
        ContinuationDomainProfile(
            domain_id="workflow_graph",
            source_kind="workflow_graph",
            state_slots=(),
            followup_target_kind="workflow_graph",
            task_kinds=("workflow_graph", "graph_coordination"),
            capability_kinds=("workflow_graph", "coordination"),
            compatible_markers=("任务图", "图任务", "节点", "阶段", "handoff", "多agent", "协作"),
            handle_prefixes=("graph.", "coordination:"),
        ),
    )
