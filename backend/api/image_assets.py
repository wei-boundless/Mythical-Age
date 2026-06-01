from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from capability_system.capabilities.image_generation.image_asset_service import ImageAssetError, ImageAssetService

router = APIRouter()


class ImageAssetGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    target_id: str = ""
    asset_kind: str = "chat"
    size: str = "1024x1024"
    quality: str = ""
    model: str = ""
    request_timeout_seconds: float | None = None
    output_size: str = ""
    overwrite: bool = False


@router.get("/image-assets/config")
async def image_asset_config() -> dict[str, Any]:
    runtime = require_runtime()
    return ImageAssetService(runtime.base_dir).config_summary()


@router.post("/image-assets/generate")
async def generate_image_asset(payload: ImageAssetGenerateRequest) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await ImageAssetService(runtime.base_dir).generate(
            prompt=payload.prompt,
            target_id=payload.target_id,
            asset_kind=payload.asset_kind,
            size=payload.size,
            quality=payload.quality,
            model=payload.model,
            request_timeout_seconds=payload.request_timeout_seconds,
            output_size=payload.output_size,
            overwrite=payload.overwrite,
        )
    except ImageAssetError as exc:
        raise HTTPException(status_code=_image_error_http_status(exc), detail=exc.to_dict()) from exc


def _image_error_http_status(exc: ImageAssetError) -> int:
    code = str(exc.code or "")
    if code in {"timeout", "image_download_timeout"}:
        return 504
    if code == "image_provider_transient_error":
        status = 0
        for attempt in reversed(exc.attempts):
            try:
                status = int(attempt.get("http_status") or 0)
            except (TypeError, ValueError):
                status = 0
            if status:
                break
        if status in {408, 429, 500, 502, 503, 504}:
            return status
        return 502
    if code in {"image_provider_auth_error", "image_endpoint_not_found"}:
        return 502
    return 500
