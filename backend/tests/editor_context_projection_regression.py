from __future__ import annotations

from harness.runtime.dynamic_context.manager import DynamicContextManager
from harness.runtime.dynamic_context.models import DynamicContextInput


def test_editor_context_projects_content_preview_without_fake_selection() -> None:
    projection = DynamicContextManager().project(
        DynamicContextInput(
            invocation_kind="single_agent_turn",
            session_id="session:editor",
            turn_id="turn:editor",
            current_user_message="检查当前文件",
            editor_context={
                "source": "frontend.center_workspace",
                "workspace_roots": ["D:/repo"],
                "active_file": {
                    "path": "frontend/src/App.tsx",
                    "language_id": "typescriptreact",
                    "dirty": True,
                    "content_preview": {
                        "text": "export function App() { return null; }",
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 37},
                        "truncated": False,
                        "source": "frontend_inspector",
                    },
                },
            },
        )
    )

    editor_context = projection.volatile_request_projection["editor_context"]

    assert editor_context["active_file"]["path"] == "frontend/src/App.tsx"
    assert editor_context["active_file"]["content_preview"]["text"] == "export function App() { return null; }"
    assert "selection" not in editor_context["active_file"]
    assert editor_context["limits"]["content_preview_chars"] == len("export function App() { return null; }")
