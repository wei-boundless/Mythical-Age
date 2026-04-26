from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from experiments.artifacts import read_json_file
from experiments.graph_mapping import graph_refs_for_issue
from experiments.memory_trace import has_turn_memory_trace
from experiments.prompt_manifest import extract_prompt_manifest_from_turn


NODE_LABELS = {
    "app-entry": "后端应用入口",
    "api-router": "接口路由层",
    "runtime-guard": "运行时守卫",
    "runtime-root": "运行时装配中心",
    "query-core": "对话执行引擎",
    "orchestration-control": "编排控制面",
    "planner": "Legacy 查询规划器",
    "prompt": "提示词组装",
    "memory": "记忆门面",
    "retrieval": "检索服务",
    "evidence": "证据编排",
    "tooling": "工具与技能运行",
    "model": "模型流式输出",
    "session-store": "会话存储",
    "storage": "项目持久层",
    "tests": "测试与观测",
}

ORCHESTRATION_NODE_LABELS = {
    "input": "用户输入",
    "followup": "Follow-up 仲裁",
    "planner": "任务规划",
    "execution-mode": "执行模式",
    "context": "上下文压缩",
    "memory": "记忆读取",
    "prompt": "Prompt 装配",
    "capability": "能力调度",
    "model": "模型生成",
    "worker": "Worker / Agent",
    "tool": "工具执行",
    "output": "输出收口",
    "persistence": "状态写回",
}

EDGE_LABELS = {
    "app-api": "挂载接口",
    "api-guard": "取得运行时",
    "guard-root": "就绪校验",
    "root-query": "注入执行依赖",
    "query-planner": "请求行为计划",
    "orchestration-planner": "兼容旧计划",
    "orchestration-runtime": "primary / fallback",
    "orchestration-prompt": "Prompt 策略",
    "orchestration-memory": "上下文策略",
    "orchestration-tools": "契约预检",
    "orchestration-evidence": "Worker 拓扑",
    "query-prompt": "组装系统提示",
    "prompt-memory": "读取上下文",
    "query-memory": "召回与写回",
    "query-tools": "调用能力",
    "query-evidence": "生成证据任务",
    "evidence-retrieval": "检索材料",
    "query-model": "请求模型生成",
    "api-model": "流式回传",
    "query-session": "读写会话",
    "memory-storage": "记忆落盘",
    "retrieval-storage": "索引读写",
    "runtime-storage": "刷新索引",
    "tests-query": "计划回放",
    "tests-query-runtime": "执行回归",
    "tests-storage": "产物沉淀",
}

BASE_NODE_IDS = [
    "api-router",
    "runtime-guard",
    "runtime-root",
    "query-core",
    "orchestration-control",
    "prompt",
    "model",
    "session-store",
]

BASE_EDGE_IDS = [
    "api-guard",
    "guard-root",
    "root-query",
    "query-prompt",
    "query-planner",
    "orchestration-runtime",
    "query-model",
    "api-model",
    "query-session",
]


def list_turns(output_dir: Path) -> list[dict[str, Any]]:
    turn_paths = sorted(output_dir.glob("artifacts/**/turn-*.json"), key=_turn_sort_key)
    turns = [_turn_summary(path, output_dir) for path in turn_paths]
    return [turn for turn in turns if turn]


