from __future__ import annotations

from api.chat import _effective_editor_context


class _FakeVSCodeStore:
    def __init__(self, context: dict):
        self.context = context
        self.calls: list[str] = []

    def latest_editor_context(self, session_id: str, *, session_manager=None):
        self.calls.append(session_id)
        return dict(self.context)


def test_workspace_only_payload_does_not_hide_vscode_active_file(monkeypatch) -> None:
    store = _FakeVSCodeStore(
        {
            "source": "vscode",
            "workspace_roots": ["D:/AI/langchain-agent"],
            "active_file": {
                "path": "D:/AI/langchain-agent/mario.html",
                "language_id": "html",
                "dirty": False,
                "content_preview": {
                    "text": "<!doctype html>\n",
                    "truncated": False,
                    "source": "vscode_buffer",
                },
            },
            "visible_files": [
                {"path": "D:/AI/langchain-agent/mario.html", "language_id": "html", "dirty": False},
            ],
        }
    )
    monkeypatch.setattr("api.chat.get_vscode_connection_store", lambda: store)

    merged = _effective_editor_context(
        "session:mario",
        {
            "source": "frontend.center_workspace",
            "workspace_roots": ["D:/AI/langchain-agent"],
            "visible_files": [],
        },
        allow_vscode_fallback=True,
    )

    assert store.calls == ["session:mario"]
    assert merged["active_file"]["path"] == "D:/AI/langchain-agent/mario.html"
    assert merged["active_file"]["content_preview"]["source"] == "vscode_buffer"
    assert merged["visible_files"][0]["path"] == "D:/AI/langchain-agent/mario.html"
    assert merged["merge_reason"] == "payload_workspace_only_vscode_file_focus"
    assert merged["authority"] == "api.chat.effective_editor_context"


def test_payload_active_file_remains_primary_when_vscode_has_other_file(monkeypatch) -> None:
    store = _FakeVSCodeStore(
        {
            "source": "vscode",
            "workspace_roots": ["D:/repo"],
            "active_file": {"path": "D:/repo/other.html", "language_id": "html", "dirty": False},
        }
    )
    monkeypatch.setattr("api.chat.get_vscode_connection_store", lambda: store)

    merged = _effective_editor_context(
        "session:frontend-file",
        {
            "source": "frontend.center_workspace",
            "workspace_roots": ["D:/repo"],
            "active_file": {"path": "mario.html", "language_id": "html", "dirty": False},
            "visible_files": [{"path": "mario.html", "language_id": "html", "dirty": False}],
        },
        allow_vscode_fallback=True,
    )

    assert merged["active_file"]["path"] == "mario.html"
    assert merged["merge_reason"] == "payload_editor_context_preferred"


def test_payload_active_file_is_enriched_from_matching_vscode_file(monkeypatch) -> None:
    store = _FakeVSCodeStore(
        {
            "source": "vscode",
            "workspace_roots": ["D:/repo"],
            "active_file": {
                "path": "D:/repo/mario.html",
                "language_id": "html",
                "dirty": True,
                "content_preview": {"text": "<canvas></canvas>", "truncated": False, "source": "vscode_buffer"},
            },
        }
    )
    monkeypatch.setattr("api.chat.get_vscode_connection_store", lambda: store)

    merged = _effective_editor_context(
        "session:matching-file",
        {
            "source": "frontend.center_workspace",
            "workspace_roots": ["D:/repo"],
            "active_file": {"path": "D:/repo/mario.html", "language_id": "html", "dirty": False},
            "visible_files": [{"path": "D:/repo/mario.html", "language_id": "html", "dirty": False}],
        },
        allow_vscode_fallback=True,
    )

    assert merged["active_file"]["path"] == "D:/repo/mario.html"
    assert merged["active_file"]["dirty"] is True
    assert merged["active_file"]["content_preview"]["source"] == "vscode_buffer"
    assert merged["merge_reason"] == "payload_active_file_enriched_from_vscode"

