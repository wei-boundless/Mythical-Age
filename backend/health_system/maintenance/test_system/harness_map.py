from __future__ import annotations

from typing import Any

from .case_registry import TestCaseDefinition, all_cases, candidate_cases, cases_for_profile
from .harness_records import HarnessRecordBook, ManagedTestCase


OWNER_LABELS: dict[str, str] = {
    "test_system": "测试体系治理",
    "query_runtime": "入口适配链路",
    "task_system": "任务系统",
    "capability_system": "能力系统",
    "memory_system": "记忆系统",
    "soul_system": "灵魂投影系统",
    "skill_system": "技能系统",
    "model_system": "模型运行系统",
    "orchestration_system": "编排系统",
    "runtime": "运行时基础设施",
    "legacy_query": "旧 Query 链路",
    "legacy_worker": "旧 Worker 链路",
    "unknown": "待归属功能",
}


FEATURE_BOUNDARIES: dict[str, str] = {
    "test_system": "用例登记、运行 profile、产物治理、报告与问题草案。",
    "query_runtime": "QueryRuntime 只能作为统一 RuntimeLoop 的入口适配层。",
    "task_system": "任务理解、任务-操作 preview、任务绑定与链路权限。",
    "capability_system": "能力目录、资源契约、工具作用域与权限裁决。",
    "memory_system": "状态记忆、上下文策略、读写边界与长期记忆治理。",
    "soul_system": "Soul seed、ProjectionInstance、PromptManifest 与资源边界。",
    "skill_system": "Skill 合同、策略解析、工作流与运行时绑定。",
    "model_system": "模型运行适配、错误恢复与响应合同。",
    "orchestration_system": "RuntimeLoop、候选收集、提交门禁与 trace。",
    "runtime": "后端应用、配置、SSE 与系统启动合同。",
    "legacy_query": "旧链路保留为参考，不进入 curated gate。",
    "legacy_worker": "旧 worker 直连路径保留为迁移参考。",
    "unknown": "已发现测试文件，但尚未声明功能归属。",
}


TAG_PASS_CRITERIA: tuple[tuple[str, str], ...] = (
    ("runtime_loop", "RuntimeLoop 事件、checkpoint、terminal_reason 与监控摘要一致。"),
    ("operation_gate", "OperationGate 必须给出可解释的 allow/deny 结果。"),
    ("resource_policy", "ResourcePolicy 不能被任务、投影或 prompt 扩权。"),
    ("memory", "记忆读取、上下文注入和写入候选必须保持分层边界。"),
    ("soul", "灵魂投影只能改变工作姿态，不能授予工具或记忆权限。"),
    ("skill", "Skill 只能按声明合同暴露能力、输入边界和输出边界。"),
    ("tool", "工具调用必须满足注册表、作用域和输出合同。"),
    ("test_registry", "用例登记表必须覆盖 profile、layer、状态和治理分类。"),
    ("harness", "Harness 产物必须可持久化、可复盘、可映射到用例资产。"),
    ("scenario", "场景运行必须输出轮次、断言、trace 与报告证据。"),
)


