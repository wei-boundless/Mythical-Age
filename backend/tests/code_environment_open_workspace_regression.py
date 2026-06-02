from pathlib import Path

from fastapi.testclient import TestClient

import api.code_environment as code_environment_api
from app import app


def test_open_workspace_root_uses_project_root_without_accepting_arbitrary_path(monkeypatch) -> None:
    opened: list[Path] = []

    def fake_open_directory(path: Path) -> None:
        opened.append(path)

    monkeypatch.setattr(code_environment_api, "_open_directory", fake_open_directory)

    with TestClient(app) as client:
        response = client.post("/api/code-environment/open-workspace-root")

    assert response.status_code == 200
    payload = response.json()
    assert payload["opened"] is True
    assert payload["path"] == str(opened[0])
    assert opened[0].name == "langchain-agent"
