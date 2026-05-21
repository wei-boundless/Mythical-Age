from __future__ import annotations

from context_system import ContextPackage
from runtime import RuntimeContextManager
from runtime.shared.context_manager import _render_runtime_execution_block
from prompting.builder import _render_context_package_block


def test_runtime_context_prompt_omits_hot_truth_for_non_compact_packages() -> None:
    from runtime.shared.context_manager import _render_context_policy_block

    block = _render_context_policy_block(
        {
            "package": {
                "rebuild_reason": "memory_bundle_service_context_package_result",
                "compaction_strategy": "none",
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
    assert "inventory.xlsx 当前需要按仓库汇总缺口" not in block


def test_runtime_context_prompt_keeps_hot_truth_for_compact_packages() -> None:
    from runtime.shared.context_manager import _render_context_policy_block

    block = _render_context_policy_block(
        {
            "package": {
                "rebuild_reason": "history_compaction",
                "compaction_strategy": "microcompact",
                "model_visible_sections": {
                    "hot_truth_window": [
                        "user: 请继续分析 inventory.xlsx 的仓库缺口。",
                    ]
                },
            }
        }
    )

    assert "user: 请继续分析 inventory.xlsx 的仓库缺口" in block


def test_prompt_builder_omits_hot_truth_for_normal_context_package() -> None:
    package = ContextPackage(
        rebuild_reason="memory_bundle_service_context_package_result",
        compaction_strategy="none",
        model_visible_sections={
            "active_process_context": ["active_result_handle_id: result-1"],
            "hot_truth_window": ["旧会话摘要不应进入普通主回答 prompt"],
        },
    )

    block = _render_context_package_block(
        package,
        include_durable_context=False,
    )

    assert "active_result_handle_id: result-1" in block
    assert "旧会话摘要不应进入普通主回答 prompt" not in block


def test_prompt_builder_keeps_hot_truth_for_compact_context_package() -> None:
    package = ContextPackage(
        rebuild_reason="history_compaction",
        compaction_strategy="microcompact",
        model_visible_sections={
            "hot_truth_window": ["assistant: 已确认当前压缩恢复点。"],
        },
    )

    block = _render_context_package_block(
        package,
        include_durable_context=False,
    )

    assert "assistant: 已确认当前压缩恢复点。" in block


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


def test_runtime_execution_block_includes_current_time_for_realtime_search() -> None:
    block = _render_runtime_execution_block(
        {
            "runtime_capability_state": {
                "turn_requested_operations": ["op.model_response", "op.web_search"],
                "turn_adopted_operations": ["op.model_response", "op.web_search"],
            },
            "current_time_fact": {
                "timezone": "Asia/Shanghai",
                "local_date": "2026-05-18",
                "local_time": "2026-05-18T00:14+08:00",
            },
        }
    )

    assert "Current Time Facts" in block
    assert "当前时区：Asia/Shanghai" in block
    assert "当前本地日期：2026-05-18" in block
    assert "历史回答中的时间戳只表示当时证据时间" in block


def test_runtime_execution_block_omits_current_time_for_non_realtime_tasks() -> None:
    block = _render_runtime_execution_block(
        {
            "runtime_capability_state": {
                "turn_requested_operations": ["op.model_response", "op.search_text"],
                "turn_adopted_operations": ["op.model_response", "op.search_text"],
            }
        }
    )

    assert "Current Time Facts" not in block
