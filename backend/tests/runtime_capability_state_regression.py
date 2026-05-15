from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_system import build_default_operation_registry
from orchestration.agent_runtime_models import AgentRuntimeProfile
from orchestration.runtime_loop.context_manager import RuntimeContextManager
from orchestration.runtime_loop.model_adoption import (
    build_model_response_runtime_adoption,
    build_runtime_capability_state,
)


def main() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="main_interactive_agent",
        agent_id="agent:0",
        allowed_operations=(
            "op.model_response",
            "op.search_text",
            "op.write_file",
            "op.edit_file",
        ),
        blocked_operations=(),
    )
    task_operation = {
        "task_contract": {"task_id": "task:test:capability"},
        "operation_requirement": {
            "required_operations": ["op.model_response"],
            "optional_operations": [],
            "denied_operations": [],
            "metadata": {"approval_policy": "default", "safety_envelope": {"safety_class": "S0_readonly"}},
        },
    }
    _, resource_policy = build_model_response_runtime_adoption(
        task_operation,
        operation_registry=build_default_operation_registry(),
        agent_runtime_profile=profile,
    )
    state = build_runtime_capability_state(
        task_operation,
        resource_policy=resource_policy,
        agent_runtime_profile=profile,
        visible_tool_names=[],
    )

    assert state["profile_write_capable"] is True
    assert state["turn_write_operation_adopted"] is False
    assert state["turn_write_tool_visible"] is False
    assert "op.write_file" in state["agent_profile_operations"]
    assert "op.write_file" in state["blocked_by_turn_policy_operations"]

    manager = RuntimeContextManager(lambda **_: "BASE")
    snapshot = manager.prepare_model_context(
        session_id="s",
        task_id="task:test:capability",
        user_message="你不能自己创建文件吗",
        history=[],
        runtime_execution_facts={"runtime_capability_state": state},
    )
    system_prompt = snapshot.model_messages[0]["content"]
    assert "Agent 配置上限允许文件写入/编辑：是" in system_prompt
    assert "本轮任务已采用写入/编辑 operation：否" in system_prompt
    assert "当前可见工具只代表本轮执行面" in system_prompt
    assert "历史对话或记忆中的 Assistant 自我能力判断不能覆盖这一运行时能力状态" in system_prompt

    print("ALL PASSED (runtime capability state)")


if __name__ == "__main__":
    main()
