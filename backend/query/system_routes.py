from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from query.models import QueryRequest


AssistantCommitter = Callable[[dict[str, Any]], Awaitable[Any]]


def is_direct_image_generation_request(image_generation: dict[str, Any] | None) -> bool:
    payload = dict(image_generation or {})
    model = str(payload.get("model") or "").strip().lower()
    mode = str(payload.get("mode") or "").strip().lower()
    return model in {"gpt-image-2", "image-2"} or mode == "generate"


async def run_direct_system_route(
    *,
    base_dir: Path,
    request: QueryRequest,
    turn_id: str,
    assistant_message_committer: AssistantCommitter,
) -> dict[str, Any] | None:
    image_generation = dict(request.image_generation or {})
    if not is_direct_image_generation_request(image_generation):
        return None

    from soul.image_asset_service import SoulImageAssetError, SoulImageAssetService

    asset_kind = str(image_generation.get("asset_kind") or "chat").strip() or "chat"
    size = str(image_generation.get("size") or "1024x1024").strip() or "1024x1024"
    target_id = str(image_generation.get("target_id") or turn_id).strip() or turn_id
    try:
        generated = await SoulImageAssetService(base_dir).generate(
            prompt=request.message,
            target_id=target_id,
            asset_kind=asset_kind,
            size=size,
            overwrite=bool(image_generation.get("overwrite") or False),
        )
    except SoulImageAssetError as exc:
        return {"type": "error", "error": str(exc), "code": "provider_unavailable"}

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
    content = "已生成图像。"
    await assistant_message_committer(
        {
            "role": "assistant",
            "content": content,
            "image": image,
            "turn_id": turn_id,
            "answer_channel": "image",
            "answer_source": "soul_image_asset_service",
            "answer_canonical_state": "complete",
            "answer_persist_policy": "store",
            "answer_finalization_policy": "final",
        }
    )
    return {
        "type": "done",
        "content": content,
        "image": image,
    }


