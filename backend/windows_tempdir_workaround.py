from __future__ import annotations

import os
import tempfile
from pathlib import Path

BROKEN_WINDOWS_DIR_MODE = 0o700
SAFE_WINDOWS_DIR_MODE = 0o755
PYTEST_TEMPROOT_ENV = "PYTEST_DEBUG_TEMPROOT"


def install_windows_tempdir_workaround(*, repo_root: Path) -> None:
    if os.name != "nt":
        return
    if getattr(os, "_codex_windows_tempdir_workaround_installed", False):
        return

    repo_root = Path(repo_root).resolve()
    pytest_temproot = repo_root / ".tmp" / "pytest"
    pytest_temproot.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(PYTEST_TEMPROOT_ENV, str(pytest_temproot))

    original_mkdir = os.mkdir
    system_temp_root = Path(tempfile.gettempdir()).resolve()
    repo_temp_roots = (pytest_temproot,)

    def mkdir(path: os.PathLike[str] | str, mode: int = 0o777, *args, **kwargs):
        normalized_mode = mode
        if mode == BROKEN_WINDOWS_DIR_MODE and _is_temp_directory_path(
            path=Path(path),
            system_temp_root=system_temp_root,
            repo_temp_roots=repo_temp_roots,
        ):
            normalized_mode = SAFE_WINDOWS_DIR_MODE
        return original_mkdir(path, normalized_mode, *args, **kwargs)

    os.mkdir = mkdir
    setattr(os, "_codex_windows_tempdir_workaround_installed", True)


def _is_temp_directory_path(
    *,
    path: Path,
    system_temp_root: Path,
    repo_temp_roots: tuple[Path, ...],
) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = Path(path)
    for root in (system_temp_root, *repo_temp_roots):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


