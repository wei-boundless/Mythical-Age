from __future__ import annotations

from pathlib import Path

from api.souls import (
    ACTIVE_SEED_PATH,
    CORE_PATH,
    SEED_PATHS,
    build_soul_catalog,
)
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
    assert store["cards"][0]["static_projection_card"] is True
    assert store["cards"][0]["runtime_only_payload"] is True
    assert store["cards"][0]["posture_tags"] == ["evidence_first", "quiet"]
    assert store["cards"][0]["expression_density"] == "concise"
    assert store["cards"][0]["attention_focus"] == ["source_trace", "answer_boundary"]
    assert store["cards"][0]["risk_notes"] == ["投影卡不承载运行时授权。"]
    assert store["cards"][0]["usage_summary"].startswith("证据收集姿态投影")
    assert store["cards"][0]["runtime_preview"]["usage_summary"].startswith("证据收集姿态投影")
    assert "projection" not in store["cards"][0]
    assert "runtime_view" not in store["cards"][0]
