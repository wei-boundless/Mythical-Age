from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.live_five_floor_dungeon_prompt_cache_e2e import _validate_model_mode_args, _wait_for_task


class _RaisingParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def test_live_prompt_cache_script_rejects_deepseek_max_without_thinking() -> None:
    args = argparse.Namespace(
        provider="deepseek",
        thinking_mode="disabled",
        reasoning_effort="max",
    )

    with pytest.raises(ValueError) as exc_info:
        _validate_model_mode_args(args, _RaisingParser())

    assert "--reasoning-effort max requires --thinking-mode enabled" in str(exc_info.value)


def test_live_prompt_cache_wait_returns_when_task_blocks_before_min_provider_calls() -> None:
    task = SimpleNamespace(status="blocked", terminal_reason="model_call_recovery_required")
    host = SimpleNamespace(
        state_index=SimpleNamespace(get_task_run=lambda _task_run_id: task),
        prompt_accounting_ledger=SimpleNamespace(list_token_usage=lambda task_run_id: []),
        _background_tasks=set(),
    )
    runtime_facade = SimpleNamespace(single_agent_runtime_host=host)

    result = asyncio.run(
        _wait_for_task(
            runtime_facade,
            task_run_id="taskrun:test",
            min_provider_calls=6,
            stop_after_provider_calls=0,
            timeout_seconds=30,
        )
    )

    assert result["terminal_reached"] is True
    assert result["timeout"] is False
    assert result["provider_usage_sufficient"] is False
    assert result["status"] == "blocked"
