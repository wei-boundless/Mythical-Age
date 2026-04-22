from __future__ import annotations

from pydantic import BaseModel, Field


class AnswerSegment(BaseModel):
    index: int
    task_id: str = ""
    title: str
    body: str
    response_style: str = ""
    answer_source: str = ""
    answer_ref: str = ""


class StyleConstraints(BaseModel):
    dedupe: bool = False
    append_mode: str = ""
    default_style: str = ""


class AnswerAssemblyPlan(BaseModel):
    segments: list[AnswerSegment] = Field(default_factory=list)
    style_constraints: StyleConstraints = Field(default_factory=StyleConstraints)
    dedupe_targets: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
