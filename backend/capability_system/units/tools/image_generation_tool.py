from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from soul.image_asset_service import SoulImageAssetError, SoulImageAssetService


class ImageGenerationInput(BaseModel):
    prompt: str = Field(..., description="Precise visual prompt for the image model.")
    model: str = Field(default="", description="Optional image model override, for example gpt-image-2. Leave blank to use backend config.")
    target_id: str = Field(default="", description="Optional stable asset id. Leave blank to auto-generate.")
    asset_kind: str = Field(default="chat", description="Asset kind used in the saved filename.")
    size: str = Field(default="1024x1024", description="Provider generation size. Use 1024x1024 unless the provider explicitly supports another size.")
    quality: str = Field(default="", description="Optional provider quality such as low, medium, high, auto, or standard.")
    request_timeout_seconds: float = Field(default=55.0, ge=30.0, le=120.0, description="Single provider request timeout. Keep below gateway limits for long-running agent tasks.")
    output_size: str = Field(default="", description="Optional final PNG size for local resizing, for example 128x128. This is not sent to the image provider.")
    overwrite: bool = Field(default=True, description="Overwrite an existing generated asset with the same id.")


class ImageGenerationTool(BaseTool):
    name: str = "image_generate"
    description: str = (
        "Generate a raster image from a high-quality visual prompt. "
        "Returns JSON with image src, file path, revised prompt, and file size."
    )
    args_schema: Type[BaseModel] = ImageGenerationInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir

    def _run(
        self,
        prompt: str,
        model: str = "",
        target_id: str = "",
        asset_kind: str = "chat",
        size: str = "1024x1024",
        quality: str = "",
        request_timeout_seconds: float = 55.0,
        output_size: str = "",
        overwrite: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        return asyncio.run(self._arun(prompt, model, target_id, asset_kind, size, quality, request_timeout_seconds, output_size, overwrite, None))

    async def _arun(
        self,
        prompt: str,
        model: str = "",
        target_id: str = "",
        asset_kind: str = "chat",
        size: str = "1024x1024",
        quality: str = "",
        request_timeout_seconds: float = 55.0,
        output_size: str = "",
        overwrite: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            return json.dumps({"ok": False, "error": "Image prompt is required"}, ensure_ascii=False)
        safe_target = str(target_id or "").strip() or f"tool-{int(time.time())}"
        try:
            generated = await SoulImageAssetService(self._root_dir).generate(
                prompt=clean_prompt,
                target_id=safe_target,
                asset_kind=str(asset_kind or "chat").strip() or "chat",
                size=str(size or "1024x1024").strip() or "1024x1024",
                quality=str(quality or "").strip(),
                model=str(model or "").strip(),
                request_timeout_seconds=float(request_timeout_seconds or 55.0),
                output_size=str(output_size or "").strip(),
                overwrite=bool(overwrite),
            )
        except SoulImageAssetError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "structured_error": exc.to_dict(),
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "ok": True,
                "image": {
                    "src": generated.get("asset_path"),
                    "file_path": generated.get("file_path"),
                    "bytes": generated.get("bytes"),
                    "revised_prompt": generated.get("revised_prompt") or "",
                    "provider_size": generated.get("provider_size") or "",
                    "final_size": generated.get("final_size") or "",
                    "model": generated.get("model") or str(model or ""),
                    "duration_ms": generated.get("duration_ms") or 0,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )


