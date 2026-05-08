from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from .agent_models import AgentDescriptor
from soul import SoulFacade


AGENT_CATEGORIES = {"main_agent", "system_management_agent", "worker_sub_agent"}


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).orchestration_dir


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_agent_descriptors(now: float | None = None) -> tuple[AgentDescriptor, ...]:
    timestamp = time.time() if now is None else now
    return (
        AgentDescriptor(
            agent_id="agent:0",
            agent_name="主 Agent",
            agent_category="main_agent",
            interface_target="main_conversation",
            description="系统主会话入口，承接通用任务并负责最终整合输出。",
            enabled=True,
            builtin=True,
            editable=False,
            default_soul_id="",
            default_projection_id="",
            task_scope=("general_task", "final_integration"),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "main_conversation_entry", "system_key": "task_system", "slot_index": 0},
        ),
        AgentDescriptor(
            agent_id="agent:1",
            agent_name="1号权限管理Agent",
            agent_category="system_management_agent",
            interface_target="permission_system_window",
            description="对接权限系统会话窗口，负责权限系统相关管理任务。",
            enabled=True,
            builtin=True,
            editable=False,
            default_soul_id="siyue",
            default_projection_id="siyue__primary",
            task_scope=("permission_management",),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "permission_system", "slot_index": 1},
        ),
        AgentDescriptor(
            agent_id="agent:2",
            agent_name="2号记忆管理Agent",
            agent_category="system_management_agent",
            interface_target="memory_system_window",
            description="对接记忆系统会话窗口，负责记忆系统相关管理任务。",
            enabled=True,
            builtin=True,
            editable=False,
            default_soul_id="hebo",
            default_projection_id="hebo__primary",
            task_scope=("memory_management",),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "memory_system", "slot_index": 2},
        ),
        AgentDescriptor(
            agent_id="agent:3",
            agent_name="3号健康管理Agent",
            agent_category="system_management_agent",
            interface_target="health_system_window",
            description="对接健康系统会话窗口，负责健康维护和健康分析类任务。",
            enabled=True,
            builtin=True,
            editable=False,
            default_soul_id="xuannv",
            default_projection_id="xuannv__primary",
            task_scope=("health_management", "health_issue_triage"),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "health_system", "slot_index": 3},
        ),
        AgentDescriptor(
            agent_id="agent:4",
            agent_name="4号能力管理Agent",
            agent_category="system_management_agent",
            interface_target="capability_system_window",
            description="对接能力系统会话窗口，负责工具、skills 与执行能力相关管理任务。",
            enabled=True,
            builtin=True,
            editable=False,
            default_soul_id="zhurong",
            default_projection_id="zhurong__primary",
            task_scope=("capability_management", "execution_management"),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "capability_system", "slot_index": 4},
        ),
        AgentDescriptor(
            agent_id="agent:5",
            agent_name="5号灵魂管理Agent",
            agent_category="system_management_agent",
            interface_target="soul_system_window",
            description="对接灵魂系统会话窗口，负责人格设定、上下文组织风格与投影相关任务。",
            enabled=True,
            builtin=True,
            editable=False,
            default_soul_id="goumang",
            default_projection_id="goumang__primary",
            task_scope=("soul_management", "projection_management"),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "soul_system", "slot_index": 5},
        ),
    )


class AgentRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.root = _storage_root(self.base_dir)
        self.agents_path = self.root / "agents.json"

    def list_agents(self) -> list[AgentDescriptor]:
        default_payload = [item.to_dict() for item in default_agent_descriptors()]
        payload = _read_json(self.agents_path, {"agents": default_payload})
        raw_agents = _merge_items_by_key(
            default_payload,
            [item for item in list(payload.get("agents") or []) if isinstance(item, dict)],
            key="agent_id",
        )
        default_by_id = {str(item.get("agent_id") or ""): item for item in default_payload}
        migrated = [
            _enforce_system_builtin_payload(_migrate_agent_payload(item), default_by_id=default_by_id)
            for item in raw_agents
        ]
        migrated = [self._hydrate_main_agent_defaults(item) for item in migrated]
        if payload.get("agents") != migrated:
            _write_json(self.agents_path, {"agents": migrated})
        return [_agent_from_dict(item) for item in migrated]

    def get_agent(self, agent_id: str) -> AgentDescriptor | None:
        target = str(agent_id or "").strip()
        aliases = {target}
        if target == "agent:main":
            aliases.add("agent:0")
        return next((item for item in self.list_agents() if item.agent_id in aliases), None)

    def next_worker_agent_id(self) -> str:
        occupied_numbers: set[int] = set()
        for agent in self.list_agents():
            raw = str(agent.agent_id or "").strip()
            if not raw.startswith("agent:"):
                continue
            suffix = raw.split(":", 1)[1]
            if suffix.isdigit():
                occupied_numbers.add(int(suffix))
        candidate = 6
        while candidate in occupied_numbers:
            candidate += 1
        return f"agent:{candidate}"

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> AgentDescriptor:
        current = self.get_agent(agent_id)
        if current is None:
            raise KeyError(agent_id)
        if current.builtin and not enabled:
            raise PermissionError("system builtin agent cannot be disabled")
        updated = replace(current, enabled=bool(enabled), updated_at=time.time())
        agents = [updated if item.agent_id == updated.agent_id else item for item in self.list_agents()]
        _write_json(self.agents_path, {"agents": [item.to_dict() for item in agents]})
        return updated

    def upsert_agent(
        self,
        *,
        agent_id: str,
        agent_name: str | None = None,
        display_name: str | None = None,
        agent_category: str | None = None,
        profile_type: str | None = None,
        interface_target: str = "",
        description: str = "",
        enabled: bool | None = None,
        lifecycle_state: str | None = None,
        editable: bool | None = None,
        default_soul_id: str = "",
        default_projection_id: str = "",
        task_scope: tuple[str, ...] | list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        owner_system: str | None = None,
        governance_status: str | None = None,
    ) -> AgentDescriptor:
        _ = owner_system
        _ = governance_status
        target = str(agent_id or "").strip()
        if not target.startswith("agent:"):
            raise ValueError("agent_id must start with agent:")
        normalized_category = _normalize_agent_category(agent_category or profile_type or "worker_sub_agent")
        if normalized_category not in AGENT_CATEGORIES:
            raise ValueError("unsupported agent_category")
        current = self.get_agent(target)
        timestamp = time.time()
        if current is not None and current.builtin:
            if _builtin_mutation_attempted(
                current,
                agent_name=agent_name,
                display_name=display_name,
                agent_category=agent_category,
                profile_type=profile_type,
                interface_target=interface_target,
                description=description,
                enabled=enabled,
                lifecycle_state=lifecycle_state,
                editable=editable,
                task_scope=task_scope,
                metadata=metadata,
            ):
                raise PermissionError("system builtin agent is locked")
            return current
        current_projection_id = current.default_projection_id if current is not None else ""
        current_soul_id = current.default_soul_id if current is not None else ""
        current_description = current.description if current is not None else ""
        current_editable = current.editable if current is not None else True
        current_metadata = dict(current.metadata) if current is not None else {}
        resolved_task_scope = task_scope if task_scope is not None else (current.task_scope if current is not None else ())
        if current is not None and current.builtin:
            normalized_category = current.agent_category
        normalized_enabled = bool(enabled if enabled is not None else lifecycle_state != "disabled")
        normalized_projection_id = str(default_projection_id or current_projection_id).strip()
        normalized_soul_id = str(default_soul_id or current_soul_id).strip()
        if normalized_category == "main_agent":
            normalized_projection_id, normalized_soul_id = self._resolve_main_agent_runtime_defaults(
                projection_id=normalized_projection_id,
                soul_id=normalized_soul_id,
            )
        if normalized_projection_id:
            projection_card = SoulFacade(self.base_dir).get_projection_card(normalized_projection_id)
            if projection_card is not None:
                normalized_soul_id = str(projection_card.get("soul_id") or normalized_soul_id).strip()
        updated = AgentDescriptor(
            agent_id=target,
            agent_name=str(agent_name or display_name or target).strip() or target,
            agent_category=normalized_category,
            interface_target=str(interface_target or _default_interface_target(target, normalized_category)).strip(),
            description=str(description or current_description).strip(),
            enabled=normalized_enabled,
            builtin=current.builtin if current is not None else False,
            editable=bool(editable if editable is not None else current_editable),
            default_soul_id=normalized_soul_id,
            default_projection_id=normalized_projection_id,
            task_scope=tuple(str(item).strip() for item in resolved_task_scope if str(item).strip()),
            created_at=current.created_at if current is not None else timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or current_metadata),
        )
        agents = [item for item in self.list_agents() if item.agent_id != target]
        agents.append(updated)
        agents.sort(key=lambda item: _agent_sort_key(item.agent_id))
        _write_json(self.agents_path, {"agents": [item.to_dict() for item in agents]})
        return updated

    def _resolve_main_agent_runtime_defaults(self, *, projection_id: str, soul_id: str) -> tuple[str, str]:
        normalized_projection_id = str(projection_id or "").strip()
        normalized_soul_id = str(soul_id or "").strip().lower()
        facade = SoulFacade(self.base_dir)
        if normalized_projection_id:
            projection_card = facade.get_projection_card(normalized_projection_id)
            if projection_card is not None:
                normalized_soul_id = str(projection_card.get("soul_id") or normalized_soul_id).strip().lower()
        if not normalized_soul_id:
            normalized_soul_id = facade.registry_service.active_soul_id()
        normalized_projection_id = f"{normalized_soul_id}__primary" if normalized_soul_id else ""
        return normalized_projection_id, normalized_soul_id

    def _hydrate_main_agent_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        if str(payload.get("agent_category") or "") != "main_agent":
            return payload
        projection_id, soul_id = self._resolve_main_agent_runtime_defaults(
            projection_id=str(payload.get("default_projection_id") or ""),
            soul_id=str(payload.get("default_soul_id") or ""),
        )
        normalized_name = str(payload.get("agent_name") or payload.get("display_name") or "").strip()
        expected_name = "主 Agent"
        if (
            projection_id == str(payload.get("default_projection_id") or "")
            and soul_id == str(payload.get("default_soul_id") or "").strip().lower()
            and normalized_name == expected_name
        ):
            return payload
        next_payload = dict(payload)
        next_payload["default_projection_id"] = projection_id
        next_payload["default_soul_id"] = soul_id
        next_payload["agent_name"] = expected_name
        next_payload["display_name"] = expected_name
        return next_payload

    def delete_agent(self, agent_id: str) -> None:
        current = self.get_agent(agent_id)
        if current is None:
            raise KeyError(agent_id)
        if current.builtin:
            raise PermissionError("system builtin agent cannot be deleted")
        agents = [item for item in self.list_agents() if item.agent_id != current.agent_id]
        _write_json(self.agents_path, {"agents": [item.to_dict() for item in agents]})

    def build_catalog(self) -> dict[str, Any]:
        agents = self.list_agents()
        return {
            "authority": "orchestration.agent_registry",
            "agents": [agent.to_dict() for agent in agents],
            "summary": {
                "agent_count": len(agents),
                "enabled_agent_count": sum(1 for item in agents if item.enabled),
                "main_agent_count": sum(1 for item in agents if item.agent_category == "main_agent"),
                "system_management_agent_count": sum(1 for item in agents if item.agent_category == "system_management_agent"),
                "worker_sub_agent_count": sum(1 for item in agents if item.agent_category == "worker_sub_agent"),
                "builtin_agent_count": sum(1 for item in agents if item.builtin),
            },
        }


