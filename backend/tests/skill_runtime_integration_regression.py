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
    def __init__(self) -> None:
        self.runtime_view_calls: list[dict] = []

    def build_memory_runtime_view(self, **_kwargs):
        self.runtime_view_calls.append(dict(_kwargs))
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
        self.runtime_view_calls.append(dict(_kwargs))
        profile = dict(_kwargs.get("memory_request_profile") or {})
        if "state" not in list(profile.get("requested_memory_layers") or []):
            return {"view_id": "memory-view:test"}
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
    assert "Workflow ID: runtime.recipe.information_search" in contents
    assert "Task mode: information_search" in contents


def test_agent_runtime_chain_uses_intent_gated_state_recall_for_followup() -> None:
    memory_facade = _FileBindingMemoryFacadeStub()
    assembler = AgentRuntimeChainAssembler(
        base_dir=ROOT,
        memory_facade=memory_facade,
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
    current_turn = dict(runtime.get("current_turn_context") or {})
    task_inputs = dict(dict(task_operation.get("task_spec") or {}).get("inputs") or {})
    protocol = dict(task_inputs.get("agent_communication_protocol") or {})
    recall_context = dict(dict(protocol.get("handoff_context") or {}).get("recall_context") or {})

    requested_layers_by_call = [
        list(dict(call.get("memory_request_profile") or {}).get("requested_memory_layers") or [])
        for call in memory_facade.runtime_view_calls
    ]
    assert [] in requested_layers_by_call
    assert ["state"] in requested_layers_by_call
    assert active_skill == {}
    assert understanding["route"] == "agent"
    assert understanding["tool_name"] is None
    assert understanding["skill_name"] is None
    assert understanding["candidate_tools"] == []
    assert understanding["tool_input"] == {"query": "按仓库汇总前五。"}
    assert current_turn["resolved_bindings"] == []
    assert current_turn["context_recall_candidates"][0]["recall_payload"]["active_dataset"] == "Data/inventory.xlsx"
    assert recall_context["candidate_policy"] == "candidate_only_child_must_verify_before_use"
    assert recall_context["candidates"][0]["recall_payload"]["active_dataset"] == "Data/inventory.xlsx"
    assert "op.mcp_structured_data" in list(operation_requirement.get("required_operations") or [])
    assert "conversation" in list(memory_request_profile.get("requested_memory_layers") or [])
