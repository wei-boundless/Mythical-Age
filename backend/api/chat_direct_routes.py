from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from harness.entrypoint.models import HarnessRuntimeRequest


AssistantCommitter = Callable[[dict[str, Any]], Awaitable[Any]]


def is_direct_image_generation_request(image_generation: dict[str, Any] | None) -> bool:
    payload = dict(image_generation or {})
    model = str(payload.get("model") or "").strip().lower()
    mode = str(payload.get("mode") or "").strip().lower()
    return model in {"gpt-image-1", "gpt-image-2", "image-2"} or mode == "generate"


async def run_direct_system_route(
    *,
    base_dir: Path,
    request: HarnessRuntimeRequest,
    turn_id: str,
    assistant_message_committer: AssistantCommitter,
) -> dict[str, Any] | None:
    image_generation = dict(request.image_generation or {})
    if not is_direct_image_generation_request(image_generation):
        return None

    from capability_system.capabilities.image_generation.image_asset_service import ImageAssetError, ImageAssetService

    asset_kind = str(image_generation.get("asset_kind") or "chat").strip() or "chat"
    model = str(image_generation.get("model") or "").strip()
    size = str(image_generation.get("size") or "1024x1024").strip() or "1024x1024"
    quality = str(image_generation.get("quality") or "").strip()
    request_timeout_seconds = image_generation.get("request_timeout_seconds")
    target_id = str(image_generation.get("target_id") or turn_id).strip() or turn_id
    try:
        generated = await ImageAssetService(base_dir).generate(
            prompt=request.message,
            target_id=target_id,
            asset_kind=asset_kind,
            size=size,
            quality=quality,
            model=model,
            request_timeout_seconds=float(request_timeout_seconds) if request_timeout_seconds is not None else None,
            overwrite=bool(image_generation.get("overwrite") or False),
        )
    except ImageAssetError as exc:
        return {
            "type": "error",
            "error": "运行中断",
            "content": "运行中断",
            "code": "provider_unavailable",
            "reason": str(exc),
        }

    asset_path = str(generated.get("asset_path") or "").strip()
    revised_prompt = str(generated.get("revised_prompt") or "").strip()
    image = (
        {
            "src": asset_path,
            "alt": request.message,
            "caption": revised_prompt or "",
        }
        if asset_path
        else None
    )
    await assistant_message_committer(
        {
            "role": "assistant",
            "content": "",
            "image": image,
            "turn_id": turn_id,
            "answer_channel": "image",
            "answer_source": "image_asset_service",
            "answer_canonical_state": "stable_answer",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "final",
        }
    )
    return {
        "type": "done",
        "content": "",
        "image": image,
        "answer_channel": "image",
        "answer_source": "image_asset_service",
        "answer_canonical_state": "stable_answer",
        "answer_persist_policy": "persist_canonical",
        "answer_finalization_policy": "final",
    }



