from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field


class SpawnSubagentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent_id: str = Field(description="Visible subagent id to start.")
    goal: str = Field(description="Concrete goal for the subagent.")
    instructions: str = Field(default="", description="Execution instructions, boundaries, output expectations, and failure handling.")
    context_refs: list[str] = Field(default_factory=list, description="Explicit context or artifact refs the subagent may use.")
    expected_outputs: list[str] = Field(default_factory=list, description="Expected result kinds, evidence, verdicts, or artifact refs.")


class SubagentMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subagent_run_ref: str = Field(description="Subagent run ref returned by spawn_subagent.")
    message: str = Field(description="Message or additional instruction for the subagent.")
    context_refs: list[str] = Field(default_factory=list, description="Additional context refs.")


class WaitSubagentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subagent_run_ref: str = Field(description="Subagent run ref returned by spawn_subagent.")
    since_message_ref: str = Field(default="", description="Only return messages after this mailbox ref when provided.")


class ListSubagentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="", description="Optional status filter: pending, running, completed, failed, or killed.")


class CloseSubagentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subagent_run_ref: str = Field(description="Subagent run ref returned by spawn_subagent.")
    reason: str = Field(default="", description="Why the parent is closing the child run.")


class _SubagentLifecycleTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        _ = root_dir

    def _run(self, run_manager: CallbackManagerForToolRun | None = None, **kwargs: Any) -> str:
        _ = run_manager, kwargs
        return "subagent lifecycle tools are executed by the harness loop"

    async def _arun(self, run_manager: AsyncCallbackManagerForToolRun | None = None, **kwargs: Any) -> str:
        _ = run_manager, kwargs
        return "subagent lifecycle tools are executed by the harness loop"


class SpawnSubagentTool(_SubagentLifecycleTool):
    name: str = "spawn_subagent"
    description: str = (
        "Start a real child agent run when the current task benefits from a specialist worker. "
        "Provide a concrete goal, clear instructions, explicit context refs, expected outputs, and boundaries. "
        "The tool returns a subagent_run_ref; use wait_subagent or list_subagents to observe progress."
    )
    args_schema: type[BaseModel] = SpawnSubagentInput


class SendSubagentMessageTool(_SubagentLifecycleTool):
    name: str = "send_subagent_message"
    description: str = "Send a follow-up instruction or context reference to an existing child agent run."
    args_schema: type[BaseModel] = SubagentMessageInput


class WaitSubagentTool(_SubagentLifecycleTool):
    name: str = "wait_subagent"
    description: str = "Check a child agent mailbox once and return new status/messages/result refs without blocking the main loop."
    args_schema: type[BaseModel] = WaitSubagentInput


class ListSubagentsTool(_SubagentLifecycleTool):
    name: str = "list_subagents"
    description: str = "List child agent runs owned by the current task and parent agent."
    args_schema: type[BaseModel] = ListSubagentsInput


class CloseSubagentTool(_SubagentLifecycleTool):
    name: str = "close_subagent"
    description: str = "Close or kill a child agent run that is no longer needed or should stop."
    args_schema: type[BaseModel] = CloseSubagentInput

