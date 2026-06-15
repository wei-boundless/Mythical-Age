from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bootstrap.settings import AppSettingsService
from config import RuntimeConfigManager


def test_attachment_and_image_ocr_runtime_config_defaults_and_normalizes(tmp_path: Path) -> None:
    manager = RuntimeConfigManager(tmp_path / "config.json")

    attachment_defaults = manager.get_attachments_config()
    assert attachment_defaults["enabled"] is True
    assert attachment_defaults["max_upload_bytes"] == 10 * 1024 * 1024
    assert attachment_defaults["max_files_per_message"] == 8
    assert attachment_defaults["storage_relative_dir"] == "storage/chat_attachments"

    defaults = manager.get_image_ocr_config()
    assert defaults["enabled"] is True
    assert defaults["provider"] == "rapidocr"
    assert defaults["default_language"] == "chi_sim+eng"
    assert defaults["timeout_seconds"] == 60
    assert defaults["max_text_chars"] == 12000
    assert defaults["mcp_route"] == "image_ocr"

    attachment_saved = manager.set_attachments_config(
        {
            "enabled": "false",
            "max_upload_bytes": 12,
            "max_files_per_message": 100,
            "storage_relative_dir": "../escape",
        }
    )
    attachments = dict(attachment_saved["attachments"])
    assert attachments["enabled"] is False
    assert attachments["max_upload_bytes"] == 1024
    assert attachments["max_files_per_message"] == 16
    assert attachments["storage_relative_dir"] == "storage/chat_attachments"

    saved = manager.set_image_ocr_config(
        {
            "enabled": "false",
            "provider": "unknown",
            "default_language": "",
            "timeout_seconds": 999,
            "max_text_chars": 999999,
            "mcp_route": "image_ocr",
        }
    )

    payload = dict(saved["image_ocr"])
    assert payload["enabled"] is False
    assert payload["provider"] == "rapidocr"
    assert payload["default_language"] == "chi_sim+eng"
    assert payload["timeout_seconds"] == 240
    assert payload["max_text_chars"] == 120000
    assert payload["mcp_route"] == "image_ocr"


def test_runtime_config_console_exposes_image_ocr_group() -> None:
    payload = AppSettingsService(BACKEND_DIR).runtime_config_console_payload()
    groups = {str(group["group_id"]): group for group in payload["groups"]}

    assert "attachments" in groups
    attachment_group = groups["attachments"]
    attachment_field_keys = {str(field["key"]) for field in attachment_group["fields"]}
    assert {"enabled", "max_upload_bytes", "max_files_per_message", "storage_relative_dir"} <= attachment_field_keys

    assert "image_ocr" in groups
    ocr_group = groups["image_ocr"]
    field_keys = {str(field["key"]) for field in ocr_group["fields"]}
    assert {"enabled", "provider", "default_language", "timeout_seconds", "max_text_chars"} <= field_keys
    assert ocr_group["metadata"]["tool_name"] == "attachment_extract_text"
    assert ocr_group["metadata"]["local_mcp_unit"] == "local_mcp:image_ocr"
