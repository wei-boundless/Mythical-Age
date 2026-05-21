from __future__ import annotations

from pathlib import Path

from orchestration.resource_inventory import build_runtime_resource_inventory


def test_runtime_resource_inventory_marks_only_current_turn_and_obligation_as_side_effect_authorities(tmp_path: Path) -> None:
    inventory = build_runtime_resource_inventory(tmp_path)
    items = {item.resource_id: item for item in inventory.items}

    authoritative = {
        item.resource_id
        for item in inventory.items
        if item.can_authorize_side_effects
    }

    assert authoritative == {
        "resource.user_current_turn",
        "resource.execution_obligation",
    }
    assert items["resource.task_domains"].authority_layer == "L4_directory_resource"
    assert items["resource.task_domains"].runtime_consumer == "admin_and_resource_filtering"
    assert items["resource.soul_projection"].authority_layer == "L6_projection_style"
    assert "cannot override obligations" in items["resource.soul_projection"].notes
    assert items["resource.runtime_checkpoint"].authority_layer == "L7_persistent_state"
    assert "current turn is re-evaluated" in items["resource.runtime_checkpoint"].notes


def test_runtime_resource_inventory_paths_are_resolved_from_backend_layout(tmp_path: Path) -> None:
    inventory = build_runtime_resource_inventory(tmp_path)
    items = {item.resource_id: item for item in inventory.items}

    assert str(items["resource.task_domains"].path).startswith(str(tmp_path))
    assert str(items["resource.task_graphs"].path).startswith(str(tmp_path))
    assert str(items["resource.orchestration_agents"].path).startswith(str(tmp_path))
    assert str(items["resource.runtime_checkpoint"].path).startswith(str(tmp_path))
