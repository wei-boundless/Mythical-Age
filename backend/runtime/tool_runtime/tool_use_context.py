from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolUseContext:
    workspace_root: Path
    sandbox_root: Path | None = None
    runtime_base_dir: str = ""
    tool_invocation_id: str = ""
    caller_kind: str = ""
    caller_ref: str = ""
    turn_id: str = ""
    idempotency_key: str = ""
    task_run_id: str = ""
    session_id: str = ""
    agent_run_id: str = ""
    run_cell_id: str = ""
    tool_call_id: str = ""
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    material_mounts: tuple[dict[str, Any], ...] = ()
    artifact_root: str = ""
    approval_policy: str = ""
    approval_fingerprint: str = ""
    permission_mode: str = ""
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    file_management_policy: dict[str, Any] = field(default_factory=dict)
    file_evidence_scope: dict[str, Any] = field(default_factory=dict)
    environment_snapshot: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    runtime_assembly: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workspace_root"] = str(self.workspace_root)
        payload["sandbox_root"] = str(self.sandbox_root) if self.sandbox_root is not None else ""
        payload["runtime_base_dir"] = str(self.runtime_base_dir or "")
        payload["material_mounts"] = [dict(item) for item in self.material_mounts]
        payload["sandbox_policy"] = dict(self.sandbox_policy)
        payload["file_management_policy"] = dict(self.file_management_policy)
        payload["file_evidence_scope"] = dict(self.file_evidence_scope)
        payload["environment_snapshot"] = dict(self.environment_snapshot)
        payload["execution_receipt"] = dict(self.execution_receipt)
        payload["runtime_assembly"] = dict(self.runtime_assembly)
        return payload

