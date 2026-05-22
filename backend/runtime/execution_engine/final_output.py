from __future__ import annotations

from typing import Any

from response_system.boundary.boundary import AssistantOutputBoundary
from runtime.memory.observation_aggregator import ObservationAggregation


def runtime_budget_exhausted_answer_metadata() -> dict[str, str]:
    return {
        "answer_channel": "answer_candidate",
        "answer_source": "runtime_loop_control",
        "answer_canonical_state": "progress_only",
        "answer_persist_policy": "persist_debug_only",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "runtime_budget_exhausted",
    }


def repeated_tool_halt_answer_metadata() -> dict[str, str]:
    return {
        "answer_channel": "answer_candidate",
        "answer_source": "runtime_loop_control",
        "answer_canonical_state": "progress_only",
        "answer_persist_policy": "persist_debug_only",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "repeated_tool_halt",
    }


def forced_synthesis_answer_metadata(*, source: str = "runtime_loop_synthesis") -> dict[str, str]:
    return {
        "answer_channel": "tool_visible_summary",
        "answer_source": source,
        "answer_canonical_state": "stable_answer",
        "answer_persist_policy": "persist_canonical",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "",
    }


def artifact_success_fallback_answer_metadata(*, source: str = "runtime_loop.artifact_success_fallback") -> dict[str, str]:
    return {
        "answer_channel": "tool_visible_summary",
        "answer_source": source,
        "answer_canonical_state": "stable_answer",
        "answer_persist_policy": "persist_canonical",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "artifact_success_fallback",
    }


def build_runtime_budget_exhausted_message(message: str = "", *, tool_observation_count: int = 0) -> str:
    reason = str(message or "").strip()
    if "max_runtime_seconds" in reason:
        reason_text = "本轮运行时间达到上限"
    elif "max_model_calls" in reason:
        reason_text = "本轮模型续写次数达到上限"
    elif "max_events" in reason:
        reason_text = "本轮链路事件数量达到上限"
    else:
        reason_text = "本轮运行预算达到上限"
    evidence_text = (
        f"已经收到 {tool_observation_count} 条工具结果"
        if tool_observation_count > 0
        else "还没有收到可用于总结的工具结果"
    )
    return (
        f"{reason_text}，所以先停止继续调用工具。{evidence_text}，但模型还没有把这些结果收口成最终回答。"
        "请直接继续问“基于已读取内容总结”，我会从现有上下文继续收口。"
    )


def build_repeated_tool_halt_message(*, tool_observation_count: int = 0) -> str:
    evidence_text = (
        f"已经连续收到了 {tool_observation_count} 条相似工具结果"
        if tool_observation_count > 0
        else "已经连续触发了相似工具调用"
    )
    return (
        f"{evidence_text}，继续重复读取不会带来新的信息，所以我先停止本轮重复工具调用。"
        "你可以直接继续基于当前已绑定对象提问，我会从现有上下文继续收口。"
    )


def build_answer_readiness_judge_message(
    *,
    user_message: str,
    aggregation: ObservationAggregation,
    current_bundle_items: list[dict[str, Any]],
    remaining_model_calls: int,
) -> str:
    evidence_items = list(aggregation.evidence_items or [])
    if not evidence_items:
        return ""
    lines = [
        "你已经收到工具返回的证据。现在先判断证据是否足够回答用户，而不是默认继续调用工具。",
        "",
        "你的任务：",
        "1. 如果证据已经足够覆盖用户当前问题，请直接收口回答。",
        "2. 如果证据只缺少少量关键信息，才继续调用工具；继续前必须明确缺口是什么。",
        "3. 如果用户问题本身不清楚，请向用户说明缺少的限定条件。",
        "4. 不要为了确认已经足够的信息而重复查询同类工具。",
        "",
        f"用户当前问题：{str(user_message or '').strip()}",
        f"剩余模型调用预算：{max(int(remaining_model_calls or 0), 0)}",
    ]
    if current_bundle_items:
        lines.append("")
        lines.append("当前是复合任务；只有未完成的子项才需要继续补证。")
    lines.append("")
    lines.append("已有证据：")
    for index, item in enumerate(evidence_items[-6:], start=1):
        tool_name = str(item.get("tool_name") or "tool").strip()
        result_preview = str(item.get("result_preview") or "").strip()
        result_chars = int(item.get("result_chars") or len(result_preview))
        truncated = "，已截断" if item.get("truncated") else ""
        args = dict(item.get("tool_args") or {})
        request_text = str(args.get("query") or args.get("path") or "").strip()
        request_part = f"；请求：{request_text}" if request_text else ""
        lines.append(f"{index}. 工具：{tool_name}{request_part}；结果长度：{result_chars}{truncated}")
        if result_preview:
            lines.append(f"   证据摘要：{result_preview}")
    lines.extend(
        [
            "",
            "请基于上述证据决定下一步。",
            "如果可以回答，请直接给用户可读结论，不要输出 JSON，不要解释内部判断过程。",
            "如果仍要调用工具，请只调用能补齐明确缺口的工具。",
        ]
    )
    return "\n".join(lines).strip()


