from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.agent_chain import AgentRuntimeChainAssembler
from skill_system import SkillRegistry
from tools.tool_registry import ToolRegistry


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


def test_agent_runtime_chain_injects_active_skill_and_runtime_operations() -> None:
    assembler = AgentRuntimeChainAssembler(
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
    task_prompt_contract = dict(task_operation.get("task_prompt_contract") or {})

    assert active_skill
    assert active_skill["name"] == "web-search"
    assert understanding["tool_name"] == "web_search"
    assert "op.web_search" in list(operation_requirement.get("required_operations") or [])
    assert "OpenAI API 最新更新" in str(task_prompt_contract.get("task_section") or "")
    assert "联网搜索" in str(task_prompt_contract.get("workflow_section") or "")


def test_agent_runtime_chain_uses_active_file_binding_for_followup() -> None:
    assembler = AgentRuntimeChainAssembler(
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

    assert active_skill["name"] == "structured-data-analysis"
    assert understanding["tool_name"] == "structured_data_analysis"
    assert understanding["tool_input"] == {
        "query": "按仓库汇总前五。",
        "path": "Data/inventory.xlsx",
    }
    assert "bound_dataset_followup" in list(understanding.get("reasons") or [])
    assert "op.structured_data_analysis" in list(operation_requirement.get("required_operations") or [])