def build_run_overlay(output_dir: Path) -> dict[str, Any]:
    run_id = output_dir.name
    run_result = read_json_file(output_dir / "run_result.json", {})
    issues = read_json_file(output_dir / "issues.json", [])
    turns = list_turns(output_dir)

    node_status: dict[str, str] = {}
    edge_status: dict[str, str] = {}
    node_events: dict[str, list[str]] = {}
    edge_events: dict[str, list[str]] = {}

    for node_id in ["tests", *BASE_NODE_IDS]:
        _merge_item(node_status, node_events, node_id, "passed", "测试运行进入主链")
    for edge_id in ["tests-query", *BASE_EDGE_IDS]:
        _merge_item(edge_status, edge_events, edge_id, "passed", "测试运行覆盖主链")

    for turn in turns:
        status = _overlay_status(str(turn.get("status") or "unknown"))
        overlay = build_turn_overlay(output_dir, str(turn.get("turn_id") or ""))
        for node in overlay.get("nodes", []):
            _merge_item(node_status, node_events, str(node.get("id")), status, str(node.get("reason") or "turn 覆盖"))
        for edge in overlay.get("edges", []):
            _merge_item(edge_status, edge_events, str(edge.get("id")), status, str(edge.get("reason") or "turn 覆盖"))

    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            refs = graph_refs_for_issue(issue)
            reason = str(refs.get("reason") or issue.get("summary") or "issue 命中")
            for node_id in refs.get("nodes", []):
                _merge_item(node_status, node_events, str(node_id), "failed", reason)
            for edge_id in refs.get("edges", []):
                _merge_item(edge_status, edge_events, str(edge_id), "failed", reason)

    summary = _run_summary(run_result)
    return {
        "run_id": run_id,
        "turn_id": None,
        "mode": "inferred",
        "status": "failed" if summary.get("failed", 0) else "passed",
        "summary": _run_summary_text(run_result, issues, turns),
        "nodes": [_node_payload(node_id, node_status[node_id], node_events.get(node_id, [])) for node_id in node_status],
        "edges": [_edge_payload(edge_id, edge_status[edge_id], edge_events.get(edge_id, [])) for edge_id in edge_status],
        "artifacts": _artifact_paths(output_dir),
        "prompt_manifest_id": None,
    }


def build_turn_overlay(output_dir: Path, turn_id: str) -> dict[str, Any]:
    turn_path = _find_turn_path(output_dir, turn_id)
    if turn_path is None:
        return {
            "run_id": output_dir.name,
            "turn_id": turn_id,
            "mode": "inferred",
            "status": "unknown",
            "summary": "没有找到对应 turn artifact。",
            "nodes": [],
            "edges": [],
            "artifacts": _artifact_paths(output_dir),
            "prompt_manifest_id": None,
        }

    payload = read_json_file(turn_path, {})
    result = _dict(payload.get("result"))
    plan = _dict(payload.get("plan"))
    events = list(payload.get("events") or [])
    event_names = [str(item.get("event") or "") for item in events if isinstance(item, dict)]
    status = _status_from_turn(payload)
    reason = _turn_reason(payload)
    node_ids = list(BASE_NODE_IDS)
    edge_ids = list(BASE_EDGE_IDS)
    event_notes = _turn_event_notes(payload)

    if _has_orchestration_signal(payload, event_names):
        _append_unique(node_ids, "orchestration-control")
        _append_unique(edge_ids, "query-planner")
        _append_unique(edge_ids, "orchestration-runtime")
        _append_unique(edge_ids, "tests-query")

    if _has_planner_signal(plan, result, event_names):
        _append_unique(node_ids, "planner")
        _append_unique(edge_ids, "orchestration-planner")

    if _has_memory_signal(payload, result, event_names):
        _append_unique(node_ids, "memory")
        _append_unique(node_ids, "storage")
        _append_unique(edge_ids, "orchestration-memory")
        _append_unique(edge_ids, "prompt-memory")
        _append_unique(edge_ids, "query-memory")
        _append_unique(edge_ids, "memory-storage")

    if _has_evidence_signal(plan, result, event_names):
        _append_unique(node_ids, "evidence")
        _append_unique(node_ids, "retrieval")
        _append_unique(node_ids, "storage")
        _append_unique(edge_ids, "orchestration-evidence")
        _append_unique(edge_ids, "query-evidence")
        _append_unique(edge_ids, "evidence-retrieval")
        _append_unique(edge_ids, "retrieval-storage")

    if _has_tool_signal(plan, result, event_names):
        _append_unique(node_ids, "tooling")
        _append_unique(edge_ids, "orchestration-tools")
        _append_unique(edge_ids, "query-tools")

    if _has_storage_signal(payload, result):
        _append_unique(node_ids, "storage")
        _append_unique(edge_ids, "tests-storage")

    failed_edges = _suspect_edges(payload)
    nodes = []
    for node_id in node_ids:
        node_status = _node_status(node_id, status, payload)
        nodes.append(_node_payload(node_id, node_status, event_notes, reason=reason))

    edges = []
    for edge_id in edge_ids:
        edge_status = "failed" if edge_id in failed_edges and status in {"failed", "warning"} else status
        edges.append(_edge_payload(edge_id, edge_status, event_notes, reason=reason))

    artifacts = _artifact_paths(output_dir)
    artifacts["turn"] = _repo_relative(turn_path)
    prompt_manifest = extract_prompt_manifest_from_turn(payload if isinstance(payload, dict) else {})
    if prompt_manifest:
        artifacts["prompt_manifest"] = str(prompt_manifest.get("prompt_id") or "")
    if has_turn_memory_trace(payload if isinstance(payload, dict) else {}):
        artifacts["memory_trace"] = "available"
    trace_url = str(result.get("trace_url") or "")
    if trace_url:
        artifacts["local_trace"] = trace_url

    return {
        "run_id": output_dir.name,
        "turn_id": turn_id,
        "mode": "inferred",
        "status": status,
        "summary": _turn_summary_text(payload),
        "nodes": nodes,
        "edges": edges,
        "artifacts": artifacts,
        "prompt_manifest_id": str(prompt_manifest.get("prompt_id") or "") if prompt_manifest else None,
    }


