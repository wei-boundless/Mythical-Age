from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import PromptCompositionGraph, PromptCompositionPlan


def build_prompt_composition_graph(plan: PromptCompositionPlan) -> PromptCompositionGraph:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    previous_slot_id = ""
    for slot in plan.slots:
        nodes.append(
            {
                "node_id": slot.slot_id,
                "node_type": "slot",
                "layer": slot.layer,
                "slot_kind": slot.slot_kind,
                "prompt_ref": slot.prompt_ref,
                "source_ref": slot.source_ref,
                "source_kind": slot.source_kind,
                "target_role": slot.target_role,
                "lifecycle": slot.lifecycle,
                "cache_role": slot.cache_role,
                "prefix_tier": slot.prefix_tier,
                "order": slot.order,
            }
        )
        if previous_slot_id:
            edges.append(
                {
                    "from": previous_slot_id,
                    "to": slot.slot_id,
                    "edge_type": "composition_order",
                }
            )
        previous_slot_id = slot.slot_id
    seed = {
        "plan_id": plan.plan_id,
        "nodes": [node["node_id"] for node in nodes],
        "edges": edges,
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return PromptCompositionGraph(
        graph_id=f"pcgraph:{digest}",
        plan_id=plan.plan_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        diagnostics={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "authority": "prompt_composition.graph_builder",
        },
    )
