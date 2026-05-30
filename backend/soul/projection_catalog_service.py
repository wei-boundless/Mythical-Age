from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .registry import BUILTIN_SOUL_NAMES, read_text, write_text


CATALOG_PATH = "soul/projections/catalog.json"
DEFAULT_SELECTED_PROJECTION_ID = "projection.worker.web_evidence_researcher"


class SoulProjectionCatalogError(ValueError):
    pass


def build_projection_catalog(base_dir: Path) -> dict[str, Any]:
    payload = _read_payload(base_dir)
    custom_cards = [_normalize_card(item, system_default=False) for item in _payload_cards(payload)]
    custom_cards = [
        item
        for item in custom_cards
        if item["projection_id"] and item["projection_id"] not in DEFAULT_PROJECTION_IDS
    ]
    cards = [dict(item) for item in DEFAULT_PROJECTION_CARDS]
    cards.extend(custom_cards)
    card_ids = {str(item.get("projection_id") or "") for item in cards}
    selected = str(payload.get("selected_projection_id") or "").strip()
    if selected not in card_ids:
        selected = DEFAULT_SELECTED_PROJECTION_ID if DEFAULT_SELECTED_PROJECTION_ID in card_ids else next(iter(card_ids), "")
    return {
        "authority": "soul.projection_catalog",
        "selected_projection_id": selected,
        "cards": cards,
    }


