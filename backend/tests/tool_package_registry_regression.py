from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tool_packages import (
    ToolPackageSelection,
    default_tool_packages,
    resolve_tool_package_operations,
)


def main() -> None:
    packages = {item.package_id: item for item in default_tool_packages()}
    assert "pkg.git.read" in packages
    assert "pkg.git.write" in packages
    assert "pkg.git.remote" in packages
    assert packages["pkg.git.read"].category == "版本控制"
    assert packages["pkg.git.remote"].default_enabled is False

    resolved = resolve_tool_package_operations(
        (
            ToolPackageSelection(package_id="pkg.git.read"),
            ToolPackageSelection(package_id="pkg.git.write", exclude_operations=("op.git_restore",)),
        ),
        extra_allowed_operations=("op.read_file",),
        blocked_operations=("op.git_push",),
    )
    assert "op.git_status" in resolved
    assert "op.git_commit" in resolved
    assert "op.git_restore" not in resolved
    assert "op.git_push" not in resolved
    assert "op.read_file" in resolved

    print("ALL PASSED (tool package registry)")


if __name__ == "__main__":
    main()
