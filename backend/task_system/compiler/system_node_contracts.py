from __future__ import annotations

from typing import Any


def build_system_node_contract_index(*, graph_id: str) -> dict[str, dict[str, Any]]:
    return {
        "__configurator__": {
            "node_id": "__configurator__",
            "role": "authoring_assistant",
            "lifecycle": "draft_compile",
            "visible_lane": "system_control",
            "can_apply_draft_patch": True,
            "can_publish": False,
            "authority": "task_system.system_node_contract",
        },
        "__supervisor__": {
            "node_id": "__supervisor__",
            "role": "runtime_supervisor",
            "lifecycle": "graph_run",
            "visible_lane": "system_control",
            "can_mutate_contract": False,
            "can_override_result": False,
            "authority": "task_system.system_node_contract",
        },
    }


def build_maintenance_contract(*, graph_id: str) -> dict[str, Any]:
    return {
        "contract_id": f"maintenance:{graph_id}",
        "system_node_id": "__supervisor__",
        "auto_actions": [
            "emit_health_alert",
            "emit_missing_receipt_diagnostic",
            "mark_recoverable_blocked_node",
        ],
        "require_human_approval": [
            "requeue_failed_node",
            "skip_node",
            "override_result",
            "force_commit_resource",
            "mutate_contract",
        ],
        "max_auto_recovery_attempts": 2,
        "audit_required": True,
        "receipt_required": True,
        "authority": "task_system.maintenance_contract",
    }
