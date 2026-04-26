from __future__ import annotations

from pathlib import Path

from api.souls import (
    ACTIVE_SEED_PATH,
    AGENT_PROFILE_PATH,
    CORE_PATH,
    SEED_PATHS,
    build_soul_catalog,
)


def _write(base_dir: Path, relative_path: str, content: str) -> None:
    path = base_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_soul_catalog_exposes_injection_chain_and_seed_contracts(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
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
    assert all(str(seed["portrait_path"]).startswith("/souls/") for seed in catalog["seeds"])
    assert any(file["path"] == AGENT_PROFILE_PATH and file["model_visible"] for file in catalog["static_files"])
    assert "logs" not in catalog