def build_artifact_success_fallback_answer(
    *,
    selected_recipe_payload: dict[str, Any],
    artifact_validation: dict[str, Any],
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> str:
    artifact_items = [
        str(dict(item).get("path") or "").strip()
        for item in list(artifact_validation.get("artifacts") or [])
        if str(dict(item).get("path") or "").strip()
    ]
    task_title = str(
        selected_recipe_payload.get("title")
        or selected_recipe_payload.get("task_mode")
        or selected_recipe_payload.get("template_id")
        or "任务"
    ).strip()
    summary = forced_tool_synthesis_answer(
        user_message="",
        final_task_summary_refs=final_task_summary_refs,
        final_main_context=final_main_context,
    )
    lines = [f"{task_title}已完成真实产物写入。"]
    if artifact_items:
        lines.append("产物文件：")
        lines.extend(f"- {item}" for item in artifact_items[:6])
    if summary:
        lines.append(summary)
    else:
        lines.append("本轮所需 artifact 已通过 write_file 写入并通过存在性校验。")
    lines.append("模型后续收口阶段中断，但正式产物已经落盘，可基于现有产物继续下一阶段。")
    return "\n".join(lines)


def forced_tool_synthesis_from_available_evidence(
    *,
    user_message: str,
    aggregation: ObservationAggregation,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> str:
    synthesized = forced_tool_synthesis_answer(
        user_message=user_message,
        final_task_summary_refs=final_task_summary_refs,
        final_main_context=final_main_context,
    )
    if synthesized:
        return synthesized
    return forced_tool_synthesis_from_observation_aggregation(
        user_message=user_message,
        aggregation=aggregation,
    )


def forced_tool_synthesis_from_observation_aggregation(
    *,
    user_message: str,
    aggregation: ObservationAggregation,
) -> str:
    boundary = AssistantOutputBoundary()
    eligible = 0
    for item in list(aggregation.evidence_items or [])[-8:]:
        tool_name = str(item.get("tool_name") or "").strip()
        preview = str(item.get("result_preview") or "").strip()
        if not tool_name or not preview:
            continue
        if tool_name in {"search_text", "web_search", "fetch_url"} and len(preview) < 80:
            continue
        boundary.ingest_tool_result(tool_name, preview)
        eligible += 1
    if eligible <= 0:
        return ""
    boundary.finalize_segment()
    response = boundary.build_response(
        route="runtime_force_synthesis",
        execution_posture="tool_synthesis",
        user_message=user_message,
        tool_name="aggregated_tool_results",
        retrieval_results=None,
    )
    content = str(response.canonical_answer or "").strip()
    if not content or response.fallback_reason:
        return ""
    if response.selected_channel not in {"tool_visible_summary", "answer_candidate"}:
        return ""
    if looks_like_runtime_internal_answer(content):
        return ""
    return content


def should_force_answer_after_tool_results(
    *,
    aggregation: ObservationAggregation,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> bool:
    tool_names = [str(item).strip() for item in list(aggregation.tool_names or []) if str(item).strip()]
    if final_task_summary_refs:
        return True
    active_constraints = dict(final_main_context.get("active_constraints") or {})
    if active_constraints.get("active_pdf") or active_constraints.get("active_dataset"):
        return True
    if "delegate_to_agent" in tool_names:
        return True
    return False


def forced_tool_synthesis_answer(
    *,
    user_message: str,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> str:
    if not final_task_summary_refs:
        return ""
    active_constraints = dict(final_main_context.get("active_constraints") or {})
    source = str(active_constraints.get("active_pdf") or active_constraints.get("active_dataset") or "").strip()
    summaries: list[str] = []
    for item in final_task_summary_refs[-3:]:
        summary = clean_text(item.get("answer") or item.get("summary"))
        if not summary:
            continue
        summaries.append(summary)
    if not summaries:
        return ""
    body = summaries[0] if len(summaries) == 1 else "\n".join(
        f"{index}. {summary}" for index, summary in enumerate(summaries, start=1)
    )
    prefix = "基于已读取结果"
    if source:
        prefix += f"（{source}）"
    prefix += "，" if user_message else "："
    return f"{prefix}{body}"


def select_final_answer_from_task_summary_refs(final_task_summary_refs: list[dict[str, Any]]) -> str:
    for item in final_task_summary_refs:
        answer = clean_text(item.get("answer"))
        if answer:
            return answer
    for item in final_task_summary_refs:
        summary = clean_text(item.get("summary"))
        if summary:
            return summary
    return ""


def select_final_answer_from_context(final_main_context: dict[str, Any]) -> str:
    for key in ("answer", "resolved_answer", "canonical_answer"):
        value = clean_text(final_main_context.get(key))
        if value:
            return value
    return ""


def builtin_tool_lane_answer_from_observation(
    *,
    user_message: str,
    observation_payload: dict[str, Any],
) -> dict[str, str] | None:
    tool_name = str(observation_payload.get("tool_name") or "").strip()
    result_text = str(observation_payload.get("result") or "").strip()
    if not tool_name or not result_text:
        return None
    boundary = AssistantOutputBoundary()
    boundary.ingest_tool_result(tool_name, result_text)
    boundary.finalize_segment()
    response = boundary.build_response(
        route="builtin_tool_lane",
        execution_posture="builtin_tool_lane",
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=None,
    )
    content = str(response.canonical_answer or "").strip()
    if not content or response.fallback_reason:
        return None
    if response.selected_channel not in {"tool_visible_summary", "answer_candidate"}:
        return None
    return {
        "content": content,
        "answer_channel": str(response.selected_channel or "answer_candidate"),
        "answer_source": f"builtin_tool_lane.{tool_name}",
        "answer_canonical_state": str(response.canonical_state or "stable_answer"),
        "answer_persist_policy": str(response.persist_policy or "persist_canonical"),
        "answer_finalization_policy": str(response.finalization_policy or "none"),
        "answer_fallback_reason": "",
    }


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def looks_like_runtime_internal_answer(value: str) -> bool:
    text = str(value or "").strip()
    internal_markers = (
        "本轮运行预算达到上限",
        "本轮运行时间达到上限",
        "本轮模型续写次数达到上限",
        "本轮委派全部被限流",
        "委派被限流",
        "请直接继续问",
        "下一轮我会优先调用",
    )
    return any(marker in text for marker in internal_markers)
