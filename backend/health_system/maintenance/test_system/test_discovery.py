from __future__ import annotations

from pathlib import Path


TEST_FILE_PATTERNS: tuple[str, ...] = (
    "*_regression.py",
    "*_eval.py",
    "*_experiment.py",
    "*_smoke.py",
    "*_test.py",
    "test_*.py",
)


def discover_test_files(tests_root: Path) -> list[str]:
    backend_root = tests_root.parent
    if not tests_root.exists():
        return []

    result: list[str] = []
    for pattern in TEST_FILE_PATTERNS:
        for path in tests_root.rglob(pattern):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                result.append(path.relative_to(backend_root).as_posix())
            except ValueError:
                continue
    return sorted(set(result))
