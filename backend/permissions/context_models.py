from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PermissionContext:
    context_id: str
    task_run_id: str = ""
    agent_run_id: str = ""
    environment_id: str = ""
    tool_capability_table_id: str = ""
    file_access_table_ids: tuple[str, ...] = ()
    session_approval_refs: tuple[str, ...] = ()
    risk_policy_ref: str = ""
    execution_policy_ref: str = ""
    permission_mode: str = "default"
    approval_state: dict[str, Any] = field(default_factory=dict)
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    file_management_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "permissions.permission_context"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["file_access_table_ids"] = list(self.file_access_table_ids)
        payload["session_approval_refs"] = list(self.session_approval_refs)
        payload["approval_state"] = dict(self.approval_state)
        payload["sandbox_policy"] = dict(self.sandbox_policy)
        payload["file_management_policy"] = dict(self.file_management_policy)
        return payload


