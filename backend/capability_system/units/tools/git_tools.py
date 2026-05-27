from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class GitStatusInput(BaseModel):
    short: bool = Field(default=True, description="Use porcelain short status output")


class GitDiffInput(BaseModel):
    path: str = Field(default="", description="Optional pathspec relative to the repository root")
    staged: bool = Field(default=False, description="Show staged diff")
    max_chars: int = Field(default=12000, ge=1000, le=50000, description="Maximum output characters")


class GitLogInput(BaseModel):
    max_count: int = Field(default=10, ge=1, le=50, description="Number of commits to show")


class GitShowInput(BaseModel):
    revision: str = Field(default="HEAD", description="Revision to show, such as HEAD or a commit SHA")
    max_chars: int = Field(default=12000, ge=1000, le=50000, description="Maximum output characters")


class _GitTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()

    def _repo_root(self) -> Path:
        candidate = self._root_dir.parent.resolve() if self._root_dir.name == "backend" else self._root_dir
        return candidate

    def _run_git(self, args: list[str], *, max_chars: int = 12000) -> str:
        command = ["git", *args]
        try:
            completed = subprocess.run(
                command,
                cwd=self._repo_root(),
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except Exception as exc:
            return f"Git failed: {exc}"
        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        if completed.returncode != 0:
            return f"Git failed ({completed.returncode}): {error or output}"
        return (output or "(empty)")[:max_chars]


class GitStatusTool(_GitTool):
    name: str = "git_status"
    description: str = "Show read-only git working tree status."
    args_schema: Type[BaseModel] = GitStatusInput

    def _run(self, short: bool = True, run_manager: CallbackManagerForToolRun | None = None) -> str:
        return self._run_git(["status", "--short" if short else "--branch"])

    async def _arun(self, short: bool = True, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, short, None)


class GitDiffTool(_GitTool):
    name: str = "git_diff"
    description: str = "Show read-only git diff for the working tree or staged changes."
    args_schema: Type[BaseModel] = GitDiffInput

    def _run(self, path: str = "", staged: bool = False, max_chars: int = 12000, run_manager: CallbackManagerForToolRun | None = None) -> str:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.extend(["--", str(path).strip()])
        return self._run_git(args, max_chars=max_chars)

    async def _arun(self, path: str = "", staged: bool = False, max_chars: int = 12000, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, path, staged, max_chars, None)


class GitLogTool(_GitTool):
    name: str = "git_log"
    description: str = "Show read-only git commit log."
    args_schema: Type[BaseModel] = GitLogInput

    def _run(self, max_count: int = 10, run_manager: CallbackManagerForToolRun | None = None) -> str:
        count = max(1, min(int(max_count or 10), 50))
        return self._run_git(["log", f"--max-count={count}", "--oneline", "--decorate"])

    async def _arun(self, max_count: int = 10, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, max_count, None)


class GitShowTool(_GitTool):
    name: str = "git_show"
    description: str = "Show read-only git object or commit details."
    args_schema: Type[BaseModel] = GitShowInput

    def _run(self, revision: str = "HEAD", max_chars: int = 12000, run_manager: CallbackManagerForToolRun | None = None) -> str:
        rev = str(revision or "HEAD").strip()
        if not rev or rev.startswith("-"):
            return "Git failed: invalid revision."
        return self._run_git(["show", "--stat", "--patch", rev], max_chars=max_chars)

    async def _arun(self, revision: str = "HEAD", max_chars: int = 12000, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, revision, max_chars, None)


