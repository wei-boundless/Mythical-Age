from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.a2a_cards import A2A_COMPATIBLE_PROTOCOL_VERSION, build_default_agent_cards
from api.deps import require_runtime

router = APIRouter()


class AgentEnabledRequest(BaseModel):
    enabled: bool = True


class ProtocolLinkUpdateRequest(BaseModel):
    enabled: bool | None = None
    input_contract: str = Field(default="")
    output_contract: str = Field(default="")
    handoff_policy: str = Field(default="")


def _default_control_agents() -> list[dict[str, Any]]:
    cards = build_default_agent_cards()
    return [
        {
            "agent_id": "agent:local:worker",
            "name": "执行智能体",
            "description": "承接实现、修复、验证和文件级任务，把结果回传主会话。",
            "kind": "execution",
            "mcp_route": "worker",
            "protocol_version": A2A_COMPATIBLE_PROTOCOL_VERSION,
            "supports_streaming": True,
            "supports_long_task": True,
            "default_input_modes": ["text/plain", "application/json"],
            "default_output_modes": ["text/plain", "application/json", "text/markdown"],
            "skills": [
                {
                    "id": "bounded-implementation",
                    "name": "有界执行",
                    "description": "执行明确范围内的代码、测试或文件任务。",
                    "tags": ["worker", "implementation", "verification"],
                    "input_modes": ["text/plain", "application/json"],
                    "output_modes": ["text/plain", "text/markdown"],
                }
            ],
            "mcp_profile": {"protocol_version": "mcp-compatible.v1", "tools": []},
            "extensions": {"x-langchain-agent.mcp_route": "worker"},
        },
        {
            **cards["agent:knowledge:retrieval"].to_dict(),
            "kind": "retrieval",
            "mcp_route": "retrieval",
        },
        {
            **cards["agent:document:pdf"].to_dict(),
            "kind": "document",
            "mcp_route": "pdf",
        },
        {
            **cards["agent:data:structured"].to_dict(),
            "kind": "data",
            "mcp_route": "structured_data",
        },
    ]


def _default_protocol_links() -> list[dict[str, Any]]:
    return [
        {
            "link_id": "main-to-worker",
            "from_agent": "agent:main:conversation",
            "to_agent": "agent:local:worker",
            "label": "任务委派",
            "enabled": True,
            "input_contract": "任务简报 + 工作区边界 + 验收检查",
            "output_contract": "变更摘要 + 文件清单 + 验证结果",
            "handoff_policy": "主会话生成边界清晰的任务，执行智能体只返回结构化结果，不直接污染对话状态。",
            "channels": ["task.submitted", "task.completed", "task.failed"],
        },
        {
            "link_id": "main-to-retrieval",
            "from_agent": "agent:main:conversation",
            "to_agent": "agent:knowledge:retrieval",
            "label": "证据召回",
            "enabled": True,
            "input_contract": "用户问题 + 来源约束 + 目标句柄线索",
            "output_contract": "候选证据 + 对象句柄 + 可信度",
            "handoff_policy": "检索结果必须以候选证据返回，由主会话或证据编排器完成答案合成。",
            "channels": ["worker.requested", "worker.evidence", "worker.completed"],
        },
        {
            "link_id": "main-to-pdf",
            "from_agent": "agent:main:conversation",
            "to_agent": "agent:document:pdf",
            "label": "文档解析",
            "enabled": True,
            "input_contract": "用户问题 + 当前 PDF/路径 + 页码/章节模式",
            "output_contract": "规范化文档答案 + 页码引用 + 降级原因",
            "handoff_policy": "文档智能体负责页码、章节和证据稳定性；降级原因必须回传测试系统。",
            "channels": ["worker.requested", "worker.artifacts", "worker.completed"],
        },
        {
            "link_id": "pdf-to-structured",
            "from_agent": "agent:document:pdf",
            "to_agent": "agent:data:structured",
            "label": "表格移交",
            "enabled": True,
            "input_contract": "表格产物句柄 + 结构预览 + 用户问题",
            "output_contract": "结构化摘要 + 子集句柄 + 聚合追踪",
            "handoff_policy": "PDF 中抽出的表格不直接进答案，先交由结构化数据智能体校验和分析。",
            "channels": ["artifact.detected", "worker.requested", "worker.completed"],
        },
        {
            "link_id": "retrieval-to-pdf",
            "from_agent": "agent:knowledge:retrieval",
            "to_agent": "agent:document:pdf",
            "label": "文档候选绑定",
            "enabled": True,
            "input_contract": "文档候选句柄 + 追问问题",
            "output_contract": "已绑定 PDF 句柄 + 页码/章节证据",
            "handoff_policy": "当检索只找到 PDF 候选时，由文档智能体绑定具体对象并返回可追踪证据。",
            "channels": ["candidate.selected", "worker.requested", "worker.completed"],
        },
    ]


