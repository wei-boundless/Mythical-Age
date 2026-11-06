from __future__ import annotations

from typing import Any

from .models import GraphLoopState


class LoopEngine:
    """Resolves dynamic loop variables for one node execution."""

    authority = "graph_system.loop_engine"

    def context_for_node(self, *, state: GraphLoopState, node: dict[str, Any]) -> dict[str, Any]:
        node_loop = dict(node.get("loop") or {})
        scope_id = str(node_loop.get("scope_id") or "").strip()
        frames = dict(dict(state.loop_state or {}).get("frames") or {})
        active_frame = dict(frames.get(scope_id) or {}) if scope_id else {}
        if not active_frame:
            active_frame = _active_frame_for_node(frames=frames, node_id=str(node.get("node_id") or ""))
        history = [
            dict(item)
            for item in list(dict(state.loop_state or {}).get("route_history") or [])
            if isinstance(item, dict) and (not scope_id or str(item.get("scope_id") or "") == scope_id)
        ]
        active_frames = [
            _frame_projection(dict(frame))
            for frame in frames.values()
            if isinstance(frame, dict) and str(dict(frame).get("status") or "active") == "active"
        ]
        current_frame = _frame_projection(active_frame)
        iteration_results = dict(dict(state.loop_state or {}).get("iteration_results") or {})
        return {
            "authority": self.authority,
            "scope_id": str(active_frame.get("scope_id") or scope_id),
            "current_scope_id": str(active_frame.get("scope_id") or scope_id),
            "current_frame_id": str(active_frame.get("frame_id") or ""),
            "iteration_index": active_frame.get("iteration_index"),
            "iteration_id": str(active_frame.get("active_iteration_id") or ""),
            "cursor_key": str(active_frame.get("cursor_key") or ""),
            "cursor_value": active_frame.get("cursor"),
            "node_loop": node_loop,
            "active_frame": active_frame,
            "current_frame": current_frame,
            "active_frames": active_frames,
            "iteration_results": iteration_results,
            "route_history": history,
            "result_history_counts": {
                key: len(list(value or []))
                for key, value in dict(state.result_history or {}).items()
            },
            "contract_inputs": dict(state.initial_inputs or {}),
        }


def _active_frame_for_node(*, frames: dict[str, Any], node_id: str) -> dict[str, Any]:
    for raw in frames.values():
        frame = dict(raw or {}) if isinstance(raw, dict) else {}
        if str(frame.get("status") or "active") != "active":
            continue
        scope_node_ids = [str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)]
        if node_id in scope_node_ids:
            return frame
    return {}


def _frame_projection(frame: dict[str, Any]) -> dict[str, Any]:
    if not frame:
        return {}
    return {
        "frame_id": str(frame.get("frame_id") or ""),
        "scope_id": str(frame.get("scope_id") or ""),
        "parent_scope_id": str(frame.get("parent_scope_id") or ""),
        "status": str(frame.get("status") or ""),
        "kind": str(frame.get("kind") or ""),
        "algorithm_kind": str(frame.get("algorithm_kind") or frame.get("kind") or ""),
        "unit_kind": str(frame.get("unit_kind") or ""),
        "iteration_index": frame.get("iteration_index"),
        "iteration_id": str(frame.get("active_iteration_id") or ""),
        "cursor_key": str(frame.get("cursor_key") or ""),
        "cursor_value": frame.get("cursor"),
        "start": frame.get("start"),
        "end": frame.get("end"),
        "step": frame.get("step"),
        "tree_reduce": _tree_reduce_projection(frame.get("tree_reduce")),
        "aggregate_policy": dict(frame.get("aggregate_policy") or {}),
    }


def _tree_reduce_projection(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    if not payload:
        return {}
    return {
        "physical_authority": str(payload.get("physical_authority") or ""),
        "semantic_authority": str(payload.get("semantic_authority") or ""),
        "frame_status": str(payload.get("frame_status") or ""),
        "depth": payload.get("depth"),
        "folder_node_id": str(payload.get("folder_node_id") or ""),
        "folder_stable_ref": str(payload.get("folder_stable_ref") or ""),
        "manifest_ref": str(payload.get("manifest_ref") or ""),
        "direct_file_count": payload.get("direct_file_count"),
        "child_folder_count": payload.get("child_folder_count"),
        "child_return_count": payload.get("child_return_count"),
        "aggregate_policy": str(payload.get("aggregate_policy") or ""),
        "authority": "graph_system.loop_engine.tree_reduce_projection",
    }
