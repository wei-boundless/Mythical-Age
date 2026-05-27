from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from artifact_system.artifact_repository_service import ArtifactRepositoryService
from project_layout import ProjectLayout

from .contracts import SoulActivityEvent, SoulWorkLogView


class SoulActivityService:
    """Read-only work log view over existing runtime and artifact records."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.layout = ProjectLayout.from_backend_dir(self.base_dir)
        self.project_root = self.layout.project_root
        self.runtime_state_dir = self.layout.runtime_state_dir

    def work_log(self, soul_id: str, *, limit: int = 20) -> SoulWorkLogView:
        normalized_soul_id = str(soul_id or "").strip().lower()
        safe_limit = max(1, min(int(limit or 20), 100))
        events: list[SoulActivityEvent] = []

        for task_payload in self._list_task_runs():
            resolved_soul_id = self._soul_id_for_payload(task_payload)
            if resolved_soul_id != normalized_soul_id:
                continue
            events.append(
                self._activity_for_task(
                    soul_id=resolved_soul_id,
                    task_payload=task_payload,
                )
            )

        events.sort(key=lambda item: item.last_activity_at, reverse=True)
        return SoulWorkLogView(
            soul_id=normalized_soul_id,
            limit=safe_limit,
            events=tuple(events[:safe_limit]),
        )

    def _activity_for_task(self, *, soul_id: str, task_payload: dict[str, Any]) -> SoulActivityEvent:
        task_run_id = str(task_payload.get("task_run_id") or "")
        artifact_refs = tuple(self._artifact_refs(task_run_id))
        agent_run = self._latest_agent_run(task_run_id)
        source_refs = self._source_refs(task_run_id, agent_run)
        status = str(task_payload.get("status") or "")
        task_id = str(task_payload.get("task_id") or "")
        title = self._task_title(task_payload)
        summary = f"{title}：{status or 'unknown'}"
        return SoulActivityEvent(
            event_id=f"soulwork:{self._safe_id(soul_id)}:{self._safe_id(task_run_id)}",
            soul_id=soul_id,
            task_run_id=task_run_id,
            session_id=str(task_payload.get("session_id") or ""),
            task_id=task_id,
            work_prompt_id=self._first_non_empty(
                task_payload.get("work_prompt_id"),
                dict(task_payload.get("diagnostics") or {}).get("work_prompt_id"),
            ),
            agent_id=str((agent_run or {}).get("agent_id") or task_payload.get("agent_id") or ""),
            agent_run_id=str((agent_run or {}).get("agent_run_id") or ""),
            status=status,
            title=title,
            summary=summary,
            artifact_count=len(artifact_refs),
            artifact_refs=artifact_refs,
            source_refs=tuple(source_refs),
            last_activity_at=float(task_payload.get("updated_at") or task_payload.get("created_at") or 0.0),
        )

    def _soul_id_for_payload(self, task_payload: dict[str, Any]) -> str:
        diagnostics = dict(task_payload.get("diagnostics") or {})
        return self._first_non_empty(
            task_payload.get("soul_id"),
            task_payload.get("default_soul_id"),
            diagnostics.get("soul_id"),
            diagnostics.get("default_soul_id"),
        ).lower()

    def _artifact_refs(self, task_run_id: str) -> list[str]:
        repo_root = self.project_root / "storage" / "artifact_repository"
        if not repo_root.exists():
            return []
        overview = ArtifactRepositoryService(repo_root, workspace_root=self.project_root).overview(
            task_run_id=task_run_id,
            limit=100,
        )
        refs: list[str] = []
        for item in list(overview.get("artifacts") or []):
            if isinstance(item, dict) and str(item.get("artifact_ref") or "").strip():
                refs.append(str(item["artifact_ref"]))
        return refs

    def _latest_agent_run(self, task_run_id: str) -> dict[str, Any]:
        runs = [item for item in self._list_agent_runs() if str(item.get("task_run_id") or "") == task_run_id]
        runs.sort(key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0.0), reverse=True)
        return runs[0] if runs else {}

    def _list_task_runs(self) -> list[dict[str, Any]]:
        return self._read_json_records(self.runtime_state_dir / "state_index" / "task_runs")

    def _list_agent_runs(self) -> list[dict[str, Any]]:
        return self._read_json_records(self.runtime_state_dir / "state_index" / "agent_runs")

    def _read_json_records(self, directory: Path) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def _source_refs(self, task_run_id: str, agent_run: dict[str, Any]) -> list[str]:
        refs = [f"state_index:task_runs/{task_run_id}"]
        if agent_run.get("agent_run_id"):
            refs.append(f"state_index:agent_runs/{agent_run['agent_run_id']}")
        event_path = self.runtime_state_dir / "events" / f"{self._safe_id(task_run_id)}.jsonl"
        if event_path.exists():
            refs.append(f"events:{event_path.name}")
        return refs

    def _task_title(self, task_payload: dict[str, Any]) -> str:
        diagnostics = dict(task_payload.get("diagnostics") or {})
        return self._first_non_empty(
            diagnostics.get("task_title"),
            diagnostics.get("task_graph_title"),
            diagnostics.get("project_title"),
            task_payload.get("task_id"),
            task_payload.get("task_run_id"),
        )

    @staticmethod
    def _first_non_empty(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _safe_id(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or ""))