def upsert_projection_card(base_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    catalog_payload = _read_payload(base_dir)
    now = time.time()
    card = _normalize_card(
        {
            **payload,
            "projection_id": _resolve_projection_id(payload),
            "created_at": payload.get("created_at") or now,
            "updated_at": now,
        },
        system_default=False,
    )
    projection_id = card["projection_id"]
    if projection_id in DEFAULT_PROJECTION_IDS:
        raise SoulProjectionCatalogError("System projection cards cannot be overwritten")
    custom_cards = [
        dict(item)
        for item in _payload_cards(catalog_payload)
        if str(item.get("projection_id") or "").strip() != projection_id
        and str(item.get("projection_id") or "").strip() not in DEFAULT_PROJECTION_IDS
    ]
    custom_cards.append(card)
    selected = (
        projection_id
        if bool(payload.get("select_after_create"))
        else str(catalog_payload.get("selected_projection_id") or DEFAULT_SELECTED_PROJECTION_ID).strip()
    )
    _write_payload(base_dir, selected_projection_id=selected, custom_cards=custom_cards)
    return build_projection_catalog(base_dir)


def select_projection_card(base_dir: Path, projection_id: str) -> dict[str, Any]:
    normalized = str(projection_id or "").strip()
    catalog = build_projection_catalog(base_dir)
    if normalized not in {str(item.get("projection_id") or "") for item in catalog["cards"]}:
        raise SoulProjectionCatalogError("Unknown projection_id")
    _write_payload(
        base_dir,
        selected_projection_id=normalized,
        custom_cards=[
            item
            for item in _payload_cards(_read_payload(base_dir))
            if str(item.get("projection_id") or "").strip() not in DEFAULT_PROJECTION_IDS
        ],
    )
    return build_projection_catalog(base_dir)


def delete_projection_card(base_dir: Path, projection_id: str) -> dict[str, Any]:
    normalized = str(projection_id or "").strip()
    if normalized in DEFAULT_PROJECTION_IDS:
        raise SoulProjectionCatalogError("System projection cards cannot be deleted")
    payload = _read_payload(base_dir)
    custom_cards = [
        item
        for item in _payload_cards(payload)
        if str(item.get("projection_id") or "").strip() != normalized
        and str(item.get("projection_id") or "").strip() not in DEFAULT_PROJECTION_IDS
    ]
    if len(custom_cards) == len(_payload_cards(payload)):
        raise SoulProjectionCatalogError("Unknown projection_id")
    selected = str(payload.get("selected_projection_id") or "").strip()
    if selected == normalized:
        selected = DEFAULT_SELECTED_PROJECTION_ID
    _write_payload(base_dir, selected_projection_id=selected, custom_cards=custom_cards)
    return build_projection_catalog(base_dir)


def _catalog_path(base_dir: Path) -> Path:
    candidate = (Path(base_dir) / CATALOG_PATH).resolve()
    root = Path(base_dir).resolve()
    if root not in candidate.parents:
        raise ValueError("Invalid soul projection catalog path")
    return candidate


def _read_payload(base_dir: Path) -> dict[str, Any]:
    path = _catalog_path(base_dir)
    if not path.exists():
        return {"selected_projection_id": DEFAULT_SELECTED_PROJECTION_ID, "items": []}
    try:
        payload = json.loads(read_text(path) or "{}")
    except json.JSONDecodeError:
        return {"selected_projection_id": DEFAULT_SELECTED_PROJECTION_ID, "items": []}
    return payload if isinstance(payload, dict) else {"selected_projection_id": DEFAULT_SELECTED_PROJECTION_ID, "items": []}


def _write_payload(base_dir: Path, *, selected_projection_id: str, custom_cards: list[dict[str, Any]]) -> None:
    write_text(
        _catalog_path(base_dir),
        json.dumps(
            {
                "authority": "soul.projection_catalog",
                "selected_projection_id": selected_projection_id,
                "items": custom_cards,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _payload_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("items")
    if raw is None:
        raw = payload.get("cards")
    return [dict(item) for item in list(raw or []) if isinstance(item, dict)]


def _resolve_projection_id(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("projection_id") or "").strip()
    if explicit:
        return explicit
    seed = str(
        payload.get("projection_name")
        or payload.get("title")
        or payload.get("role_type")
        or payload.get("task_mode")
        or int(time.time())
    )
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", seed.strip().lower()).strip(".-")
    return f"projection.custom.{slug[:72] or int(time.time())}"


def _normalize_card(payload: dict[str, Any], *, system_default: bool) -> dict[str, Any]:
    projection_id = str(payload.get("projection_id") or "").strip()
    soul_id = str(payload.get("soul_id") or "hebo").strip().lower() or "hebo"
    title = str(payload.get("title") or payload.get("projection_name") or projection_id).strip() or projection_id
    now = time.time()
    return {
        "projection_id": projection_id,
        "title": title,
        "soul_id": soul_id,
        "soul_name": str(payload.get("soul_name") or BUILTIN_SOUL_NAMES.get(soul_id, soul_id)).strip(),
        "projection_kind": str(payload.get("projection_kind") or "worker_agent_projection").strip(),
        "owner_system": str(payload.get("owner_system") or "orchestration_system").strip(),
        "source_task_graph_refs": _string_list(payload.get("source_task_graph_refs")),
        "projection_nodes": [dict(item) for item in list(payload.get("projection_nodes") or []) if isinstance(item, dict)],
        "identity_anchor": str(payload.get("identity_anchor") or "").strip(),
        "role_type": str(payload.get("role_type") or "").strip(),
        "task_mode": str(payload.get("task_mode") or "").strip(),
        "agent_profile_id": str(payload.get("agent_profile_id") or "").strip(),
        "posture_tags": _string_list(payload.get("posture_tags")),
        "expression_density": str(payload.get("expression_density") or "normal").strip(),
        "attention_focus": _string_list(payload.get("attention_focus")),
        "risk_notes": _string_list(payload.get("risk_notes")),
        "projection_prompt": str(payload.get("projection_prompt") or "").strip(),
        "usage_summary": str(payload.get("usage_summary") or payload.get("identity_anchor") or "").strip(),
        "skill_views": [dict(item) for item in list(payload.get("skill_views") or []) if isinstance(item, dict)],
        "tool_views": [dict(item) for item in list(payload.get("tool_views") or []) if isinstance(item, dict)],
        "memory_policy_summary": str(payload.get("memory_policy_summary") or "").strip(),
        "output_contract_summary": str(payload.get("output_contract_summary") or "").strip(),
        "runtime_only_payload": bool(payload.get("runtime_only_payload", True)),
        "static_projection_card": bool(payload.get("static_projection_card", system_default)),
        "created_at": float(payload.get("created_at") or now),
        "updated_at": float(payload.get("updated_at") or now),
        "is_system_default": bool(payload.get("is_system_default", system_default)),
    }


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in list(value or []) if str(item).strip()]


DEFAULT_PROJECTION_CARDS = (
    _normalize_card(
        {
            "projection_id": "projection.worker.web_evidence_researcher",
            "title": "网页证据研究员",
            "soul_id": "hebo",
            "identity_anchor": "围绕委派问题检索公开网页、识别可靠来源，并整理成可判断的证据报告。",
            "role_type": "web_evidence_researcher",
            "task_mode": "general_qa",
            "agent_profile_id": "web_evidence_agent",
            "posture_tags": ["worker_sub_agent", "web", "evidence_first"],
            "attention_focus": ["freshness", "source_quality", "conflicts", "unknowns"],
            "projection_prompt": "优先寻找官方来源、原始公告、官方文档、权威媒体、一手数据或明确署名的可靠来源。对今天、现在、最新、近期、当前、实时等问题，必须核验时间点、发布时间和来源时效。",
            "usage_summary": "用于公开网页研究，整理可靠来源、时间核验、冲突信息和可回答事实。",
            "memory_policy_summary": "只读取当前委派问题和必要上下文，不写长期记忆。",
            "output_contract_summary": "返回网页证据报告，不替主 Agent 做最终表达。",
        },
        system_default=True,
    ),
    _normalize_card(
        {
            "projection_id": "projection.worker.table_evidence_analyst",
            "title": "表格证据分析员",
            "soul_id": "hebo",
            "identity_anchor": "读取数据结构，按委派问题完成受限计算，并整理计算口径、结果和边界。",
            "role_type": "table_evidence_analyst",
            "task_mode": "structured_data_analysis",
            "agent_profile_id": "structured_data_analysis_agent",
            "posture_tags": ["worker_sub_agent", "table", "evidence_first"],
            "attention_focus": ["schema", "filters", "group_by", "metrics", "unknowns"],
            "projection_prompt": "先确认对象、维度、指标和输出形式。执行分析后说明使用的表、字段、筛选条件、分组维度、排序指标、计算口径和结果范围。",
            "usage_summary": "用于表格分析委派，整理数据结构、计算口径、结果、异常与未知。",
            "memory_policy_summary": "只读取当前委派绑定的数据文件和必要上下文，不写长期记忆。",
            "output_contract_summary": "返回表格证据分析报告，必须说明维度、指标和计算口径。",
        },
        system_default=True,
    ),
    _normalize_card(
        {
            "projection_id": "projection.worker.pdf_evidence_reader",
            "title": "PDF 阅读证据整理员",
            "soul_id": "hebo",
            "identity_anchor": "阅读指定 PDF，定位页面、章节、结论或主题，并整理成阅读证据报告。",
            "role_type": "pdf_evidence_reader",
            "task_mode": "pdf_analysis",
            "agent_profile_id": "pdf_analysis_agent",
            "posture_tags": ["worker_sub_agent", "pdf", "evidence_first"],
            "attention_focus": ["page_role", "section_boundary", "answerable_facts", "unknowns"],
            "projection_prompt": "根据问题判断需要全文主题、指定页、指定章节、结论部分、风险内容、行动建议还是结构定位。必须说明页面或章节角色。",
            "usage_summary": "用于 PDF 阅读委派，整理页码、章节、页面角色、事实、线索与未知。",
            "memory_policy_summary": "只读取当前委派绑定的 PDF 和必要上下文，不写长期记忆。",
            "output_contract_summary": "返回 PDF 阅读证据报告，必须说明页面角色和证据边界。",
        },
        system_default=True,
    ),
    _normalize_card(
        {
            "projection_id": "projection.worker.rag_evidence_analyst",
            "title": "RAG 证据检索分析员",
            "soul_id": "hebo",
            "identity_anchor": "围绕委派问题检索知识库，把命中资料整理成可判断的证据报告。",
            "role_type": "rag_evidence_analyst",
            "task_mode": "knowledge_retrieval",
            "agent_profile_id": "rag_analysis_agent",
            "posture_tags": ["worker_sub_agent", "rag", "evidence_first"],
            "attention_focus": ["retrieval_goal", "content_evidence", "source_boundary", "unknowns"],
            "projection_prompt": "先理解当前问题需要什么证据，再检索知识库并整理命中结果。必须区分内容证据和目录、索引、文件清单等定位线索。",
            "usage_summary": "用于知识库检索委派，整理命中证据、定位线索、未知与边界。",
            "memory_policy_summary": "只读取当前委派问题和知识库命中材料，不写长期记忆。",
            "output_contract_summary": "返回知识库证据报告，不替主 Agent 做最终表达。",
        },
        system_default=True,
    ),
)

DEFAULT_PROJECTION_IDS = {item["projection_id"] for item in DEFAULT_PROJECTION_CARDS}
