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
    target_id: str = Field(default="", description="Optional stable asset id. Leave blank to auto-generate.")
    asset_kind: str = Field(default="chat", description="Asset kind used in the saved filename.")
    size: str = Field(default="1024x1024", description="Image size, for example 1024x1024.")
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
        target_id: str = "",
        asset_kind: str = "chat",
        size: str = "1024x1024",
        overwrite: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        return asyncio.run(self._arun(prompt, target_id, asset_kind, size, overwrite, None))

    async def _arun(
        self,
        prompt: str,
        target_id: str = "",
        asset_kind: str = "chat",
        size: str = "1024x1024",
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
                overwrite=bool(overwrite),
            )
        except SoulImageAssetError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        return json.dumps(
            {
                "ok": True,
                "image": {
                    "src": generated.get("asset_path"),
                    "file_path": generated.get("file_path"),
                    "bytes": generated.get("bytes"),
                    "revised_prompt": generated.get("revised_prompt") or "",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
