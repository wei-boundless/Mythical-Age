from __future__ import annotations

from orchestration.runtime_loop.context_manager import _render_context_policy_block


def test_runtime_context_prompt_filters_stale_operational_limit_summaries() -> None:
    block = _render_context_policy_block(
        {
            "package": {
                "model_visible_sections": {
                    "hot_truth_window": [
                        "本轮委派次数已用完，无法通过子Agent完成全表扫描。下一轮继续。",
                        "inventory.xlsx 当前需要按仓库汇总缺口。",
                    ]
                }
            }
        }
    )

    assert "本轮委派次数已用完" not in block
    assert "无法通过子Agent完成全表扫描" not in block
    assert "inventory.xlsx 当前需要按仓库汇总缺口" in block
