from __future__ import annotations

from pathlib import Path

from runtime.context_management.tool_result_storage import (
    DEFAULT_FIELD_SIZE_LIMIT_BYTES,
    DEFAULT_PAYLOAD_BUDGET_BYTES,
    DEFAULT_PREVIEW_SIZE_BYTES,
    PERSISTED_OUTPUT_TAG,
    ContentReplacement,
    ToolResultStore,
)


class SearchToolResultStore(ToolResultStore):
    def __init__(self, root_dir: Path, *, run_id: str = "") -> None:
        super().__init__(root_dir, run_id=run_id, namespace="deepsearch_capability")


__all__ = [
    "ContentReplacement",
    "DEFAULT_FIELD_SIZE_LIMIT_BYTES",
    "DEFAULT_PAYLOAD_BUDGET_BYTES",
    "DEFAULT_PREVIEW_SIZE_BYTES",
    "PERSISTED_OUTPUT_TAG",
    "SearchToolResultStore",
]


