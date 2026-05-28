from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from config import runtime_config


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

    def set_config(self, *, base_url: str, model: str, api_key: str | None = None) -> dict[str, Any]:
        current = dict(runtime_config.load().get("soul_image_assets") or {})
        payload: dict[str, Any] = {
            "base_url": str(base_url or "").strip(),
            "model": str(model or "gpt-image-2").strip() or "gpt-image-2",
        }
        next_api_key = str(api_key or "").strip()
        if next_api_key:
            payload["api_key"] = next_api_key
        elif str(current.get("api_key") or "").strip():
            payload["api_key"] = str(current.get("api_key") or "").strip()
        runtime_config.save({"soul_image_assets": payload})
        return self.config_summary()

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

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise SoulImageAssetError("Image API request timed out") from exc
        except httpx.HTTPError as exc:
            raise SoulImageAssetError(f"Image API request failed: {exc}") from exc
        if response.status_code >= 400:
            raise SoulImageAssetError(f"Image API failed with status {response.status_code}: {response.text[:500]}")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            content_type = str(response.headers.get("content-type") or "").strip()
            body_preview = response.text[:300].strip()
            detail = f"Image API returned non-JSON response"
            if content_type:
                detail += f" ({content_type})"
            if body_preview:
                detail += f": {body_preview}"
            raise SoulImageAssetError(detail) from exc
        items = list(data.get("data") or [])
        if not items:
            raise SoulImageAssetError("Image API returned no image data")
        first_item = dict(items[0] or {})
        b64 = str(first_item.get("b64_json") or "")
        if b64:
            try:
                image_bytes = base64.b64decode(b64)
            except Exception as exc:  # pragma: no cover - defensive decode guard
                raise SoulImageAssetError("Image API returned invalid base64") from exc
        else:
            image_url = str(first_item.get("url") or "").strip()
            if not image_url:
                returned_keys = ", ".join(sorted(str(key) for key in first_item.keys())) or "none"
                task_ref = str(data.get("task_id") or data.get("id") or "").strip()
                detail = f"Image API returned no b64_json or url; item keys: {returned_keys}"
                if task_ref:
                    detail += f"; task_id: {task_ref}"
                raise SoulImageAssetError(detail)
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                    image_response = await client.get(image_url)
            except httpx.TimeoutException as exc:
                raise SoulImageAssetError("Image download timed out") from exc
            except httpx.HTTPError as exc:
                raise SoulImageAssetError(f"Image download failed: {exc}") from exc
            if image_response.status_code >= 400:
                raise SoulImageAssetError(
                    f"Image download failed with status {image_response.status_code}: {image_response.text[:300]}"
                )
            image_bytes = image_response.content
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SoulImageAssetError("Generated asset is not a PNG")

        self.public_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return {
            **self._asset_response(output_path, filename, reused=False),
            "created": data.get("created"),
            "revised_prompt": first_item.get("revised_prompt") or "",
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
        override = dict(runtime_config.load().get("soul_image_assets") or {})
        return str(os.getenv("SOUL_IMAGE_API_BASE_URL") or override.get("base_url") or "").strip()

    @staticmethod
    def _api_key() -> str:
        override = dict(runtime_config.load().get("soul_image_assets") or {})
        return str(os.getenv("SOUL_IMAGE_API_KEY") or override.get("api_key") or "").strip()

    @staticmethod
    def _model() -> str:
        override = dict(runtime_config.load().get("soul_image_assets") or {})
        return str(os.getenv("SOUL_IMAGE_MODEL") or override.get("model") or "gpt-image-2").strip()


