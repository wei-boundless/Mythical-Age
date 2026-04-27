from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.artifacts import read_json_file


NODE_DEFS: tuple[tuple[str, str, str], ...] = (
    ("input", "用户输入", "接收本轮用户请求，并绑定 session 与历史上下文。"),
    ("followup", "Follow-up 仲裁", "判断本轮是否续接已有任务、bundle item 或绑定对象。"),
    ("planner", "任务规划", "形成 route、execution mode、tool、skill 和 worker 决策。"),
    ("execution-mode", "执行模式", "选择 single_execution、bundle_execution 或 explicit_fanout。"),
    ("context", "上下文压缩", "整理历史窗口，决定是否压缩与保留哪些上下文。"),
    ("memory", "记忆读取", "读取状态记忆、长期记忆和上下文包。"),
    ("restore", "恢复仲裁", "把状态记忆、长期记忆和上下文句柄恢复结果投影为候选，并预检是否允许采用。"),
    ("prompt", "Prompt 装配", "组合 soul、core、memory、skill、turn 等提示词片段。"),
    ("capability", "能力调度", "决定是否进入工具、worker、证据编排或模型直答。"),
    ("model", "模型生成", "请求模型流式生成，并处理中途工具调用。"),
    ("worker", "Worker / Agent", "执行 retrieval、PDF、结构化数据等 worker 分支。"),
    ("tool", "工具执行", "执行 direct tool 或模型发起的工具调用。"),
    ("output", "输出收口", "通过 output boundary 选择最终可见答案。"),
    ("persistence", "状态写回", "写回会话、状态记忆和长期记忆抽取任务。"),
)

EDGE_DEFS: tuple[tuple[str, str, str, str], ...] = (
    ("input-followup", "input", "followup", "提交本轮请求"),
    ("followup-planner", "followup", "planner", "需要新规划或继续执行"),
    ("planner-execution", "planner", "execution-mode", "确定执行拓扑"),
    ("execution-context", "execution-mode", "context", "创建执行上下文"),
    ("context-memory", "context", "memory", "读取记忆上下文"),
    ("memory-restore", "memory", "restore", "提交恢复候选"),
    ("restore-prompt", "restore", "prompt", "注入允许使用的上下文"),
    ("prompt-capability", "prompt", "capability", "交给能力调度"),
    ("capability-model", "capability", "model", "模型主链"),
    ("capability-worker", "capability", "worker", "证据/worker 分支"),
    ("capability-tool", "capability", "tool", "工具分支"),
    ("model-output", "model", "output", "模型候选答案"),
    ("worker-output", "worker", "output", "worker canonical result"),
    ("tool-output", "tool", "output", "工具结果续写"),
    ("output-persistence", "output", "persistence", "答案与状态落盘"),
)


