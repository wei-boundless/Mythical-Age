from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolUseContext:
    workspace_root: Path
    sandbox_root: Path | None = None
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    material_mounts: tuple[dict[str, Any], ...] = ()
    artifact_root: str = ""
    approval_policy: str = ""
    permission_mode: str = ""
    environment_snapshot: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workspace_root"] = str(self.workspace_root)
        payload["sandbox_root"] = str(self.sandbox_root) if self.sandbox_root is not None else ""
        payload["material_mounts"] = [dict(item) for item in self.material_mounts]
        payload["environment_snapshot"] = dict(self.environment_snapshot)
        payload["execution_receipt"] = dict(self.execution_receipt)
        return payload