def _turn_summary(path: Path, output_dir: Path) -> dict[str, Any] | None:
    payload = read_json_file(path, {})
    if not isinstance(payload, dict):
        return None
    result = _dict(payload.get("result"))
    turn = _dict(payload.get("turn"))
    index = _turn_index(path, result)
    scenario = path.parent.name
    status = _status_from_turn(payload)
    failed_checks = list(result.get("failed_checks") or [])
    prompt_manifest = extract_prompt_manifest_from_turn(payload)
    memory_trace_available = has_turn_memory_trace(payload)
    problem_node_id = _turn_problem_node_id(payload, failed_checks)
    return {
        "turn_id": path.stem,
        "index": index,
        "scenario": scenario,
        "session_alias": str(result.get("session_alias") or turn.get("session") or ""),
        "status": status,
        "summary": _turn_summary_text(payload),
        "problem_node_id": problem_node_id,
        "problem_node_label": ORCHESTRATION_NODE_LABELS.get(problem_node_id, ""),
        "artifact_path": _repo_relative(path),
        "issue_count": len(failed_checks) or (1 if status == "failed" else 0),
        "has_trace": bool(result.get("trace_available") or result.get("trace_url")),
        "has_prompt_manifest": bool(prompt_manifest),
        "has_memory_trace": memory_trace_available,
    }


def _find_turn_path(output_dir: Path, turn_id: str) -> Path | None:
    normalized = str(turn_id or "").strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized.startswith("."):
        return None
    for path in output_dir.glob("artifacts/**/turn-*.json"):
        if path.stem == normalized:
            return path
    return None


def _turn_sort_key(path: Path) -> tuple[int, str]:
    return (_turn_index(path, {}), path.name)


def _turn_index(path: Path, result: dict[str, Any]) -> int:
    raw = result.get("index")
    if isinstance(raw, int):
        return raw
    match = re.search(r"turn-(\d+)", path.stem)
    return int(match.group(1)) if match else 0


def _status_from_turn(payload: dict[str, Any]) -> str:
    result = _dict(payload.get("result"))
    passed = result.get("passed")
    failed_checks = list(result.get("failed_checks") or [])
    orchestration_diff = _turn_orchestration_diff(payload)
    if str(orchestration_diff.get("status") or "") == "mismatch":
        return "failed"
    fallback = str(result.get("answer_source") or "").lower()
    fallback_reason = str(result.get("answer_fallback_reason") or "").lower()
    if passed is False or failed_checks:
        return "failed"
    if "fallback" in fallback or fallback_reason:
        return "warning"
    if passed is True:
        return "passed"
    return "unknown"


