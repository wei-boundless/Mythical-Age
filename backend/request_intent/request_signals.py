from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent_runtime.understanding.request_facts import RequestFacts, build_request_facts

from .memory_intent import MemoryIntent


@dataclass(frozen=True, slots=True)
class TurnSignals:
    explicit_paths: tuple[str, ...] = ()
    material_suffixes: tuple[str, ...] = ()
    weak_capability_needs: tuple[str, ...] = ()
    memory_recall_marker: bool = False
    memory_write_marker: bool = False
    authority: str = "request_facts.structural_facts"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "explicit_paths",
            "material_suffixes",
            "weak_capability_needs",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class RequestSignals:
    frame_id: str
    user_message: str
    structural_signals: dict[str, Any] = field(default_factory=dict)
    capability_needs: tuple[str, ...] = ()
    target_domain_hints: tuple[str, ...] = ()
    context_binding: dict[str, Any] = field(default_factory=dict)
    decision_trace: tuple[dict[str, Any], ...] = ()
    confidence: float = 0.0
    authority: str = "request_facts.frame"

    @property
    def turn_signals(self) -> dict[str, Any]:
        return dict(self.structural_signals or {})

    @property
    def capability_intent(self) -> dict[str, Any]:
        return {
            "capability_needs": list(self.capability_needs),
            "tool_selection_allowed": False,
            "diagnostics": {
                "owner": "request_facts",
                "no_intent_or_route_authority": True,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["structural_signals"] = dict(self.structural_signals or {})
        payload["turn_signals"] = dict(self.structural_signals or {})
        payload["capability_needs"] = list(self.capability_needs)
        payload["target_domain_hints"] = list(self.target_domain_hints)
        payload["context_binding"] = dict(self.context_binding or {})
        payload["capability_intent"] = self.capability_intent
        payload["decision_trace"] = [dict(item) for item in self.decision_trace]
        return payload


def build_request_signals(
    message: str,
    memory_intent: MemoryIntent | None = None,
    *,
    current_turn_context: dict[str, Any] | None = None,
) -> RequestSignals:
    current_turn = dict(current_turn_context or {})
    facts = build_request_facts(
        user_message=message,
        session_id=str(current_turn.get("session_id") or ""),
        task_id=str(current_turn.get("task_id") or current_turn.get("selected_task_id") or ""),
        turn_id=str(current_turn.get("turn_id") or ""),
        source=str(current_turn.get("source") or ""),
        explicit_selection=_explicit_selection(current_turn),
    )
    signals = _signals_from_facts(facts, memory_intent=memory_intent)
    return RequestSignals(
        frame_id=facts.facts_id,
        user_message=facts.user_message,
        structural_signals=signals.to_dict(),
        capability_needs=signals.weak_capability_needs,
        target_domain_hints=tuple(_target_domain_hints(facts=facts, signals=signals, current_turn=current_turn)),
        context_binding=_context_binding(facts=facts, signals=signals),
        decision_trace=(
            {
                "stage": "request_facts",
                "decision": "facts_only",
                "reason": "current-turn intent, route, action, and execution mode are owned by ModelTurnDecision",
            },
        ),
        confidence=_confidence(facts=facts, signals=signals),
    )


def _signals_from_facts(facts: RequestFacts, *, memory_intent: MemoryIntent | None) -> TurnSignals:
    suffixes = tuple(facts.material_suffixes or ())
    capability_needs: list[str] = []
    if any(suffix in {".csv", ".tsv", ".xlsx", ".xls", ".parquet"} for suffix in suffixes):
        capability_needs.append("dataset_material")
    if ".pdf" in suffixes:
        capability_needs.append("pdf_material")
    if any(suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html"} for suffix in suffixes):
        capability_needs.append("code_material")
    if bool(memory_intent is not None and getattr(memory_intent, "should_skip_rag", False)):
        capability_needs.append("memory_candidate")
    return TurnSignals(
        explicit_paths=tuple(facts.explicit_paths or ()),
        material_suffixes=suffixes,
        weak_capability_needs=tuple(_dedupe(capability_needs)),
        memory_recall_marker=bool(memory_intent is not None and getattr(memory_intent, "should_skip_rag", False)),
        memory_write_marker=bool(memory_intent is not None and getattr(memory_intent, "explicit_write_request", False)),
    )


def _explicit_selection(current_turn: dict[str, Any]) -> dict[str, Any]:
    selected_task_id = str(
        current_turn.get("selected_task_id")
        or current_turn.get("task_id")
        or current_turn.get("specific_task_id")
        or current_turn.get("task_assignment_id")
        or ""
    ).strip()
    if not selected_task_id:
        return {}
    return {"kind": "explicit_task_selection", "selected_task_id": selected_task_id}


def _target_domain_hints(*, facts: RequestFacts, signals: TurnSignals, current_turn: dict[str, Any]) -> list[str]:
    domains: list[str] = []
    explicit = str(current_turn.get("task_domain") or current_turn.get("target_domain_hint") or "").strip()
    if explicit:
        domains.append(explicit)
    for suffix in facts.material_suffixes:
        if suffix == ".pdf":
            domains.append("pdf")
        elif suffix in {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}:
            domains.append("dataset")
        elif suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html"}:
            domains.append("workspace")
    if signals.memory_recall_marker:
        domains.append("memory")
    return _dedupe(domains)


def _context_binding(*, facts: RequestFacts, signals: TurnSignals) -> dict[str, Any]:
    selection = dict(facts.explicit_selection or {})
    if selection:
        return selection
    return {"kind": "current_turn"}


def _confidence(*, facts: RequestFacts, signals: TurnSignals) -> float:
    score = 0.34
    if facts.explicit_paths:
        score += 0.18
    if signals.weak_capability_needs:
        score += 0.08
    return min(score, 0.72)


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


