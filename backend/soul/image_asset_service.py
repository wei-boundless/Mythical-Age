from __future__ import annotations

import base64
import asyncio
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from PIL import Image
from config import runtime_config


class SoulImageAssetError(RuntimeError):
    def __init__(self, message: str, *, code: str = "image_generation_failed", retryable: bool = True, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.attempts = [dict(item) for item in list(attempts or []) if isinstance(item, dict)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "origin": "image_provider",
            "attempts": [dict(item) for item in self.attempts],
        }


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
        output_size: str = "",
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
        provider_size, requested_size = _resolve_generation_and_output_sizes(size=size, output_size=output_size)

        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self._base_url().rstrip('/')}/images/generations"

        attempts: list[dict[str, Any]] = []
        data: dict[str, Any] | None = None
        for payload in self._generation_payloads(prompt=clean_prompt, size=provider_size):
            result = await self._post_generation_payload_concurrently(endpoint=endpoint, headers=headers, payload=payload)
            attempts.extend(list(result.get("attempts") or []))
            if result.get("data") is not None:
                data = dict(result.get("data") or {})
                break
            api_error = dict(result.get("api_error") or {})
            if api_error and _should_try_next_payload(api_error):
                continue
            if api_error:
                raise SoulImageAssetError(
                    _format_generation_failure(attempts),
                    code=str(api_error.get("code") or "image_api_error"),
                    retryable=bool(api_error.get("retryable", True)),
                    attempts=attempts,
                )
        if data is None:
            raise SoulImageAssetError(_format_generation_failure(attempts), code="all_image_generation_attempts_failed", retryable=True, attempts=attempts)

        items = list(data.get("data") or [])
        if not items:
            raise SoulImageAssetError("Image API returned no image data", code="empty_image_data", retryable=True, attempts=attempts)
        first_item = dict(items[0] or {})
        b64 = str(first_item.get("b64_json") or "")
        if b64:
            try:
                image_bytes = base64.b64decode(b64)
            except Exception as exc:  # pragma: no cover - defensive decode guard
                raise SoulImageAssetError("Image API returned invalid base64", code="invalid_image_base64", retryable=True, attempts=attempts) from exc
        else:
            image_url = str(first_item.get("url") or "").strip()
            if not image_url:
                returned_keys = ", ".join(sorted(str(key) for key in first_item.keys())) or "none"
                task_ref = str(data.get("task_id") or data.get("id") or "").strip()
                detail = f"Image API returned no b64_json or url; item keys: {returned_keys}"
                if task_ref:
                    detail += f"; task_id: {task_ref}"
                raise SoulImageAssetError(detail, code="missing_image_payload", retryable=True, attempts=attempts)
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
                    image_response = await client.get(image_url)
            except httpx.TimeoutException as exc:
                raise SoulImageAssetError("Image download timed out", code="image_download_timeout", retryable=True, attempts=attempts) from exc
            except httpx.HTTPError as exc:
                raise SoulImageAssetError(f"Image download failed: {exc}", code="image_download_failed", retryable=True, attempts=attempts) from exc
            if image_response.status_code >= 400:
                raise SoulImageAssetError(
                    f"Image download failed with status {image_response.status_code}: {image_response.text[:300]}",
                    code="image_download_http_error",
                    retryable=True,
                    attempts=attempts,
                )
            image_bytes = image_response.content
        if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SoulImageAssetError("Generated asset is not a PNG", code="generated_asset_not_png", retryable=False, attempts=attempts)
        final_size = _png_size(image_bytes)
        if requested_size and requested_size != final_size:
            image_bytes = _resize_png(image_bytes, requested_size)
            final_size = requested_size

        self.public_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return {
            **self._asset_response(output_path, filename, reused=False),
            "created": data.get("created"),
            "revised_prompt": first_item.get("revised_prompt") or "",
            "requested_size": _format_size(requested_size) if requested_size else str(size or ""),
            "provider_size": provider_size,
            "final_size": _format_size(final_size) if final_size else "",
        }

    def _generation_payloads(self, *, prompt: str, size: str) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for model in self._model_candidates():
            base = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "n": 1,
            }
            payloads.append({**base, "response_format": "b64_json"})
            payloads.append(dict(base))
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            result.append(payload)
        return result

    def _model_candidates(self) -> list[str]:
        primary = self._model()
        override = dict(runtime_config.load().get("soul_image_assets") or {})
        configured = override.get("fallback_models") or override.get("model_fallbacks") or []
        env_fallbacks = [
            item.strip()
            for item in str(os.getenv("SOUL_IMAGE_FALLBACK_MODELS") or "").split(",")
            if item.strip()
        ]
        values = [primary, *env_fallbacks]
        if isinstance(configured, list):
            values.extend(str(item).strip() for item in configured if str(item).strip())
        elif isinstance(configured, str):
            values.extend(item.strip() for item in configured.split(",") if item.strip())
        return _dedupe_strings(values)

    async def _post_generation_payload_concurrently(self, *, endpoint: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        concurrency = self._request_concurrency()
        tasks = [
            asyncio.create_task(self._post_generation_payload(endpoint=endpoint, headers=headers, payload=payload, attempt_index=index + 1))
            for index in range(concurrency)
        ]
        attempts: list[dict[str, Any]] = []
        last_api_error: dict[str, Any] = {}
        try:
            for task in asyncio.as_completed(tasks):
                result = await task
                attempts.extend(list(result.get("attempts") or []))
                if result.get("data") is not None:
                    for pending in tasks:
                        if not pending.done():
                            pending.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    return {"data": result.get("data"), "attempts": attempts}
                api_error = dict(result.get("api_error") or {})
                if api_error:
                    last_api_error = api_error
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return {"data": None, "attempts": attempts, "api_error": last_api_error}

    async def _post_generation_payload(self, *, endpoint: str, headers: dict[str, str], payload: dict[str, Any], attempt_index: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._request_timeout_seconds(), connect=20.0)) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
        except httpx.TimeoutException:
            attempt = _attempt_error(payload=payload, code="timeout", message="Image API request timed out", retryable=True, attempt_index=attempt_index)
            return {"data": None, "attempts": [attempt], "api_error": {"code": "timeout", "retryable": True}}
        except httpx.HTTPError as exc:
            attempt = _attempt_error(payload=payload, code="network_error", message=f"Image API request failed: {exc}", retryable=True, attempt_index=attempt_index)
            return {"data": None, "attempts": [attempt], "api_error": {"code": "network_error", "retryable": True}}
        if response.status_code >= 400:
            api_error = _api_error_from_response(response)
            attempt = _attempt_error(payload=payload, attempt_index=attempt_index, **api_error)
            return {"data": None, "attempts": [attempt], "api_error": api_error}
        try:
            return {"data": response.json(), "attempts": [_attempt_success(payload=payload, attempt_index=attempt_index)]}
        except json.JSONDecodeError as exc:
            content_type = str(response.headers.get("content-type") or "").strip()
            body_preview = response.text[:300].strip()
            detail = "Image API returned non-JSON response"
            if content_type:
                detail += f" ({content_type})"
            if body_preview:
                detail += f": {body_preview}"
            attempt = _attempt_error(payload=payload, code="non_json_response", message=detail, retryable=False, attempt_index=attempt_index)
            return {"data": None, "attempts": [attempt], "api_error": {"code": "non_json_response", "retryable": False, "message": detail}}

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

    @staticmethod
    def _request_timeout_seconds() -> float:
        override = dict(runtime_config.load().get("soul_image_assets") or {})
        raw = os.getenv("SOUL_IMAGE_REQUEST_TIMEOUT_SECONDS") or override.get("request_timeout_seconds") or 600
        try:
            return max(30.0, float(raw))
        except (TypeError, ValueError):
            return 600.0

    @staticmethod
    def _request_concurrency() -> int:
        override = dict(runtime_config.load().get("soul_image_assets") or {})
        raw = os.getenv("SOUL_IMAGE_CONCURRENCY") or override.get("concurrency") or 1
        try:
            return min(8, max(1, int(raw)))
        except (TypeError, ValueError):
            return 1


