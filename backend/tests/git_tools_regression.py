from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system.tools.tool_units.git_tools import (
    GitBranchCreateTool,
    GitBranchListTool,
    GitCommitTool,
    GitRestoreTool,
    GitStageTool,
    GitStatusTool,
    GitUnstageTool,
)


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def test_git_tools_cover_status_stage_commit_branch_and_restore_boundaries() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _git(repo, "init")
        _git(repo, "config", "user.email", "agent@example.test")
        _git(repo, "config", "user.name", "Agent Test")
        (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
        _git(repo, "add", "tracked.txt")
        _git(repo, "commit", "-m", "initial")

        (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
        (repo / "other.txt").write_text("other\n", encoding="utf-8")

        status = GitStatusTool(root_dir=repo).invoke({})
        assert "tracked.txt" in status
        assert "other.txt" in status

        unsafe_stage = GitStageTool(root_dir=repo).invoke({"paths": ["."]})
        assert "unsafe git pathspec" in unsafe_stage

        stage_result = GitStageTool(root_dir=repo).invoke({"paths": ["tracked.txt"]})
        assert stage_result
        porcelain = _git(repo, "status", "--short")
        assert porcelain.startswith("M  tracked.txt")
        assert "?? other.txt" in porcelain

        unstage_result = GitUnstageTool(root_dir=repo).invoke({"paths": ["tracked.txt"]})
        assert unstage_result
        assert "M tracked.txt" in _git(repo, "status", "--short").splitlines()

        GitStageTool(root_dir=repo).invoke({"paths": ["tracked.txt"]})
        commit_result = GitCommitTool(root_dir=repo).invoke({"message": "update tracked"})
        assert "update tracked" in commit_result or "files changed" in commit_result or "file changed" in commit_result
        assert "?? other.txt" in _git(repo, "status", "--short")

        branch_result = GitBranchCreateTool(root_dir=repo).invoke({"branch_name": "feature/test"})
        assert branch_result
        branches = GitBranchListTool(root_dir=repo).invoke({})
        assert "feature/test" in branches

        try:
            GitRestoreTool(root_dir=repo).invoke({"paths": []})
        except Exception as exc:
            assert "at least 1 item" in str(exc)
        else:
            raise AssertionError("empty restore paths must be rejected")


if __name__ == "__main__":
    test_git_tools_cover_status_stage_commit_branch_and_restore_boundaries()
