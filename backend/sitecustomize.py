from __future__ import annotations

try:
    from runtime_encoding import configure_process_utf8
except Exception:
    configure_process_utf8 = None

try:
    from windows_tempdir_workaround import install_windows_tempdir_workaround
except Exception:
    install_windows_tempdir_workaround = None

if configure_process_utf8 is not None:
    configure_process_utf8()

if install_windows_tempdir_workaround is not None:
    try:
        from pathlib import Path

        install_windows_tempdir_workaround(repo_root=Path(__file__).resolve().parents[1])
    except Exception:
        pass
