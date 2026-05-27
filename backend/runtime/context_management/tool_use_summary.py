from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolUseSummary:
    summary_id: str
    tool_name: str
    tool_call_id: str
    status: str
    summary: str
    facts: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    authority: str = "orchestration.tool_use_summary"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.tool_use_summary":
            raise ValueError("ToolUseSummary authority must be orchestration.tool_use_summary")
        if not self.summary_id:
            raise ValueError("ToolUseSummary requires summary_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("facts", "unknowns", "limitations", "evidence_refs", "artifact_refs", "next_actions"):
            payload[key] = list(payload[key])
        return payload


def build_tool_use_summary(observation: Any, *, max_items: int = 8) -> ToolUseSummary | None:
    if str(getattr(observation, "observation_type", "") or "") != "tool_result":
        return None
    payload = dict(getattr(observation, "payload", {}) or {})
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_call_id = str(payload.get("tool_call_id") or "").strip()
    result = str(payload.get("result") or "")
    envelope = dict(payload.get("result_envelope") or {})
    structured = dict(payload.get("structured_payload") or envelope.get("structured_payload") or {})
    parsed_result = _parse_json_object(result)
    packet = _agent_evidence_packet(parsed_result, structured, envelope)
    status = _status(payload, envelope, parsed_result)
    facts = _facts(packet, parsed_result, structured, max_items=max_items)
    unknowns = _strings(
        packet.get("unknowns")
        or parsed_result.get("unknowns")
        or structured.get("unknowns"),
        field="description",
        max_items=max_items,
    )
    limitations = _strings(
        packet.get("limitations")
        or parsed_result.get("limitations")
        or structured.get("limitations"),
        max_items=max_items,
    )
    evidence_refs = _strings(
        packet.get("evidence_refs")
        or parsed_result.get("evidence_refs")
        or structured.get("evidence_refs")
        or envelope.get("evidence_refs"),
        max_items=max_items,
    )
    artifact_refs = _artifact_refs(payload, parsed_result, structured, envelope, max_items=max_items)
    next_actions = _strings(
        parsed_result.get("next_actions")
        or structured.get("next_actions")
        or packet.get("next_actions"),
        max_items=max_items,
    )
    summary = _summary_text(
        tool_name=tool_name,
        status=status,
        result=result,
        parsed_result=parsed_result,
        facts=facts,
        unknowns=unknowns,
        limitations=limitations,
    )
    return ToolUseSummary(
        summary_id=f"toolsum:{getattr(observation, 'observation_id', '') or tool_call_id or tool_name}",
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        status=status,
        summary=summary,
        facts=tuple(facts),
        unknowns=tuple(unknowns),
        limitations=tuple(limitations),
        evidence_refs=tuple(evidence_refs),
        artifact_refs=tuple(artifact_refs),
        next_actions=tuple(next_actions),
    )


def _status(payload: dict[str, Any], envelope: dict[str, Any], parsed_result: dict[str, Any]) -> str:
    if bool(payload.get("truncated") is True):
        return "truncated"
    for source in (envelope, parsed_result):
        status = str(source.get("status") or "").strip()
        if status:
            return status
    text = str(payload.get("result") or "").lower()
    if any(token in text for token in ("error", "failed", "denied", "被阻止", "失败")):
        return "error"
    return "ok"


def _summary_text(
    *,
    tool_name: str,
    status: str,
    result: str,
    parsed_result: dict[str, Any],
    facts: list[str],
    unknowns: list[str],
    limitations: list[str],
) -> str:
    explicit = str(parsed_result.get("summary") or parsed_result.get("visible_summary") or "").strip()
    if explicit:
        return _compact(explicit, 600)
    if facts:
        return _compact(f"{tool_name or 'tool'} returned {len(facts)} evidence fact(s). {facts[0]}", 600)
    if unknowns:
        return _compact(f"{tool_name or 'tool'} completed with unresolved item: {unknowns[0]}", 600)
    if limitations:
        return _compact(f"{tool_name or 'tool'} completed with limitation: {limitations[0]}", 600)
    prefix = f"{tool_name or 'tool'} result ({status})"
    preview = " ".join(result.split())
    if preview:
        return _compact(f"{prefix}: {preview}", 600)
    return prefix


def _agent_evidence_packet(*sources: dict[str, Any]) -> dict[str, Any]:
    for source in sources:
        diagnostics = dict(source.get("diagnostics") or {})
        packet = diagnostics.get("agent_evidence_packet") or source.get("agent_evidence_packet")
        if isinstance(packet, dict):
            return dict(packet)
    return {}


def _facts(packet: dict[str, Any], parsed_result: dict[str, Any], structured: dict[str, Any], *, max_items: int) -> list[str]:
    sources = packet.get("facts") or parsed_result.get("facts") or structured.get("facts")
    facts: list[str] = []
    for item in list(sources or []):
        if isinstance(item, dict):
            claim = str(item.get("claim") or item.get("text") or item.get("summary") or "").strip()
            if claim:
                facts.append(claim)
        elif str(item).strip():
            facts.append(str(item).strip())
        if len(facts) >= max_items:
            break
    return _dedupe(facts)


def _artifact_refs(
    payload: dict[str, Any],
    parsed_result: dict[str, Any],
    structured: dict[str, Any],
    envelope: dict[str, Any],
    *,
    max_items: int,
) -> list[str]:
    refs: list[str] = []
    for source in (payload, parsed_result, structured, envelope):
        for item in list(dict(source).get("artifact_refs") or []):
            if isinstance(item, dict):
                ref = str(item.get("ref") or item.get("artifact_ref") or item.get("path") or item.get("id") or "").strip()
            else:
                ref = str(item or "").strip()
            if ref:
                refs.append(ref)
            if len(refs) >= max_items:
                return _dedupe(refs)
    return _dedupe(refs)


def _strings(value: Any, *, field: str = "", max_items: int) -> list[str]:
    items: list[str] = []
    for item in list(value or []):
        if isinstance(item, dict):
            text = str(item.get(field) or item.get("text") or item.get("summary") or item.get("claim") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            items.append(text)
        if len(items) >= max_items:
            break
    return _dedupe(items)


def _parse_json_object(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return dict(parsed) if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        first = text.find("{")
        last = text.rfind("}")
        if first < 0 or last <= first:
            return {}
        try:
            parsed = json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


