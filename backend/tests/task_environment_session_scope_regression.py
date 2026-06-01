from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import app


WRITING_SCOPE = {
    "workspace_view": "task_environment",
    "task_environment_id": "env.creation.writing",
    "project_id": "project.creation.writing.honghuang",
}


def test_session_detail_rejects_wrong_task_environment_scope() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/sessions",
            json={"title": "Scoped writing", "scope": WRITING_SCOPE},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]

        response = client.get(
            f"/api/sessions/{session_id}/history",
            params={
                "workspace_view": "task_environment",
                "task_environment_id": "env.development.code",
                "project_id": "project.creation.writing.honghuang",
            },
        )

        assert response.status_code == 409
        assert response.json()["detail"]["message"] == "Session scope mismatch"


def test_task_environment_session_resolver_creates_project_scoped_session() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/task-environments/env.creation.writing/sessions/resolve",
            json={
                "workspace_view": "task_environment",
                "project_id": "project.creation.writing.honghuang",
                "intent": "new_conversation",
                "title": "洪荒时代 会话",
                "create_if_missing": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["created"] is True
        assert payload["scope"] == WRITING_SCOPE
        assert payload["session"]["scope"] == WRITING_SCOPE


def test_graph_run_start_rejects_session_scope_that_does_not_match_session() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/sessions",
            json={"title": "Writing graph", "scope": WRITING_SCOPE},
        )
        assert created.status_code == 200
        session_id = created.json()["id"]

        response = client.post(
            "/api/orchestration/harness/task-graphs/creation.writing.honghuang/start",
            json={
                "session_id": session_id,
                "session_scope": {
                    "workspace_view": "task_environment",
                    "task_environment_id": "env.development.code",
                    "project_id": "project.creation.writing.honghuang",
                },
                "include_trace": False,
                "dispatch_ready": False,
            },
        )

        assert response.status_code in {404, 409}
        if response.status_code == 409:
            detail = response.json()["detail"]
            assert "scope" in str(detail).lower() or "environment" in str(detail).lower()
