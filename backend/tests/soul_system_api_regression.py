from __future__ import annotations

from pathlib import Path

from api.souls import (
    ACTIVE_SEED_PATH,
    AGENT_PROFILE_PATH,
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
    _write(tmp_path, CORE_PATH, "# Core\n\n通用准则")
    _write(tmp_path, AGENT_PROFILE_PATH, "# Agent\n\n长期偏好")

    catalog = build_soul_catalog(tmp_path)

    assert catalog["active_soul_key"] == "siyue"
    assert [item["path"] for item in catalog["injection_chain"]] == [
        ACTIVE_SEED_PATH,
        CORE_PATH,
        AGENT_PROFILE_PATH,
    ]
    assert {seed["key"] for seed in catalog["seeds"]} == set(SEED_PATHS)
    assert {profile["soul_id"] for profile in catalog["soul_profiles"]} == set(SEED_PATHS)
    assert all(str(seed["portrait_path"]).startswith("/souls/") for seed in catalog["seeds"])
    assert any(file["path"] == AGENT_PROFILE_PATH and file["model_visible"] for file in catalog["static_files"])
    assert "logs" not in catalog


def test_soul_projection_card_stores_static_binding_without_runtime_view(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["hebo"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n静态共同准则")
    _write(tmp_path, AGENT_PROFILE_PATH, "# Agent\n\n长期偏好")

    request = {
        "soul_id": "hebo",
        "role_type": "collect",
        "task_mode": "knowledge_lookup",
        "agent_profile_id": "knowledge_agent",
        "projection_name": "河伯 / RAG 收集",
        "task_contract_summary": "动态任务契约：只收集证据，不提交最终答案。",
        "style_content": "# 河伯风格\n\n## 表达\n\n- 先列证据，再下结论。",
    }
    store = upsert_projection_card(tmp_path, request=request, soul_name="河伯", selected=True)
    assert store["selected_projection_id"] == store["cards"][0]["projection_id"]
    assert store["cards"][0]["title"] == "河伯 / RAG 收集"
    assert store["cards"][0]["style_content"].startswith("# 河伯风格")
    assert "projection" not in store["cards"][0]
    assert "runtime_view" not in store["cards"][0]