def _api_error_from_response(response: httpx.Response) -> dict[str, Any]:
    status = int(response.status_code)
    message = response.text[:500]
    provider_code = ""
    provider_type = ""
    try:
        payload = response.json()
        error = dict(payload.get("error") or {}) if isinstance(payload, dict) else {}
        message = str(error.get("message") or message)
        provider_code = str(error.get("code") or "")
        provider_type = str(error.get("type") or "")
    except Exception:
        pass
    lowered = message.lower()
    if "tool choice" in lowered and "image_generation" in lowered:
        code = "model_endpoint_incompatible"
        retryable = True
    elif status in {408, 409, 425, 429, 500, 502, 503, 504}:
        code = "image_provider_transient_error"
        retryable = True
    elif status in {401, 403}:
        code = "image_provider_auth_error"
        retryable = False
    elif status == 404:
        code = "image_endpoint_not_found"
        retryable = False
    else:
        code = provider_code or "image_provider_request_error"
        retryable = status >= 500
    return {
        "code": code,
        "message": f"Image API failed with status {status}: {message}",
        "retryable": retryable,
        "http_status": status,
        "provider_code": provider_code,
        "provider_type": provider_type,
    }


def _attempt_error(*, payload: dict[str, Any], code: str, message: str, retryable: bool, **extra: Any) -> dict[str, Any]:
    return {
        "model": str(payload.get("model") or ""),
        "payload_shape": sorted(str(key) for key in payload.keys()),
        "code": code,
        "message": message,
        "retryable": bool(retryable),
        **{key: value for key, value in dict(extra).items() if key not in {"payload"}},
    }