def _turn_problem_node_id(payload: dict[str, Any], failed_checks: list[Any]) -> str:
    result = _dict(payload.get("result"))
    orchestration_diff = _turn_orchestration_diff(payload)
    if str(orchestration_diff.get("status") or "") == "mismatch":
        first_field = _first_diff_field(orchestration_diff)
        return _problem_node_from_diff_field(first_field)
    text = " ".join(str(item) for item in failed_checks).lower()
    fallback = str(result.get("answer_source") or "").lower()
    fallback_reason = str(result.get("answer_fallback_reason") or "").lower()
    if not text and ("fallback" in fallback or fallback_reason):
        if result.get("worker_names"):
            return "worker"
        if result.get("tool_names"):
            return "tool"
        return "output"
    if not text:
        return ""
    if "followup" in text or "memory" in text or "preview" in text:
        return "memory"
    if "prompt" in text:
        return "prompt"
    if "tool" in text or "search_knowledge" in text:
        return "tool"
    if "worker" in text or "retrieval" in text or "evidence" in text:
        return "worker"
    if "response" in text or "contains" in text:
        return "output"
    return "output"


def _turn_orchestration_diff(payload: dict[str, Any]) -> dict[str, Any]:
    direct = _dict(payload.get("orchestration_diff"))
    if direct:
        return direct
    for item in reversed(list(payload.get("events") or [])):
        if not isinstance(item, dict) or item.get("event") != "orchestration_diff":
            continue
        return _dict(_dict(item.get("data")).get("diff"))
    return {}


