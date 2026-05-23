from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    packet_id: str
    task_run_id: str
    semantic_contract_ref: str
    source_observation_refs: tuple[str, ...] = ()
    material_refs: tuple[dict[str, Any], ...] = ()
    facts: tuple[dict[str, Any], ...] = ()
    classifications: tuple[dict[str, Any], ...] = ()
    deliverable_coverage: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    confidence: str = "medium"
    authority: str = "orchestration.evidence_packet"

    def __post_init__(self) -> None:
        if self.authority != "orchestration.evidence_packet":
            raise ValueError("EvidencePacket authority must be orchestration.evidence_packet")
        if not self.packet_id:
            raise ValueError("EvidencePacket requires packet_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_observation_refs"] = list(self.source_observation_refs)
        payload["material_refs"] = [dict(item) for item in self.material_refs]
        payload["facts"] = [dict(item) for item in self.facts]
        payload["classifications"] = [dict(item) for item in self.classifications]
        payload["deliverable_coverage"] = dict(self.deliverable_coverage)
        payload["limitations"] = list(self.limitations)
        return payload


def build_evidence_packet(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any] | None,
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> EvidencePacket:
    contract = dict(semantic_contract or {})
    task_goal_type = str(contract.get("task_goal_type") or "")
    if task_goal_type == "test_report_triage":
        return _test_report_triage_packet(
            task_run_id=task_run_id,
            semantic_contract=contract,
            observations=[dict(item) for item in list(observations or []) if isinstance(item, dict)],
        )
    return EvidencePacket(
        packet_id=f"evidence:{task_run_id}:general",
        task_run_id=task_run_id,
        semantic_contract_ref=str(contract.get("contract_id") or ""),
        source_observation_refs=tuple(_observation_ref(item) for item in observations if _observation_ref(item)),
        material_refs=tuple(dict(item) for item in list(contract.get("materials") or []) if isinstance(item, dict)),
        facts=tuple(_fact_from_observation(item) for item in observations if _fact_from_observation(item)),
        limitations=() if observations else ("未收到可结构化的工具观察。",),
    )


def _test_report_triage_packet(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any],
    observations: list[dict[str, Any]],
) -> EvidencePacket:
    facts: list[dict[str, Any]] = []
    classifications: list[dict[str, Any]] = []
    limitations: list[str] = []
    for observation in observations:
        parsed = _structured_payload_data(observation)
        if parsed is None:
            parsed = _parse_jsonish_observation(observation)
        if not parsed:
            text = str(observation.get("result") or observation.get("content") or "")
            if text:
                extracted = _extract_failure_lines(text[:400], observation_ref=_observation_ref(observation))
                if extracted:
                    facts.extend(extracted)
                else:
                    operational_fact = _fact_from_observation(observation)
                    if operational_fact:
                        facts.append(operational_fact)
            continue
        facts.extend(_facts_from_failure_payload(parsed, observation_ref=_observation_ref(observation)))
    if not facts:
        limitations.append("未能从工具观察中抽取结构化失败项。")
    for fact in facts:
        classification = _classify_failure_fact(fact)
        if classification:
            classifications.append(classification)
    return EvidencePacket(
        packet_id=f"evidence:{task_run_id}:test_report_triage",
        task_run_id=task_run_id,
        semantic_contract_ref=str(semantic_contract.get("contract_id") or ""),
        source_observation_refs=tuple(_observation_ref(item) for item in observations if _observation_ref(item)),
        material_refs=tuple(dict(item) for item in list(semantic_contract.get("materials") or []) if isinstance(item, dict)),
        facts=tuple(facts),
        classifications=tuple(classifications),
        deliverable_coverage=_triage_deliverable_coverage(facts, classifications),
        limitations=tuple(limitations),
        confidence="high" if facts else "low",
    )


def _structured_payload_data(observation: dict[str, Any]) -> Any | None:
    payload = dict(observation.get("structured_payload") or {})
    if not payload:
        envelope = dict(observation.get("result_envelope") or {})
        payload = dict(envelope.get("structured_payload") or {})
    tool_result = dict(payload.get("tool_result") or {}) if isinstance(payload.get("tool_result"), dict) else {}
    if not tool_result:
        return None
    if str(tool_result.get("kind") or "") == "structured_file" and "data" in tool_result:
        return tool_result.get("data")
    return tool_result.get("data")