def build_turn_orchestration_snapshot(output_dir: Path, turn_id: str, artifact_path: str = "") -> dict[str, Any]:
    turn_path = _find_turn_path(output_dir, turn_id, artifact_path=artifact_path)
    if turn_path is None:
        return _empty_snapshot(
            source="test-turn",
            run_id=output_dir.name,
            turn_id=turn_id,
            status="failed",
            summary="没有找到对应 turn artifact。",
        )

    payload = read_json_file(turn_path, {})
    if not isinstance(payload, dict):
        return _empty_snapshot(
            source="test-turn",
            run_id=output_dir.name,
            turn_id=turn_id,
            status="failed",
            summary="turn artifact 不是可读取的 JSON 对象。",
        )

    plan = _dict(payload.get("plan"))
    result = _dict(payload.get("result"))
    turn = _dict(payload.get("turn"))
    events = _events(payload)
    event_names = [event["event"] for event in events]
    orchestration_plan = _latest_event_payload(events, "orchestration_plan").get("plan", {})
    if not isinstance(orchestration_plan, dict) or not orchestration_plan:
        orchestration_plan = _dict(payload.get("orchestration_plan"))
    orchestration_diff = _latest_event_payload(events, "orchestration_diff").get("diff", {})
    if not isinstance(orchestration_diff, dict) or not orchestration_diff:
        orchestration_diff = _dict(payload.get("orchestration_diff"))
    prompt_manifest = _dict(_latest_event_payload(events, "prompt_manifest").get("prompt_manifest"))
    topology = _dict(_dict(orchestration_plan).get("topology"))
    failed_checks = [str(item) for item in result.get("failed_checks", []) if str(item or "").strip()]
    passed = bool(result.get("passed", not failed_checks))
    fallback = str(result.get("answer_source") or "").lower()
    fallback_reason = str(result.get("answer_fallback_reason") or "").lower()
    status = "success" if passed else "failed"
    if status == "success" and ("fallback" in fallback or fallback_reason):
        status = "warning"
    execution_mode = str(topology.get("mode") or plan.get("execution_mode") or result.get("execution_mode") or "unknown")
    route = str(topology.get("route") or plan.get("route") or result.get("runtime_effective_route") or result.get("plan_route") or "unknown")
    problem_node_id = _problem_node_id(payload, event_names, failed_checks, _dict(orchestration_diff))

    visited = _visited_node_ids(plan, result, event_names, payload)
    nodes = [
        _node_payload(
            node_id,
            label,
            description,
            status=_node_status(node_id, visited, problem_node_id, status),
            summary=_node_summary(node_id, plan, result, payload, event_names),
            source_event=_node_source_event(node_id, event_names),
        )
        for node_id, label, description in NODE_DEFS
    ]
    _apply_plan_overlay_to_nodes(nodes, _dict(orchestration_plan), _dict(orchestration_diff))
    _apply_prompt_manifest_to_nodes(nodes, prompt_manifest)
    edges = [
        _edge_payload(edge_id, source, target, label, nodes)
        for edge_id, source, target, label in EDGE_DEFS
    ]
    summary = _summary_text(turn, plan, result, event_names, failed_checks)
    return {
        "source": "test-turn",
        "session_id": str(result.get("session_id") or ""),
        "run_id": output_dir.name,
        "turn_id": turn_id,
        "turn_index": int(result.get("index") or 0),
        "execution_mode": execution_mode,
        "route": route,
        "status": status,
        "summary": summary,
        "problem_node_id": problem_node_id,
        "nodes": nodes,
        "edges": edges,
        "events": events,
        "artifacts": {
            "turn": _repo_relative(turn_path),
            "trace": str(result.get("trace_url") or ""),
            "prompt_manifest": str(prompt_manifest.get("prompt_id") or ""),
        },
        "orchestration_plan": orchestration_plan if isinstance(orchestration_plan, dict) else {},
        "orchestration_diff": orchestration_diff if isinstance(orchestration_diff, dict) else {},
    }


def _empty_snapshot(*, source: str, run_id: str = "", turn_id: str = "", status: str, summary: str) -> dict[str, Any]:
    nodes = [
        _node_payload(node_id, label, description, status="idle", summary="", source_event="")
        for node_id, label, description in NODE_DEFS
    ]
    return {
        "source": source,
        "session_id": "",
        "run_id": run_id,
        "turn_id": turn_id,
        "turn_index": 0,
        "execution_mode": "unknown",
        "route": "unknown",
        "status": status,
        "summary": summary,
        "problem_node_id": "",
        "nodes": nodes,
        "edges": [_edge_payload(edge_id, source_id, target_id, label, nodes) for edge_id, source_id, target_id, label in EDGE_DEFS],
        "events": [],
        "artifacts": {},
    }


def _find_turn_path(output_dir: Path, turn_id: str, *, artifact_path: str = "") -> Path | None:
    artifact_candidate = _safe_artifact_path(output_dir, artifact_path)
    if artifact_candidate is not None:
        return artifact_candidate

    normalized = str(turn_id or "").strip()
    if not normalized:
        return None
    candidates = sorted(output_dir.glob("artifacts/**/turn-*.json"))
    for path in candidates:
        if path.stem == normalized or path.name == normalized:
            return path
    for path in candidates:
        payload = read_json_file(path, {})
        if not isinstance(payload, dict):
            continue
        result = _dict(payload.get("result"))
        if str(result.get("turn_id") or "").strip() == normalized:
            return path
    return None


def _safe_artifact_path(output_dir: Path, artifact_path: str) -> Path | None:
    raw = str(artifact_path or "").strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    candidates: list[Path] = []
    raw_path = Path(normalized)
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(output_dir / normalized)
        try:
            repo_root = output_dir.resolve().parents[2]
            candidates.append(repo_root / normalized)
        except IndexError:
            pass
    output_resolved = output_dir.resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(output_resolved)
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file() and resolved.suffix.lower() == ".json":
            return resolved
    return None