def build_harness_map(
    *,
    records: HarnessRecordBook,
    agent_report: dict[str, Any],
) -> dict[str, Any]:
    cases = [*all_cases(), *candidate_cases()]
    governance_findings = [dict(item) for item in list(agent_report.get("findings") or []) if isinstance(item, dict)]
    issues = [item.to_dict() for item in records.issues]
    drafts = [item.to_dict() for item in records.case_drafts]

    issue_by_owner = _group_by(issues, "owner_system")
    findings_by_case = _group_by(governance_findings, "case_id")
    findings_by_path = _group_by(governance_findings, "path")
    drafts_by_issue = _group_by(drafts, "source_issue_id")

    case_rows: list[dict[str, Any]] = []
    feature_rows: dict[str, dict[str, Any]] = {}

    def register_row(row: dict[str, Any], *, finding_count: int = 0) -> None:
        feature_id = str(row["feature_id"])
        bucket = feature_rows.setdefault(
            feature_id,
            {
                "feature_id": feature_id,
                "title": str(row["feature_title"]),
                "owner_system": str(row["owner_system"]),
                "boundary": str(row["feature_boundary"]),
                "case_count": 0,
                "active_case_count": 0,
                "candidate_case_count": 0,
                "open_issue_count": 0,
                "governance_finding_count": 0,
                "case_ids": [],
                "case_paths": [],
                "issue_refs": [],
                "risk_status": "healthy",
            },
        )
        bucket["case_count"] += 1
        bucket["case_ids"].append(row["case_id"])
        if row["path"]:
            bucket["case_paths"].append(row["path"])
        if row["status"] == "active":
            bucket["active_case_count"] += 1
        elif row["status"] == "candidate":
            bucket["candidate_case_count"] += 1
        bucket["governance_finding_count"] += finding_count
        bucket["issue_refs"] = _merge_issue_refs(list(bucket["issue_refs"]), list(row["issue_refs"]))

    for case in cases:
        feature = _feature_for_case(case)
        feature_id = str(feature["feature_id"])
        case_findings = [
            *findings_by_case.get(case.case_id, []),
            *findings_by_path.get(case.path.replace("\\", "/"), []),
        ]
        linked_issues = list(issue_by_owner.get(case.owner_system, []))
        linked_drafts = [
            draft
            for issue in linked_issues
            for draft in drafts_by_issue.get(str(issue.get("issue_id") or ""), [])
        ]
        row = {
            "case_id": case.case_id,
            "title": case.title,
            "layer": case.layer,
            "path": case.path,
            "runner": case.runner,
            "status": case.status,
            "profiles": list(case.profiles),
            "owner_system": case.owner_system,
            "feature_id": feature_id,
            "feature_title": feature["title"],
            "feature_boundary": feature["boundary"],
            "behavior_under_test": _behavior_under_test(case, feature),
            "problem_statement": _problem_statement(case, linked_issues, case_findings),
            "pass_criteria": _pass_criteria(case),
            "assertions": list(case.assertions),
            "tags": list(case.tags),
            "replaces": list(case.replaces),
            "reason": case.reason,
            "issue_refs": [_issue_ref(item) for item in linked_issues],
            "case_draft_refs": [_draft_ref(item) for item in linked_drafts],
            "governance_findings": case_findings,
            "traceability": {
                "test_file": case.path,
                "harness_ref": f"{case.runner}:{case.path}",
                "profile_refs": list(case.profiles),
                "status": case.status,
                "owner_system": case.owner_system,
            },
        }
        case_rows.append(row)
        register_row(row, finding_count=len(case_findings))

    for managed_case in records.managed_cases:
        row = _managed_case_row(managed_case, issue_by_owner)
        case_rows.append(row)
        register_row(row)

    for feature in feature_rows.values():
        open_issues = [item for item in feature["issue_refs"] if item.get("status") not in {"resolved", "archived"}]
        feature["open_issue_count"] = len(open_issues)
        feature["risk_status"] = _feature_risk_status(feature)

    profile_matrix = [
        {
            "profile": profile,
            "case_count": len(cases_for_profile(profile)),
            "case_ids": [case.case_id for case in cases_for_profile(profile)],
        }
        for profile in ("chain", "functional", "system", "scenario", "stable", "full")
    ]

    return {
        "authority": "test_system.harness_map",
        "summary": {
            "feature_count": len(feature_rows),
            "case_count": len(case_rows),
            "active_case_count": sum(1 for item in case_rows if item["status"] == "active"),
            "candidate_case_count": sum(1 for item in case_rows if item["status"] == "candidate"),
            "open_issue_count": sum(1 for item in issues if item.get("status") not in {"resolved", "archived"}),
            "case_draft_count": len(drafts),
            "managed_case_count": len(records.managed_cases),
            "governance_finding_count": len(governance_findings),
            "unregistered_file_count": int(dict(agent_report.get("summary") or {}).get("unregistered_file_count") or 0),
        },
        "features": sorted(feature_rows.values(), key=lambda item: (str(item["risk_status"]), str(item["title"]))),
        "cases": sorted(case_rows, key=lambda item: (str(item["feature_title"]), str(item["layer"]), str(item["case_id"]))),
        "issues": issues,
        "case_drafts": drafts,
        "managed_cases": [item.to_dict() for item in records.managed_cases],
        "governance_findings": governance_findings,
        "profile_matrix": profile_matrix,
        "link_contract": {
            "case_to_feature": "owner_system -> feature_id",
            "case_to_file": "path -> backend test file",
            "case_to_problem": "owner_system / case_id / path -> harness issue or governance finding",
            "case_to_pass": "assertions + runner return code + profile membership",
        },
    }


