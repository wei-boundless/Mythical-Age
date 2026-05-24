from __future__ import annotations

from context_system import ContextPackage
from runtime import RuntimeContextManager
from runtime.shared.action_request import build_tool_result_observation
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


def test_runtime_context_microcompacts_large_old_history_and_keeps_recent_messages(tmp_path) -> None:
    manager = RuntimeContextManager(
        system_prompt_builder=lambda **_: "基础系统提示"
    )
    large_old_observation = "agent_evidence_packet " + ("大量旧证据 " * 2000)

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="继续处理当前问题",
        history=[
            {"role": "assistant", "content": large_old_observation},
            {"role": "user", "content": "中间历史 1"},
            {"role": "assistant", "content": "中间历史 2"},
            {"role": "user", "content": "中间历史 3"},
            {"role": "assistant", "content": "中间历史 4"},
            {"role": "user", "content": "中间历史 5"},
            {"role": "assistant", "content": "中间历史 6"},
            {"role": "user", "content": "最近问题需要完整保留"},
            {"role": "assistant", "content": "最近回答也要完整保留"},
        ],
        runtime_assembly={
            "assembly_id": "runtime-assembly:test",
            "root_dir": str(tmp_path),
            "context_sections": [
                {
                    "section_id": "main_session_history",
                    "content_mode": "full",
                }
            ],
        },
    )

    history_messages = list(snapshot.model_messages[1:-1])
    assert snapshot.diagnostics["compression_applied"] is True
    assert snapshot.diagnostics["history_compaction"]["compacted_message_count"] == 1
    assert "<persisted-output>" in history_messages[0]["content"]
    assert len(history_messages[0]["content"]) < len(large_old_observation)
    assert history_messages[-2]["content"] == "最近问题需要完整保留"
    assert history_messages[-1]["content"] == "最近回答也要完整保留"
    assert snapshot.model_messages[-1]["content"] == "继续处理当前问题"
    replacement = snapshot.diagnostics["history_compaction"]["content_replacements"][0]
    assert replacement["path"]


def test_runtime_context_marks_context_compactor_required_when_pressure_high(tmp_path) -> None:
    manager = RuntimeContextManager(
        system_prompt_builder=lambda **_: "基础系统提示"
    )
    history = [
        {"role": "user", "content": "请研究 Responses API web search 能力"},
        {
            "role": "assistant",
            "content": (
                '{"summary":"完成一轮搜索","evidence_refs":["web:evidence:1"],'
                '"artifact_refs":["artifact:web:1"],"limitations":["pricing unknown"],'
                '"diagnostics":{"agent_evidence_packet":{"facts":[{"claim":"官方文档确认 web_search 工具可用"}],'
                '"unknowns":[{"description":"支持模型未知"}]}}}'
            ),
        },
        {"role": "user", "content": "中间历史 1"},
        {"role": "assistant", "content": "中间历史 2"},
        {"role": "user", "content": "中间历史 3"},
        {"role": "assistant", "content": "中间历史 4"},
        {"role": "user", "content": "最近问题需要完整保留"},
        {"role": "assistant", "content": "最近回答也要完整保留"},
    ]

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="继续深搜",
        history=history,
        context_policy_result={
            "package": {
                "pressure_level": "high",
                "compaction_strategy": "autocompact",
            }
        },
        runtime_assembly={
            "assembly_id": "runtime-assembly:test",
            "root_dir": str(tmp_path),
            "context_sections": [
                {
                    "section_id": "main_session_history",
                    "content_mode": "full",
                }
            ],
        },
    )

    messages = list(snapshot.model_messages)
    history_messages = messages[1:-1]
    assert snapshot.diagnostics["context_compactor_agent_required"] is True
    assert "上下文压缩恢复点" not in history_messages[0]["content"]
    assert "官方文档确认 web_search 工具可用" in history_messages[1]["content"]
    assert history_messages[-2]["content"] == "最近问题需要完整保留"
    assert history_messages[-1]["content"] == "最近回答也要完整保留"
    assert messages[-1]["content"] == "继续深搜"


def test_runtime_context_marks_context_compactor_required_when_actual_history_is_large(tmp_path) -> None:
    manager = RuntimeContextManager(
        system_prompt_builder=lambda **_: "基础系统提示"
    )
    history = [
        {"role": "user", "content": "请继续研究 deepsearch runtime"},
        {"role": "assistant", "content": "已确认需要保留证据引用。"},
        *[
            {"role": "assistant", "content": "旧的大段工具输出 " + ("证据片段 " * 6000)}
            for _ in range(4)
        ],
        {"role": "user", "content": "最近问题需要完整保留"},
        {"role": "assistant", "content": "最近回答也要完整保留"},
    ]

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="继续优化",
        history=history,
        context_policy_result={"package": {"pressure_level": "normal"}},
        runtime_assembly={
            "assembly_id": "runtime-assembly:test",
            "root_dir": str(tmp_path),
            "context_sections": [{"section_id": "main_session_history", "content_mode": "full"}],
        },
    )

    assert snapshot.token_pressure["pressure_level"] in {"high", "critical"}
    assert snapshot.token_pressure["actual_pressure_level"] in {"high", "critical"}
    assert snapshot.diagnostics["context_compactor_agent_required"] is True
    assert all("上下文压缩恢复点" not in item["content"] for item in snapshot.model_messages)
    assert snapshot.model_messages[-2]["content"] == "最近回答也要完整保留"
    assert snapshot.model_messages[-1]["content"] == "继续优化"


def test_runtime_context_does_not_require_context_compactor_when_pressure_normal(tmp_path) -> None:
    manager = RuntimeContextManager(system_prompt_builder=lambda **_: "基础系统提示")

    snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="继续",
        history=[{"role": "user", "content": f"历史 {index}"} for index in range(8)],
        context_policy_result={"package": {"pressure_level": "normal"}},
        runtime_assembly={
            "assembly_id": "runtime-assembly:test",
            "root_dir": str(tmp_path),
            "context_sections": [{"section_id": "main_session_history", "content_mode": "full"}],
        },
    )

    assert snapshot.diagnostics["context_compactor_agent_required"] is False
    assert all("上下文压缩恢复点" not in item["content"] for item in snapshot.model_messages)


def test_runtime_context_record_observation_builds_tool_use_summary() -> None:
    manager = RuntimeContextManager(system_prompt_builder=lambda **_: "基础系统提示")
    observation = build_tool_result_observation(
        task_run_id="taskrun:test",
        request_ref="rtact:test",
        directive_ref="directive:test",
        tool_name="deepsearch",
        tool_call_id="call:test",
        tool_args={"query": "Codex search runtime"},
        result=(
            '{"summary":"检索完成","diagnostics":{"agent_evidence_packet":'
            '{"facts":[{"claim":"官方文档确认 web search 工具存在"}],'
            '"unknowns":[{"description":"价格仍需核验"}],'
            '"evidence_refs":["web:evidence:1"]}}}'
        ),
    )

    record = manager.record_observation(observation)
    summary = record.context_update["tool_use_summary"]

    assert record.diagnostics["tool_use_summary_built"] is True
    assert summary["tool_name"] == "deepsearch"
    assert summary["tool_call_id"] == "call:test"
    assert "官方文档确认 web search 工具存在" in summary["facts"]
    assert "价格仍需核验" in summary["unknowns"]
    assert "web:evidence:1" in summary["evidence_refs"]


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
