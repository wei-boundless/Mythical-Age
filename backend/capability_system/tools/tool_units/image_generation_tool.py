from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.capabilities.image_generation.image_asset_service import ImageAssetError, ImageAssetService


class ImageGenerationInput(BaseModel):
    prompt: str = Field(..., description="Precise visual prompt for the image model.")
    model: str = Field(default="", description="Optional image model override, for example gpt-image-2. Leave blank to use backend config.")
    target_id: str = Field(default="", description="Optional stable asset id. Leave blank to auto-generate.")
    asset_kind: str = Field(default="chat", description="Asset kind used in the saved filename.")
    size: str = Field(default="1024x1024", description="Provider generation size. Use 1024x1024 unless the provider explicitly supports another size.")
    quality: str = Field(default="", description="Optional provider quality such as low, medium, high, auto, or standard.")
    request_timeout_seconds: float = Field(default=150.0, ge=30.0, le=240.0, description="Single provider request timeout. Image providers can take around 100 seconds for a completed asset.")
    output_size: str = Field(default="", description="Optional final PNG size for local resizing, for example 128x128. This is not sent to the image provider.")
    overwrite: bool = Field(default=False, description="Reuse an existing generated asset with the same id unless explicitly set true.")


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
        request_timeout_seconds: float = 150.0,
        output_size: str = "",
        overwrite: bool = False,
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
        request_timeout_seconds: float = 150.0,
        output_size: str = "",
        overwrite: bool = False,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            return json.dumps({"ok": False, "error": "Image prompt is required"}, ensure_ascii=False)
        safe_target = str(target_id or "").strip()
        try:
            generated = await ImageAssetService(self._root_dir).generate(
                prompt=clean_prompt,
                target_id=safe_target,
                asset_kind=str(asset_kind or "chat").strip() or "chat",
                size=str(size or "1024x1024").strip() or "1024x1024",
                quality=str(quality or "").strip(),
                model=str(model or "").strip(),
                request_timeout_seconds=float(request_timeout_seconds or 150.0),
                output_size=str(output_size or "").strip(),
                overwrite=bool(overwrite),
            )
        except ImageAssetError as exc:
            structured_error = exc.to_dict()
            provider_retryable = bool(structured_error.get("retryable", False))
            structured_error["provider_retryable"] = provider_retryable
            structured_error["retryable"] = False
            structured_error["agent_auto_retry_allowed"] = False
            structured_error["agent_retry_policy"] = "do_not_auto_retry"
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "structured_error": structured_error,
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
                "artifact_refs": [
                    {
                        "kind": "image",
                        "path": generated.get("file_path"),
                        "src": generated.get("asset_path"),
                        "bytes": generated.get("bytes"),
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )



