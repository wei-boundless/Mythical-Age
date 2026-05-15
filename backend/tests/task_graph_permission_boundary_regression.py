from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.agent_runtime_chain import AgentRuntimeChainAssembler
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.runtime_loop.task_run_loop import _task_operation_allows_context_retrieval
from understanding.capability_resolution_view import capability_resolution_view


class _MemoryFacadeStub:
    def build_memory_context_package(self, **kwargs):
        retrieval_results = kwargs.get("retrieval_results")
        return {
            "package": {
                "sections": {
                    "retrieval_evidence": [
                        str(item.get("text") or "")
                        for item in list(retrieval_results or [])
                    ]
                }
            },
            "diagnostics": {
                "retrieval_evidence_count": len(list(retrieval_results or [])),
            },
        }

    def build_memory_runtime_view(self, **_kwargs):
        return {"view_id": "memview:test", "state_snapshot": {}}


def test_explicit_task_selection_suppresses_nested_rag_resolution() -> None:
    chain = AgentRuntimeChainAssembler(
        base_dir=BACKEND_DIR,
        memory_facade=_MemoryFacadeStub(),
    )
    profile = AgentRuntimeRegistry(BACKEND_DIR).get_profile("agent:world_designer_a")
    task_selection = {
        "selected_task_id": "task.writing_team.long_novel.world_designer_a",
        "task_id": "task.writing_team.long_novel.world_designer_a",
        "agent_id": "agent:world_designer_a",
        "coordination_run_id": "coordrun:test",
        "continuation_stage_id": "world_designer_a",
        "stage_execution_request": {"node_id": "world_designer_a"},
    }

    runtime = chain.build_runtime(
        session_id="test-explicit-task-boundary",
        task_id="taskinst:turn:test:world_designer_a",
        turn_id="turn:test",
        message="本轮工作：世界观设计。小说名为《洪荒时代》。主角是一名来自大泽的少年。",
        source="test",
        task_selection=task_selection,
        current_turn_context_override=task_selection,
        agent_runtime_profile=profile,
    )

    task_operation = dict(runtime.get("task_operation") or {})
    understanding = dict(task_operation.get("query_understanding") or {})
    resolution = capability_resolution_view(understanding)
    execution_shape = dict(task_operation.get("execution_shape") or {})
    recipe = dict(task_operation.get("selected_recipe") or {})

    assert understanding["route"] == "agent"
    assert understanding["execution_posture"] == "task_runtime"
    assert understanding["should_skip_rag"] is True
    assert resolution.route == "agent"
    assert resolution.execution_posture == "task_runtime"
    assert resolution.preferred_skill == ""
    assert execution_shape["recipe_preset_id"] != "template.rag.knowledge_answer"
    assert "rag_execution_posture" not in list(execution_shape.get("resolution_reasons") or [])
    assert recipe["execution_kind"] == "task_runtime"


def test_coordination_task_context_retrieval_requires_explicit_permission() -> None:
    task_operation = {
        "query_understanding": {"should_skip_rag": True},
        "current_turn_context": {
            "coordination_run_id": "coordrun:test",
            "continuation_stage_id": "world_designer_a",
        },
        "operation_requirement": {
            "required_operations": ["op.model_response"],
        },
        "selected_recipe": {"source_kind": "knowledge"},
    }

    assert not _task_operation_allows_context_retrieval(
        task_operation=task_operation,
        allowed_search_sources={"rag"},
    )
