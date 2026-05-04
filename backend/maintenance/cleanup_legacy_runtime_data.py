from __future__ import annotations

from config import get_settings
from maintenance.legacy_cleanup import cleanup_legacy_runtime_data, legacy_runtime_data_paths


def main() -> int:
    settings = get_settings()
    candidates = legacy_runtime_data_paths(settings.backend_dir)
    removed = cleanup_legacy_runtime_data(settings.backend_dir)

    print("legacy cleanup candidates:")
    for path in candidates:
        print(f"- {path}")

    print("removed:")
    if not removed:
        print("- <none>")
        return 0

    for path in removed:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
