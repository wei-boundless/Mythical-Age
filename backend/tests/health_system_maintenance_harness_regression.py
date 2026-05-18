from __future__ import annotations

from pathlib import Path

from health_system.maintenance.harness.run import main as harness_main


def test_long_profile_harness_resolves_backend_root(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run(cmd, cwd=None, check=False):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["check"] = check
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setattr("sys.argv", ["run.py", "--profile", "long"])

    assert harness_main() == 0
    assert str(captured["cwd"]).endswith("backend")
    assert any("backend/tests/system_eval/long_runner.py" in str(item).replace("\\", "/") for item in captured["cmd"])
