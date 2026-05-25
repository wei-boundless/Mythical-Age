from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from capability_system.skill_registry import SkillRegistry
from capability_system.tool_registry import ToolRegistry
from tests.support.runtime_stubs import model_turn_context


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
        current_turn_context_override=model_turn_context(
            action_intent="search_external",
            work_mode="read_only_analysis",
            interaction_intent="answer",
            desired_outcome="联网查 OpenAI API 最新更新",
            deliverables=["source_backed_answer"],
        ),
    )

    task_operation = dict(runtime.get("task_operation") or {})
    skill_runtime_views = list(task_operation.get("skill_runtime_views") or [])
    task_spec = dict(task_operation.get("task_spec") or {})
    understanding = dict(task_operation.get("query_understanding") or {})
    operation_requirement = dict(task_operation.get("operation_requirement") or {})
    task_body_orchestration = dict(task_operation.get("task_body_orchestration") or {})
    memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
    diagnostics = dict(task_body_orchestration.get("diagnostics") or {})
    prompt_flow_trace = dict(diagnostics.get("prompt_flow_trace") or {})
    prompt_assembly_plan = dict(diagnostics.get("prompt_assembly_plan") or {})

    assert skill_runtime_views == []
    assert list(task_spec.get("selected_skill_ids") or []) == []
    assert understanding["authority"] == "request_facts.frame"
    assert understanding["model_turn_decision"]["action_intent"] == "search_external"
    assert understanding["capability_intent"]["tool_selection_allowed"] is False
    assert "route_hint" not in understanding["capability_intent"]
    assert "tool_name" not in understanding
    assert "candidate_tools" not in understanding
    assert "op.web_search" in list(operation_requirement.get("required_operations") or [])
    assert memory_request_profile["requested_memory_layers"] == ["conversation"]
    sections = list(dict(task_body_orchestration.get("soul_runtime_view") or {}).get("sections") or [])
    contents = "\n".join(str(dict(item).get("content") or "") for item in sections)
    assert "OpenAI API 最新更新" in contents
    assert "Workflow ID:" not in contents
    assert "Task mode:" not in contents
    assert "当前工作方式" in contents
    assert task_body_orchestration["stage_plan"]["section_order"]
    assert prompt_flow_trace["authority"] == "prompt_library.flow_trace"
    assert prompt_assembly_plan["authority"] == "prompt_library.assembly_plan"
    assert str(prompt_assembly_plan["diagnostics"]["selector"]).startswith("prompt_library.flow_aware_v")
    assert "prompt_flow_trace" in task_body_orchestration["stage_plan"]


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
        current_turn_context_override=model_turn_context(
            action_intent="read_context",
            work_mode="read_only_analysis",
            interaction_intent="continue",
            target_objects=["Data/inventory.xlsx"],
            desired_outcome="按仓库汇总前五",
            deliverables=["structured_summary"],
        ),
    )

    task_operation = dict(runtime.get("task_operation") or {})
    skill_runtime_views = list(task_operation.get("skill_runtime_views") or [])
    task_spec = dict(task_operation.get("task_spec") or {})
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
    skill_ids = [str(dict(item).get("skill_id") or "") for item in skill_runtime_views if isinstance(item, dict)]
    assert "skill.structured-data-analysis" in skill_ids
    assert list(task_spec.get("selected_skill_ids") or []) == []
    assert understanding["authority"] == "request_facts.frame"
    assert understanding["model_turn_decision"]["action_intent"] == "read_context"
    assert understanding["capability_intent"]["tool_selection_allowed"] is False
    assert "route" not in understanding
    assert "tool_name" not in understanding
    assert "skill_name" not in understanding
    assert "candidate_tools" not in understanding
    assert "tool_input" not in understanding
    assert current_turn["resolved_bindings"] == []
    assert current_turn["context_recall_candidates"][0]["recall_payload"]["active_dataset"] == "Data/inventory.xlsx"
    assert recall_context["candidate_policy"] == "candidate_only_child_must_verify_before_use"
    assert recall_context["candidates"][0]["recall_payload"]["active_dataset"] == "Data/inventory.xlsx"
    assert "op.mcp_structured_data" not in list(operation_requirement.get("required_operations") or [])
    assert "op.mcp_structured_data" in list(operation_requirement.get("optional_operations") or [])
    assert "conversation" in list(memory_request_profile.get("requested_memory_layers") or [])


def test_agent_runtime_chain_expands_skill_only_after_model_selection() -> None:
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
        current_turn_context_override=model_turn_context(
            action_intent="read_context",
            work_mode="read_only_analysis",
            interaction_intent="continue",
            target_objects=["Data/inventory.xlsx"],
            desired_outcome="按仓库汇总前五",
            deliverables=["structured_summary"],
            selected_skill_ids=["skill.structured-data-analysis"],
        ),
    )

    task_operation = dict(runtime.get("task_operation") or {})
    task_spec = dict(task_operation.get("task_spec") or {})
    task_body_orchestration = dict(task_operation.get("task_body_orchestration") or {})
    runtime_sections = {
        str(dict(item).get("section_id") or ""): dict(item)
        for item in list(dict(task_body_orchestration.get("soul_runtime_view") or {}).get("sections") or [])
    }

    assert list(task_spec.get("selected_skill_ids") or []) == ["skill.structured-data-analysis"]
    assert "skill_catalog_section" in runtime_sections
    assert "skill_detail_section" in runtime_sections
    assert "候选 Skills（第一阶段）" in runtime_sections["skill_catalog_section"]["content"]
    assert "已激活 Skills（第二阶段）" in runtime_sections["skill_detail_section"]["content"]
    assert "structured-data-analysis" in runtime_sections["skill_detail_section"]["content"]
