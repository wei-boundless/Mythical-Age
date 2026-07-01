from __future__ import annotations

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
            continue
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
    for key in ("structured_output", "node_output", "project_network", "graph_build"):
        nested = outputs.get(key)
        if isinstance(nested, dict):
            candidates.append(nested.get("graph_build_work_products"))
            candidates.append(nested.get("work_products"))
    for value in candidates:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
    return []