def _parse_jsonish_observation(observation: dict[str, Any]) -> Any | None:
    raw = observation.get("result")
    if raw is None:
        raw = observation.get("content")
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    candidates = [text]
    if "```" in text:
        candidates.extend(part.strip() for part in text.split("```") if part.strip().startswith(("{", "[")))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _facts_from_failure_payload(payload: Any, *, observation_ref: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        summary_keys = ("run_id", "total_turns", "passed_turns", "failed_turns", "scenario")
        summary = {key: payload.get(key) for key in summary_keys if payload.get(key) is not None}
        if summary:
            facts.append({"fact_type": "run_summary", "summary": summary, "observation_ref": observation_ref})
        failure_items = []
        for key in ("failures", "failed", "failed_turn_details", "failure_details", "turn_failures"):
            value = payload.get(key)
            if isinstance(value, list):
                failure_items.extend(value)
        if not failure_items:
            failure_items.extend(_walk_failure_items(payload))
        for index, item in enumerate(failure_items):
            if isinstance(item, dict):
                facts.append(
                    {
                        "fact_type": "failure",
                        "index": index,
                        "turn": item.get("turn") or item.get("turn_id") or item.get("case") or item.get("id"),
                        "check": item.get("check") or item.get("assertion") or item.get("name") or item.get("kind"),
                        "symptom": item.get("symptom") or item.get("message") or item.get("error") or item.get("reason"),
                        "evidence": item.get("evidence") or item.get("details") or item.get("output") or item.get("actual"),
                        "observation_ref": observation_ref,
                    }
                )
            elif item:
                facts.append({"fact_type": "failure", "index": index, "symptom": str(item), "observation_ref": observation_ref})
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if isinstance(item, dict):
                facts.extend(_facts_from_failure_payload({"failures": [item]}, observation_ref=observation_ref))
            elif item:
                facts.append({"fact_type": "failure", "index": index, "symptom": str(item), "observation_ref": observation_ref})
    return facts


def _walk_failure_items(payload: Any) -> list[Any]:
    result: list[Any] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).lower()
            if "fail" in key_text and isinstance(value, list):
                result.extend(value)
            elif isinstance(value, (dict, list)):
                result.extend(_walk_failure_items(value))
    elif isinstance(payload, list):
        for item in payload:
            result.extend(_walk_failure_items(item))
    return result


def _extract_failure_lines(text: str, *, observation_ref: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for index, line in enumerate(str(text or "").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if _is_structural_summary_line(stripped):
            continue
        if re.search(r"fail|失败|error|assert|missing|timeout|leak", stripped, flags=re.IGNORECASE):
            facts.append({"fact_type": "failure", "index": index, "symptom": stripped[:300], "observation_ref": observation_ref})
    return facts[:20]


def _triage_deliverable_coverage(facts: list[dict[str, Any]], classifications: list[dict[str, Any]]) -> dict[str, Any]:
    failure_facts = [fact for fact in facts if str(fact.get("fact_type") or "") == "failure"]
    return {
        "failure_classification": {
            "satisfied": bool(classifications),
            "evidence_refs": _dedupe_refs(str(item.get("observation_ref") or "") for item in classifications),
        },
        "structural_root_causes": {
            "satisfied": bool(failure_facts and classifications),
            "evidence_refs": _dedupe_refs(str(item.get("observation_ref") or "") for item in failure_facts),
        },
        "regression_test_plan": {
            "satisfied": bool(failure_facts),
            "evidence_refs": _dedupe_refs(str(item.get("observation_ref") or "") for item in failure_facts),
        },
        "evidence_limits": {
            "satisfied": True,
            "evidence_refs": _dedupe_refs(str(item.get("observation_ref") or "") for item in facts),
        },
    }


def _dedupe_refs(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _is_structural_summary_line(line: str) -> bool:
    lowered = str(line or "").lower()
    return (
        lowered.startswith("root_type:")
        or "object keys=" in lowered
        or "array len=" in lowered
    )


def _classify_failure_fact(fact: dict[str, Any]) -> dict[str, Any]:
    if str(fact.get("fact_type") or "") != "failure":
        return {}
    text = " ".join(str(fact.get(key) or "") for key in ("check", "symptom", "evidence")).lower()
    layer = "runtime checkpoint"
    if any(token in text for token in ("memory", "记忆", "recall")):
        layer = "memory"
    elif any(token in text for token in ("context", "上下文", "summary")):
        layer = "context"
    elif any(token in text for token in ("artifact", "write", "file", "产物", "写入")):
        layer = "artifact/writeback"
    elif any(token in text for token in ("approval", "permission", "sandbox", "权限")):
        layer = "approval/sandbox"
    elif any(token in text for token in ("tool", "invoke", "dsml", "markup")):
        layer = "tool loop/output boundary"
    elif any(token in text for token in ("response.nonempty", "final_content", "answer was cut", "output_boundary")):
        layer = "tool loop/output boundary"
    elif any(token in text for token in ("timeout", "budget", "stalled")):
        layer = "timeout/budget"
    elif any(token in text for token in ("active_dataset", "writeback", "write back", "final_outputs", "写回")):
        layer = "artifact/writeback"
    elif any(token in text for token in ("tool_requires_approval", "approval")):
        layer = "approval/sandbox"
    return {
        "fact_index": fact.get("index"),
        "system_layer": layer,
        "reason": text[:240],
        "observation_ref": fact.get("observation_ref") or "",
    }


def _fact_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    ref = _observation_ref(observation)
    structured_data = _structured_payload_data(observation)
    if structured_data is not None:
        return {"fact_type": "structured_observation", "data": structured_data, "observation_ref": ref}
    text = str(observation.get("result") or observation.get("content") or "").strip()
    if not text:
        return {}
    return {"fact_type": "observation", "preview": text[:500], "observation_ref": ref}


def _observation_ref(observation: dict[str, Any]) -> str:
    return str(
        observation.get("observation_ref")
        or observation.get("observation_id")
        or observation.get("event_id")
        or observation.get("ref")
        or ""
    ).strip()
