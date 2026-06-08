from __future__ import annotations

from typing import Any


def build_resource_contract_index(
    *,
    resource_nodes: list[dict[str, Any]],
    graph_environment: dict[str, Any],
    graph_binding_contract: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        _resource_id(resource): build_resource_contract(
            resource=resource,
            graph_environment=graph_environment,
            graph_binding_contract=graph_binding_contract,
        )
        for resource in resource_nodes
        if _resource_id(resource)
    }


def build_resource_contract(
    *,
    resource: dict[str, Any],
    graph_environment: dict[str, Any],
    graph_binding_contract: dict[str, Any],
) -> dict[str, Any]:
    resource_id = _resource_id(resource)
    resource_kind = str(resource.get("resource_kind") or resource.get("resource_type") or resource.get("node_type") or "").strip()
    return _drop_empty(
        {
            "contract_id": f"resource-contract:{resource_id}",
            "resource_id": resource_id,
            "resource_kind": resource_kind,
            "resource_node_id": str(resource.get("node_id") or ""),
            "environment_binding": _drop_empty(
                {
                    "task_environment_id": str(resource.get("task_environment_id") or graph_environment.get("task_environment_id") or ""),
                    "environment_id": str(resource.get("environment_id") or graph_environment.get("environment_id") or ""),
                }
            ),
            "project_binding": _drop_empty(
                {
                    "binding_mode": str(graph_binding_contract.get("binding_mode") or "project_scoped"),
                    "project_id": str(resource.get("project_id") or graph_binding_contract.get("project_id") or ""),
                }
            ),
            "read_policy": _drop_empty(
                {
                    "readable_by": list(resource.get("readable_by") or []),
                    "visibility": str(resource.get("visibility") or "contract_bound"),
                }
            ),
            "write_candidate_policy": _drop_empty(
                {
                    "write_owner_node_ids": list(resource.get("write_owner_node_ids") or []),
                    "candidate_visibility": "candidate_not_committed",
                }
            ),
            "commit_policy": dict(resource.get("commit_policy") or {}),
            "audit_policy": {"receipt_required": True},
            "authority": "task_system.compiled_resource_contract",
        }
    )


def _resource_id(resource: dict[str, Any]) -> str:
    return str(resource.get("resource_id") or resource.get("node_id") or resource.get("repository_id") or "").strip()


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