def _agent_sort_key(agent_id: str) -> tuple[int, str]:
    try:
        return (0, f"{int(agent_id.split(':', 1)[1]):04d}")
    except Exception:
        return (1, agent_id)


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


def _default_interface_target(agent_id: str, agent_category: str) -> str:
    if agent_category == "main_agent":
        return "main_conversation"
    if agent_category == "system_management_agent":
        return f"{agent_id.replace('agent:', '').replace(':', '_')}_window"
    return "worker_task_console"


def _normalize_agent_category(value: str) -> str:
    normalized = str(value or "worker_sub_agent").strip()
    if normalized == "main_agent":
        return "main_agent"
    if normalized == "system_management_agent":
        return "system_management_agent"
    return "worker_sub_agent"


def _migrate_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "").strip()
    legacy_name = str(payload.get("display_name") or payload.get("agent_name") or agent_id).strip() or agent_id
    legacy_category = _normalize_agent_category(str(payload.get("agent_category") or payload.get("profile_type") or "worker_sub_agent"))
    owner_system = str(payload.get("owner_system") or payload.get("metadata", {}).get("system_key") or "").strip()
    if agent_id in {"agent:main", "agent:0"}:
        legacy_category = "main_agent"
    elif owner_system and owner_system not in {"", "task_system", "worker_pool"}:
        legacy_category = "system_management_agent"
    normalized_soul_id = str(payload.get("default_soul_id") or "").strip()
    normalized_projection_id = str(payload.get("default_projection_id") or "").strip()
    return {
        "agent_id": "agent:0" if agent_id == "agent:main" else "agent:3" if agent_id == "agent:health:maintainer" else agent_id,
        "agent_name": legacy_name,
        "display_name": legacy_name,
        "agent_category": legacy_category,
        "profile_type": legacy_category,
        "interface_target": str(payload.get("interface_target") or _default_interface_target(agent_id or "agent:worker", legacy_category)),
        "description": str(payload.get("description") or payload.get("metadata", {}).get("role") or "").strip(),
        "enabled": bool(payload.get("enabled", str(payload.get("lifecycle_state") or "enabled") != "disabled")),
        "builtin": bool(payload.get("builtin", str(payload.get("lifecycle_state") or "") == "system_builtin")),
        "editable": bool(payload.get("editable", not bool(payload.get("builtin", str(payload.get("lifecycle_state") or "") == "system_builtin")))),
        "default_soul_id": normalized_soul_id,
        "default_projection_id": normalized_projection_id,
        "task_scope": list(payload.get("task_scope") or []),
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "metadata": {
            **dict(payload.get("metadata") or {}),
            **(
                {
                    "definition_source": "system_builtin",
                    "lifecycle_policy": "system_locked",
                }
                if bool(payload.get("builtin", str(payload.get("lifecycle_state") or "") == "system_builtin"))
                else {}
            ),
            **(
                {
                    "system_key": owner_system
                }
                if owner_system
                else {}
            ),
        },
    }


