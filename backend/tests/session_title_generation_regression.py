from __future__ import annotations

import asyncio
from pathlib import Path

from api import sessions as sessions_api
from sessions import SessionManager


class TitleModelStub:
    def __init__(self, title: str) -> None:
        self.title = title
        self.first_user_message = ""

    async def generate_title(self, first_user_message: str) -> str:
        self.first_user_message = first_user_message
        return self.title


class RuntimeStub:
    def __init__(self, session_manager: SessionManager, model_runtime: TitleModelStub) -> None:
        self.session_manager = session_manager
        self.model_runtime = model_runtime


def test_generate_title_repairs_assistant_summary_title_from_first_user_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(
        title="经过全面排查，以下是我的诊断结果： --- ## 诊断结论 ##",
    )["id"]
    manager.append_messages(
        session_id,
        [
            {"role": "user", "content": "你可以帮我检查一下我的项目里的简历制作网站吗，为什么模板按钮没有反应"},
            {"role": "assistant", "content": "经过全面排查，以下是我的诊断结果：\n\n## 诊断结论"},
        ],
    )
    model = TitleModelStub("检查简历网站按钮")
    monkeypatch.setattr(sessions_api, "require_runtime", lambda: RuntimeStub(manager, model))
    updated_at_before = manager.get_session_summary(session_id)["updated_at"]

    result = asyncio.run(
        sessions_api.generate_title_from_first_user_message(
            session_id,
            sessions_api.GenerateTitleRequest(),
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert model.first_user_message == "你可以帮我检查一下我的项目里的简历制作网站吗，为什么模板按钮没有反应"
    assert result == {"session_id": session_id, "title": "检查简历网站按钮"}
    summary = manager.get_session_summary(session_id)
    assert summary["title"] == "检查简历网站按钮"
    assert summary["updated_at"] == updated_at_before


def test_generate_title_preserves_manual_title(tmp_path: Path, monkeypatch) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    manager = SessionManager(backend_dir)
    session_id = manager.create_session(title="手动命名")["id"]
    manager.append_messages(session_id, [{"role": "user", "content": "这句话不应该覆盖手动标题"}])
    model = TitleModelStub("错误覆盖")
    monkeypatch.setattr(sessions_api, "require_runtime", lambda: RuntimeStub(manager, model))

    result = asyncio.run(
        sessions_api.generate_title_from_first_user_message(
            session_id,
            sessions_api.GenerateTitleRequest(),
            workspace_view=None,
            task_environment_id=None,
            project_id=None,
        )
    )

    assert model.first_user_message == ""
    assert result == {"session_id": session_id, "title": "手动命名"}
    assert manager.get_session_summary(session_id)["title"] == "手动命名"
