from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from .agent_identity import agent_id_aliases, normalize_agent_id
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
            editable=True,
            default_soul_id="",
            default_projection_id="",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "main_conversation_entry", "system_key": "task_system", "slot_index": 0},
        ),
        AgentDescriptor(
            agent_id="agent:1",
            agent_name="权限管理Agent",
            agent_category="system_management_agent",
            interface_target="permission_system_window",
            description="负责权限策略、操作准入和安全边界的系统管理 Agent。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="",
            default_projection_id="",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "permission_system", "slot_index": 1},
        ),
        AgentDescriptor(
            agent_id="agent:2",
            agent_name="配置管理Agent",
            agent_category="system_management_agent",
            interface_target="config_system_window",
            description="负责系统配置、运行参数和环境状态的系统管理 Agent。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="",
            default_projection_id="",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "config_system", "slot_index": 2},
        ),
        AgentDescriptor(
            agent_id="agent:3",
            agent_name="3号健康管理Agent",
            agent_category="system_management_agent",
            interface_target="health_system_window",
            description="对接健康系统会话窗口，负责健康维护和健康分析类任务。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="xuannv",
            default_projection_id="xuannv__primary",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "health_system", "slot_index": 3},
        ),
        AgentDescriptor(
            agent_id="agent:4",
            agent_name="任务管理Agent",
            agent_category="system_management_agent",
            interface_target="task_system_window",
            description="负责任务注册、任务契约和任务运行状态的系统管理 Agent。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="",
            default_projection_id="",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "task_management_system", "slot_index": 4},
        ),
        AgentDescriptor(
            agent_id="agent:5",
            agent_name="能力管理Agent",
            agent_category="system_management_agent",
            interface_target="capability_system_window",
            description="负责工具、技能、MCP 能力目录的系统管理 Agent。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="",
            default_projection_id="",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "system_key": "capability_system", "slot_index": 5},
        ),
        AgentDescriptor(
            agent_id="agent:rag_analyst",
            agent_name="RAG检索分析Agent",
            agent_category="worker_sub_agent",
            interface_target="worker_task_console",
            description="你是一名证据检索分析员。你负责围绕问题检索知识库，整理证据、引用和不确定性，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="hebo",
            default_projection_id="projection.worker.rag_evidence_analyst",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "worker_kind": "rag_analysis", "slot_index": 6, "legacy_agent_id": "agent:6"},
        ),
        AgentDescriptor(
            agent_id="agent:pdf_reader",
            agent_name="PDF阅读分析Agent",
            agent_category="worker_sub_agent",
            interface_target="worker_task_console",
            description="你是一名 PDF 阅读分析员。你负责阅读指定 PDF 内容，抽取要点、证据位置和限制说明，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="hebo",
            default_projection_id="projection.worker.pdf_evidence_reader",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "worker_kind": "pdf_analysis", "slot_index": 7, "legacy_agent_id": "agent:7"},
        ),
        AgentDescriptor(
            agent_id="agent:table_analyst",
            agent_name="表格分析Agent",
            agent_category="worker_sub_agent",
            interface_target="worker_task_console",
            description="你是一名表格与结构化数据分析员。你负责读取数据结构、执行受限分析并返回结论依据，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="hebo",
            default_projection_id="projection.worker.table_evidence_analyst",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "worker_kind": "structured_data_analysis", "slot_index": 8, "legacy_agent_id": "agent:8"},
        ),
        AgentDescriptor(
            agent_id="agent:web_researcher",
            agent_name="网页证据研究Agent",
            agent_category="worker_sub_agent",
            interface_target="worker_task_console",
            description="你是一名网页证据研究员。你负责检索公开网页、识别可靠来源、整理事实证据和未知边界，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            default_soul_id="hebo",
            default_projection_id="projection.worker.web_evidence_researcher",
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "worker_kind": "web_research", "slot_index": 9, "legacy_agent_id": "agent:9"},
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
        stored_agents = [_migrate_agent_payload(item) for item in list(payload.get("agents") or []) if isinstance(item, dict)]
        raw_agents = (
            default_payload
            if not self.agents_path.exists()
            else _merge_items_by_key(default_payload, stored_agents, key="agent_id")
        )
        default_by_id = {str(item.get("agent_id") or ""): item for item in default_payload}
        migrated = [
            _enforce_system_builtin_payload(item, default_by_id=default_by_id)
            for item in raw_agents
        ]
        migrated = [self._hydrate_main_agent_defaults(item) for item in migrated]
        if payload.get("agents") != migrated:
            _write_json(self.agents_path, {"agents": migrated})
        return [_agent_from_dict(item) for item in migrated]

    def get_agent(self, agent_id: str) -> AgentDescriptor | None:
        target = normalize_agent_id(agent_id)
        aliases = set(agent_id_aliases(target))
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
        candidate = 1
        while candidate in occupied_numbers:
            candidate += 1
        return f"agent:{candidate}"

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> AgentDescriptor:
        current = self.get_agent(agent_id)
        if current is None:
            raise KeyError(agent_id)
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
        metadata: dict[str, Any] | None = None,
        owner_system: str | None = None,
        governance_status: str | None = None,
    ) -> AgentDescriptor:
        _ = owner_system
        _ = governance_status
        target = normalize_agent_id(agent_id)
        if not target.startswith("agent:"):
            raise ValueError("agent_id must start with agent:")
        normalized_category = _normalize_agent_category(agent_category or profile_type or "worker_sub_agent")
        if normalized_category not in AGENT_CATEGORIES:
            raise ValueError("unsupported agent_category")
        current = self.get_agent(target)
        timestamp = time.time()
        current_projection_id = current.default_projection_id if current is not None else ""
        current_soul_id = current.default_soul_id if current is not None else ""
        current_description = current.description if current is not None else ""
        current_editable = current.editable if current is not None else True
        current_metadata = dict(current.metadata) if current is not None else {}
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
        if (
            projection_id == str(payload.get("default_projection_id") or "")
            and soul_id == str(payload.get("default_soul_id") or "").strip().lower()
        ):
            return payload
        next_payload = dict(payload)
        next_payload["default_projection_id"] = projection_id
        next_payload["default_soul_id"] = soul_id
        return next_payload

    def delete_agent(self, agent_id: str) -> None:
        current = self.get_agent(agent_id)
        if current is None:
            raise KeyError(agent_id)
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
    canonical_agent_id = normalize_agent_id(agent_id)
    legacy_name = str(payload.get("display_name") or payload.get("agent_name") or agent_id).strip() or agent_id
    legacy_category = _normalize_agent_category(str(payload.get("agent_category") or payload.get("profile_type") or "worker_sub_agent"))
    owner_system = str(payload.get("owner_system") or payload.get("metadata", {}).get("system_key") or "").strip()
    if canonical_agent_id == "agent:0":
        legacy_category = "main_agent"
    elif owner_system and owner_system not in {"", "task_system", "worker_pool"}:
        legacy_category = "system_management_agent"
    normalized_soul_id = str(payload.get("default_soul_id") or "").strip()
    normalized_projection_id = str(payload.get("default_projection_id") or "").strip()
    return {
        "agent_id": canonical_agent_id,
        "agent_name": legacy_name,
        "display_name": legacy_name,
        "agent_category": legacy_category,
        "profile_type": legacy_category,
        "interface_target": str(payload.get("interface_target") or _default_interface_target(canonical_agent_id or "agent:worker", legacy_category)),
        "description": str(payload.get("description") or payload.get("metadata", {}).get("role") or "").strip(),
        "enabled": bool(payload.get("enabled", str(payload.get("lifecycle_state") or "enabled") != "disabled")),
        "builtin": bool(payload.get("builtin", str(payload.get("lifecycle_state") or "") == "system_builtin")),
        "editable": bool(payload.get("editable", True)),
        "default_soul_id": normalized_soul_id,
        "default_projection_id": normalized_projection_id,
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "metadata": {
            **dict(payload.get("metadata") or {}),
            **({"legacy_agent_id": agent_id} if agent_id and agent_id != canonical_agent_id else {}),
            **(
                {
                    "definition_source": "system_builtin",
                    "lifecycle_policy": "system_builtin",
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
    enforced.update(payload)
    enforced["agent_id"] = agent_id
    enforced["agent_category"] = str(default_payload.get("agent_category") or payload.get("agent_category") or "worker_sub_agent")
    enforced["profile_type"] = str(default_payload.get("profile_type") or enforced["agent_category"])
    enforced["builtin"] = True
    enforced["created_at"] = float(payload.get("created_at") or default_payload.get("created_at") or 0.0)
    enforced["updated_at"] = float(payload.get("updated_at") or default_payload.get("updated_at") or 0.0)
    enforced["metadata"] = {
        **dict(payload.get("metadata") or {}),
        **{
            key: value
            for key, value in dict(default_payload.get("metadata") or {}).items()
            if key in {"role", "system_key", "slot_index"}
        },
        "definition_source": "system_builtin",
        "lifecycle_policy": str(
            dict(payload.get("metadata") or {}).get("lifecycle_policy")
            or payload.get("lifecycle_policy")
            or "system_builtin"
        ),
    }
    return enforced