def _agent_from_dict(payload: dict[str, Any]) -> AgentDescriptor:
    return AgentDescriptor(
        agent_id=str(payload.get("agent_id") or ""),
        agent_name=str(payload.get("agent_name") or payload.get("display_name") or ""),
        agent_category=_normalize_agent_category(str(payload.get("agent_category") or payload.get("profile_type") or "worker_sub_agent")),
        interface_target=str(payload.get("interface_target") or ""),
        description=str(payload.get("description") or ""),
        enabled=bool(payload.get("enabled", True)),
        builtin=bool(payload.get("builtin", False)),
        editable=bool(payload.get("editable", True)),
        default_soul_id=str(payload.get("default_soul_id") or ""),
        default_projection_id=str(payload.get("default_projection_id") or ""),
        task_scope=tuple(str(item) for item in list(payload.get("task_scope") or []) if str(item)),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _enforce_system_builtin_payload(
    payload: dict[str, Any],
    *,
    default_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "").strip()
    default_payload = default_by_id.get(agent_id)
    if not default_payload or not bool(default_payload.get("builtin")):
        return payload
    enforced = dict(default_payload)
    enforced["created_at"] = float(payload.get("created_at") or default_payload.get("created_at") or 0.0)
    enforced["updated_at"] = float(payload.get("updated_at") or default_payload.get("updated_at") or 0.0)
    enforced["metadata"] = {
        **dict(default_payload.get("metadata") or {}),
        "definition_source": "system_builtin",
        "lifecycle_policy": "system_locked",
    }
    enforced["editable"] = False
    enforced["enabled"] = True
    enforced["builtin"] = True
    return enforced


def _builtin_mutation_attempted(
    current: AgentDescriptor,
    *,
    agent_name: str | None,
    display_name: str | None,
    agent_category: str | None,
    profile_type: str | None,
    interface_target: str,
    description: str,
    enabled: bool | None,
    lifecycle_state: str | None,
    editable: bool | None,
    task_scope: tuple[str, ...] | list[str] | None,
    metadata: dict[str, Any] | None,
) -> bool:
    requested_name = str(agent_name or display_name or current.agent_name).strip()
    requested_category = _normalize_agent_category(agent_category or profile_type or current.agent_category)
    requested_interface = str(interface_target or current.interface_target).strip()
    requested_description = str(description or current.description).strip()
    requested_enabled = bool(enabled if enabled is not None else lifecycle_state != "disabled")
    requested_editable = bool(editable if editable is not None else current.editable)
    requested_scope = (
        tuple(str(item).strip() for item in task_scope if str(item).strip())
        if task_scope is not None
        else current.task_scope
    )
    protected_metadata = dict(metadata or current.metadata)
    protected_keys = ("role", "system_key", "slot_index")
    metadata_changed = any(
        str(protected_metadata.get(key) or "") != str(current.metadata.get(key) or "")
        for key in protected_keys
    )
    return any(
        (
            requested_name != current.agent_name,
            requested_category != current.agent_category,
            requested_interface != current.interface_target,
            requested_description != current.description,
            requested_enabled is not True,
            requested_editable is not False,
            requested_scope != current.task_scope,
            metadata_changed,
        )
    )
