from __future__ import annotations

from typing import Any


AGENT_DELEGATION_PROTOCOL_ID = "protocol.agent.direct_delegation.v1"


def build_agent_delegation_protocol(
    *,
    source_agent_id: str = "agent:0",
    target_agent_id: str = "",
    delegation_kind: str = "",
    source_kind: str = "",
    user_goal: str = "",
    recall_context: dict[str, Any] | None = None,
    intent_decision: dict[str, Any] | None = None,
    runtime_assembly_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recall_payload = dict(recall_context or {})
    source = str(source_kind or recall_payload.get("source_kind") or "").strip()
    return {
        "authority": "orchestration.agent_communication_protocol",
        "protocol_id": AGENT_DELEGATION_PROTOCOL_ID,
        "transport": "runtime_tool:delegate_to_agent",
        "source_agent_id": str(source_agent_id or "").strip(),
        "target_agent_id": str(target_agent_id or "").strip(),
        "delegation_kind": str(delegation_kind or "").strip(),
        "source_kind": source,
        "main_agent_contract": {
            "delegate_when": _delegate_when(source),
            "must_send": _must_send_fields(source),
            "instruction_style": _instruction_style(source),
        "scope_rule": _scope_rule(source, recall_payload),
        },
        "child_agent_contract": {
            "role_instruction": _child_role_instruction(source),
            "must_return": ["summary", "answer_candidate", "confidence", "limitations"],
            "should_return": ["evidence_refs", "artifact_refs", "consumed_handles", "produced_handles", "followup_questions"],
            "failure_rule": "If evidence or required inputs are missing, return explicit limitations instead of inventing an answer.",
        },
        "parent_closeout_contract": {
            "closeout_rule": "The main Agent must synthesize the child result into the final user-facing answer and preserve stated limitations.",
            "do_not_expose": ["internal protocol ids", "tool routing details", "raw child prompt"],
            "use_child_result_as": "evidence_packet",
        },
        "handoff_context": {
            "user_goal": str(user_goal or "").strip(),
            "intent_decision": dict(intent_decision or {}),
            "runtime_assembly_hint": dict(runtime_assembly_hint or {}),
            "recall_context": recall_payload,
        },
    }


def default_expected_output_contract(*, source_kind: str = "", delegation_kind: str = "") -> dict[str, Any]:
    source = str(source_kind or "").strip()
    return {
        "authority": "orchestration.agent_delegation_output_contract",
        "contract_id": f"contract.agent_delegation.{source or delegation_kind or 'general'}",
        "required": ["summary", "answer_candidate"],
        "optional": ["evidence_refs", "artifact_refs", "confidence", "limitations", "followup_questions", "consumed_handles", "produced_handles"],
        "quality_rules": [
            "Answer only within the delegated scope.",
            "Return concrete evidence refs when available.",
            "State missing inputs or extraction limits explicitly.",
        ],
    }


def _must_send_fields(source_kind: str) -> list[str]:
    if source_kind == "dataset":
        return ["query", "path or active_dataset", "grouping/filter/sort scope", "followup constraint if any"]
    if source_kind == "pdf":
        return ["query", "path or active_pdf", "page/section/document mode", "followup constraint if any"]
    if source_kind == "knowledge":
        return ["query", "answer scope", "known anchors", "retrieval limits"]
    return ["query", "scope", "expected output", "constraints"]


def _delegate_when(source_kind: str) -> str:
    if source_kind == "dataset":
        return "Use a structured-data child Agent when the answer requires filtering, ranking, grouping, or aggregating tabular data."
    if source_kind == "pdf":
        return "Use a PDF child Agent when the answer depends on a specific document, page, or section."
    if source_kind == "knowledge":
        return "Use a RAG child Agent when the answer must be grounded in the local knowledge base."
    return "Use a child Agent only for bounded specialist work that can return evidence for main-Agent closeout."


def _instruction_style(source_kind: str) -> str:
    if source_kind == "dataset":
        return "Tell the child exactly which dataset/subset to use, what operation to compute, and whether expanding to the full table is forbidden."
    if source_kind == "pdf":
        return "Tell the child exactly which PDF and page/section scope to read, plus the answer shape expected by the user."
    if source_kind == "knowledge":
        return "Tell the child the exact question and evidence scope; do not ask it to browse arbitrary files or web pages."
    return "Use role-language instructions, not developer shorthand or node labels."


def _scope_rule(source_kind: str, recall_context: dict[str, Any]) -> str:
    if recall_context:
        return "The child may use supplied recall candidates only after verifying they match the current user request; candidates are not execution facts."
    if source_kind in {"dataset", "pdf"}:
        return "The child must not switch source objects unless the main Agent explicitly delegates a different source."
    return "The child must stay inside the supplied delegation scope."


def _child_role_instruction(source_kind: str) -> str:
    if source_kind == "dataset":
        return "你是一名结构化数据分析员。你只基于主 Agent 给定的数据集或结果子集计算，不自行扩大范围。"
    if source_kind == "pdf":
        return "你是一名 PDF 阅读分析员。你只阅读主 Agent 指定的文档范围，并回传页码、章节或抽取限制。"
    if source_kind == "knowledge":
        return "你是一名知识库检索分析员。你只基于本地知识库证据回答，并标明证据是否足够。"
    return "你是一名受限子 Agent。你只完成主 Agent 委派的边界化任务，并把结果回传给主 Agent 收口。"
