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


def test_runtime_context_prompt_applies_agent_assembly_contract() -> None:
    manager = RuntimeContextManager(
        system_prompt_builder=lambda **_: "基础系统提示"
    )

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="请审核世界观设定",
        history=[],
        agent_assembly_contract={
            "assembly_id": "assembly:world-review",
            "prompt_assembly": {
                "role_name": "世界观审核员",
                "role_summary": "你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。",
                "instruction_text": "你不负责替创作者扩写设定。",
                "required_outputs": ["问题清单", "是否允许进入下一阶段"],
                "forbidden_actions": ["扩写世界观正文"],
            },
            "output_boundary": {
                "selected_channel": "graph_node_result",
            },
        },
    )
    system_prompt = snapshot.model_messages[0]["content"]

    assert snapshot.diagnostics["agent_assembly_contract_applied"] is True
    assert snapshot.diagnostics["agent_assembly_contract_ref"] == "assembly:world-review"
    assert "当前 Agent 工作契约" in system_prompt
    assert "你是一名世界观审核员" in system_prompt
    assert "你不负责替创作者扩写设定" in system_prompt
    assert "是否允许进入下一阶段" in system_prompt
    assert "runtime 节点" not in system_prompt


def test_runtime_context_prompt_keeps_single_user_visible_receipt_protocol_source() -> None:
    manager = RuntimeContextManager(
        system_prompt_builder=lambda **_: (
            "基础系统提示\n\n"
            "用户可见回执协议：当你完成用户命令、工具操作、文件编辑或任务执行时，必须用自然语言说明做了什么、影响范围是什么、"
            "是否产生了文件或其它产物。默认可见内容必须面向用户，不要把 taskrun_id、taskinst_id、node_id、event_name、"
            "运行状态字段、装配字段或权限记录作为回答正文或状态摘要。这些内部标识只能进入 debug、diagnostics、运行监控详情或开发者可展开区域。"
        )
    )

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="请修改文件",
        history=[],
    )
    system_prompt = snapshot.model_messages[0]["content"]

    assert "用户可见回执协议" in system_prompt
    assert "文件编辑或任务执行" in system_prompt
    assert "taskrun_id" in system_prompt
    assert "开发者可展开区域" in system_prompt
    assert system_prompt.count("用户可见回执协议") == 1


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