def _attempt_success(*, payload: dict[str, Any], attempt_index: int) -> dict[str, Any]:
    return {
        "model": str(payload.get("model") or ""),
        "payload_shape": sorted(str(key) for key in payload.keys()),
        "code": "ok",
        "message": "Image API request succeeded",
        "retryable": False,
        "attempt_index": attempt_index,
    }


def _should_try_next_payload(api_error: dict[str, Any]) -> bool:
    return str(api_error.get("code") or "") in {"model_endpoint_incompatible", "image_provider_transient_error"} and bool(api_error.get("retryable", True))


def _format_generation_failure(attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return "Image generation failed before reaching provider"
    compact = []
    for attempt in attempts[-6:]:
        compact.append(f"{attempt.get('model') or 'unknown'}:{attempt.get('code') or 'error'}:{attempt.get('message') or ''}")
    return "Image generation failed after compatible attempts: " + " | ".join(compact)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _parse_image_size(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d{2,5})\s*x\s*(\d{2,5})\s*", str(value or ""), flags=re.IGNORECASE)
    if not match:
        return None
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return None
    return width, height


def _format_size(size: tuple[int, int] | None) -> str:
    return f"{size[0]}x{size[1]}" if size else ""


def _provider_generation_size(requested: str) -> str:
    requested_size = _parse_image_size(requested)
    if requested_size in {(1024, 1024), (1024, 1536), (1536, 1024)}:
        return _format_size(requested_size)
    return "1024x1024"


def _resolve_generation_and_output_sizes(*, size: str, output_size: str) -> tuple[str, tuple[int, int] | None]:
    explicit_output_size = _parse_image_size(output_size)
    requested_generation_size = _parse_image_size(size)
    provider_size = _provider_generation_size(size)
    if explicit_output_size:
        return provider_size, explicit_output_size
    if requested_generation_size and _format_size(requested_generation_size) != provider_size:
        return provider_size, requested_generation_size
    return provider_size, None


def _png_size(image_bytes: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            return int(image.width), int(image.height)
    except Exception as exc:
        raise SoulImageAssetError("Generated PNG could not be inspected", code="generated_asset_invalid_png", retryable=True) from exc


def _resize_png(image_bytes: bytes, target_size: tuple[int, int]) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            converted = image.convert("RGBA")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            resized = converted.resize(target_size, resampling)
            output = io.BytesIO()
            resized.save(output, format="PNG")
            return output.getvalue()
    except Exception as exc:
        raise SoulImageAssetError("Generated PNG could not be resized", code="generated_asset_resize_failed", retryable=True) from exc


