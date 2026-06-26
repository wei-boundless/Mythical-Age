from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ManagedFileTarget(BaseModel):
    repository_id: str = Field(..., min_length=1, max_length=240)
    repository_kind: str = Field(default="", max_length=120)
    scope_kind: str = Field(default="", max_length=120)
    scope_id: str = Field(default="", max_length=240)
    logical_path: str = Field(..., min_length=1, max_length=2000)
    workspace_root: str = Field(default="", max_length=4000)
    profile_id: str = Field(default="", max_length=240)


class ManagedFileReadRequest(BaseModel):
    target: ManagedFileTarget
    session_id: str = Field(default="", max_length=240)


class ManagedFileSelectOpenRequest(BaseModel):
    session_id: str = Field(default="", max_length=240)


class ManagedFileWriteRequest(BaseModel):
    target: ManagedFileTarget
    content: str
    expected_sha256: str = Field(default="", max_length=160)
    source: str = Field(default="agent_ui", max_length=80)
    reason: str = Field(default="user_save", max_length=160)
    force: bool = False
    session_id: str = Field(default="", max_length=240)


class ManagedFileEditRequest(BaseModel):
    target: ManagedFileTarget
    old_text: str = ""
    new_text: str = ""
    expected_sha256: str = Field(default="", max_length=160)
    source: str = Field(default="agent_ui", max_length=80)
    reason: str = Field(default="user_edit", max_length=160)
    force: bool = False
    session_id: str = Field(default="", max_length=240)


class ManagedFileOpenInVSCodeRequest(BaseModel):
    target: ManagedFileTarget
    session_id: str = Field(default="", max_length=240)


class ExternalReadScopeRequest(BaseModel):
    source_path: str = Field(..., min_length=1, max_length=4000)
    scope_id: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=240)
    enabled: bool = True


class VSCodeCommandResultRequest(BaseModel):
    status: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=2000)
    dirty: bool = False
    document_sha256: str = Field(default="", max_length=160)
    applied_at: str = Field(default="", max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)
