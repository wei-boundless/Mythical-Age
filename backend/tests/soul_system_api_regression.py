from __future__ import annotations

from pathlib import Path

from api.souls import (
    ACTIVE_SEED_PATH,
    CORE_PATH,
    SEED_PATHS,
    build_soul_catalog,
)
from agent_system.registry.agent_registry import AgentRegistry
from soul.projection_store import upsert_projection_card


def _write(base_dir: Path, relative_path: str, content: str) -> None:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_soul_catalog_exposes_injection_chain_and_seed_contracts(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["siyue"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n通用准则\n\n## 用户与项目偏好\n\n长期偏好固定到共同契约。")

    catalog = build_soul_catalog(tmp_path)

    assert catalog["active_soul_key"] == "siyue"
    assert [item["path"] for item in catalog["injection_chain"]] == [
        ACTIVE_SEED_PATH,
        CORE_PATH,
        "soul/common_contracts/catalog.json",
    ]
    assert {seed["key"] for seed in catalog["seeds"]} == set(SEED_PATHS)
    assert {profile["soul_id"] for profile in catalog["soul_profiles"]} == set(SEED_PATHS)
    assert all(str(seed["portrait_path"]).startswith("/souls/") for seed in catalog["seeds"])
    assert all(file["path"] != "soul/agent.md" for file in catalog["static_files"])
    assert all(item["path"] != "soul/agent.md" for item in catalog["injection_chain"])
    assert "logs" not in catalog


def test_soul_projection_card_stores_static_binding_without_runtime_view(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["hebo"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n静态共同准则")

    request = {
        "soul_id": "hebo",
        "identity_anchor": "你是证据优先的资料收束投影，不是灵魂本体。",
        "role_type": "collect",
        "task_mode": "knowledge_lookup",
        "agent_profile_id": "knowledge_agent",
        "projection_name": "河伯 / RAG 收集",
        "posture_tags": ["evidence_first", "quiet"],
        "expression_density": "concise",
        "attention_focus": ["source_trace", "answer_boundary"],
        "risk_notes": ["投影卡不承载运行时授权。"],
        "usage_summary": "证据收集姿态投影，供任务系统按需选择。",
    }
    store = upsert_projection_card(tmp_path, request=request, soul_name="河伯", selected=True)
    assert store["selected_projection_id"] == store["cards"][0]["projection_id"]
    assert store["cards"][0]["title"] == "河伯 / RAG 收集"
    assert store["cards"][0]["identity_anchor"] == "你是证据优先的资料收束投影，不是灵魂本体。"
    assert store["cards"][0]["static_projection_card"] is True
    assert store["cards"][0]["runtime_only_payload"] is True
    assert store["cards"][0]["posture_tags"] == ["evidence_first", "quiet"]
    assert store["cards"][0]["expression_density"] == "concise"
    assert store["cards"][0]["attention_focus"] == ["source_trace", "answer_boundary"]
    assert store["cards"][0]["risk_notes"] == ["投影卡不承载运行时授权。"]
    assert store["cards"][0]["usage_summary"].startswith("证据收集姿态投影")
    assert store["cards"][0]["runtime_preview"]["identity_anchor"] == "你是证据优先的资料收束投影，不是灵魂本体。"
    assert store["cards"][0]["runtime_preview"]["usage_summary"].startswith("证据收集姿态投影")
    assert "projection" not in store["cards"][0]
    assert "runtime_view" not in store["cards"][0]


def test_primary_projection_keeps_manual_edits_during_reconcile(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。\n\n## 工作职责\n\n- 默认职责")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["hebo"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n静态共同准则")

    request = {
        "projection_id": "hebo__primary",
        "soul_id": "hebo",
        "projection_name": "河伯 / 原始投影",
        "projection_nodes": [
            {"id": "identity", "type": "identity_anchor", "title": "身份锚点", "content": "你是运行中的河伯原始投影。"},
            {"id": "duty", "type": "template_section", "title": "工作职责", "content": "负责资料收束与主会话承接。"},
        ],
        "identity_anchor": "你是运行中的河伯原始投影。",
        "projection_prompt": "## 工作职责\n\n负责资料收束与主会话承接。",
    }
    upsert_projection_card(tmp_path, request=request, soul_name="河伯", selected=True)

    reconciled = build_soul_catalog(tmp_path)
    cards = reconciled["projection_catalog"]["cards"] if "projection_catalog" in reconciled else None
    assert cards is None

    from soul.projection_store import list_projection_cards

    projection_catalog = list_projection_cards(tmp_path, soul_profiles=reconciled["soul_profiles"], active_soul_id="hebo")
    primary = next(card for card in projection_catalog["cards"] if card["projection_id"] == "hebo__primary")
    assert primary["identity_anchor"] == "你是运行中的河伯原始投影。"
    assert any(node["content"] == "负责资料收束与主会话承接。" for node in primary["projection_nodes"])


def test_main_agent_defaults_follow_active_primary_projection(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["siyue"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n静态共同准则")

    registry = AgentRegistry(tmp_path)
    main_agent = registry.get_agent("agent:0")
    assert main_agent is not None
    assert main_agent.default_projection_id == "siyue__primary"
    assert main_agent.default_soul_id == "siyue"
