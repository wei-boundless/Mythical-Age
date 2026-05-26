from __future__ import annotations

from typing import Any

from runtime.shared.action_request import RuntimeObservation, build_tool_result_observation


def build_timeout_recovery_observation(
    *,
    task_run_id: str,
    directive_ref: str,
    stage_summary: dict[str, Any],
    suggested_tool_names: list[str] | tuple[str, ...] = (),
) -> RuntimeObservation:
    compact_summary = _compact_timeout_stage_summary(dict(stage_summary or {}))
    payload = {
        "type": "runtime_timeout_observation",
        "reason": "model_response_timeout",
        "stage_summary": compact_summary,
        "suggested_tool_names": [str(item) for item in list(suggested_tool_names or []) if str(item).strip()],
        "repair_instruction": (
            "上一轮模型响应超时。请根据阶段总结继续推进真实任务；如果需要工具，请自主选择合适工具，"
            "不要重复已经失败或无推进的动作。"
        ),
    }
    return build_tool_result_observation(
        task_run_id=task_run_id,
        request_ref=f"timeout:{task_run_id}",
        directive_ref=directive_ref,
        tool_name="runtime_timeout",
        tool_call_id=f"timeout:{task_run_id}",
        tool_args={},
        result=payload,
        result_envelope={
            "status": "error",
            "tool_name": "runtime_timeout",
            "tool_args": {},
            "structured_payload": payload,
        },
    )


def timeout_recovery_messages(
    *,
    user_message: str,
    timeout_observation: RuntimeObservation,
) -> list[dict[str, Any]]:
    payload = _compact_timeout_recovery_payload(_timeout_payload(timeout_observation))
    return [
        {
            "role": "system",
            "content": (
                "上一轮在等待模型输出时超时。你需要继续当前专业任务。"
                "下面是运行时给出的精简 timeout observation；它只包含真实观察索引、路径、缺口和下一步候选工具。"
            ),
        },
        {"role": "user", "content": str(user_message or "")},
        {"role": "system", "content": "runtime_timeout_observation=" + repr(payload)},
    ]


def _timeout_payload(timeout_observation: RuntimeObservation) -> dict[str, Any]:
    payload = dict(timeout_observation.payload or {})
    structured = dict(payload.get("structured_payload") or {})
    if str(structured.get("type") or "") == "runtime_timeout_observation":
        return structured
    result_envelope = dict(payload.get("result_envelope") or {})
    envelope_structured = dict(result_envelope.get("structured_payload") or {})
    if str(envelope_structured.get("type") or "") == "runtime_timeout_observation":
        return envelope_structured
    result = payload.get("result")
    if isinstance(result, dict) and str(result.get("type") or "") == "runtime_timeout_observation":
        return dict(result)
    if str(payload.get("type") or "") == "runtime_timeout_observation":
        return payload
    return {}


def _compact_timeout_recovery_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item = dict(payload or {})
    return {
        "type": str(item.get("type") or "runtime_timeout_observation"),
        "reason": str(item.get("reason") or ""),
        "stage_summary": _compact_timeout_stage_summary(dict(item.get("stage_summary") or {})),
        "suggested_tool_names": [
            str(tool).strip()
            for tool in list(item.get("suggested_tool_names") or [])
            if str(tool).strip()
        ],
        "repair_instruction": str(item.get("repair_instruction") or ""),
    }


def _compact_timeout_stage_summary(stage_summary: dict[str, Any]) -> dict[str, Any]:
    summary = dict(stage_summary or {})
    return {
        "task_run_id": str(summary.get("task_run_id") or ""),
        "turn_count": int(summary.get("turn_count") or 0),
        "tool_call_count": int(summary.get("tool_call_count") or 0),
        "tool_observation_count": int(summary.get("tool_observation_count") or 0),
        "written_paths": _compact_string_list(summary.get("written_paths")),
        "artifact_refs": [
            dict(ref)
            for ref in list(summary.get("artifact_refs") or [])
            if isinstance(ref, dict)
        ][:8],
        "latest_observations": [
            _compact_timeout_observation(dict(item))
            for item in list(summary.get("latest_observations") or [])
            if isinstance(item, dict)
        ],
        "pending_deliverables": _compact_string_list(summary.get("pending_deliverables")),
        "verification_passed": bool(summary.get("verification_passed") is True),
        "summary": str(summary.get("summary") or "")[:800],
    }


def _compact_timeout_observation(observation: dict[str, Any]) -> dict[str, Any]:
    item = dict(observation or {})
    return {
        "observation_ref": str(item.get("observation_ref") or ""),
        "tool_name": str(item.get("tool_name") or ""),
        "tool_args": _compact_tool_args(dict(item.get("tool_args") or {})),
        "status": str(item.get("status") or ""),
        "observed_paths": _compact_string_list(item.get("observed_paths")),
        "matched_paths": _compact_string_list(item.get("matched_paths")),
        "artifact_refs": [
            dict(ref)
            for ref in list(item.get("artifact_refs") or [])
            if isinstance(ref, dict)
        ][:8],
        "command_receipt": dict(item.get("command_receipt") or {}),
        "result_preview": str(item.get("result_preview") or item.get("result") or "")[:240],
        "result_chars": int(item.get("result_chars") or len(str(item.get("result") or ""))),
    }


def _compact_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in dict(args or {}).items():
        if key == "content":
            text = str(value or "")
            compact[key] = f"<content_chars:{len(text)}>"
            continue
        compact[key] = value
    return compact


def _compact_string_list(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
