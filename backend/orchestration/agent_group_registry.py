from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .agent_group_models import AgentGroup


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).orchestration_dir


def _groups_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "agent_groups.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_agent_groups() -> tuple[AgentGroup, ...]:
    return ()


def _merge_items_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in default_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    for item in stored_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    return list(merged.values())


def _group_from_dict(payload: dict[str, Any]) -> AgentGroup:
    return AgentGroup(
        group_id=str(payload.get("group_id") or ""),
        title=str(payload.get("title") or ""),
        group_kind=str(payload.get("group_kind") or "coordination_team"),
        coordinator_agent_id=str(payload.get("coordinator_agent_id") or ""),
        member_agent_ids=tuple(str(item).strip() for item in list(payload.get("member_agent_ids") or []) if str(item).strip()),
        description=str(payload.get("description") or ""),
        default_topology_template_ids=tuple(
            str(item).strip() for item in list(payload.get("default_topology_template_ids") or []) if str(item).strip()
        ),
        default_communication_protocol_ids=tuple(
            str(item).strip() for item in list(payload.get("default_communication_protocol_ids") or []) if str(item).strip()
        ),
        allowed_coordination_task_ids=tuple(
            str(item).strip() for item in list(payload.get("allowed_coordination_task_ids") or []) if str(item).strip()
        ),
        lifecycle_state=str(payload.get("lifecycle_state") or "enabled"),
        metadata=dict(payload.get("metadata") or {}),
    )


class AgentGroupRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.path = _groups_path(self.base_dir)

    def list_groups(self) -> list[AgentGroup]:
        default_payload = [item.to_dict() for item in default_agent_groups()]
        path_missing = not self.path.exists()
        payload = _read_json(self.path, {"groups": default_payload})
        merged_payload = _merge_items_by_key(
            default_payload,
            [item for item in list(payload.get("groups") or []) if isinstance(item, dict)],
            key="group_id",
        )
        groups = [_group_from_dict(item) for item in merged_payload]
        normalized = [item.to_dict() for item in groups]
        if path_missing or payload.get("groups") != normalized:
            _write_json(self.path, {"groups": normalized})
        return groups

    def get_group(self, group_id: str) -> AgentGroup | None:
        target = str(group_id or "").strip()
        return next((item for item in self.list_groups() if item.group_id == target), None)

    def upsert_group(
        self,
        *,
        group_id: str,
        title: str,
        group_kind: str,
        coordinator_agent_id: str,
        member_agent_ids: tuple[str, ...] = (),
        description: str = "",
        default_topology_template_ids: tuple[str, ...] = (),
        default_communication_protocol_ids: tuple[str, ...] = (),
        allowed_coordination_task_ids: tuple[str, ...] = (),
        lifecycle_state: str = "enabled",
        metadata: dict[str, Any] | None = None,
    ) -> AgentGroup:
        target = str(group_id or "").strip()
        if not target.startswith("group."):
            raise ValueError("group_id must start with group.")
        group = AgentGroup(
            group_id=target,
            title=str(title or target).strip(),
            group_kind=str(group_kind or "coordination_team").strip(),
            coordinator_agent_id=str(coordinator_agent_id or "").strip(),
            member_agent_ids=tuple(str(item).strip() for item in member_agent_ids if str(item).strip()),
            description=str(description or "").strip(),
            default_topology_template_ids=tuple(str(item).strip() for item in default_topology_template_ids if str(item).strip()),
            default_communication_protocol_ids=tuple(
                str(item).strip() for item in default_communication_protocol_ids if str(item).strip()
            ),
            allowed_coordination_task_ids=tuple(str(item).strip() for item in allowed_coordination_task_ids if str(item).strip()),
            lifecycle_state=str(lifecycle_state or "enabled").strip() or "enabled",
            metadata=dict(metadata or {}),
        )
        groups = [item for item in self.list_groups() if item.group_id != target]
        groups.append(group)
        _write_json(self.path, {"groups": [item.to_dict() for item in groups]})
        return group

    def delete_group(self, group_id: str) -> None:
        target = str(group_id or "").strip()
        groups = self.list_groups()
        if not any(item.group_id == target for item in groups):
            raise KeyError(target)
        remaining = [item for item in groups if item.group_id != target]
        _write_json(self.path, {"groups": [item.to_dict() for item in remaining]})