def _group_by(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        value = str(item.get(key) or "").replace("\\", "/")
        if not value:
            continue
        grouped.setdefault(value, []).append(item)
    return grouped


def _feature_for_case(case: TestCaseDefinition) -> dict[str, Any]:
    return _feature_for_owner(case.owner_system)


def _feature_for_owner(owner_system: str) -> dict[str, Any]:
    owner = owner_system or "unknown"
    title = OWNER_LABELS.get(owner, owner)
    return {
        "feature_id": f"feature:{owner}",
        "title": title,
        "owner_system": owner,
        "boundary": FEATURE_BOUNDARIES.get(owner, "该功能尚未补充测试边界说明。"),
    }


def _behavior_under_test(case: TestCaseDefinition, feature: dict[str, Any]) -> str:
    if case.description:
        return case.description
    return f"{feature['title']}：{case.title}"


def _problem_statement(
    case: TestCaseDefinition,
    linked_issues: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> str:
    if findings:
        first = findings[0]
        return str(first.get("message") or first.get("recommendation") or "测试治理发现需要处理。")
    if linked_issues:
        first = linked_issues[0]
        return str(first.get("observed") or first.get("title") or "该功能已有待处理问题。")
    if case.reason:
        return case.reason
    if case.status == "candidate":
        return "测试文件已被发现，但尚未声明功能归属、通过标准和是否进入 curated gate。"
    return f"防止 {case.title} 在 {OWNER_LABELS.get(case.owner_system, case.owner_system)} 中回退。"


def _pass_criteria(case: TestCaseDefinition) -> list[str]:
    criteria = [item for item in case.assertions if item]
    criteria.append(f"{case.runner} 执行 `{case.path}` 返回码为 0。")
    if case.profiles:
        criteria.append(f"在 {', '.join(case.profiles)} profile 中作为门禁用例稳定通过。")
    if case.status == "candidate":
        criteria.append("补齐 owner_system、profiles、assertions 或迁移结论后才能进入正式门禁。")
    for tag, criterion in TAG_PASS_CRITERIA:
        if tag in case.tags and criterion not in criteria:
            criteria.append(criterion)
    return _dedupe(criteria)


def _issue_ref(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": str(issue.get("issue_id") or ""),
        "title": str(issue.get("title") or ""),
        "status": str(issue.get("status") or ""),
        "severity": str(issue.get("severity") or ""),
        "origin": str(issue.get("origin") or ""),
        "problem_node_id": str(issue.get("problem_node_id") or ""),
    }


def _draft_ref(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_id": str(draft.get("draft_id") or ""),
        "title": str(draft.get("title") or ""),
        "status": str(draft.get("status") or ""),
        "source_issue_id": str(draft.get("source_issue_id") or ""),
    }


def _managed_case_row(managed_case: ManagedTestCase, issue_by_owner: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    feature = _feature_for_owner(managed_case.owner_system)
    linked_issues = list(issue_by_owner.get(managed_case.owner_system, []))
    pass_criteria = list(managed_case.pass_criteria)
    if managed_case.path:
        pass_criteria.append(f"{managed_case.runner} 执行 `{managed_case.path}` 返回码为 0。")
    else:
        pass_criteria.append("补齐可执行路径后才能进入正式门禁。")
    return {
        "case_id": managed_case.case_id,
        "title": managed_case.title,
        "layer": managed_case.layer,
        "path": managed_case.path,
        "runner": managed_case.runner,
        "status": managed_case.status,
        "profiles": list(managed_case.profiles),
        "owner_system": managed_case.owner_system,
        "feature_id": feature["feature_id"],
        "feature_title": feature["title"],
        "feature_boundary": feature["boundary"],
        "behavior_under_test": managed_case.description or f"{feature['title']}：{managed_case.title}",
        "problem_statement": managed_case.problem_statement or "前端管理的规范化用例，等待绑定真实问题或运行证据。",
        "pass_criteria": _dedupe(pass_criteria),
        "scenario_turns": [dict(item) for item in managed_case.scenario_turns],
        "assertions": list(managed_case.assertions),
        "tags": [*list(managed_case.tags), "managed_case"],
        "replaces": [],
        "reason": "front_managed_case",
        "issue_refs": [_issue_ref(item) for item in linked_issues],
        "case_draft_refs": [],
        "governance_findings": [],
        "traceability": {
            "test_file": managed_case.path,
            "harness_ref": f"{managed_case.runner}:{managed_case.path}" if managed_case.path else "managed_case:pending_path",
            "profile_refs": list(managed_case.profiles),
            "status": managed_case.status,
            "owner_system": managed_case.owner_system,
            "source_template_id": managed_case.source_template_id,
        },
    }


def _merge_issue_refs(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = list(current)
    seen = {str(item.get("issue_id") or "") for item in result}
    for item in incoming:
        issue_id = str(item.get("issue_id") or "")
        if issue_id and issue_id not in seen:
            seen.add(issue_id)
            result.append(item)
    return result


def _feature_risk_status(feature: dict[str, Any]) -> str:
    if int(feature.get("governance_finding_count") or 0) > 0:
        return "needs_governance"
    if int(feature.get("open_issue_count") or 0) > 0:
        return "has_open_issue"
    if int(feature.get("candidate_case_count") or 0) > 0:
        return "has_candidates"
    return "healthy"


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