def _first_diff_field(diff: dict[str, Any]) -> str:
    for item in list(diff.get("items") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") in {"mismatch", "warning"}:
            return str(item.get("field") or "")
    return ""


def _problem_node_from_diff_field(field: str) -> str:
    if field.startswith("executions[") or field == "executions.count":
        if ".worker_route" in field:
            return "worker"
        if ".tool_name" in field:
            return "tool"
        return "execution-mode"
    if field.startswith("topology.") or field in {"route", "execution_mode", "execution_kind"}:
        return "planner"
    if field.startswith("context_policy"):
        return "context"
    if field.startswith("prompt_policy") or "prompt" in field:
        return "prompt"
    if "contract" in field or "permission" in field:
        return "tool"
    if "worker" in field:
        return "worker"
    if "tool" in field:
        return "tool"
    return "planner"


def _overlay_status(status: str) -> str:
    return status if status in {"passed", "failed", "warning", "unknown"} else "unknown"


def _node_status(node_id: str, status: str, payload: dict[str, Any]) -> str:
    if status not in {"failed", "warning"}:
        return status
    if node_id in {"query-core", "model"}:
        return status
    if node_id == "orchestration-control" and _has_orchestration_signal(payload, _event_names(payload)):
        return status
    if node_id == "planner" and _has_planner_signal(_dict(payload.get("plan")), _dict(payload.get("result")), _event_names(payload)):
        return status
    if node_id == "tooling" and _has_tool_signal(_dict(payload.get("plan")), _dict(payload.get("result")), _event_names(payload)):
        return status
    if node_id in {"evidence", "retrieval"} and _has_evidence_signal(_dict(payload.get("plan")), _dict(payload.get("result")), _event_names(payload)):
        return status
    if node_id in {"memory", "storage"} and _has_memory_signal(payload, _dict(payload.get("result")), _event_names(payload)):
        return status
    return "passed"


def _suspect_edges(payload: dict[str, Any]) -> set[str]:
    result = _dict(payload.get("result"))
    text = _lower_blob(payload)
    suspect = {"query-model"}
    orchestration_diff = _turn_orchestration_diff(payload)
    if str(orchestration_diff.get("status") or "") == "mismatch":
        suspect.add("query-planner")
        suspect.add("orchestration-runtime")
    if result.get("answer_fallback_reason"):
        suspect.add("query-model")
    if "timeout" in text:
        suspect.add("query-model")
    if "tool" in text or "pdf_analysis" in text:
        suspect.add("orchestration-tools")
        suspect.add("query-tools")
    if "pdf" in text or "retrieval" in text or "evidence" in text:
        suspect.add("orchestration-evidence")
        suspect.add("query-evidence")
        suspect.add("evidence-retrieval")
    if "memory" in text or "context" in text or "状态" in text:
        suspect.add("orchestration-memory")
        suspect.add("query-memory")
        suspect.add("prompt-memory")
    return suspect


def _has_orchestration_signal(payload: dict[str, Any], event_names: list[str]) -> bool:
    text = _lower_blob(payload)
    return bool(
        payload.get("orchestration_plan")
        or payload.get("orchestration_diff")
        or "orchestration_plan" in event_names
        or "orchestration_diff" in event_names
        or "orchestration_runtime_control" in event_names
        or "orchestration_plan" in text
        or "orchestration_diff" in text
    )


def _has_planner_signal(plan: dict[str, Any], result: dict[str, Any], event_names: list[str]) -> bool:
    return bool(
        plan.get("route")
        or result.get("plan_route")
        or result.get("followup_mode")
        or "planner" in event_names
        or "context_management" in event_names
    )


def _has_memory_signal(payload: dict[str, Any], result: dict[str, Any], event_names: list[str]) -> bool:
    text = _lower_blob(payload)
    return bool(
        "memory_context" in event_names
        or result.get("memory_sync_ms")
        or "durable_memory" in text
        or "session_memory" in text
        or "hot_truth" in text
    )


def _has_evidence_signal(plan: dict[str, Any], result: dict[str, Any], event_names: list[str]) -> bool:
    text = " ".join(
        [
            str(plan.get("worker") or ""),
            str(plan.get("skill") or ""),
            str(result.get("plan_worker") or ""),
            str(result.get("answer_source") or ""),
            " ".join(event_names),
            " ".join(str(item) for item in result.get("worker_names") or []),
        ]
    ).lower()
    return any(token in text for token in ["retrieval", "rag", "pdf", "structured", "evidence", "worker"])


def _has_tool_signal(plan: dict[str, Any], result: dict[str, Any], event_names: list[str]) -> bool:
    text = " ".join(
        [
            str(plan.get("tool") or ""),
            str(plan.get("route") or ""),
            str(result.get("plan_tool") or ""),
            str(result.get("runtime_effective_route") or ""),
            str(result.get("answer_source") or ""),
            " ".join(event_names),
            " ".join(str(item) for item in result.get("tool_names") or []),
        ]
    ).lower()
    return any(token in text for token in ["tool", "skill", "direct_tool", "tool_start", "function"])


def _has_storage_signal(payload: dict[str, Any], result: dict[str, Any]) -> bool:
    text = _lower_blob(payload)
    return bool(result.get("trace_url") or "storage" in text or "session-memory" in text)


def _event_names(payload: dict[str, Any]) -> list[str]:
    events = list(payload.get("events") or [])
    return [str(item.get("event") or "") for item in events if isinstance(item, dict)]


def _turn_event_notes(payload: dict[str, Any]) -> list[str]:
    result = _dict(payload.get("result"))
    plan = _dict(payload.get("plan"))
    notes = [
        f"route={plan.get('route') or result.get('plan_route') or 'unknown'}",
        f"effective={result.get('runtime_effective_route') or 'unknown'}",
    ]
    tool_names = [str(item) for item in result.get("tool_names") or []]
    worker_names = [str(item) for item in result.get("worker_names") or []]
    if tool_names:
        notes.append(f"tools={', '.join(tool_names)}")
    if worker_names:
        notes.append(f"workers={', '.join(worker_names)}")
    if result.get("answer_source"):
        notes.append(f"answer_source={result.get('answer_source')}")
    if result.get("answer_fallback_reason"):
        notes.append(f"fallback={result.get('answer_fallback_reason')}")
    return notes


def _turn_reason(payload: dict[str, Any]) -> str:
    result = _dict(payload.get("result"))
    if result.get("answer_fallback_reason"):
        return f"本轮触发 fallback：{result.get('answer_fallback_reason')}"
    failed_checks = list(result.get("failed_checks") or [])
    if failed_checks:
        return f"本轮未通过检查：{', '.join(str(item) for item in failed_checks[:3])}"
    return "根据 turn artifact 中的 plan、events 和 result 推断运行链路。"


def _turn_summary_text(payload: dict[str, Any]) -> str:
    result = _dict(payload.get("result"))
    turn = _dict(payload.get("turn"))
    message = str(result.get("message") or turn.get("content") or "").strip()
    status = _status_from_turn(payload)
    route = str(result.get("runtime_effective_route") or result.get("plan_route") or _dict(payload.get("plan")).get("route") or "unknown")
    prefix = f"{status} · {route}"
    if message:
        return f"{prefix} · {_truncate(message, 72)}"
    return prefix


def _run_summary_text(run_result: dict[str, Any], issues: Any, turns: list[dict[str, Any]]) -> str:
    summary = _run_summary(run_result)
    first_issue = ""
    if isinstance(issues, list) and issues and isinstance(issues[0], dict):
        first_issue = str(issues[0].get("summary") or issues[0].get("title") or "")
    if first_issue:
        return first_issue
    return f"{summary.get('passed', 0)}/{summary.get('total', len(turns))} passed · {summary.get('failed', 0)} failed"


def _run_summary(run_result: dict[str, Any]) -> dict[str, int]:
    metadata = _dict(run_result.get("metadata"))
    results = list(run_result.get("results") or [])
    total = int(metadata.get("total") or len(results) or 0)
    passed = int(metadata.get("passed") or sum(1 for item in results if isinstance(item, dict) and item.get("passed")) or 0)
    failed = int(metadata.get("failed") or max(total - passed, 0))
    return {"total": total, "passed": passed, "failed": failed}


def _merge_item(
    statuses: dict[str, str],
    events: dict[str, list[str]],
    item_id: str,
    status: str,
    event: str,
) -> None:
    if not item_id:
        return
    current = statuses.get(item_id)
    statuses[item_id] = _worse_status(current, status)
    bucket = events.setdefault(item_id, [])
    if event and event not in bucket and len(bucket) < 5:
        bucket.append(event)


def _worse_status(current: str | None, next_status: str) -> str:
    rank = {"unknown": 0, "passed": 1, "warning": 2, "failed": 3}
    if current is None:
        return next_status
    return next_status if rank.get(next_status, 0) > rank.get(current, 0) else current


def _node_payload(node_id: str, status: str, events: list[str], *, reason: str | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "status": status,
        "label": NODE_LABELS.get(node_id, node_id),
        "events": events[:6],
        "latency_ms": None,
        "reason": reason or _default_reason(node_id, status),
    }


def _edge_payload(edge_id: str, status: str, events: list[str], *, reason: str | None = None) -> dict[str, Any]:
    return {
        "id": edge_id,
        "status": status,
        "label": EDGE_LABELS.get(edge_id, edge_id),
        "events": events[:6],
        "latency_ms": None,
        "reason": reason or _default_reason(edge_id, status),
    }


def _default_reason(item_id: str, status: str) -> str:
    return f"{item_id} 在本次推断链路中标记为 {status}。"


def _artifact_paths(output_dir: Path) -> dict[str, str]:
    return {
        "run_result": _repo_relative(output_dir / "run_result.json"),
        "issues": _repo_relative(output_dir / "issues.json"),
        "trace": _repo_relative(output_dir / "trace.jsonl"),
        "report": _repo_relative(output_dir / "report.md"),
    }


def _repo_relative(path: Path) -> str:
    try:
        repo_root = Path(__file__).resolve().parents[2]
        return str(path.resolve().relative_to(repo_root)).replace("\\", "/")
    except Exception:
        return str(path)


def _lower_blob(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, default=str).lower()
    except Exception:
        return str(payload).lower()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
