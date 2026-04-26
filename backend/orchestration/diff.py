from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


DiffStatus = Literal["matched", "mismatch", "warning", "unknown"]


@dataclass(slots=True)
class OrchestrationDiffItem:
    field: str
    expected: Any
    actual: Any
    status: DiffStatus
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OrchestrationPlanDiff:
    plan_id: str
    status: DiffStatus
    summary: str
    items: list[OrchestrationDiffItem] = field(default_factory=list)
    actual: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status,
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
            "actual": dict(self.actual),
        }


def build_plan_actual_diff(
    plan: dict[str, Any] | None,
    *,
    actual: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(plan, dict) or not plan:
        return OrchestrationPlanDiff(
            plan_id="",
            status="unknown",
            summary="没有可比较的 orchestration plan。",
            actual=actual,
        ).to_dict()

    topology = dict(plan.get("topology") or {})
    expected_execution = _first_execution(plan)
    execution_kind = str(topology.get("execution_kind") or expected_execution.get("execution_kind") or "")
    actual_status = str(actual.get("status") or "")
    expected_executions = _expected_executions(plan)
    items = [
        _compare("topology.mode", topology.get("mode"), actual.get("execution_mode")),
        _compare("topology.route", topology.get("route"), actual.get("route")),
        _compare("topology.execution_kind", topology.get("execution_kind"), actual.get("execution_kind")),
    ]
    if len(expected_executions) <= 1:
        items.extend(
            [
                _compare("execution.tool_name", expected_execution.get("tool_name"), actual.get("tool_name")),
                _compare("execution.worker_route", expected_execution.get("worker_route"), actual.get("worker_route")),
            ]
        )
    items.extend(_execution_list_items(plan, actual))
    items.extend(_policy_observation_items(plan, actual=actual, execution_kind=execution_kind))
    relevant_items = [
        item for item in items
        if item.status != "unknown" or item.expected not in (None, "", [], {})
    ]
    if actual_status == "error":
        relevant_items.append(
            OrchestrationDiffItem(
                field="runtime.status",
                expected="done",
                actual="error",
                status="mismatch",
                reason=str(actual.get("error") or "runtime_error"),
            )
        )

    if any(item.status == "mismatch" for item in relevant_items):
        status: DiffStatus = "mismatch"
    elif any(item.status == "warning" for item in relevant_items):
        status = "warning"
    elif relevant_items:
        status = "matched"
    else:
        status = "unknown"
    summary = {
        "matched": "编排计划与实际执行的关键字段一致。",
        "mismatch": "编排计划与实际执行存在关键字段差异。",
        "warning": "编排计划与实际执行缺少部分可比字段。",
        "unknown": "编排计划缺少足够的实际执行字段用于比较。",
    }[status]
    return OrchestrationPlanDiff(
        plan_id=str(plan.get("plan_id") or ""),
        status=status,
        summary=summary,
        items=relevant_items,
        actual=actual,
    ).to_dict()


def actual_from_runtime_event(
    event: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
    actual_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topology = dict((plan or {}).get("topology") or {})
    first_execution = _first_execution(plan or {})
    actual_trace = dict(actual_trace or {})
    event_type = str(event.get("type") or "")
    answer_source = str(event.get("answer_source") or "")
    execution_kind = str(event.get("execution_kind") or event.get("execution_protocol") or "")
    if execution_kind == "direct_tool":
        normalized_kind = "direct_tool"
    elif answer_source in {"worker", "evidence_worker", "retrieval_worker", "pdf_worker", "structured_data_worker"}:
        normalized_kind = "worker"
    elif execution_kind:
        normalized_kind = execution_kind
    else:
        normalized_kind = str(topology.get("execution_kind") or first_execution.get("execution_kind") or "")
    contract = _dict(event.get("contract")) or _dict(actual_trace.get("contract"))
    prompt_manifest = _dict(actual_trace.get("prompt_manifest"))
    context_management = _dict(actual_trace.get("context_management"))
    memory_context = _dict(actual_trace.get("memory_context"))
    actual = {
        "status": "error" if event_type == "error" else "done",
        "execution_mode": str(event.get("execution_mode") or topology.get("mode") or ""),
        "route": str(event.get("route") or topology.get("route") or ""),
        "execution_kind": normalized_kind,
        "tool_name": str(event.get("tool") or actual_trace.get("tool_name") or first_execution.get("tool_name") or ""),
        "worker_route": str(event.get("worker_route") or actual_trace.get("worker_route") or first_execution.get("worker_route") or ""),
        "answer_source": answer_source,
        "answer_channel": str(event.get("answer_channel") or ""),
        "error": str(event.get("error") or ""),
        "context_management_present": bool(context_management),
        "context_pressure_level": str(context_management.get("pressure_level") or ""),
        "memory_context_present": bool(memory_context),
        "prompt_manifest_present": bool(prompt_manifest),
        "prompt_manifest_id": str(prompt_manifest.get("prompt_id") or ""),
        "prompt_total_sections": int(prompt_manifest.get("total_sections") or 0),
        "prompt_total_chars": int(prompt_manifest.get("total_chars") or 0),
        "contract_present": bool(contract),
        "contract_tool_name": str(contract.get("tool_name") or ""),
        "contract_action": str(contract.get("action") or ""),
        "contract_reason": str(contract.get("reason") or ""),
        "executions": _actual_executions(actual_trace, fallback_event=event, plan=plan or {}),
        "agent_tool_calls": [
            dict(item)
            for item in list(actual_trace.get("agent_tool_calls") or [])
            if isinstance(item, dict)
        ],
        "answer_assembly": _answer_assembly_from_event(event),
    }
    return actual


def update_actual_trace(actual_trace: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Accumulate runtime observations that arrive before the final done/error event."""
    trace = dict(actual_trace or {})
    event_type = str(event.get("type") or "")
    if event_type == "context_management":
        trace["context_management"] = _dict(event.get("context"))
    elif event_type == "memory_context":
        trace["memory_context"] = _dict(event.get("memory"))
    elif event_type == "prompt_manifest":
        trace["prompt_manifest"] = _dict(event.get("prompt_manifest"))
    elif event_type == "subtask_start":
        trace = _upsert_actual_execution(
            trace,
            _execution_observation_from_event(event, status="running"),
        )
    elif event_type == "subtask_end":
        trace = _upsert_actual_execution(
            trace,
            _execution_observation_from_event(event, status="done"),
        )
    elif event_type in {"tool_start", "tool_end"}:
        tool_name = str(event.get("tool") or "")
        tool_execution_kind = str(event.get("execution_kind") or event.get("execution_protocol") or "")
        if tool_execution_kind != "direct_tool":
            trace = _append_agent_tool_call(
                trace,
                {
                    "type": event_type,
                    "tool_name": tool_name,
                    "status": "running" if event_type == "tool_start" else "done",
                    "input_preview": _preview_text(event.get("input")),
                    "output_preview": _preview_text(event.get("output")),
                },
            )
            return trace
        if tool_name:
            trace["tool_name"] = tool_name
        trace = _upsert_actual_execution(
            trace,
            _execution_observation_from_event(event, status="running" if event_type == "tool_start" else "done"),
        )
        contract = _dict(event.get("contract"))
        if contract:
            trace["contract"] = contract
    elif event_type.startswith("worker"):
        worker_route = str(event.get("worker_route") or event.get("worker") or "")
        if worker_route:
            trace["worker_route"] = worker_route
        trace = _upsert_actual_execution(
            trace,
            _execution_observation_from_event(event, status="running" if event_type == "worker_start" else "done"),
        )
    contract = _dict(event.get("contract"))
    if contract:
        trace["contract"] = contract
    return trace


def _append_agent_tool_call(trace: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    calls = [
        dict(item)
        for item in list(trace.get("agent_tool_calls") or [])
        if isinstance(item, dict)
    ]
    calls.append(observation)
    trace["agent_tool_calls"] = calls[-20:]
    return trace


def _execution_list_items(plan: dict[str, Any], actual: dict[str, Any]) -> list[OrchestrationDiffItem]:
    expected = _expected_executions(plan)
    actual_executions = [
        dict(item)
        for item in list(actual.get("executions") or [])
        if isinstance(item, dict)
    ]
    if len(expected) <= 1 and not actual_executions:
        return []

    items: list[OrchestrationDiffItem] = [
        _compare("executions.count", len(expected), len(actual_executions))
    ]
    by_id = {
        str(item.get("execution_id") or ""): item
        for item in actual_executions
        if str(item.get("execution_id") or "")
    }
    for index, expected_execution in enumerate(expected):
        field_prefix = f"executions[{index}]"
        expected_id = str(expected_execution.get("execution_id") or "")
        actual_execution = by_id.get(expected_id) if expected_id else None
        if actual_execution is None and index < len(actual_executions):
            actual_execution = actual_executions[index]
        if actual_execution is None:
            items.append(
                OrchestrationDiffItem(
                    field=f"{field_prefix}.execution_id",
                    expected=expected_id,
                    actual="",
                    status="mismatch",
                    reason="execution_missing",
                )
            )
            continue
        items.append(_compare(f"{field_prefix}.execution_id", expected_id, actual_execution.get("execution_id")))
        items.append(
            _compare(
                f"{field_prefix}.execution_kind",
                expected_execution.get("execution_kind"),
                actual_execution.get("execution_kind"),
            )
        )
        if expected_execution.get("tool_name") or actual_execution.get("tool_name"):
            items.append(_compare(f"{field_prefix}.tool_name", expected_execution.get("tool_name"), actual_execution.get("tool_name")))
        if expected_execution.get("worker_route") or actual_execution.get("worker_route"):
            items.append(
                _compare(
                    f"{field_prefix}.worker_route",
                    expected_execution.get("worker_route"),
                    actual_execution.get("worker_route"),
                )
            )
    return items


def _policy_observation_items(
    plan: dict[str, Any],
    *,
    actual: dict[str, Any],
    execution_kind: str,
) -> list[OrchestrationDiffItem]:
    context_policy = _dict(plan.get("context_policy"))
    prompt_policy = _dict(plan.get("prompt_policy"))
    items: list[OrchestrationDiffItem] = []
    if context_policy.get("mode") == "runtime":
        items.append(
            _observe(
                "context_policy.context_management",
                True,
                bool(actual.get("context_management_present")),
                missing_status="warning",
                missing_reason="context_management_event_missing",
            )
        )
    if execution_kind == "agent" and prompt_policy.get("mode") == "runtime":
        items.append(
            _observe(
                "prompt_policy.prompt_manifest",
                True,
                bool(actual.get("prompt_manifest_present")),
                missing_status="warning",
                missing_reason="prompt_manifest_event_missing",
            )
        )
    if execution_kind == "direct_tool":
        expected_tool = str(_first_execution(plan).get("tool_name") or "")
        expected_contract = _expected_contract_preview(plan, expected_tool)
        expected_action = str(expected_contract.get("contract_action") or "")
        items.append(
            _observe(
                "contract.tool_name",
                expected_tool,
                actual.get("contract_tool_name"),
                missing_status="warning",
                missing_reason="contract_observation_missing",
            )
        )
        if expected_action:
            items.append(
                _observe(
                    "contract.action",
                    expected_action,
                    actual.get("contract_action"),
                    missing_status="warning",
                    missing_reason="contract_observation_missing",
                )
            )
        action = str(actual.get("contract_action") or "")
        if action == "deny" and expected_action != "deny":
            items.append(
                OrchestrationDiffItem(
                    field="contract.runtime_block",
                    expected="allow_or_observe",
                    actual=action,
                    status="mismatch",
                    reason=str(actual.get("contract_reason") or "contract_denied"),
                )
            )
        elif action and not expected_action:
            items.append(
                OrchestrationDiffItem(
                    field="contract.runtime_block",
                    expected="allow_or_observe",
                    actual=action,
                    status="matched",
                )
            )
    if prompt_policy:
        expected_skill = str(prompt_policy.get("active_skill_name") or "")
        if expected_skill:
            items.append(
                _observe(
                    "prompt_policy.active_skill_name",
                    expected_skill,
                    expected_skill if bool(actual.get("prompt_manifest_present")) else "",
                    missing_status="warning",
                    missing_reason="prompt_manifest_event_missing",
                )
            )
    return items


def _first_execution(plan: dict[str, Any]) -> dict[str, Any]:
    executions = plan.get("executions")
    if isinstance(executions, list) and executions and isinstance(executions[0], dict):
        return dict(executions[0])
    return {}


def _expected_executions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    executions = plan.get("executions")
    if not isinstance(executions, list):
        return []
    return [dict(item) for item in executions if isinstance(item, dict)]


def _actual_executions(
    actual_trace: dict[str, Any],
    *,
    fallback_event: dict[str, Any],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    executions = [
        _public_execution(item)
        for item in list(actual_trace.get("executions") or [])
        if isinstance(item, dict)
    ]
    if executions:
        return executions
    first = _first_execution(plan)
    if not first:
        return []
    event_type = str(fallback_event.get("type") or "")
    if event_type not in {"done", "error"}:
        return []
    return [
        {
            "execution_id": str(first.get("execution_id") or "main"),
            "execution_kind": str(
                fallback_event.get("execution_kind")
                or fallback_event.get("execution_protocol")
                or first.get("execution_kind")
                or ""
            ),
            "tool_name": str(fallback_event.get("tool") or first.get("tool_name") or ""),
            "worker_route": str(fallback_event.get("worker_route") or first.get("worker_route") or ""),
            "status": "error" if event_type == "error" else "done",
        }
    ]


def _execution_observation_from_event(event: dict[str, Any], *, status: str) -> dict[str, Any]:
    subtask_plan = _dict(event.get("subtask_plan"))
    bundle_item = _dict(event.get("bundle_item"))
    result = _dict(event.get("result"))
    summary_payload = _dict(event.get("summary"))
    content_preview = _preview_text(
        event.get("content")
        or event.get("output")
        or result.get("answer")
        or result.get("summary")
        or result.get("result")
    )
    summary_preview = _preview_text(
        summary_payload.get("response")
        or summary_payload.get("summary")
        or result.get("answer")
        or result.get("summary")
        or event.get("content")
    )
    execution_id = str(
        event.get("execution_id")
        or bundle_item.get("bundle_item_id")
        or subtask_plan.get("subtask_plan_id")
        or event.get("task_id")
        or ""
    )
    event_type = str(event.get("type") or "")
    execution_kind = ""
    if event_type.startswith("worker"):
        execution_kind = "worker"
    elif event_type.startswith("tool"):
        execution_kind = "direct_tool"
    return {
        "execution_id": execution_id or ("main" if event_type.startswith(("worker", "tool")) else ""),
        "task_id": str(event.get("task_id") or ""),
        "message_id": str(event.get("message_id") or ""),
        "subtask_index": _optional_int(event.get("subtask_index")) or _optional_int(event.get("index")),
        "query": str(event.get("subtask_query") or event.get("query") or ""),
        "execution_kind": execution_kind,
        "tool_name": str(event.get("tool") or ""),
        "worker_route": str(event.get("worker_route") or event.get("worker") or ""),
        "bundle_item_id": str(bundle_item.get("bundle_item_id") or ""),
        "bundle_id": str(bundle_item.get("bundle_id") or ""),
        "summary_preview": summary_preview,
        "content_preview": content_preview,
        "output_chars": len(str(event.get("content") or event.get("output") or result.get("answer") or "")),
        "status": status,
    }


def _upsert_actual_execution(trace: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    if not any(value not in (None, "", [], {}, 0) for value in observation.values()):
        return trace
    executions = [
        dict(item)
        for item in list(trace.get("executions") or [])
        if isinstance(item, dict)
    ]
    key = str(observation.get("execution_id") or observation.get("task_id") or "")
    if not key:
        key = f"execution-{len(executions) + 1}"
        observation["execution_id"] = key
    for index, item in enumerate(executions):
        item_key = str(item.get("execution_id") or item.get("task_id") or "")
        if item_key != key:
            continue
        merged = dict(item)
        for field, value in observation.items():
            if value not in (None, "", [], {}, 0):
                merged[field] = value
        executions[index] = merged
        trace["executions"] = executions
        return trace
    executions.append(observation)
    trace["executions"] = executions
    return trace


def _public_execution(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_id": str(item.get("execution_id") or ""),
        "task_id": str(item.get("task_id") or ""),
        "subtask_index": _optional_int(item.get("subtask_index")),
        "query": str(item.get("query") or ""),
        "execution_kind": str(item.get("execution_kind") or ""),
        "tool_name": str(item.get("tool_name") or ""),
        "worker_route": str(item.get("worker_route") or ""),
        "bundle_id": str(item.get("bundle_id") or ""),
        "bundle_item_id": str(item.get("bundle_item_id") or ""),
        "summary_preview": str(item.get("summary_preview") or ""),
        "content_preview": str(item.get("content_preview") or ""),
        "output_chars": _optional_int(item.get("output_chars")) or 0,
        "status": str(item.get("status") or ""),
    }


def _compare(field: str, expected: Any, actual: Any) -> OrchestrationDiffItem:
    if expected in (None, "", [], {}) and actual in (None, "", [], {}):
        return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="unknown")
    if expected in (None, "", [], {}):
        return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="mismatch", reason="unexpected_actual")
    if actual in (None, "", [], {}):
        return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="mismatch", reason="actual_missing")
    if str(expected) == str(actual):
        return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="matched")
    return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="mismatch")


def _expected_contract_preview(plan: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for decision in list(plan.get("decisions") or []):
        if not isinstance(decision, dict) or str(decision.get("node_id") or "") != "contract-policy":
            continue
        outputs = _dict(decision.get("outputs"))
        previews = list(outputs.get("contract_previews") or [])
        for preview in previews:
            if not isinstance(preview, dict):
                continue
            if not tool_name or str(preview.get("tool_name") or "") == tool_name:
                return dict(preview)
    return {}


def _observe(
    field: str,
    expected: Any,
    actual: Any,
    *,
    missing_status: DiffStatus = "warning",
    missing_reason: str = "actual_missing",
) -> OrchestrationDiffItem:
    if expected in (None, "", [], {}) and actual in (None, "", [], {}):
        return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="unknown")
    if actual in (None, "", [], {}, False):
        return OrchestrationDiffItem(
            field=field,
            expected=expected,
            actual=actual,
            status=missing_status,
            reason=missing_reason,
        )
    if str(expected) == str(actual) or (expected is True and actual is True):
        return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="matched")
    return OrchestrationDiffItem(field=field, expected=expected, actual=actual, status="mismatch")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _answer_assembly_from_event(event: dict[str, Any]) -> dict[str, Any]:
    if str(event.get("type") or "") != "done":
        return {}
    if str(event.get("answer_source") or "") != "answer_assembler":
        return {}
    explicit = _dict(event.get("answer_assembly"))
    if explicit:
        selected_task_ids = [
            str(item or "").strip()
            for item in list(explicit.get("selected_task_ids") or [])
            if str(item or "").strip()
        ]
        dropped = [
            dict(item)
            for item in list(explicit.get("dropped_segments") or [])
            if isinstance(item, dict)
        ]
        return {
            "answer_source": "answer_assembler",
            "selected_task_ids": selected_task_ids,
            "selected_count": int(explicit.get("selected_count") or len(selected_task_ids)),
            "dropped_count": int(explicit.get("dropped_count") or len(dropped)),
            "dropped_segments": dropped,
            "dedupe_targets": list(explicit.get("dedupe_targets") or []),
            "source_refs": list(explicit.get("source_refs") or []),
            "task_summary_refs": [
                dict(item)
                for item in list(event.get("task_summary_refs") or [])
                if isinstance(item, dict)
            ],
            "content_preview": _preview_text(explicit.get("content_preview") or event.get("content")),
            "content_chars": int(explicit.get("content_chars") or len(str(event.get("content") or ""))),
        }
    refs = [
        dict(item)
        for item in list(event.get("task_summary_refs") or [])
        if isinstance(item, dict)
    ]
    task_ids = [
        str(item.get("task_id") or "").strip()
        for item in refs
        if str(item.get("task_id") or "").strip()
    ]
    return {
        "answer_source": "answer_assembler",
        "selected_task_ids": task_ids,
        "selected_count": len(task_ids),
        "dropped_count": 0,
        "dropped_segments": [],
        "dedupe_targets": [],
        "source_refs": [],
        "task_summary_refs": refs,
        "content_preview": _preview_text(event.get("content")),
        "content_chars": len(str(event.get("content") or "")),
    }


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _preview_text(value: Any, *, limit: int = 220) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        for key in ("answer", "summary", "content", "text", "result", "output"):
            preview = _preview_text(value.get(key), limit=limit)
            if preview:
                return preview
        value = value
    if isinstance(value, list):
        value = " ".join(_preview_text(item, limit=limit) for item in value[:3])
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."
