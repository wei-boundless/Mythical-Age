from __future__ import annotations

from pathlib import Path

from backend.windows_tempdir_workaround import install_windows_tempdir_workaround

install_windows_tempdir_workaround(repo_root=Path(__file__).resolve().parent)
