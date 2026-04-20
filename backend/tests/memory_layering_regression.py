from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from RAG.collections import build_default_collections
from retrieval.memory_index import memory_indexer
from structured_memory import MemoryManager, MemoryNote


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_memory_collections_keep_session_and_durable_layers_separate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        collections = build_default_collections(root)

        durable = collections["durable_memory"]
        session = collections["session_memory"]

        _assert(
            durable.source_dirs == (root / "durable_memory",),
            "durable collection should only index durable memory sources",
        )
        _assert(
            durable.allowed_roots == (root / "durable_memory",),
            "durable collection should only allow durable memory roots",
        )
        _assert(
            session.source_dirs == (root / "session-memory",),
            "session collection should keep per-session summaries in their own layer",
        )
        _assert(
            session.allow_chat_queries is False,
            "session-memory collection should not participate in direct chat retrieval",
        )


def test_memory_indexer_repairs_manifest_and_excludes_session_sources() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = MemoryManager(root / "durable_memory")
        manager.save_note(
            MemoryNote(
                slug="keep-note",
                title="Keep Note",
                summary="Canonical durable memory note.",
                body="Durable memory should use markdown note files as the source of truth.",
                memory_type="project",
                memory_class="work",
                tags=["memory", "durable"],
            )
        )
        (root / "durable_memory" / "MEMORY.md").write_text(
            "# Memory Index\n\n"
            "- [Ghost](ghost-note.md) - stale index entry\n"
            "- [Keep Note](keep-note.md) - Canonical durable memory note.\n",
            encoding="utf-8",
        )
        session_dir = root / "session-memory" / "session-1"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "summary.md").write_text(
            "# Session Title\n\nPreview session summary that should not enter durable indexing.\n",
            encoding="utf-8",
        )

        audit = manager.ensure_index_consistent()
        _assert(audit["repaired"] is True, "drifted durable index should be repaired from note files")
        _assert(audit["ghost_entries"] == [], "ghost durable entries should be removed from the manifest")
        _assert(
            audit["index_files"] == ["keep-note.md"],
            "repaired durable index should only contain canonical note files",
        )

        memory_indexer.configure(root)
        index_audit = memory_indexer.audit_sources()
        indexed_sources = set(index_audit["indexed_sources"])

        _assert(
            "durable_memory/keep-note.md" in indexed_sources,
            "memory indexer should still index canonical durable note files",
        )
        _assert(
            "durable_memory/MEMORY.md" in indexed_sources,
            "memory indexer should include the repaired durable manifest",
        )
        _assert(
            all(not source.startswith("session-memory/") for source in indexed_sources),
            "session-memory summaries should not leak into durable indexing",
        )


def main() -> None:
    tests = [
        test_memory_collections_keep_session_and_durable_layers_separate,
        test_memory_indexer_repairs_manifest_and_excludes_session_sources,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
