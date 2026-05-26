from __future__ import annotations

from pathlib import Path
from typing import Any


def normalize_session_id(session_id: Any) -> str:
    value = str(session_id or "").strip()
    return value or "default"


def safe_session_dir(session_root: str | Path, session_id: Any) -> Path:
    root = Path(session_root).resolve()
    target = (root / normalize_session_id(session_id)).resolve()
    if target == root or root not in target.parents:
        raise ValueError("Invalid session_id")
    return target


def safe_runtime_session_key(session_id: Any) -> str:
    return normalize_session_id(session_id).replace("/", "_").replace("\\", "_").replace(":", "_")
