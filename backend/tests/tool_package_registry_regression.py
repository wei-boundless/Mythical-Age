from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from permissions.operation_packages import (
    ToolPackageSelection,
    default_tool_packages,
    resolve_tool_package_operations,
)
from permissions.operations import default_operation_descriptors


def test_tool_package_registry_resolves_operation_packages() -> None:
    packages = {item.package_id: item for item in default_tool_packages()}
    operation_ids = {item.operation_id for item in default_operation_descriptors()}
    for package in packages.values():
        missing = [item for item in package.operation_ids if item not in operation_ids]
        assert not missing, f"{package.package_id} contains unknown operations: {missing}"

    assert "pkg.development.python" in packages
    assert "pkg.git.read" in packages
    assert "pkg.git.write" in packages
    assert "pkg.git.remote" in packages
    assert "pkg.mcp.local" in packages
    assert packages["pkg.development.python"].category == "开发工具"
    assert packages["pkg.development.python"].default_enabled is True
    assert packages["pkg.development.python"].metadata["parser_authority"] == "python.stdlib.ast"
    assert "op.codebase_search" in packages["pkg.development.python"].operation_ids
    assert "op.python_code_outline" in packages["pkg.development.python"].operation_ids
    assert "op.python_symbol_search" in packages["pkg.development.python"].operation_ids
    assert "op.python_parse_check" in packages["pkg.development.python"].operation_ids
    assert "op.git_diff" in packages["pkg.development.python"].operation_ids
    assert "op.read_file" not in packages["pkg.development.python"].operation_ids
    assert "op.write_file" not in packages["pkg.development.python"].operation_ids
    assert "op.edit_file" not in packages["pkg.development.python"].operation_ids
    assert "op.shell" not in packages["pkg.development.python"].operation_ids
    assert packages["pkg.git.read"].category == "版本控制"
    assert packages["pkg.git.remote"].default_enabled is False
    assert "op.mcp_image_ocr" in packages["pkg.mcp.local"].operation_ids
    assert "op.mcp_image_ocr" not in packages["pkg.multimodal"].operation_ids

    resolved = resolve_tool_package_operations(
        (
            ToolPackageSelection(package_id="pkg.development.python"),
            ToolPackageSelection(package_id="pkg.git.read"),
            ToolPackageSelection(package_id="pkg.git.write", exclude_operations=("op.git_restore",)),
        ),
        extra_allowed_operations=("op.read_file",),
        blocked_operations=("op.git_push",),
    )
    assert "op.python_code_outline" in resolved
    assert "op.python_symbol_search" in resolved
    assert "op.python_parse_check" in resolved
    assert "op.codebase_search" in resolved
    assert "op.git_status" in resolved
    assert "op.git_commit" in resolved
    assert "op.git_restore" not in resolved
    assert "op.git_push" not in resolved
    assert "op.read_file" in resolved

