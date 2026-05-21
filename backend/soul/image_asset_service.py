from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


class SoulImageAssetError(RuntimeError):
    pass


class SoulImageAssetService:
    """Generate and store soul visual assets through an OpenAI-compatible image API."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        load_dotenv(self.base_dir / ".env")
        self.project_root = self.base_dir.resolve().parent
        self.public_dir = (self.project_root / "frontend" / "public" / "souls" / "generated").resolve()

    def configured(self) -> bool:
        return bool(self._api_key() and self._base_url() and self._model())

    def config_summary(self) -> dict[str, Any]:
        return {
            "configured": self.configured(),
            "base_url": self._base_url(),
            "model": self._model(),
            "api_key_present": bool(self._api_key()),
            "public_dir": str(self.public_dir),
        }

    async def generate(
        self,
        *,
        prompt: str,
        target_id: str,
        asset_kind: str = "world",
        size: str = "1024x1024",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise SoulImageAssetError("Image prompt is required")
        if not self.configured():
            raise SoulImageAssetError("Soul image generation is not configured")

        safe_kind = self._safe_slug(asset_kind or "asset")
        safe_target = self._safe_slug(target_id or f"asset-{int(time.time())}")
        filename = f"{safe_kind}-{safe_target}.png"
        output_path = (self.public_dir / filename).resolve()
        if self.public_dir not in output_path.parents:
            raise SoulImageAssetError("Invalid image output path")
        if output_path.exists() and not overwrite:
            return self._asset_response(output_path, filename, reused=True)

        payload = {
            "model": self._model(),
            "prompt": clean_prompt,
            "size": size,
            "n": 1,
            "response_format": "b64_json",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self._base_url().rstrip('/')}/images/generations"

        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
        if response.status_code >= 400:
            raise SoulImageAssetError(f"Image API failed with status {response.status_code}: {response.text[:500]}")

        data = response.json()
        items = list(data.get("data") or [])
        if not items:
            raise SoulImageAssetError("Image API returned no image data")
        b64 = str(items[0].get("b64_json") or "")
        if not b64:
            raise SoulImageAssetError("Image API did not return b64_json")

        try:
            image_bytes = base64.b64decode(b64)
        except Exception as exc:  # pragma: no cover - defensive decode guard
            raise SoulImageAssetError("Image API returned invalid base64") from exc
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SoulImageAssetError("Generated asset is not a PNG")

        self.public_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return {
            **self._asset_response(output_path, filename, reused=False),
            "created": data.get("created"),
            "revised_prompt": items[0].get("revised_prompt") or "",
        }

    def _asset_response(self, output_path: Path, filename: str, *, reused: bool) -> dict[str, Any]:
        return {
            "asset_path": f"/souls/generated/{filename}",
            "file_path": str(output_path),
            "reused": reused,
            "bytes": output_path.stat().st_size if output_path.exists() else 0,
        }

    @staticmethod
    def _safe_slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lower())
        slug = slug.strip(".-")
        return slug[:80] or "asset"

    @staticmethod
    def _base_url() -> str:
        return str(os.getenv("SOUL_IMAGE_API_BASE_URL") or "").strip()

    @staticmethod
    def _api_key() -> str:
        return str(os.getenv("SOUL_IMAGE_API_KEY") or "").strip()

    @staticmethod
    def _model() -> str:
        return str(os.getenv("SOUL_IMAGE_MODEL") or "gpt-image-2").strip()
