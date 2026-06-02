from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.live_five_floor_dungeon_prompt_cache_e2e import _validate_model_mode_args


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
