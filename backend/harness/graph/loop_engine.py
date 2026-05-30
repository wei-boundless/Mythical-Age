from __future__ import annotations

from typing import Any

from .models import GraphLoopState


class LoopEngine:
    """Resolves dynamic loop variables for one node execution."""

    authority = "harness.graph.loop_engine"

    def context_for_node(self, *, state: GraphLoopState, node: dict[str, Any]) -> dict[str, Any]:
        node_loop = dict(node.get("loop") or {})
        scope_id = str(node_loop.get("scope_id") or "").strip()
        frames = dict(dict(state.loop_state or {}).get("frames") or {})
        active_frame = dict(frames.get(scope_id) or {}) if scope_id else {}
        history = [
            dict(item)
            for item in list(dict(state.loop_state or {}).get("route_history") or [])
            if isinstance(item, dict) and (not scope_id or str(item.get("scope_id") or "") == scope_id)
        ]
        return {
            "authority": self.authority,
            "scope_id": scope_id,
            "node_loop": node_loop,
            "active_frame": active_frame,
            "route_history": history,
            "result_history_counts": {
                key: len(list(value or []))
                for key, value in dict(state.result_history or {}).items()
            },
            "contract_inputs": dict(state.initial_inputs or {}),
        }
