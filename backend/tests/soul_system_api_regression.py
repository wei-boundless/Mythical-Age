from __future__ import annotations

from pathlib import Path

from api.souls import (
    ACTIVE_SEED_PATH,
    CORE_PATH,
    SEED_PATHS,
    build_soul_catalog,
)
from agent_system.registry.agent_registry import AgentRegistry


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


def test_soul_role_prompt_is_role_only_without_runtime_duties(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["hebo"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n静态共同准则")

    role_prompt = build_soul_catalog(tmp_path)["resource_catalog"]["cards"][1]
    assert "default_projection_id" not in role_prompt

    from soul import SoulFacade

    prompt = SoulFacade(tmp_path).build_role_prompt(soul_id="hebo")
    assert prompt["resource_type"] == "role_prompt"
    assert prompt["role_prompt_id"] == "soul.role_prompt.hebo"
    assert "不授予任何工作职责" in prompt["content"]
    assert "工具权限" in prompt["content"]


def test_main_agent_defaults_follow_active_soul_without_projection(tmp_path: Path) -> None:
    for key, path in SEED_PATHS.items():
        name = {"goumang": "句芒", "hebo": "河伯", "siyue": "四岳", "zhurong": "祝融", "xuannv": "玄女"}[key]
        _write(tmp_path, path, f"# {name}\n\n## 身份锚点\n\n- 你是“{name}”。")
    _write(tmp_path, ACTIVE_SEED_PATH, (tmp_path / SEED_PATHS["siyue"]).read_text(encoding="utf-8"))
    _write(tmp_path, CORE_PATH, "# Core\n\n静态共同准则")

    registry = AgentRegistry(tmp_path)
    main_agent = registry.get_agent("agent:0")
    assert main_agent is not None
    assert main_agent.default_soul_id == "siyue"
    assert "default_projection_id" not in main_agent.to_dict()