def _events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("events") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("event") or "unknown")
        data = _dict(item.get("data"))
        events.append(
            {
                "index": index + 1,
                "event": name,
                "node_id": _event_node_id(name),
                "summary": _event_summary(name, data),
                "ts_ms": item.get("ts_ms"),
                "data": data,
            }
        )
    return events


def _latest_event_payload(events: list[dict[str, Any]], event_name: str) -> dict[str, Any]:
    for item in reversed(events):
        if item.get("event") != event_name:
            continue
        data = item.get("data")
        return dict(data) if isinstance(data, dict) else {}
    return {}


def _visited_node_ids(
    plan: dict[str, Any],
    result: dict[str, Any],
    event_names: list[str],
    payload: dict[str, Any],
) -> set[str]:
    visited = {"input", "followup", "planner", "execution-mode", "context", "memory", "restore", "prompt", "capability", "output", "persistence"}
    route = str(plan.get("route") or result.get("runtime_effective_route") or result.get("plan_route") or "")
    if route:
        visited.add("model")
    if any(name.startswith("worker") or name == "retrieval" for name in event_names) or result.get("worker_names"):
        visited.add("worker")
    if any(name.startswith("tool") for name in event_names) or result.get("tool_names"):
        visited.add("tool")
    if any(name in event_names for name in ["token", "done"]) or result.get("response_text"):
        visited.add("model")
    if payload.get("memory_sync"):
        visited.add("persistence")
    return visited


def _problem_node_id(
    payload: dict[str, Any],
    event_names: list[str],
    failed_checks: list[str],
    orchestration_diff: dict[str, Any] | None = None,
) -> str:
    orchestration_diff = _dict(orchestration_diff) or _dict(payload.get("orchestration_diff"))
    if str(orchestration_diff.get("status") or "") == "mismatch":
        return "planner"
    result = _dict(payload.get("result"))
    fallback = str(result.get("answer_source") or "").lower()
    fallback_reason = str(result.get("answer_fallback_reason") or "").lower()
    if not failed_checks and ("fallback" in fallback or fallback_reason):
        if result.get("worker_names"):
            return "worker"
        if result.get("tool_names"):
            return "tool"
        return "output"
    if not failed_checks and "error" not in event_names:
        return ""
    if "error" in event_names:
        return "model"
    text = " ".join(failed_checks).lower()
    if "memory" in text or "preview" in text or "followup" in text:
        return "memory"
    if "tool" in text or "search_knowledge" in text:
        return "tool"
    if "worker" in text or "retrieval" in text or "evidence" in text:
        return "worker"
    if "prompt" in text:
        return "prompt"
    if "response" in text or "contains" in text:
        return "output"
    return "output"


def _node_status(node_id: str, visited: set[str], problem_node_id: str, snapshot_status: str) -> str:
    if node_id == problem_node_id:
        return "failed"
    if node_id not in visited:
        return "idle"
    if snapshot_status == "failed" and node_id in {"output", "persistence"}:
        return "warning"
    return "success"


def _node_summary(
    node_id: str,
    plan: dict[str, Any],
    result: dict[str, Any],
    payload: dict[str, Any],
    event_names: list[str],
) -> str:
    if node_id == "input":
        return str(result.get("message") or _dict(payload.get("turn")).get("content") or "读取到本轮输入。")
    if node_id == "followup":
        return str(result.get("followup_mode") or _dict(result.get("main_context")).get("followup_mode") or "未记录 follow-up 模式。")
    if node_id == "planner":
        return f"route={plan.get('route') or result.get('plan_route') or 'unknown'} / tool={plan.get('tool') or '-'} / worker={plan.get('worker') or '-'} / skill={plan.get('skill') or '-'}"
    if node_id == "execution-mode":
        return f"execution_mode={plan.get('execution_mode') or result.get('execution_mode') or 'unknown'} / subqueries={len(plan.get('subqueries') or [])}"
    if node_id == "context":
        timing = _dict(result.get("timing"))
        return f"事件数 {timing.get('event_count') or len(event_names)}，耗时 {timing.get('duration_ms') or '-'} ms。"
    if node_id == "memory":
        memory_sync = _dict(payload.get("memory_sync"))
        return f"session summary {memory_sync.get('session_summary_chars') or 0} chars / durable saved {memory_sync.get('durable_saved') or 0}"
    if node_id == "restore":
        restore = _restore_authority_from_payload(payload)
        if restore:
            gate = _dict(restore.get("adoption_gate"))
            dry_run = _dict(restore.get("dry_run_comparison"))
            return (
                f"候选 {restore.get('candidate_count') or 0} / "
                f"采用门禁 {gate.get('state') or 'unknown'} / "
                f"对照 {dry_run.get('state') or 'unknown'}"
            )
        return "本轮未记录恢复仲裁。"
    if node_id == "prompt":
        return "prompt_manifest" if "prompt_manifest" in event_names or result.get("prompt_manifest_id") else "该 turn 未记录 prompt manifest。"
    if node_id == "capability":
        return f"tools={', '.join(result.get('tool_names') or []) or '-'} / workers={', '.join(result.get('worker_names') or []) or '-'}"
    if node_id == "model":
        return f"terminal={_dict(result.get('timing')).get('terminal_event') or 'unknown'} / first_token={_dict(result.get('timing')).get('first_token_ms') or '-'}"
    if node_id == "worker":
        return ", ".join(result.get("worker_names") or []) or "本轮没有 worker 分支。"
    if node_id == "tool":
        return ", ".join(result.get("tool_names") or []) or "本轮没有 direct/tool-call 分支。"
    if node_id == "output":
        return f"{result.get('answer_channel') or '-'} / {result.get('answer_source') or '-'} / leak={', '.join(result.get('answer_leak_flags') or []) or '-'}"
    if node_id == "persistence":
        return f"persisted_matches_done={result.get('persisted_matches_done', '-')}"
    return ""


