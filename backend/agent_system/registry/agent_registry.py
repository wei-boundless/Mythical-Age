from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout
from ..identity import agent_id_aliases, normalize_agent_id
from ..models.agent_models import AgentDescriptor


AGENT_CATEGORIES = {"main_agent", "builtin_agent", "custom_agent"}


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
            agent_name="通用主 Agent",
            agent_category="main_agent",
            interface_target="main_conversation",
            description="你是通用主会话 Agent。你负责处理广泛工作请求，理解用户目标、组织必要上下文和工具调用，并给出最终答复或交付结果。你可以委派专门 Agent 执行局部检索、验证或实现任务，但最终判断、取舍和对用户的说明由你负责。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "role": "main_conversation_entry",
                "builtin_kind": "primary",
                "system_key": "task_system",
                "slot_index": 0,
                "agent_template_id": "builtin.main.general",
                "main_agent_kind": "general",
                "default_task_environment_id": "env.general.workspace",
                "subagent_enabled": False,
                "group_eligible": False,
            },
        ),
        AgentDescriptor(
            agent_id="agent:main_coding",
            agent_name="编码主 Agent",
            agent_category="main_agent",
            interface_target="main_conversation",
            description="你是编码主会话 Agent。你负责真实代码工作区里的开发、排查、重构和验证交付。你必须以当前代码事实、用户最新要求、项目规则和可验证结果为准；可以委派检索或复核子 Agent，但最终实现判断、风险取舍和对用户说明由你负责。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "role": "main_conversation_entry",
                "builtin_kind": "primary",
                "system_key": "task_system",
                "slot_index": 1,
                "agent_template_id": "builtin.main.coding",
                "main_agent_kind": "coding",
                "default_task_environment_id": "env.coding.vibe_workspace",
                "subagent_enabled": False,
                "group_eligible": False,
            },
        ),
        AgentDescriptor(
            agent_id="agent:main_office",
            agent_name="办公主 Agent",
            agent_category="main_agent",
            interface_target="main_conversation",
            description="你是办公资料主会话 Agent。你负责文件资料、来源核验、摘要整理、表格或文档材料处理和可交付办公产物。你必须基于真实读取和来源证据作答；可以委派资料、PDF、表格或网页研究子 Agent，但最终来源裁决和对用户说明由你负责。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "role": "main_conversation_entry",
                "builtin_kind": "primary",
                "system_key": "task_system",
                "slot_index": 2,
                "agent_template_id": "builtin.main.office",
                "main_agent_kind": "office",
                "default_task_environment_id": "env.office.file_search",
                "subagent_enabled": False,
                "group_eligible": False,
            },
        ),
        AgentDescriptor(
            agent_id="agent:1",
            agent_name="记忆管理Agent",
            agent_category="builtin_agent",
            interface_target="memory_system_window",
            description="你是一名记忆治理员。你负责检查会话记忆、长期记忆、记忆候选和记忆整理请求是否准确、必要、可追溯。你不凭空写入事实，不把临时推测当作长期记忆；发现冲突、过期或证据不足时，需要明确说明原因和处理建议。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "builtin_kind": "system_manager", "system_key": "memory_system", "slot_index": 3, "agent_template_id": "builtin.system.memory_manager", "subagent_enabled": False, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:2",
            agent_name="配置管理Agent",
            agent_category="builtin_agent",
            interface_target="config_system_window",
            description="你是一名配置治理员。你负责审查系统配置、运行参数和环境状态是否清晰、一致、可执行。你只基于已提供的配置和可观测状态作判断；发现缺失、冲突或风险时，需要指出具体配置项、影响范围和建议操作。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "builtin_kind": "system_manager", "system_key": "config_system", "slot_index": 4, "agent_template_id": "builtin.system.config_manager", "subagent_enabled": False, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:3",
            agent_name="3号健康管理Agent",
            agent_category="builtin_agent",
            interface_target="health_system_window",
            description="你是一名运行健康分析员。你负责分析健康系统窗口中的状态、告警、运行指标和维护请求。你需要区分已观测事实、可能原因和建议动作；证据不足时不要下确定结论，要说明还需要检查什么。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "builtin_kind": "system_manager", "system_key": "health_system", "slot_index": 5, "agent_template_id": "builtin.system.health_manager", "subagent_enabled": False, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:4",
            agent_name="任务管理Agent",
            agent_category="builtin_agent",
            interface_target="task_system_window",
            description="你是一名任务治理员。你负责审查任务注册、任务契约、运行状态和交付边界是否明确。你需要确认任务目标、授权范围、可执行步骤和完成标准；发现契约不完整、状态异常或边界不清时，需要给出阻断原因和修正建议。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "builtin_kind": "system_manager", "system_key": "task_management_system", "slot_index": 6, "agent_template_id": "builtin.system.task_manager", "subagent_enabled": False, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:5",
            agent_name="能力管理Agent",
            agent_category="builtin_agent",
            interface_target="capability_system_window",
            description="你是一名能力治理员。你负责审查工具、技能和 MCP 能力目录是否可用、边界清楚、权限合理。你不能假设未注册能力存在；发现能力缺失、重复、权限过宽或描述不清时，需要指出具体能力项和修正建议。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "builtin_kind": "system_manager", "system_key": "capability_system", "slot_index": 7, "agent_template_id": "builtin.system.capability_manager", "subagent_enabled": False, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:knowledge_searcher",
            agent_name="知识库检索Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名知识库检索员。你只负责检索项目知识库和 RAG 文档块，整理来源、引用、相关片段和不确定性，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "knowledge_search", "slot_index": 8, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.knowledge_searcher", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:pdf_reader",
            agent_name="PDF阅读分析Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名 PDF 阅读分析员。你负责阅读指定 PDF 内容，抽取要点、证据位置和限制说明，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "pdf_analysis", "slot_index": 9, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.pdf_reader", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:table_analyst",
            agent_name="表格分析Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名表格与结构化数据分析员。你负责读取数据结构、执行受限分析并返回结论依据，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "structured_data_analysis", "slot_index": 10, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.table_analyst", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:web_researcher",
            agent_name="网页研究Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名网页研究员。你只负责检索公开网页、官方文档、公告和实时外部信息，核验来源、日期、可信度和冲突，不读取本地文件、知识库或记忆，不负责替主 Agent 做最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "web_research", "slot_index": 11, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.web_researcher", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:codebase_searcher",
            agent_name="代码库检索Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名代码库检索员。你只负责在本地工作区中搜索文件、符号、配置、测试和调用线索，返回文件路径、行号、证据片段和不确定性，不修改文件，不负责最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "codebase_search", "slot_index": 12, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.codebase_searcher", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:memory_searcher",
            agent_name="记忆检索Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名记忆检索员。你只负责检索正式记忆、历史任务结论和会话状态摘要，并明确区分历史结论与当前事实，不读取网页、本地代码或知识库，不负责最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "memory_search", "slot_index": 13, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.memory_searcher", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:verifier",
            agent_name="交付复核Agent",
            agent_category="builtin_agent",
            interface_target="worker_task_console",
            description="你是一名交付复核员。你负责检查主 Agent 的回答、产物、证据和用户目标是否一致，只给复核裁决和返工建议，不替主 Agent 修改产物或最终回答。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "worker_specialist", "builtin_kind": "specialist", "worker_kind": "completion_verification", "slot_index": 14, "system_key": "builtin_specialist_pool", "agent_template_id": "builtin.specialist.verifier", "subagent_enabled": True, "group_eligible": False},
        ),
        AgentDescriptor(
            agent_id="agent:context_compactor",
            agent_name="上下文压缩Agent",
            agent_category="builtin_agent",
            interface_target="runtime_context_pipeline",
            description="你是一名上下文压缩员。你只负责把已有运行历史整理成后续模型可以继续工作的恢复点，不能引入新事实，不能自主搜索，不能修改文件。",
            enabled=True,
            builtin=True,
            editable=True,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={"role": "system_manager", "builtin_kind": "system_manager", "system_key": "context_management", "slot_index": 15, "agent_template_id": "builtin.system.context_compactor", "subagent_enabled": False, "group_eligible": False},
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
        stored_agents = [
            _migrate_agent_payload(item)
            for item in list(payload.get("agents") or [])
            if isinstance(item, dict)
        ]
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
        if payload.get("agents") != migrated:
            _write_json(self.agents_path, {"agents": migrated})
        return [_agent_from_dict(item) for item in migrated]

    def get_agent(self, agent_id: str) -> AgentDescriptor | None:
        target = normalize_agent_id(agent_id)
        aliases = set(agent_id_aliases(target))
        return next((item for item in self.list_agents() if item.agent_id in aliases), None)

    def next_worker_agent_id(self) -> str:
        occupied_ids = {str(agent.agent_id or "").strip() for agent in self.list_agents()}
        candidate = 1
        while f"agent:worker:{candidate}" in occupied_ids:
            candidate += 1
        return f"agent:worker:{candidate}"

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
        normalized_category = _normalize_agent_category(agent_category or profile_type or "custom_agent")
        if normalized_category not in AGENT_CATEGORIES:
            raise ValueError("unsupported agent_category")
        current = self.get_agent(target)
        timestamp = time.time()
        current_projection_id = current.default_projection_id if current is not None else ""
        current_description = current.description if current is not None else ""
        current_editable = current.editable if current is not None else True
        current_metadata = dict(current.metadata) if current is not None else {}
        if current is not None and current.builtin:
            normalized_category = current.agent_category
        normalized_enabled = bool(enabled if enabled is not None else lifecycle_state != "disabled")
        updated = AgentDescriptor(
            agent_id=target,
            agent_name=str(agent_name or display_name or target).strip() or target,
            agent_category=normalized_category,
            interface_target=str(interface_target or _default_interface_target(target, normalized_category)).strip(),
            description=str(description or current_description).strip(),
            enabled=normalized_enabled,
            builtin=current.builtin if current is not None else False,
            editable=bool(editable if editable is not None else current_editable),
            default_projection_id=str(default_projection_id or current_projection_id).strip(),
            created_at=current.created_at if current is not None else timestamp,
            updated_at=timestamp,
            metadata=dict(metadata or current_metadata),
        )
        agents = [item for item in self.list_agents() if item.agent_id != target]
        agents.append(updated)
        agents.sort(key=lambda item: _agent_sort_key(item.agent_id))
        _write_json(self.agents_path, {"agents": [item.to_dict() for item in agents]})
        return updated

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
                "builtin_agent_count": sum(1 for item in agents if item.agent_category == "builtin_agent"),
                "custom_agent_count": sum(1 for item in agents if item.agent_category == "custom_agent"),
                "system_manager_agent_count": sum(1 for item in agents if item.builtin_kind == "system_manager"),
                "subagent_enabled_agent_count": sum(1 for item in agents if item.subagent_enabled),
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
    if agent_category == "builtin_agent":
        return f"{agent_id.replace('agent:', '').replace(':', '_')}_window"
    return "worker_task_console"


def _normalize_agent_category(value: str) -> str:
    normalized = str(value or "custom_agent").strip()
    if normalized == "main_agent":
        return "main_agent"
    if normalized in {"builtin_agent", "system_management_agent"}:
        return "builtin_agent"
    return "custom_agent"


def _migrate_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "").strip()
    canonical_agent_id = normalize_agent_id(agent_id)
    display_name = str(payload.get("display_name") or payload.get("agent_name") or agent_id).strip() or agent_id
    agent_category = _normalize_agent_category(str(payload.get("agent_category") or payload.get("profile_type") or "custom_agent"))
    owner_system = str(payload.get("owner_system") or payload.get("metadata", {}).get("system_key") or "").strip()
    if canonical_agent_id == "agent:0":
        agent_category = "main_agent"
    elif bool(payload.get("builtin")) and (
        owner_system not in {"", "task_system", "worker_pool", "builtin_specialist_pool"}
        or str(dict(payload.get("metadata") or {}).get("role") or "").strip() == "system_manager"
    ):
        agent_category = "builtin_agent"
    elif bool(payload.get("builtin")):
        agent_category = "builtin_agent"
    else:
        agent_category = "custom_agent"
    metadata = dict(payload.get("metadata") or {})
    metadata.pop("legacy_agent_id", None)
    if "subagent_enabled" not in metadata:
        metadata["subagent_enabled"] = agent_category == "custom_agent" or bool(payload.get("builtin")) and owner_system in {"worker_pool", "builtin_specialist_pool"}
    if "group_eligible" not in metadata:
        metadata["group_eligible"] = agent_category == "custom_agent"
    if "agent_template_id" not in metadata:
        if bool(payload.get("builtin")):
            if str(metadata.get("role") or "").strip() == "system_manager":
                metadata["agent_template_id"] = f"builtin.system.{canonical_agent_id.removeprefix('agent:')}"
            else:
                metadata["agent_template_id"] = f"builtin.specialist.{canonical_agent_id.removeprefix('agent:')}"
    return {
        "agent_id": canonical_agent_id,
        "agent_name": display_name,
        "display_name": display_name,
        "agent_category": agent_category,
        "profile_type": agent_category,
        "interface_target": str(payload.get("interface_target") or _default_interface_target(canonical_agent_id or "agent:worker", agent_category)),
        "description": str(payload.get("description") or payload.get("metadata", {}).get("role") or "").strip(),
        "enabled": bool(payload.get("enabled", str(payload.get("lifecycle_state") or "enabled") != "disabled")),
        "builtin": bool(payload.get("builtin", str(payload.get("lifecycle_state") or "") == "system_builtin")),
        "editable": bool(payload.get("editable", True)),
        "default_projection_id": str(payload.get("default_projection_id") or "").strip(),
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "metadata": {
            **metadata,
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
        agent_category=_normalize_agent_category(str(payload.get("agent_category") or payload.get("profile_type") or "custom_agent")),
        interface_target=str(payload.get("interface_target") or ""),
        description=str(payload.get("description") or ""),
        enabled=bool(payload.get("enabled", True)),
        builtin=bool(payload.get("builtin", False)),
        editable=bool(payload.get("editable", True)),
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
    enforced["agent_category"] = str(default_payload.get("agent_category") or payload.get("agent_category") or "custom_agent")
    enforced["profile_type"] = str(default_payload.get("profile_type") or enforced["agent_category"])
    enforced["builtin"] = True
    enforced["created_at"] = float(payload.get("created_at") or default_payload.get("created_at") or 0.0)
    enforced["updated_at"] = float(payload.get("updated_at") or default_payload.get("updated_at") or 0.0)
    enforced["metadata"] = {
        **dict(payload.get("metadata") or {}),
        **{
            key: value
            for key, value in dict(default_payload.get("metadata") or {}).items()
            if key in {
                "role",
                "system_key",
                "slot_index",
                "builtin_kind",
                "agent_template_id",
                "main_agent_kind",
                "default_task_environment_id",
                "subagent_enabled",
                "group_eligible",
            }
        },
        "definition_source": "system_builtin",
        "lifecycle_policy": str(
            dict(payload.get("metadata") or {}).get("lifecycle_policy")
            or payload.get("lifecycle_policy")
            or "system_builtin"
        ),
    }
    return enforced




