from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestration import AgentRuntimeChainAssembler
from capability_system.skill_registry import SkillRegistry
from capability_system.tool_registry import ToolRegistry


class _MemoryFacadeStub:
    def build_memory_runtime_view(self, **_kwargs):
        return {"view_id": "memory-view:test"}

    def build_memory_context_package(self, **_kwargs):
        return {
            "result_id": "context-policy:test",
            "package": {
                "package_id": "ctxpkg:test",
                "model_visible_sections": {},
                "selected_sections": [],
            },
        }


class _FileBindingMemoryFacadeStub(_MemoryFacadeStub):
    def build_memory_runtime_view(self, **_kwargs):
        return {
            "view_id": "memory-view:test",
            "state_snapshot": {
                "context_slots": {
                    "active_dataset": "Data/inventory.xlsx",
                    "active_binding_kind": "active_dataset",
                    "active_binding_identity": "data/inventory.xlsx",
                },
                "active_handles": {
                    "active_object_handle_id": "source:dataset:inventory",
                    "active_result_handle_id": "result:structured_answer:inventory",
                },
            },
        }


def test_agent_runtime_chain_uses_realtime_network_without_active_skill() -> None:
    assembler = AgentRuntimeChainAssembler(
        base_dir=ROOT,
        memory_facade=_MemoryFacadeStub(),
        skill_registry=SkillRegistry(ROOT),
        tool_registry=ToolRegistry(ROOT),
    )

    runtime = assembler.build_runtime(
        session_id="session-test",
        task_id="task-test",
        message="帮我联网查 OpenAI API 最新更新",
        source="regression",
    )

    task_operation = dict(runtime.get("task_operation") or {})
    active_skill = dict(task_operation.get("active_skill") or {})
    understanding = dict(task_operation.get("query_understanding") or {})
    operation_requirement = dict(task_operation.get("operation_requirement") or {})
    task_body_orchestration = dict(task_operation.get("task_body_orchestration") or {})
    memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})

    assert active_skill == {}
    assert understanding["route"] == "realtime_network"
    assert understanding["tool_name"] == "web_search"
    assert any(item["candidate_type"] == "tool" and item["name"] == "web_search" for item in list(understanding.get("candidate_capabilities") or []))
    assert "op.web_search" in list(operation_requirement.get("required_operations") or [])
    assert memory_request_profile["requested_memory_layers"] == ["conversation"]
    sections = list(dict(task_body_orchestration.get("soul_runtime_view") or {}).get("sections") or [])
    contents = "\n".join(str(dict(item).get("content") or "") for item in sections)
    assert "OpenAI API 最新更新" in contents
    assert "Workflow ID: workflow.general.main_conversation" in contents


def test_agent_runtime_chain_uses_active_file_binding_for_followup() -> None:
    assembler = AgentRuntimeChainAssembler(
        base_dir=ROOT,
        memory_facade=_FileBindingMemoryFacadeStub(),
        skill_registry=SkillRegistry(ROOT),
        tool_registry=ToolRegistry(ROOT),
    )

    runtime = assembler.build_runtime(
        session_id="session-test",
        task_id="task-test",
        message="按仓库汇总前五。",
        source="regression",
    )

    task_operation = dict(runtime.get("task_operation") or {})
    active_skill = dict(task_operation.get("active_skill") or {})
    understanding = dict(task_operation.get("query_understanding") or {})
    operation_requirement = dict(task_operation.get("operation_requirement") or {})
    memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})

    assert active_skill["name"] == "structured-data-analysis"
    assert understanding["route"] == "structured_data"
    assert understanding["tool_name"] is None
    assert understanding["skill_name"] == "structured-data-analysis"
    assert understanding["candidate_tools"] == []
    assert any(item["candidate_type"] == "mcp" and item["name"] == "structured_data" for item in list(understanding.get("candidate_capabilities") or []))
    assert understanding["tool_input"] == {
        "query": "按仓库汇总前五。",
        "path": "Data/inventory.xlsx",
    }
    assert "bound_dataset_followup" in list(understanding.get("reasons") or [])
    assert "op.mcp_structured_data" in list(operation_requirement.get("required_operations") or [])
    assert "conversation" in list(memory_request_profile.get("requested_memory_layers") or [])
