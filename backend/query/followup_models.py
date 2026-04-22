from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class FollowupResolution(BaseModel):
    mode: str = "none"
    target_kind: str = "none"
    resolved_target_kind: str = ""
    task_id: str = ""
    task_ids: list[str] = Field(default_factory=list)
    resolved_task_id: str = ""
    resolved_task_ids: list[str] = Field(default_factory=list)
    resolved_task_kind: str = ""
    binding_key: str = ""
    binding_kind: str = ""
    binding_identity: str = ""
    binding_owner_task_id: str = ""
    resolved_binding_ref: str = ""
    resolved_binding_kind: str = ""
    resolved_binding_identity: str = ""
    resolved_binding_owner_task_id: str = ""
    resolution_source: str = "none"
    confidence: float = 0.0
    reason: str = ""
    source_query: str = ""
    requires_clarification: bool = False
    clarification_prompt: str = ""

    @model_validator(mode="after")
    def _sync_compatibility_fields(self) -> "FollowupResolution":
        if not self.resolved_target_kind:
            self.resolved_target_kind = self.target_kind
        if not self.target_kind:
            self.target_kind = self.resolved_target_kind

        if not self.resolved_task_id:
            self.resolved_task_id = self.task_id
        if not self.task_id:
            self.task_id = self.resolved_task_id

        if not self.resolved_task_ids:
            self.resolved_task_ids = list(self.task_ids)
        if not self.task_ids:
            self.task_ids = list(self.resolved_task_ids)

        if not self.resolved_binding_kind:
            self.resolved_binding_kind = self.binding_kind or self.binding_key
        if not self.binding_kind:
            self.binding_kind = self.resolved_binding_kind
        if not self.binding_key:
            self.binding_key = self.resolved_binding_kind

        if not self.resolved_binding_identity:
            self.resolved_binding_identity = self.binding_identity
        if not self.binding_identity:
            self.binding_identity = self.resolved_binding_identity

        if not self.resolved_binding_ref:
            self.resolved_binding_ref = self.resolved_binding_identity

        if not self.resolved_binding_owner_task_id:
            self.resolved_binding_owner_task_id = self.binding_owner_task_id
        if not self.binding_owner_task_id:
            self.binding_owner_task_id = self.resolved_binding_owner_task_id

        return self
