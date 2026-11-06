from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from pydantic import BaseModel, ConfigDict, Field


class SubagentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["spawn", "send", "wait", "list", "close"] = Field(description="Subagent lifecycle action.")
    target_agent_id: str = Field(default="", description="Canonical subagent id for spawn.")
    goal: str = Field(default="", description="Concrete goal for spawn.")
    instructions: str = Field(default="", description="Complete execution brief for spawn.")
    context_refs: list[str] = Field(default_factory=list, description="Explicit refs the child agent may use.")
    expected_outputs: list[str] = Field(default_factory=list, description="Expected result kinds or evidence.")
    subagent_run_ref: str = Field(default="", description="Subagent run ref for send/wait/close.")
    message: str = Field(default="", description="Message for send.")
    since_message_ref: str = Field(default="", description="Mailbox cursor for wait.")
    status: str = Field(default="", description="Optional status filter for list.")
    reason: str = Field(default="", description="Reason for close.")


class SubagentTool(BaseTool):
    name: str = "subagent"
    description: str = (
        "Request subagent lifecycle actions through the runtime control plane. "
        "Spawn requires a complete brief; wait/list only observe returned child state; never invent child findings."
    )
    args_schema: type[BaseModel] = SubagentInput

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        _ = root_dir

    def _run(self, action: str, run_manager: CallbackManagerForToolRun | None = None, **kwargs: Any) -> str:
        _ = action, run_manager, kwargs
        raise RuntimeError("subagent_lifecycle_requires_control_plane")

    async def _arun(self, action: str, run_manager: AsyncCallbackManagerForToolRun | None = None, **kwargs: Any) -> str:
        _ = action, run_manager, kwargs
        raise RuntimeError("subagent_lifecycle_requires_control_plane")
