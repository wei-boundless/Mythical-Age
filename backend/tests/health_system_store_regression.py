from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest

from health_system.evidence_scorer import score_runtime_event
from health_system.models import HealthIssue, HealthTaskRequest
from health_system.store import HealthStore


def test_runtime_event_temporal_weight_uses_zero_based_indices() -> None:
    event = {"event_type": "step_completed", "payload": {}}

    first = score_runtime_event(event, total_events=3, index=0).temporal_score
    second = score_runtime_event(event, total_events=3, index=1).temporal_score
    third = score_runtime_event(event, total_events=3, index=2).temporal_score

    assert first < second < third
    assert first == 0.5
    assert second == 0.75
    assert third == 1.0


def test_health_store_upsert_issue_serializes_concurrent_writers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = HealthStore(tmp_path)
    original_read = HealthStore._read_jsonl_dicts

    def slow_read(self: HealthStore, path: Path) -> list[dict[str, object]]:
        rows = original_read(self, path)
        time.sleep(0.05)
        return rows

    monkeypatch.setattr(HealthStore, "_read_jsonl_dicts", slow_read)

    def upsert(issue_id: str) -> None:
        store.upsert_issue(
            HealthIssue(
                issue_id=issue_id,
                title=issue_id,
                owner_system="test",
                severity="medium",
                status="triage_ready",
                source="test",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(upsert, "issue:a"), executor.submit(upsert, "issue:b")]
        for future in futures:
            future.result(timeout=5)

    assert {issue.issue_id for issue in store.load_issues()} == {"issue:a", "issue:b"}


def test_atomic_write_text_removes_temp_file_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = HealthStore(tmp_path)
    target = store.store_dir / "issues.jsonl"
    original_replace = Path.replace

    def failing_replace(self: Path, target_path: str | Path) -> Path:
        if self.name.startswith(".issues.") and self.suffix == ".tmp":
            raise PermissionError("target is locked")
        return original_replace(self, target_path)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(PermissionError):
        store._atomic_write_text(target, "content\n")

    assert list(store.store_dir.glob(".issues.*.tmp")) == []


def test_task_request_authority_survives_store_roundtrip(tmp_path: Path) -> None:
    store = HealthStore(tmp_path)
    request = HealthTaskRequest(
        request_id="request:authority",
        issue_id="issue:authority",
        task_kind="diagnosis",
        task_id="task:authority",
        flow_id="flow:authority",
        authority="health_system.agent_generated",
    )

    store.upsert_task_request(request)

    assert store.load_task_requests()[0].authority == "health_system.agent_generated"
