from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from task_system.graph_instances.decision_models import (
    HumanEdgeDecision,
    human_edge_decision_from_dict,
    next_human_edge_decision_id,
)
from task_system.storage import TaskSystemStorage


GRAPH_INSTANCE_DECISIONS_DIR = "graph_instance_decisions"


class HumanEdgeDecisionRepository:
    authority = "task_system.graph_instance.human_edge_decision_repository"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = TaskSystemStorage(self.base_dir)

    def list(self, instance_id: str, *, limit: int | None = None) -> list[HumanEdgeDecision]:
        payload = self._read(instance_id)
        decisions = [
            human_edge_decision_from_dict(item)
            for item in list(payload.get("decisions") or [])
            if isinstance(item, dict)
        ]
        decisions = sorted(decisions, key=lambda item: (float(item.created_at or 0.0), item.decision_id))
        if limit is not None and int(limit) > 0:
            decisions = decisions[-int(limit) :]
        normalized = [item.to_dict() for item in decisions]
        if payload.get("decisions") != normalized:
            self._write(instance_id, normalized)
        return decisions

    def get(self, instance_id: str, decision_id: str) -> HumanEdgeDecision | None:
        target = str(decision_id or "").strip()
        return next((item for item in self.list(instance_id) if item.decision_id == target), None)

    def require(self, instance_id: str, decision_id: str) -> HumanEdgeDecision:
        decision = self.get(instance_id, decision_id)
        if decision is None:
            raise KeyError(f"human edge decision not found: {decision_id}")
        return decision

    def find_by_idempotency_key(self, instance_id: str, key: str) -> HumanEdgeDecision | None:
        target = str(key or "").strip()
        if not target:
            return None
        return next((item for item in self.list(instance_id) if item.idempotency_key == target), None)

    def create(self, instance_id: str, payload: dict[str, Any]) -> HumanEdgeDecision:
        candidate = dict(payload or {})
        candidate.setdefault("decision_id", next_human_edge_decision_id(instance_id))
        candidate.setdefault("graph_task_instance_id", str(instance_id or "").strip())
        now = time.time()
        candidate.setdefault("created_at", now)
        candidate["updated_at"] = now
        decision = human_edge_decision_from_dict(candidate)
        existing = self.find_by_idempotency_key(instance_id, decision.idempotency_key)
        if existing is not None:
            _assert_idempotent_match(existing, decision)
            return existing
        return self.upsert(instance_id, decision)

    def upsert(self, instance_id: str, decision: HumanEdgeDecision) -> HumanEdgeDecision:
        decisions = [item for item in self.list(instance_id) if item.decision_id != decision.decision_id]
        decisions.append(decision)
        self._write(instance_id, [item.to_dict() for item in sorted(decisions, key=lambda item: item.decision_id)])
        return decision

    def transition(
        self,
        instance_id: str,
        decision_id: str,
        status: str,
        patch: dict[str, Any] | None = None,
    ) -> HumanEdgeDecision:
        current = self.require(instance_id, decision_id)
        payload = current.to_dict()
        payload.update(dict(patch or {}))
        payload["status"] = str(status or "").strip()
        payload["updated_at"] = time.time()
        return self.upsert(instance_id, human_edge_decision_from_dict(payload))

    def _read(self, instance_id: str) -> dict[str, Any]:
        instance = _safe_path_component(instance_id)
        return self.storage.read_object(
            f"{GRAPH_INSTANCE_DECISIONS_DIR}/{instance}.json",
            {
                "authority": "task_system.graph_instance.human_edge_decision_ledger",
                "graph_task_instance_id": str(instance_id or "").strip(),
                "decisions": [],
                "updated_at": 0.0,
            },
        )

    def _write(self, instance_id: str, decisions: list[dict[str, Any]]) -> None:
        self.storage.write_object(
            f"{GRAPH_INSTANCE_DECISIONS_DIR}/{_safe_path_component(instance_id)}.json",
            {
                "authority": "task_system.graph_instance.human_edge_decision_ledger",
                "graph_task_instance_id": str(instance_id or "").strip(),
                "decisions": decisions,
                "updated_at": time.time(),
            },
        )


def _assert_idempotent_match(existing: HumanEdgeDecision, candidate: HumanEdgeDecision) -> None:
    existing_core = _decision_core(existing)
    candidate_core = _decision_core(candidate)
    if existing_core != candidate_core:
        raise ValueError("HumanEdgeDecision idempotency key conflicts with different payload")


def _decision_core(decision: HumanEdgeDecision) -> dict[str, Any]:
    return {
        "graph_task_instance_id": decision.graph_task_instance_id,
        "graph_run_id": decision.graph_run_id,
        "edge_id": decision.edge_id,
        "source_node_id": decision.source_node_id,
        "target_node_id": decision.target_node_id,
        "decision": decision.decision,
        "instruction": decision.instruction,
        "artifact_refs": [dict(item) for item in decision.artifact_refs],
        "content_submission": dict(decision.content_submission or {}),
    }


def _safe_path_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    safe = safe.strip("._-")
    return safe or "graph_task_instance"

