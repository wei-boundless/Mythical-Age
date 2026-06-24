from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from core.json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, json_file_lock, read_json_dict, write_json_dict
from core.project_layout import ProjectLayout

from .models import EngagementEvent, EngagementRunRecord
from .repository import EngagementPlanConfigError


ENGAGEMENT_RUNS_FILENAME = "engagement_runs.json"


class EngagementRunRepository:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)
        self.root = ProjectLayout.from_backend_dir(self.backend_dir).tasks_dir

    @property
    def path(self) -> Path:
        return self.root / ENGAGEMENT_RUNS_FILENAME

    def list_runs(self) -> list[dict[str, Any]]:
        with json_file_lock(self.path):
            return [dict(item) for item in list(self._read_payload().get("engagement_runs") or []) if isinstance(item, dict)]

    def list_events(self) -> list[dict[str, Any]]:
        with json_file_lock(self.path):
            return [dict(item) for item in list(self._read_payload().get("engagement_events") or []) if isinstance(item, dict)]

    def upsert_run(self, record: EngagementRunRecord) -> EngagementRunRecord:
        with json_file_lock(self.path):
            payload = self._read_payload()
            runs = [
                dict(item)
                for item in list(payload.get("engagement_runs") or [])
                if isinstance(item, dict) and str(item.get("engagement_run_id") or "") != record.engagement_run_id
            ]
            runs.append(record.to_dict())
            payload["engagement_runs"] = sorted(runs, key=lambda item: str(item.get("engagement_run_id") or ""))
            self._write_payload(payload)
            return record

    def update_run(self, engagement_run_id: str, **updates: Any) -> EngagementRunRecord:
        existing = self.get_run(engagement_run_id)
        if existing is None:
            raise KeyError(f"engagement run not found: {engagement_run_id}")
        return self.upsert_run(replace(existing, **updates))

    def get_run(self, engagement_run_id: str) -> EngagementRunRecord | None:
        target = str(engagement_run_id or "").strip()
        for item in self.list_runs():
            if str(item.get("engagement_run_id") or "") == target:
                return EngagementRunRecord(
                    engagement_run_id=str(item.get("engagement_run_id") or ""),
                    request_id=str(item.get("request_id") or ""),
                    contract_id=str(item.get("contract_id") or ""),
                    plan_id=str(item.get("plan_id") or ""),
                    plan_version=str(item.get("plan_version") or ""),
                    strategy_kind=str(item.get("strategy_kind") or ""),
                    status=str(item.get("status") or "requested"),  # type: ignore[arg-type]
                    task_run_id=str(item.get("task_run_id") or ""),
                    turn_result_ref=str(item.get("turn_result_ref") or ""),
                    workflow_run_id=str(item.get("workflow_run_id") or ""),
                    human_gate_id=str(item.get("human_gate_id") or ""),
                    artifact_refs=tuple(dict(ref) for ref in list(item.get("artifact_refs") or []) if isinstance(ref, dict)),
                    verification_refs=tuple(dict(ref) for ref in list(item.get("verification_refs") or []) if isinstance(ref, dict)),
                    closeout=dict(item.get("closeout") or {}),
                )
        return None

    def append_event(self, event: EngagementEvent) -> EngagementEvent:
        with json_file_lock(self.path):
            payload = self._read_payload()
            events = [dict(item) for item in list(payload.get("engagement_events") or []) if isinstance(item, dict)]
            events.append(event.to_dict())
            payload["engagement_events"] = events
            self._write_payload(payload)
            return event

    def _read_payload(self) -> dict[str, Any]:
        try:
            payload = read_json_dict(
                self.path,
                label="engagement runs",
                missing_factory=lambda: {"engagement_runs": [], "engagement_events": []},
            )
        except (JsonFileStoreError, JsonFilePayloadCorrupt) as exc:
            raise EngagementPlanConfigError(f"failed to read engagement runs: {exc}") from exc
        if not isinstance(payload, dict):
            raise EngagementPlanConfigError("engagement runs root must be an object")
        payload.setdefault("engagement_runs", [])
        payload.setdefault("engagement_events", [])
        return payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        try:
            write_json_dict(self.path, payload, label="engagement runs", sort_keys=True)
        except JsonFileStoreError as exc:
            raise EngagementPlanConfigError(f"failed to write engagement runs: {exc}") from exc


