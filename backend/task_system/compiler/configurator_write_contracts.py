from __future__ import annotations

from typing import Any


def build_configurator_write_contract(*, graph_id: str) -> dict[str, Any]:
    return {
        "contract_id": f"configurator-write:{graph_id}",
        "system_node_id": "__configurator__",
        "can_write": [
            "authoring_spec_draft",
            "node_seed_drafts",
            "resource_binding_drafts",
            "edge_prototype_selections",
            "node_contract_drafts",
            "resource_contract_drafts",
            "edge_contract_drafts",
            "graph_draft_patch",
        ],
        "can_apply_to": ["draft_graph_store"],
        "must_validate_with": ["graph_compiler"],
        "cannot_write": [
            "published_graph_contract",
            "runtime_graph_state",
            "credential_secret_value",
            "permission_grant",
        ],
        "patch_contract": {
            "authority": "task_system.graph_draft_patch_contract",
            "required_fields": ["graph_id", "patch_id", "operations"],
            "operation_kinds": [
                "upsert_node",
                "upsert_resource",
                "upsert_edge",
                "upsert_node_contract_draft",
                "upsert_resource_contract_draft",
                "upsert_edge_contract_draft",
            ],
        },
        "authority": "task_system.configurator_write_contract",
    }


def graph_draft_patch(
    *,
    graph_id: str,
    operations: list[dict[str, Any]],
    patch_id: str = "",
) -> dict[str, Any]:
    return {
        "patch_id": patch_id or f"gpatch:{graph_id}",
        "graph_id": graph_id,
        "operations": [dict(item) for item in operations],
        "status": "draft",
        "requires_compiler_validation": True,
        "authority": "task_system.graph_draft_patch",
    }
