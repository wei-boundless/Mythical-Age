from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _TraceReader(Protocol):
    def get_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
    ) -> dict[str, Any] | None:
        ...


@dataclass(slots=True)
class ArtifactRefIndex:
    """Query artifact refs from formal runtime state without task-specific branches."""

    state_index: Any
    trace_reader: _TraceReader

    def latest_output_ref(self, *, task_ref: str) -> str:
        refs = self.latest_output_refs(task_ref=task_ref)
        return refs[0] if refs else ""

    def latest_output_refs(self, *, task_ref: str) -> list[str]:
        target = str(task_ref or "").strip()
        if not target:
            return []
        matches: list[tuple[float, list[str]]] = []
        for task_run in self.state_index.list_task_runs():
            task_contract_ref = str(task_run.task_contract_ref or "").strip()
            task_id = str(task_run.task_id or "").strip()
            if task_contract_ref != target and task_id != target and not task_id.endswith(f":{target.split('.')[-1]}"):
                continue
            trace = self.trace_reader.get_trace(task_run.task_run_id, include_payloads=True)
            if not trace:
                continue
            output_refs = collect_task_result_output_refs(dict(trace.get("task_result") or {}))
            if output_refs:
                matches.append((float(task_run.updated_at or 0.0), output_refs))
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1] if matches else []

    def latest_output_refs_by_contract(self, *, output_contract_id: str) -> list[str]:
        # Current task results do not persist output_contract_id consistently yet.
        # Keep the method as a stable contract and return no guess instead of fuzzy matching.
        return []

    def accepted_refs(self, *, coordination_run_id: str, ref_kind: str = "") -> list[str]:
        coordination_run = self.state_index.get_coordination_run(str(coordination_run_id or ""))
        if coordination_run is None:
            return []
        diagnostics = dict(coordination_run.diagnostics or {})
        refs: list[str] = []
        for item in list(diagnostics.get("accepted_refs") or []):
            if isinstance(item, dict):
                if ref_kind and str(item.get("ref_kind") or "") != ref_kind:
                    continue
                refs.append(str(item.get("ref") or ""))
            else:
                refs.append(str(item or ""))
        return dedupe_refs(refs)


def collect_task_result_output_refs(task_result: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in list(task_result.get("output_refs") or []):
        value = str(item or "").strip()
        if value:
            refs.append(value)
    for step_run in list(task_result.get("step_runs") or []):
        if not isinstance(step_run, dict):
            continue
        for item in list(step_run.get("output_refs") or []):
            value = str(item or "").strip()
            if value:
                refs.append(value)
        step_result_ref = str(step_run.get("step_result_ref") or "").strip()
        if step_result_ref:
            refs.append(step_result_ref)
    for item in list(task_result.get("result_refs") or []):
        value = str(item or "").strip()
        if value:
            refs.append(value)
    return dedupe_refs(refs)


def dedupe_refs(refs: Any) -> list[str]:
    values = refs if isinstance(refs, (list, tuple)) else [refs]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
