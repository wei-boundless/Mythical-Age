from __future__ import annotations


class MemoryContextLayer:
    """Retired compatibility symbol for the pre-MemorySystem context chain."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError(
            "MemoryContextLayer is retired. Use MemoryFacade.build_memory_runtime_view(), "
            "build_memory_context_package_result(), and inspect_memory_context_compaction()."
        )


__all__ = ["MemoryContextLayer"]
