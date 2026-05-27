from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIGURE_SCRIPT = REPO_ROOT / "scripts" / "configure_writing_modular_novel_graph.py"


def load_writing_modular_config_module():
    spec = importlib.util.spec_from_file_location("configure_writing_modular_novel_graph", CONFIGURE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def seed_writing_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "storage" / "tasks", storage / "tasks")
    shutil.copytree(REPO_ROOT / "storage" / "orchestration", storage / "orchestration")
    return tmp_path


