from __future__ import annotations

from orchestration.runtime_loop import RuntimeContextManager


def test_runtime_context_prompt_filters_stale_operational_limit_summaries() -> None:
    from orchestration.runtime_loop.context_manager import _render_context_policy_block

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


def test_runtime_context_prompt_includes_runtime_assembly_block() -> None:
    manager = RuntimeContextManager(
        system_prompt_builder=lambda **_: "基础系统提示"
    )

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="请生成世界观候选",
        history=[{"role": "user", "content": "旧历史应被抑制"}],
        runtime_assembly={
            "assembly_id": "runtime-assembly:test",
            "context_sections": [
                {
                    "section_id": "artifact_refs",
                    "title": "产物引用",
                    "model_visible": True,
                }
            ],
            "handoff_packets": [
                {
                    "source_node_id": "project_brief",
                    "target_node_id": "world_candidate",
                }
            ],
        },
    )

    assert snapshot.history_message_count == 0
    assert snapshot.diagnostics["runtime_assembly_context_applied"] is True
    assert snapshot.diagnostics["runtime_assembly_ref"] == "runtime-assembly:test"
    assert "可用参考材料" in snapshot.model_messages[0]["content"]
