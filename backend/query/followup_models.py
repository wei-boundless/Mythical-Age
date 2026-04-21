from __future__ import annotations

from pydantic import BaseModel, Field


class FollowupResolution(BaseModel):
    mode: str = "none"
    task_id: str = ""
    task_ids: list[str] = Field(default_factory=list)
    binding_key: str = ""
    confidence: float = 0.0
    reason: str = ""
    source_query: str = ""
