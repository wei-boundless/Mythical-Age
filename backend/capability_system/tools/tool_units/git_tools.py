from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Type

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
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


class GitBranchListInput(BaseModel):
    all_branches: bool = Field(default=False, description="Include remote branches")


class GitBranchCreateInput(BaseModel):
    branch_name: str = Field(..., min_length=1, max_length=120, description="New branch name")
    start_point: str = Field(default="HEAD", max_length=120, description="Start point revision")


class GitStageInput(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=100, description="Workspace-relative paths to stage")


class GitUnstageInput(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=100, description="Workspace-relative paths to unstage")


class GitCommitInput(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="Commit message")


class GitRestoreInput(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=100, description="Workspace-relative paths to restore")
    staged: bool = Field(default=False, description="Restore staged version instead of working tree")


class GitPushInput(BaseModel):
    remote: str = Field(default="origin", max_length=80, description="Remote name")
    branch: str = Field(default="", max_length=120, description="Branch name; defaults to current branch")


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

    def _validate_paths(self, paths: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in paths:
            value = str(raw or "").strip().replace("\\", "/")
            if not value:
                continue
            if value in {".", "./", "*", ":/"} or value.startswith("-"):
                raise ValueError(f"unsafe git pathspec: {value}")
            candidate = Path(value)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"git path escapes workspace: {value}")
            if value not in seen:
                seen.add(value)
                cleaned.append(value)
        if not cleaned:
            raise ValueError("at least one explicit workspace-relative path is required")
        return cleaned

    def _validate_ref(self, value: str, *, field_name: str) -> str:
        ref = str(value or "").strip()
        if not ref or ref.startswith("-") or any(item in ref for item in (";", "&", "|", "`", "\n", "\r")):
            raise ValueError(f"invalid git {field_name}")
        return ref


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


class GitBranchListTool(_GitTool):
    name: str = "git_branch_list"
    description: str = "List local git branches, optionally including remote branches."
    args_schema: Type[BaseModel] = GitBranchListInput

    def _run(self, all_branches: bool = False, run_manager: CallbackManagerForToolRun | None = None) -> str:
        args = ["branch", "--list"]
        if all_branches:
            args.insert(1, "--all")
        return self._run_git(args, max_chars=20000)

    async def _arun(self, all_branches: bool = False, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, all_branches, None)


class GitBranchCreateTool(_GitTool):
    name: str = "git_branch_create"
    description: str = "Create a git branch at a validated start point. This does not switch branches."
    args_schema: Type[BaseModel] = GitBranchCreateInput

    def _run(self, branch_name: str, start_point: str = "HEAD", run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            branch = self._validate_ref(branch_name, field_name="branch name")
            start = self._validate_ref(start_point or "HEAD", field_name="start point")
        except ValueError as exc:
            return f"Git failed: {exc}"
        return self._run_git(["branch", branch, start], max_chars=12000)

    async def _arun(self, branch_name: str, start_point: str = "HEAD", run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, branch_name, start_point, None)


class GitStageTool(_GitTool):
    name: str = "git_stage"
    description: str = "Stage explicit workspace-relative paths for commit. Never stages the whole repository implicitly."
    args_schema: Type[BaseModel] = GitStageInput

    def _run(self, paths: list[str], run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            safe_paths = self._validate_paths(paths)
        except ValueError as exc:
            return f"Git failed: {exc}"
        return self._run_git(["add", "--", *safe_paths], max_chars=12000)

    async def _arun(self, paths: list[str], run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, paths, None)


class GitUnstageTool(_GitTool):
    name: str = "git_unstage"
    description: str = "Remove explicit workspace-relative paths from the git index."
    args_schema: Type[BaseModel] = GitUnstageInput

    def _run(self, paths: list[str], run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            safe_paths = self._validate_paths(paths)
        except ValueError as exc:
            return f"Git failed: {exc}"
        return self._run_git(["restore", "--staged", "--", *safe_paths], max_chars=12000)

    async def _arun(self, paths: list[str], run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, paths, None)


class GitCommitTool(_GitTool):
    name: str = "git_commit"
    description: str = "Commit the currently staged git changes after verifying that staged diff exists."
    args_schema: Type[BaseModel] = GitCommitInput

    def _run(self, message: str, run_manager: CallbackManagerForToolRun | None = None) -> str:
        msg = str(message or "").strip()
        if not msg:
            return "Git failed: commit message is required"
        staged = self._run_git(["diff", "--cached", "--stat"], max_chars=12000)
        if staged == "(empty)":
            return "Git failed: no staged changes to commit"
        return self._run_git(["commit", "-m", msg], max_chars=20000)

    async def _arun(self, message: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, message, None)


class GitRestoreTool(_GitTool):
    name: str = "git_restore"
    description: str = "Restore explicit workspace-relative paths from git. Requires paths and never restores the whole repository."
    args_schema: Type[BaseModel] = GitRestoreInput

    def _run(self, paths: list[str], staged: bool = False, run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            safe_paths = self._validate_paths(paths)
        except ValueError as exc:
            return f"Git failed: {exc}"
        args = ["restore"]
        if staged:
            args.append("--staged")
        args.extend(["--", *safe_paths])
        return self._run_git(args, max_chars=12000)

    async def _arun(self, paths: list[str], staged: bool = False, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, paths, staged, None)


class GitPushTool(_GitTool):
    name: str = "git_push"
    description: str = "Push the current or specified branch to a remote. Force push is not supported."
    args_schema: Type[BaseModel] = GitPushInput

    def _run(self, remote: str = "origin", branch: str = "", run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            safe_remote = self._validate_ref(remote or "origin", field_name="remote")
            safe_branch = self._validate_ref(branch, field_name="branch") if str(branch or "").strip() else ""
        except ValueError as exc:
            return f"Git failed: {exc}"
        args = ["push", safe_remote]
        if safe_branch:
            args.append(safe_branch)
        return self._run_git(args, max_chars=20000)

    async def _arun(self, remote: str = "origin", branch: str = "", run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, remote, branch, None)


