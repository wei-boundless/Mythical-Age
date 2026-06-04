from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from capability_system.tools.authorization import build_authorized_tool_set
from capability_system.tools.native_tool_catalog import get_tool_definitions
from harness.runtime.compiler import RuntimeCompiler
from prompt_library import PromptLibraryRegistry, tool_guidance_payload_for_visible_tools


def test_tool_guidance_resources_are_registered_as_prompt_library_resources(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    resources = {item.resource_id: item for item in registry.list_resources()}

    read_guidance = resources["tool.guidance.read_file.v1"]
    terminal_guidance = resources["tool.guidance.terminal_powershell.v1"]
    web_guidance = resources["tool.guidance.web_fetch.v1"]

    assert read_guidance.category == "tool"
    assert read_guidance.owner_layer == "tool"
    assert read_guidance.cache_scope == "static"
    assert read_guidance.allowed_invocation_kinds == (
        "single_agent_turn",
        "task_execution",
        "tool_observation_followup",
    )
    assert "has_more" in read_guidance.content
    assert "Windows PowerShell" in terminal_guidance.content
    assert "不要只凭搜索摘要下结论" in web_guidance.content
    assert "来源之间冲突" in web_guidance.content


def test_schema_plus_guidance_tools_remain_prompt_visible() -> None:
    definitions = {item.name: item for item in get_tool_definitions()}
    tool_set = build_authorized_tool_set(
        tool_instances=[SimpleNamespace(name="read_file"), SimpleNamespace(name="python_repl")],
        definitions_by_name=definitions,
        allowed_operations={"op.read_file", "op.python_repl"},
    )

    assert "read_file" in tool_set.tool_names
    assert "python_repl" not in tool_set.tool_names
    assert any(item["tool_name"] == "python_repl" and item["reason"] == "not_prompt_schema_visible" for item in tool_set.filtered_out)
    assert definitions["read_file"].prompt_exposure_policy == "schema_plus_guidance"


def test_tool_guidance_payload_only_uses_visible_schema_plus_guidance_tools() -> None:
    payload = tool_guidance_payload_for_visible_tools(
        [
            {"tool_name": "read_file", "prompt_exposure_policy": "schema_plus_guidance"},
            {"tool_name": "write_file", "prompt_exposure_policy": "schema_only"},
            {"tool_name": "python_repl", "prompt_exposure_policy": "hidden"},
            {"tool_name": "fetch_url", "prompt_exposure_policy": "schema_plus_guidance"},
        ]
    )

    refs = payload["tool_guidance_refs"]
    content = json.dumps(payload["tool_guidance"], ensure_ascii=False)

    assert "tool.guidance.read_file.v1" in refs
    assert "tool.guidance.web_fetch.v1" in refs
    assert "tool.guidance.write_file.v1" not in refs
    assert "python_repl" not in content
    assert payload["tool_guidance_hash"].startswith("sha256:")


def test_task_execution_tool_index_includes_guidance_for_visible_tools_only() -> None:
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:tool-guidance",
        task_run={
            "task_run_id": "taskrun:tool-guidance",
            "task_id": "task:tool-guidance",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={"task_run_goal": "检查工具 guidance", "completion_criteria": ["packet 包含可见工具 guidance"]},
        observations=[],
        available_tools=[
            {
                "tool_name": "read_file",
                "operation_id": "op.read_file",
                "required_inputs": ["path"],
                "prompt_exposure_policy": "schema_plus_guidance",
            },
            {
                "tool_name": "git_status",
                "operation_id": "op.git_status",
                "prompt_exposure_policy": "schema_plus_guidance",
            },
            {
                "tool_name": "write_file",
                "operation_id": "op.write_file",
                "prompt_exposure_policy": "schema_only",
            },
        ],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.test"},
        },
    ).packet

    payload = _payload_after_title(
        _message_content_with_title(packet, "Task execution tool index"),
        "Task execution tool index",
    )
    refs = payload["tool_guidance_refs"]
    guidance_text = json.dumps(payload["tool_guidance"], ensure_ascii=False)

    assert "tool.guidance.read_file.v1" in refs
    assert "tool.guidance.git_read.v1" in refs
    assert "tool.guidance.write_file.v1" not in refs
    assert "tool.guidance.git_write.v1" not in refs
    assert "不要重复读取相同行窗口" in guidance_text
    assert "Git 读取工具只用于获取版本库事实" in guidance_text
    assert payload["available_tools"][0]["prompt_exposure_policy"]


def _message_content_with_title(packet, title: str) -> str:
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if content.startswith(title + "\n"):
            return content
    raise AssertionError(f"missing message title: {title}")


def _payload_after_title(content: str, title: str) -> dict:
    assert content.startswith(title + "\n")
    return json.loads(content.split("\n", 1)[1])
