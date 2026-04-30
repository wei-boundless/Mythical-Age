from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.regression_gate import build_profile, detect_runner


def test_regression_gate_chain_profile_covers_runtime_loop_basics() -> None:
    profile = build_profile("chain")
    paths = {target.path for target in profile}
    assert "tests/test_system_runtime_loop_regression.py" in paths
    assert "tests/test_system_case_registry_regression.py" in paths
    assert "tests/test_system_agent_regression.py" in paths
    assert "tests/query_runtime_task_operation_preview_regression.py" in paths


def test_regression_gate_detects_pytest_and_script_styles(tmp_path: Path) -> None:
    pytest_style = tmp_path / "pytest_case.py"
    pytest_style.write_text("def test_sample():\n    assert True\n", encoding="utf-8")

    script_style = tmp_path / "script_case.py"
    script_style.write_text(
        "def main():\n    print('ok')\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )

    assert detect_runner(pytest_style) == "pytest"
    assert detect_runner(script_style) == "python"
