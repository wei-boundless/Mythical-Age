from __future__ import annotations

from pathlib import Path
from typing import Any

from graph_system.runtime_effect_registry import RuntimeAlgorithmEffectHandler

from .directory_runtime_service import DirectoryRuntimeService
from .repair_runtime_service import ProjectNetworkRepairRuntimeService


def register_runtime_algorithm_effect_handlers(register) -> None:
    register(
        RuntimeAlgorithmEffectHandler(
            effect_kind="project_network_work_product_ingest",
            handle=handle_project_network_work_product_ingest,
            priority=100,
        )
    )


def handle_project_network_work_product_ingest(
    *,
    request: dict[str, Any],
    graph_config: Any,
    graph_state: Any,
    node_result: Any,
    backend_dir: Path,
) -> dict[str, Any]:
    del graph_config, graph_state
    context = dict(request.get("context") or {})
    target_base_dir = _project_network_target_base_dir(context, default_base_dir=backend_dir)
    repair_item_ids = [
        str(item).strip()
        for item in list(context.get("repair_item_ids") or ())
        if str(item).strip()
    ]
    if repair_item_ids:
        ingest = ProjectNetworkRepairRuntimeService.from_backend_dir(
            target_base_dir,
            flow_registry_base_dir=backend_dir,
        ).accept_repair_node_result(
            node_result,
            repair_item_ids=tuple(repair_item_ids),
            repair_batch_id=str(context.get("repair_batch_id") or ""),
            frame_id=str(context.get("directory_frame_id") or ""),
            build_id=str(context.get("build_id") or ""),
            default_shard_id=str(context.get("default_shard_id") or ""),
            default_layer_id=str(context.get("default_layer_id") or ""),
        )
    else:
        ingest = DirectoryRuntimeService.from_backend_dir(
            target_base_dir,
            flow_registry_base_dir=backend_dir,
        ).accept_directory_node_result(
            node_result,
            frame_id=str(context.get("directory_frame_id") or ""),
            build_id=str(context.get("build_id") or ""),
            default_shard_id=str(context.get("default_shard_id") or ""),
            default_layer_id=str(context.get("default_layer_id") or ""),
        )
    work_products = tuple(getattr(ingest, "work_products", ()) or ())
    metadata = dict(getattr(ingest, "metadata", {}) or {})
    maintenance_signals = tuple(getattr(ingest, "maintenance_signals", ()) or ())
    return {
        "effect_kind": "project_network_work_product_ingest",
        "status": "completed" if work_products else "failed",
        "reason": "" if work_products else "no_project_network_work_products_ingested",
        "required": bool(request.get("required", False)),
        "build_id": str(getattr(ingest, "build_id", "") or ""),
        "graph_run_id": str(getattr(ingest, "graph_run_id", "") or ""),
        "node_id": str(getattr(ingest, "node_id", "") or ""),
        "work_product_count": len(work_products),
        "work_product_ids": [str(getattr(item, "work_product_id", "") or "") for item in work_products],
        "channel_count": len(tuple(getattr(ingest, "channel_states", ()) or ())),
        "directory_child_return_count": int(metadata.get("directory_child_return_count") or 0),
        "repair_batch_id": str(metadata.get("repair_batch_id") or context.get("repair_batch_id") or ""),
        "repair_item_count": int(metadata.get("repair_item_count") or len(repair_item_ids)),
        "materialization_lifecycle": str(metadata.get("materialization_lifecycle") or ""),
        "maintenance_signal_ids": [str(getattr(item, "signal_id", "") or "") for item in maintenance_signals],
        "dirty_signal_codes": [str(getattr(item, "signal_code", "") or "") for item in maintenance_signals],
        "authority": "project_network_tasks.runtime_effect.project_network_work_product_ingest",
    }


def _project_network_target_base_dir(context: dict[str, Any], *, default_base_dir: Path) -> Path:
    for key in ("project_network_target_backend_dir", "project_network_target_project_root"):
        raw = str(dict(context or {}).get(key) or "").strip()
        if not raw:
            continue
        try:
            return Path(raw).expanduser().resolve()
        except OSError:
            continue
    return Path(default_base_dir).resolve()
