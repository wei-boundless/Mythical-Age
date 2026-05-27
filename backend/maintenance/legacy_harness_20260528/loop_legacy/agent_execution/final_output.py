from __future__ import annotations

from typing import Any

from runtime.memory.observation_aggregator import ObservationAggregation


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


def clean_text(value: Any) -> str:
    return str(value or "").strip()


