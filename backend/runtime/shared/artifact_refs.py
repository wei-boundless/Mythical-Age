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


class _ArtifactRepository(Protocol):
    def latest_refs_by_contract(
        self,
        *,
        output_contract_id: str,
        task_run_id: str = "",
        repository_id: str = "",
        collection_id: str = "",
        status: str = "accepted",
        limit: int = 20,
    ) -> list[str]:
        ...


@dataclass(slots=True)
class ArtifactRefIndex:
    """Query artifact refs from formal runtime state without task-specific branches."""

    state_index: Any
    trace_reader: _TraceReader
    artifact_repository: _ArtifactRepository | None = None

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
        target = str(output_contract_id or "").strip()
        if not target:
            return []
        if self.artifact_repository is not None:
            refs = self.artifact_repository.latest_refs_by_contract(output_contract_id=target)
            if refs:
                return refs
        matches: list[tuple[float, list[str]]] = []
        for task_run in self.state_index.list_task_runs():
            trace = self.trace_reader.get_trace(task_run.task_run_id, include_payloads=True)
            if not trace:
                continue
            task_result = dict(trace.get("task_result") or {})
            if not _task_result_matches_output_contract(task_result, target):
                continue
            output_refs = collect_task_result_output_refs(task_result)
            if output_refs:
                matches.append((float(task_run.updated_at or 0.0), output_refs))
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1] if matches else []

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


def _task_result_matches_output_contract(task_result: dict[str, Any], output_contract_id: str) -> bool:
    target = str(output_contract_id or "").strip()
    if not target:
        return False
    contract_values = {
        str(task_result.get("output_contract_id") or "").strip(),
        str(dict(task_result.get("diagnostics") or {}).get("output_contract_id") or "").strip(),
    }
    artifact_repository = dict(dict(task_result.get("final_outputs") or {}).get("artifact_materialization") or {}).get("artifact_repository")
    if isinstance(artifact_repository, dict):
        contract_values.add(str(artifact_repository.get("output_contract_id") or "").strip())
    for step_run in list(task_result.get("step_runs") or []):
        if isinstance(step_run, dict):
            contract_values.add(str(step_run.get("output_contract_id") or "").strip())
    return target in contract_values


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