def _default_agent_system_config() -> dict[str, Any]:
    return {
        "enabled_agents": {
            "agent:local:worker": True,
            "agent:knowledge:retrieval": True,
            "agent:document:pdf": True,
            "agent:data:structured": True,
        },
        "protocol_links": _default_protocol_links(),
    }


def _agent_system_config() -> dict[str, Any]:
    from config import runtime_config

    require_runtime()
    loaded = runtime_config.load()
    agent_system = loaded.get("agent_system")
    if not isinstance(agent_system, dict):
        agent_system = _default_agent_system_config()
    defaults = _default_agent_system_config()
    enabled = dict(defaults["enabled_agents"])
    if isinstance(agent_system.get("enabled_agents"), dict):
        enabled.update({str(key): bool(value) for key, value in agent_system["enabled_agents"].items()})
    stored_links = {
        str(item.get("link_id")): item
        for item in list(agent_system.get("protocol_links") or [])
        if isinstance(item, dict) and str(item.get("link_id") or "").strip()
    }
    links = []
    for default_link in defaults["protocol_links"]:
        merged = dict(default_link)
        override = stored_links.get(str(default_link["link_id"]))
        if isinstance(override, dict):
            for key in ("enabled", "input_contract", "output_contract", "handoff_policy"):
                if key in override:
                    merged[key] = override[key]
        links.append(merged)
    return {"enabled_agents": enabled, "protocol_links": links}


def _save_agent_system_config(config: dict[str, Any]) -> dict[str, Any]:
    from config import runtime_config

    runtime_config.save({"agent_system": config})
    return config


def _catalog_payload() -> dict[str, Any]:
    config = _agent_system_config()
    agents = []
    for agent in _default_control_agents():
        agent_id = str(agent["agent_id"])
        agents.append(
            {
                **agent,
                "enabled": bool(config["enabled_agents"].get(agent_id, True)),
            }
        )
    enabled_by_agent_id = {"agent:main:conversation": True, **{item["agent_id"]: bool(item["enabled"]) for item in agents}}
    protocol_enabled_links = sum(1 for item in config["protocol_links"] if item.get("enabled"))
    operational_links = sum(
        1
        for item in config["protocol_links"]
        if item.get("enabled")
        and enabled_by_agent_id.get(str(item.get("from_agent")), False)
        and enabled_by_agent_id.get(str(item.get("to_agent")), False)
    )
    return {
        "protocol_version": A2A_COMPATIBLE_PROTOCOL_VERSION,
        "agents": agents,
        "protocol_links": list(config["protocol_links"]),
        "status_summary": {
            "total_agents": len(agents),
            "enabled_agents": sum(1 for item in agents if item["enabled"]),
            "enabled_links": operational_links,
            "protocol_enabled_links": protocol_enabled_links,
            "blocked_links": max(0, protocol_enabled_links - operational_links),
        },
    }


@router.get("/agents/catalog")
async def agent_system_catalog() -> dict[str, Any]:
    return _catalog_payload()


@router.put("/agents/{agent_id}/enabled")
async def set_agent_enabled(agent_id: str, payload: AgentEnabledRequest) -> dict[str, Any]:
    known = {item["agent_id"] for item in _default_control_agents()}
    if agent_id not in known:
        raise HTTPException(status_code=404, detail="Unknown agent")
    config = _agent_system_config()
    config["enabled_agents"][agent_id] = bool(payload.enabled)
    _save_agent_system_config(config)
    return _catalog_payload()


@router.put("/agents/protocol-links/{link_id}")
async def update_protocol_link(link_id: str, payload: ProtocolLinkUpdateRequest) -> dict[str, Any]:
    config = _agent_system_config()
    links = list(config.get("protocol_links") or [])
    for link in links:
        if str(link.get("link_id") or "") != link_id:
            continue
        if payload.enabled is not None:
            link["enabled"] = bool(payload.enabled)
        if payload.input_contract.strip():
            link["input_contract"] = payload.input_contract.strip()
        if payload.output_contract.strip():
            link["output_contract"] = payload.output_contract.strip()
        if payload.handoff_policy.strip():
            link["handoff_policy"] = payload.handoff_policy.strip()
        config["protocol_links"] = links
        _save_agent_system_config(config)
        return _catalog_payload()
    raise HTTPException(status_code=404, detail="Unknown protocol link")
