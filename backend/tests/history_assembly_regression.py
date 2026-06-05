from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.shared.history_assembler import COMPRESSED_CONTEXT_PREFIX, assemble_runtime_history


def test_history_assembly_keeps_compressed_context_separate_from_active_history() -> None:
    history = [
        {"role": "user", "content": f"user-{index}"}
        for index in range(8)
    ]

    result = assemble_runtime_history(
        history=history,
        compressed_context="此前已经完成项目结构审查。",
    )

    assert result.compressed_context == "此前已经完成项目结构审查。"
    assert [item["content"] for item in result.model_history] == [f"user-{index}" for index in range(8)]
    assert all(not item["content"].startswith(COMPRESSED_CONTEXT_PREFIX) for item in result.model_history)
    assert result.diagnostics["active_history_message_count"] == 8
    assert result.diagnostics["compressed_context_included"] is True


def test_history_assembly_does_not_create_empty_summary_message() -> None:
    result = assemble_runtime_history(
        history=[{"role": "user", "content": "hello"}],
        compressed_context="",
    )

    assert [item["content"] for item in result.model_history] == ["hello"]
    assert result.diagnostics["compressed_context_included"] is False


