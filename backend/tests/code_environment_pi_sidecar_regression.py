from __future__ import annotations

import json

import pytest

from code_environment import pi_environment


def test_disabled_pi_sidecar_does_not_require_pi_cli_build(monkeypatch: pytest.MonkeyPatch, tmp_path):
    missing_pi_root = tmp_path / "missing-pi"
    monkeypatch.setattr(
        pi_environment.runtime_config,
        "get_code_environment_config",
        lambda: {
            "enabled": True,
            "workspace_root_policy": "project_root",
            "pi_sidecar": {
                "enabled": False,
                "mode": "diagnostic_only",
                "pi_source_root": str(missing_pi_root),
                "pi_cli_path": "",
            },
        },
    )

    def command_version_should_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("disabled Pi sidecar should not probe node/npm")

    monkeypatch.setattr(pi_environment, "_command_version", command_version_should_not_run)

    status = pi_environment.build_code_environment_status(project_root=tmp_path)

    codes = [item.code for item in status.pi.diagnostics]
    assert status.pi.mode == "web_only"
    assert status.pi.available is False
    assert codes == ["pi_sidecar_optional"]
    assert "pi_cli_not_built" not in codes
    assert "pi_source_root_missing" not in codes


def test_enabled_pi_sidecar_reports_missing_cli_build(monkeypatch: pytest.MonkeyPatch, tmp_path):
    pi_root = tmp_path / "pi-main"
    coding_agent_root = pi_root / "packages" / "coding-agent"
    rpc_source = coding_agent_root / "src" / "modes" / "rpc" / "rpc-mode.ts"
    rpc_source.parent.mkdir(parents=True)
    (pi_root / "package.json").write_text(json.dumps({"name": "pi"}), encoding="utf-8")
    coding_agent_root.mkdir(parents=True, exist_ok=True)
    (coding_agent_root / "package.json").write_text(json.dumps({"name": "coding-agent"}), encoding="utf-8")
    rpc_source.write_text("export {};\n", encoding="utf-8")

    monkeypatch.setattr(
        pi_environment.runtime_config,
        "get_code_environment_config",
        lambda: {
            "enabled": True,
            "workspace_root_policy": "project_root",
            "pi_sidecar": {
                "enabled": True,
                "mode": "diagnostic_only",
                "pi_source_root": str(pi_root),
                "pi_cli_path": "",
            },
        },
    )
    monkeypatch.setattr(pi_environment, "_command_version", lambda command, diagnostics, code: "v-test")

    status = pi_environment.build_code_environment_status(project_root=tmp_path)

    codes = [item.code for item in status.pi.diagnostics]
    assert status.pi.available is True
    assert status.pi.mode == "web_only"
    assert status.pi.cli_built is False
    assert "pi_cli_not_built" in codes
