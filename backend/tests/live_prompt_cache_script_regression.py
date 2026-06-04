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

from scripts.live_five_floor_dungeon_prompt_cache_e2e import _task_selection, _validate_model_mode_args, _wait_for_task


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


def test_complex_live_prompt_cache_scenario_requires_image_generation() -> None:
    selection = _task_selection(
        run_id="five_floor_dungeon_e2e_20260602_130944_4d0391",
        artifact_path="artifacts/prompt_cache_live_e2e/run/five_floor_dungeon_complex/index.html",
        model_selection={"provider": "deepseek", "model": "deepseek-v4-pro"},
        scenario="complex",
    )

    assert "op.image_generate" in selection["allowed_operations"]
    contract = selection["task_contract"]
    goal = contract["task_run_goal"]
    assert "image_generate" in goal
    assert "five-floor-dungeon-pixel-tower-five_floor_dungeon_e2e_20260602_130944_4d0391" in goal
    assert "five-floor-dungeon-pixel-boss-five_floor_dungeon_e2e_20260602_130944_4d0391" in goal
    assert "quality=`low`" in goal
    assert "output_size=`512x512`" in goal
    assert "2D pixel art" in goal
    assert "每层章节文本" in goal
    assert "/api/image-assets/files/" in "\n".join(contract["completion_criteria"])
    artifact_paths = {item["path"] for item in contract["required_artifacts"]}
    assert "storage/generated/images/scene-five-floor-dungeon-pixel-tower-five_floor_dungeon_e2e_20260602_130944_4d0391.png" in artifact_paths
    assert "storage/generated/images/character-five-floor-dungeon-pixel-boss-five_floor_dungeon_e2e_20260602_130944_4d0391.png" in artifact_paths
    assert any(item["kind"] == "image_asset_check" for item in contract["required_verifications"])


def test_basic_live_prompt_cache_scenario_does_not_require_image_generation() -> None:
    selection = _task_selection(
        run_id="five_floor_dungeon_e2e_20260602_130944_4d0391",
        artifact_path="artifacts/prompt_cache_live_e2e/run/five_floor_dungeon/index.html",
        model_selection={"provider": "deepseek", "model": "deepseek-v4-pro"},
        scenario="basic",
    )

    assert "op.image_generate" not in selection["allowed_operations"]
    contract = selection["task_contract"]
    assert "image_generate" not in contract["task_run_goal"]
    assert all(item["kind"] != "image" for item in contract["required_artifacts"])


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
