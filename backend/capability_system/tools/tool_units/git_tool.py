from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.git_tools import (
    GitBranchCreateTool,
    GitBranchListTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitPushTool,
    GitRestoreTool,
    GitShowTool,
    GitStageTool,
    GitStatusTool,
    GitUnstageTool,
)
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


GitAction = Literal[
    "status",
    "diff",
    "log",
    "show",
    "branch_list",
    "branch_create",
    "stage",
    "unstage",
    "commit",
    "restore",
    "push",
]


class GitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: GitAction = Field(description="Git action to execute.")
    short: bool = Field(default=True, description="For status: use short porcelain output.")
    path: str = Field(default="", description="Optional pathspec for diff.")
    staged: bool = Field(default=False, description="For diff/restore: operate on staged content.")
    max_chars: int = Field(default=12000, ge=1000, le=50000, description="Maximum output characters for diff/show.")
    max_count: int = Field(default=10, ge=1, le=50, description="For log: number of commits to show.")
    revision: str = Field(default="HEAD", description="For show: revision to inspect.")
    all_branches: bool = Field(default=False, description="For branch_list: include remote branches.")
    branch_name: str = Field(default="", description="For branch_create: new branch name.")
    start_point: str = Field(default="HEAD", description="For branch_create: start point revision.")
    paths: list[str] = Field(default_factory=list, description="For stage/unstage/restore: explicit workspace-relative paths.")
    message: str = Field(default="", description="For commit: commit message.")
    remote: str = Field(default="origin", description="For push: remote name.")
    branch: str = Field(default="", description="For push: branch name; default is current branch.")


class GitTool(BaseTool):
    name: str = "git"
    description: str = (
        "Run precise git read, write, and remote actions through one action tool. "
        "Read actions inspect repository state; write actions require explicit paths or messages; push is remote."
    )
    args_schema: type[BaseModel] = GitInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = Path(root_dir).resolve()

    def _run(self, action: str, run_manager: CallbackManagerForToolRun | None = None, **kwargs: Any) -> str:
        _ = run_manager
        normalized = str(action or "").strip()
        tool = self._tool_for_action(normalized)
        if tool is None:
            return f"Git failed: unsupported action {action!r}."
        return str(tool.invoke(_payload_for_action(normalized, kwargs)))

    async def _arun(self, action: str, run_manager: AsyncCallbackManagerForToolRun | None = None, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, action, None, **kwargs)

    def _tool_for_action(self, action: str) -> BaseTool | None:
        mapping = {
            "status": GitStatusTool,
            "diff": GitDiffTool,
            "log": GitLogTool,
            "show": GitShowTool,
            "branch_list": GitBranchListTool,
            "branch_create": GitBranchCreateTool,
            "stage": GitStageTool,
            "unstage": GitUnstageTool,
            "commit": GitCommitTool,
            "restore": GitRestoreTool,
            "push": GitPushTool,
        }
        tool_cls = mapping.get(action)
        return tool_cls(root_dir=self._root_dir) if tool_cls is not None else None


def _payload_for_action(action: str, values: dict[str, Any]) -> dict[str, Any]:
    if action == "status":
        return {"short": bool(values.get("short", True))}
    if action == "diff":
        return {"path": str(values.get("path") or ""), "staged": bool(values.get("staged") is True), "max_chars": values.get("max_chars", 12000)}
    if action == "log":
        return {"max_count": values.get("max_count", 10)}
    if action == "show":
        return {"revision": str(values.get("revision") or "HEAD"), "max_chars": values.get("max_chars", 12000)}
    if action == "branch_list":
        return {"all_branches": bool(values.get("all_branches") is True)}
    if action == "branch_create":
        return {"branch_name": str(values.get("branch_name") or ""), "start_point": str(values.get("start_point") or "HEAD")}
    if action in {"stage", "unstage"}:
        return {"paths": list(values.get("paths") or [])}
    if action == "commit":
        return {"message": str(values.get("message") or "")}
    if action == "restore":
        return {"paths": list(values.get("paths") or []), "staged": bool(values.get("staged") is True)}
    if action == "push":
        return {"remote": str(values.get("remote") or "origin"), "branch": str(values.get("branch") or "")}
    return {}
