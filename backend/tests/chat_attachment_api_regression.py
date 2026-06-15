from __future__ import annotations

from io import BytesIO
import shutil
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import api.chat_attachments as chat_attachments_module
from app import app
from config import RuntimeConfigManager
from tests.support.app_client import isolated_app_client


def test_chat_attachment_upload_stores_workspace_readable_image() -> None:
    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Attachment upload"})
        assert created.status_code == 200
        session_id = created.json()["id"]
        session_dir = PROJECT_ROOT / "storage" / "chat_attachments" / session_id
        try:
            response = client.post(
                "/api/chat/attachments",
                data={"session_id": session_id},
                files={"file": ("sample.png", _png_bytes(), "image/png")},
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["session_id"] == session_id
            assert payload["filename"] == "sample.png"
            assert payload["mime_type"] == "image/png"
            assert payload["path"].startswith(f"storage/chat_attachments/{session_id}/")
            assert payload["path"].endswith(".png")
            assert payload["size_bytes"] > 0
            assert payload["width"] == 64
            assert payload["height"] == 32
            assert (PROJECT_ROOT / payload["path"]).is_file()
        finally:
            if session_dir.exists():
                shutil.rmtree(session_dir)


def test_chat_attachment_upload_rejects_non_image_file() -> None:
    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Attachment reject"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        response = client.post(
            "/api/chat/attachments",
            data={"session_id": session_id},
            files={"file": ("notes.txt", b"not an image", "text/plain")},
        )

        assert response.status_code == 400


def test_chat_attachment_upload_uses_attachment_size_limit(monkeypatch, tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")
    manager.set_attachments_config({"max_upload_bytes": 1024})
    monkeypatch.setattr(chat_attachments_module, "runtime_config", manager)

    with isolated_app_client(app) as client:
        created = client.post("/api/sessions", json={"title": "Attachment size limit"})
        assert created.status_code == 200
        session_id = created.json()["id"]

        response = client.post(
            "/api/chat/attachments",
            data={"session_id": session_id},
            files={"file": ("large.png", _png_bytes(width=1024, height=1024), "image/png")},
        )

        assert response.status_code == 413
        assert response.json()["detail"]["max_upload_bytes"] == 1024


def _png_bytes(*, width: int = 64, height: int = 32) -> bytes:
    from PIL import Image  # type: ignore

    image = Image.new("RGB", (width, height), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
