from __future__ import annotations

import hashlib
import json
from typing import Any

from .work_product_models import GraphBuildWorkProductEnvelope


def extract_graph_build_work_products(
    node_result: dict[str, Any],
    *,
    default_build_id: str = "",
    default_graph_run_id: str = "",
    default_node_id: str = "",
    default_shard_id: str = "",
    default_layer_id: str = "",
) -> tuple[GraphBuildWorkProductEnvelope, ...]:
    outputs = dict(node_result.get("outputs") or node_result.get("output") or {})
    raw_products = _raw_work_products(outputs)
    products: list[GraphBuildWorkProductEnvelope] = []
    for item in list(raw_products or []):
        if not isinstance(item, dict):
            continue
        defaults = {
            "build_id": default_build_id,
            "graph_run_id": default_graph_run_id,
            "node_id": default_node_id,
            "shard_id": default_shard_id,
            "layer_id": default_layer_id,
        }
        payload = {
            **{key: value for key, value in defaults.items() if value},
            **item,
        }
        if not payload.get("work_product_id"):
            payload["work_product_id"] = _stable_work_product_id(payload)
        try:
            products.append(GraphBuildWorkProductEnvelope.from_dict(payload))
        except ValueError:
            continue
    return tuple(products)


def _raw_work_products(outputs: dict[str, Any]) -> list[Any]:
    candidates: list[Any] = [
        outputs.get("graph_build_work_products"),
        outputs.get("work_products"),
    ]
    if _looks_like_work_product(outputs):
        candidates.append(outputs)
    for key in ("structured_output", "node_output", "project_network", "graph_build"):
        nested = outputs.get(key)
        if isinstance(nested, dict):
            candidates.append(nested.get("graph_build_work_products"))
            candidates.append(nested.get("work_products"))
            if _looks_like_work_product(nested):
                candidates.append(nested)
    products: list[Any] = []
    for value in candidates:
        if isinstance(value, list):
            products.extend(value)
        if isinstance(value, tuple):
            products.extend(list(value))
        if isinstance(value, dict) and _looks_like_work_product(value):
            products.append(value)
    return products


def _looks_like_work_product(value: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    if str(value.get("product_kind") or "").strip() and isinstance(value.get("payload"), dict):
        return True
    if str(value.get("work_product_id") or value.get("id") or "").strip() and isinstance(value.get("payload"), dict):
        return True
    return False


def _stable_work_product_id(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    prefix = _safe_id(
        ":".join(
            str(payload.get(key) or "")
            for key in ("build_id", "product_kind", "stable_ref", "node_id")
            if str(payload.get(key) or "").strip()
        )
    )
    return f"pnwp:{prefix or 'work_product'}:{digest}"


def _safe_id(value: str, *, limit: int = 96) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "")).strip("_")
    return safe[:limit]

