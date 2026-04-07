from __future__ import annotations

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime_encoding import (  # noqa: E402
    POWERSHELL_UTF8_BOOTSTRAP,
    build_utf8_env,
    build_windows_powershell_command,
    looks_like_mojibake,
    utf8_subprocess_text_kwargs,
)
from structured_memory.text_utils import repair_mojibake  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_build_utf8_env_sets_python_flags() -> None:
    env = build_utf8_env({"EXAMPLE_FLAG": "1"})
    _assert(env["EXAMPLE_FLAG"] == "1", "existing env vars should be preserved")
    _assert(env["PYTHONUTF8"] == "1", "PYTHONUTF8 should be forced to 1")
    _assert(env["PYTHONIOENCODING"] == "utf-8", "PYTHONIOENCODING should be forced to utf-8")


def test_powershell_bootstrap_forces_utf8() -> None:
    command = build_windows_powershell_command("Write-Output 'hello'")
    _assert(
        command[:5] == ["powershell", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass"],
        "PowerShell bootstrap prefix should stay stable",
    )
    _assert("OutputEncoding" in command[-1], "bootstrap should set PowerShell output encoding")
    _assert("chcp 65001" in command[-1], "bootstrap should force code page 65001")
    _assert(POWERSHELL_UTF8_BOOTSTRAP in command[-1], "bootstrap should be embedded in the final command")


def test_utf8_subprocess_text_kwargs_are_explicit() -> None:
    kwargs = utf8_subprocess_text_kwargs()
    _assert(kwargs["text"] is True, "subprocess wrapper should request text mode")
    _assert(kwargs["encoding"] == "utf-8", "subprocess wrapper should decode as utf-8")
    _assert(kwargs["errors"] == "replace", "subprocess wrapper should replace undecodable bytes instead of crashing")
    env = kwargs["env"]
    _assert(isinstance(env, dict), "subprocess wrapper should include an environment map")
    _assert(env["PYTHONUTF8"] == "1", "subprocess env should force Python UTF-8 mode")


def test_repair_mojibake_repairs_common_gbk_style_text() -> None:
    original = "\u9ec4\u91d1\u4ef7\u683c"
    garbled = original.encode("utf-8").decode("gbk")
    _assert(garbled != original, "test fixture should produce a garbled string")
    repaired = repair_mojibake(garbled)
    _assert(repaired == original, "repair_mojibake should recover common GBK-style mojibake")


def test_looks_like_mojibake_detects_common_markers() -> None:
    _assert(
        looks_like_mojibake("\u699b\u52ef\u567e\u6d60\u950b\u7278"),
        "known mojibake markers should be detected",
    )
    _assert(
        not looks_like_mojibake("\u6700\u65b0\u7ed3\u679c\u5df2\u66f4\u65b0"),
        "normal Chinese text should not be flagged as mojibake",
    )


def main() -> None:
    tests = [
        test_build_utf8_env_sets_python_flags,
        test_powershell_bootstrap_forces_utf8,
        test_utf8_subprocess_text_kwargs_are_explicit,
        test_repair_mojibake_repairs_common_gbk_style_text,
        test_looks_like_mojibake_detects_common_markers,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