def _node_source_event(node_id: str, event_names: list[str]) -> str:
    preferred = {
        "context": "context_management",
        "memory": "memory_context",
        "restore": "orchestration_runtime_control",
        "prompt": "prompt_manifest",
        "worker": "worker_end",
        "tool": "tool_end",
        "output": "done",
        "persistence": "done",
    }
    target = preferred.get(node_id, "")
    if target and target in event_names:
        return target
    return event_names[-1] if event_names and node_id in {"model", "output", "persistence"} else ""


def _event_node_id(event_name: str) -> str:
    if event_name in {"orchestration_plan", "orchestration_runtime_control"}:
        return "execution-mode"
    if event_name == "orchestration_diff":
        return "output"
    if event_name == "context_management":
        return "context"
    if event_name == "memory_context":
        return "memory"
    if event_name == "prompt_manifest":
        return "prompt"
    if event_name.startswith("worker") or event_name == "retrieval":
        return "worker"
    if event_name.startswith("tool"):
        return "tool"
    if event_name in {"token", "debug"}:
        return "model"
    if event_name in {"done", "error"}:
        return "output"
    return "capability"


def _event_summary(event_name: str, data: dict[str, Any]) -> str:
    if event_name == "orchestration_runtime_control":
        return (
            f"runtime control: {data.get('source') or 'legacy'} / "
            f"{data.get('execution_mode') or 'unknown'} / "
            f"primary={bool(data.get('primary_active'))}"
        )
    if event_name == "done":
        return str(data.get("answer_source") or data.get("content") or "完成输出")[:220]
    if event_name == "error":
        return str(data.get("error") or "执行失败")
    if event_name.startswith("tool"):
        return str(data.get("tool") or "tool")
    if event_name.startswith("worker"):
        return str(data.get("worker") or data.get("task_status") or "worker")
    if event_name == "prompt_manifest":
        manifest = _dict(data.get("prompt_manifest"))
        return f"{manifest.get('total_sections') or 0} sections / {manifest.get('total_chars') or 0} chars"
    if event_name == "memory_context":
        return "状态记忆与长期记忆上下文已生成。"
    if event_name == "context_management":
        return "上下文窗口已整理。"
    return str(data.get("kind") or event_name)


def _node_payload(
    node_id: str,
    label: str,
    description: str,
    *,
    status: str,
    summary: str,
    source_event: str,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "index": [item[0] for item in NODE_DEFS].index(node_id) + 1,
        "label": label,
        "description": description,
        "status": status,
        "summary": summary,
        "source_event": source_event,
        "source_module": "",
        "reasons": [],
        "inputs": {},
        "outputs": {},
        "refs": {},
    }


