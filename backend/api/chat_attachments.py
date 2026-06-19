from __future__ import annotations

import mimetypes
import hashlib
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.deps import require_runtime
from capability_system.capabilities.attachments import (
    SUPPORTED_ATTACHMENT_IMAGE_MIME_TYPES,
    SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES,
)
from config import runtime_config
from project_layout import ProjectLayout
from sessions import validate_session_id


router = APIRouter()
MAX_ORIGINAL_FILENAME_CHARS = 180


@router.post("/chat/attachments")
async def upload_chat_attachment(
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    runtime = require_runtime()
    validated_session_id = validate_session_id(session_id)
    try:
        runtime.session_manager.get_session_summary(validated_session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    config = runtime_config.get_attachments_config()
    if not bool(config.get("enabled", True)):
        raise HTTPException(status_code=403, detail={"message": "Chat attachments are disabled", "code": "attachments_disabled"})

    filename = _safe_original_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail={"message": "Unsupported attachment type", "supported_suffixes": sorted(SUPPORTED_ATTACHMENT_IMAGE_SUFFIXES)})

    content_type = str(file.content_type or "").strip().lower()
    allowed_mime_types = _allowed_mime_types(config)
    if content_type and content_type not in allowed_mime_types:
        raise HTTPException(status_code=400, detail={"message": "Unsupported attachment MIME type", "mime_type": content_type, "supported_mime_types": sorted(allowed_mime_types)})

    data = await file.read()
    size_bytes = len(data)
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail={"message": "Attachment file is empty", "code": "empty_attachment"})
    max_upload_bytes = int(config.get("max_upload_bytes") or 10 * 1024 * 1024)
    if size_bytes > max_upload_bytes:
        raise HTTPException(status_code=413, detail={"message": "Attachment file exceeds the configured upload limit", "max_upload_bytes": max_upload_bytes})

    image_info = _inspect_image(data)
    attachment_id = uuid.uuid4().hex
    stored_name = f"{attachment_id}{suffix}"
    storage_relative_dir = str(config.get("storage_relative_dir") or "storage/chat_attachments").replace("\\", "/").strip("/")
    root = _attachment_root(runtime.base_dir, storage_relative_dir=storage_relative_dir)
    session_dir = (root / validated_session_id).resolve()
    _ensure_within_root(root, session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    target = (session_dir / stored_name).resolve()
    _ensure_within_root(root, target)
    target.write_bytes(data)

    relative_path = f"{storage_relative_dir}/{validated_session_id}/{stored_name}"
    return {
        "attachment_id": attachment_id,
        "session_id": validated_session_id,
        "filename": filename,
        "mime_type": content_type or mimetypes.guess_type(filename)[0] or str(image_info.get("mime_type") or ""),
        "size_bytes": size_bytes,
        "content_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "path": relative_path,
        "created_at": time.time(),
        "width": image_info.get("width"),
        "height": image_info.get("height"),
        "authority": "api.chat_attachments",
        "storage_authority": "attachment_store",
    }


def _attachment_root(base_dir: str | Path, *, storage_relative_dir: str) -> Path:
    layout = ProjectLayout.from_backend_dir(base_dir)
    return (layout.project_root / storage_relative_dir).resolve()


def _ensure_within_root(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": "Attachment storage path escaped root", "code": "attachment_storage_escape"}) from exc


def _allowed_mime_types(config: dict[str, Any]) -> set[str]:
    values = config.get("allowed_mime_types")
    if isinstance(values, list):
        result = {str(item or "").strip().lower() for item in values if str(item or "").strip()}
        return result or set(SUPPORTED_ATTACHMENT_IMAGE_MIME_TYPES)
    return set(SUPPORTED_ATTACHMENT_IMAGE_MIME_TYPES)


def _safe_original_filename(filename: str | None) -> str:
    raw = Path(str(filename or "image").replace("\\", "/")).name.strip() or "image"
    cleaned = "".join(char if char.isprintable() and char not in "\r\n\t" else "_" for char in raw)
    return cleaned[:MAX_ORIGINAL_FILENAME_CHARS].strip(" .") or "image"


def _inspect_image(data: bytes) -> dict[str, Any]:
    try:
        from PIL import Image, UnidentifiedImageError  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail={"message": "Pillow is required for image attachment validation", "code": "missing_pillow"}) from exc
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            image_format = str(image.format or "").lower()
            image.verify()
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail={"message": "Attachment is not a readable image", "code": "attachment_not_image"}) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail={"message": f"Attachment image validation failed: {exc}", "code": "attachment_image_validation_failed"}) from exc
    return {"width": width, "height": height, "format": image_format, "mime_type": Image.MIME.get(image_format.upper(), "")}
