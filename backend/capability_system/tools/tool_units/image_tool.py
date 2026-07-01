from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.image_generation_tool import ImageGenerationInput, ImageGenerationTool
from pydantic import BaseModel, ConfigDict, PrivateAttr


class ImageInput(ImageGenerationInput):
    model_config = ConfigDict(extra="forbid")


class ImageTool(BaseTool):
    name: str = "image"
    description: str = "Generate a saved raster image asset from a precise visual prompt."
    args_schema: type[BaseModel] = ImageInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _delegate: ImageGenerationTool = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delegate = ImageGenerationTool(root_dir=root_dir)

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
        _ = run_manager
        return str(
            self._delegate.invoke(
                {
                    "prompt": prompt,
                    "model": model,
                    "target_id": target_id,
                    "asset_kind": asset_kind,
                    "size": size,
                    "quality": quality,
                    "request_timeout_seconds": request_timeout_seconds,
                    "output_size": output_size,
                    "overwrite": overwrite,
                }
            )
        )

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
        return await self._delegate.ainvoke(
            {
                "prompt": prompt,
                "model": model,
                "target_id": target_id,
                "asset_kind": asset_kind,
                "size": size,
                "quality": quality,
                "request_timeout_seconds": request_timeout_seconds,
                "output_size": output_size,
                "overwrite": overwrite,
            }
        )
