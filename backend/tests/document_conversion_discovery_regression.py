from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.units.mcp.local.retrieval.collections import CollectionConfig
from knowledge_system.conversion import discover_source_files


def test_discover_source_files_prefixes_same_name_files_from_distinct_roots(tmp_path: Path) -> None:
    session_a = tmp_path / "session_a"
    session_b = tmp_path / "session_b"
    session_a.mkdir()
    session_b.mkdir()
    (session_a / "summary.md").write_text("# Session A\n", encoding="utf-8")
    (session_b / "summary.md").write_text("# Session B\n", encoding="utf-8")

    records = discover_source_files(
        CollectionConfig(
            name="session_memory",
            source_dirs=(session_a, session_b),
            storage_dir=tmp_path / "indexes",
            description="session test",
            file_extensions=(".md",),
            allowed_roots=(session_a, session_b),
            allow_chat_queries=False,
        ),
        backend_dir=BACKEND_DIR,
    )

    assert [item.source_path for item in records] == [
        "session_a/summary.md",
        "session_b/summary.md",
    ]
    assert len({item.version_digest for item in records}) == 2