def _apply_plan_overlay_to_nodes(
    nodes: list[dict[str, Any]],
    orchestration_plan: dict[str, Any],
    orchestration_diff: dict[str, Any],
) -> None:
    if not orchestration_plan:
        return
    by_id = {str(node.get("id") or ""): node for node in nodes}
    plan_id = str(orchestration_plan.get("plan_id") or "")
    topology = _dict(orchestration_plan.get("topology"))
    if topology:
        node = by_id.get("execution-mode")
        if node is not None:
            node["summary"] = (
                f"mode={topology.get('mode') or 'unknown'} / "
                f"kind={topology.get('execution_kind') or 'agent'} / "
                f"branches={topology.get('branch_count') or 1}"
            )
            node["outputs"] = topology
            node["refs"] = {"orchestration_plan_id": plan_id}

    for decision in list(orchestration_plan.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        node_id = _decision_node_id(str(decision.get("node_id") or ""))
        node = by_id.get(node_id)
        if node is None:
            continue
        outputs = _dict(decision.get("outputs"))
        inputs = _dict(decision.get("inputs"))
        reasons = [str(item) for item in list(decision.get("reasons") or []) if str(item).strip()]
        risks = [str(item) for item in list(decision.get("risks") or []) if str(item).strip()]
        node["source_module"] = str(decision.get("owner_module") or "")
        node["inputs"] = inputs
        node["outputs"] = outputs
        node["reasons"] = reasons + risks
        node["refs"] = {
            "orchestration_plan_id": plan_id,
            "orchestration_decision_id": str(decision.get("node_id") or ""),
        }
        summary = _decision_summary(node_id, outputs, reasons)
        if summary:
            node["summary"] = summary

    diagnostics = _dict(orchestration_plan.get("diagnostics"))
    restore_authority = _dict(diagnostics.get("restore_authority"))
    if restore_authority:
        node = by_id.get("restore")
        if node is not None:
            node["source_module"] = "orchestration.restore_authority"
            node["source_event"] = "orchestration_runtime_control"
            node["outputs"] = restore_authority
            node["reasons"] = [str(item) for item in list(restore_authority.get("blockers") or []) if str(item).strip()]
            node["refs"] = {
                "orchestration_plan_id": plan_id,
                "phase": str(restore_authority.get("phase") or "7F"),
            }
            node["summary"] = _decision_summary("restore", restore_authority, node["reasons"])

    if str(orchestration_diff.get("status") or "") == "mismatch":
        planner = by_id.get("planner")
        if planner is not None:
            planner["status"] = "failed"
            planner["summary"] = str(orchestration_diff.get("summary") or "编排计划与实际执行存在偏移。")
            planner["outputs"] = {
                **_dict(planner.get("outputs")),
                "orchestration_diff": orchestration_diff,
            }
            planner["reasons"] = _diff_mismatch_reasons(orchestration_diff)


def _apply_prompt_manifest_to_nodes(nodes: list[dict[str, Any]], prompt_manifest: dict[str, Any]) -> None:
    if not prompt_manifest:
        return
    prompt_node = next((node for node in nodes if str(node.get("id") or "") == "prompt"), None)
    if prompt_node is None:
        return
    sections = []
    for index, item in enumerate(list(prompt_manifest.get("sections") or [])):
        section = _dict(item)
        if not section:
            continue
        sections.append(
            {
                "id": str(section.get("id") or f"section-{index + 1}"),
                "title": str(section.get("title") or "未命名片段"),
                "layer": str(section.get("layer") or "unknown"),
                "source": str(section.get("source") or "unknown"),
                "model_visible": bool(section.get("model_visible")),
                "chars": int(section.get("chars") or 0),
                "preview": str(section.get("preview") or ""),
                "order": int(section.get("order") or index + 1),
            }
        )
    prompt_node["status"] = "success"
    prompt_node["summary"] = (
        f"{prompt_manifest.get('total_sections') or len(sections)} sections / "
        f"{prompt_manifest.get('total_chars') or sum(item['chars'] for item in sections)} chars"
    )
    prompt_node["outputs"] = {
        "prompt_id": str(prompt_manifest.get("prompt_id") or ""),
        "assembly_order": list(prompt_manifest.get("assembly_order") or []),
        "total_sections": int(prompt_manifest.get("total_sections") or len(sections)),
        "total_chars": int(prompt_manifest.get("total_chars") or sum(item["chars"] for item in sections)),
        "debug_policy": str(prompt_manifest.get("debug_policy") or ""),
        "sections": sections,
    }
    prompt_node["reasons"] = [
        f"#{item['order']} {item['title']} <= {item['source']}"
        for item in sections[:6]
    ]
    prompt_node["refs"] = {
        **_dict(prompt_node.get("refs")),
        "prompt_manifest_id": str(prompt_manifest.get("prompt_id") or ""),
    }


def _decision_node_id(node_id: str) -> str:
    return {
        "memory-intent": "memory",
        "restore-authority": "restore",
        "task-understanding": "planner",
        "execution-topology": "execution-mode",
        "skill-policy": "capability",
        "capability-dispatch": "capability",
        "contract-policy": "tool",
        "execution": "capability",
        "safety": "output",
    }.get(node_id, node_id)


def _decision_summary(node_id: str, outputs: dict[str, Any], reasons: list[str]) -> str:
    if node_id == "input":
        return f"session={outputs.get('session_id') or '-'} / history={outputs.get('history_count') or 0}"
    if node_id == "memory":
        return (
            f"intent={outputs.get('intent') or 'general'} / "
            f"read={outputs.get('read_mode') or 'none'} / "
            f"write={outputs.get('write_mode') or 'none'}"
        )
    if node_id == "restore":
        return (
            f"候选={outputs.get('candidate_count') or 0} / "
            f"门禁={_dict(outputs.get('adoption_gate')).get('state') or '-'} / "
            f"dry-run={_dict(outputs.get('dry_run_comparison')).get('state') or '-'}"
        )
    if node_id == "planner":
        return (
            f"route={outputs.get('route') or 'unknown'} / "
            f"posture={outputs.get('execution_posture') or '-'} / "
            f"task={outputs.get('task_kind') or '-'}"
        )
    if node_id == "execution-mode":
        return (
            f"mode={outputs.get('mode') or 'unknown'} / "
            f"kind={outputs.get('execution_kind') or 'agent'} / "
            f"branches={outputs.get('branch_count') or 1}"
        )
    if node_id == "capability":
        selected_tool = _dict(outputs.get("selected_tool"))
        selected_worker = _dict(outputs.get("selected_worker"))
        return (
            f"tool={selected_tool.get('tool_name') or outputs.get('tool_name') or '-'} / "
            f"worker={outputs.get('worker_route') or selected_worker.get('worker_route') or '-'}"
        )
    if node_id == "tool":
        return (
            f"contract_preview={outputs.get('preview_count') or len(list(outputs.get('contract_previews') or []))} / "
            f"blocked={outputs.get('blocked_count') or 0}"
        )
    return "; ".join(reasons[:2])


def _diff_mismatch_reasons(diff: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for item in list(diff.get("items") or []):
        if not isinstance(item, dict) or str(item.get("status") or "") != "mismatch":
            continue
        reasons.append(
            f"{item.get('field') or 'unknown'}: expected={item.get('expected')!r}, actual={item.get('actual')!r}"
        )
    return reasons


def _edge_payload(edge_id: str, source: str, target: str, label: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    status_by_id = {str(node.get("id")): str(node.get("status")) for node in nodes}
    source_status = status_by_id.get(source, "idle")
    target_status = status_by_id.get(target, "idle")
    status = "idle"
    if "failed" in {source_status, target_status}:
        status = "failed"
    elif "warning" in {source_status, target_status}:
        status = "warning"
    elif source_status in {"success", "visited"} and target_status in {"success", "visited"}:
        status = "success"
    return {
        "id": edge_id,
        "from": source,
        "to": target,
        "label": label,
        "status": status,
        "summary": label,
    }


def _summary_text(
    turn: dict[str, Any],
    plan: dict[str, Any],
    result: dict[str, Any],
    event_names: list[str],
    failed_checks: list[str],
) -> str:
    if failed_checks:
        return f"Turn {result.get('index') or '?'} 未通过：{'; '.join(failed_checks[:3])}"
    return (
        f"Turn {result.get('index') or '?'} 走 {plan.get('execution_mode') or result.get('execution_mode') or 'unknown'}，"
        f"route={plan.get('route') or result.get('runtime_effective_route') or 'unknown'}，"
        f"事件 {len(event_names)} 个。"
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _restore_authority_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    events = _events(payload)
    runtime_control = _latest_event_payload(events, "orchestration_runtime_control")
    restore = _dict(
        _dict(_dict(runtime_control.get("diagnostics")).get("phase7_readiness")).get("restore_authority")
    )
    if restore:
        return restore
    plan = _dict(_latest_event_payload(events, "orchestration_plan").get("plan"))
    return _dict(_dict(plan.get("diagnostics")).get("restore_authority"))


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve())).replace("\\", "/")
    except ValueError:
        return str(path)
