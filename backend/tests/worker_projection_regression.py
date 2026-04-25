from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.context_models import MainContextState
from query.evidence_models import BindingCandidate
from query.worker_models import CanonicalResult, WorkerResult
from query.worker_projection import WorkerProjectionAdapter


def test_structured_canonical_result_projects_dataset_binding_to_session_context() -> None:
    projection = WorkerProjectionAdapter().project_done_event(
        query="查询哪些城市缺货",
        canonical_result=CanonicalResult(
            result_kind="structured_answer",
            ok=True,
            answer="数据源：inventory.xlsx 缺货城市：武汉、上海。",
            bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
            artifact_refs=["inventory-summary"],
            projection_policy="persist_canonical",
        ),
        worker_result=WorkerResult(worker_name="structured_data"),
        previous_main_context=MainContextState(active_goal="查询哪些城市缺货"),
    )

    assert projection.memory_policy == "session_context_only"
    assert projection.main_context.active_constraints["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"
    assert projection.main_context.active_constraints["source_kind"] == "dataset"
    assert projection.main_context.active_binding_identity == "knowledge/e-commerce data/inventory.xlsx"
    assert projection.main_context.followup_binding_key == "active_dataset"
    assert projection.task_summary_refs
    assert projection.task_summary_refs[0].task_kind == "structured_data"
    assert "dataset=knowledge/E-commerce Data/inventory.xlsx" in projection.task_summary_refs[0].key_points
    assert "artifact=inventory-summary" in projection.task_summary_refs[0].key_points


def test_candidate_clarification_does_not_project_stable_task_summary() -> None:
    projection = WorkerProjectionAdapter().project_done_event(
        query="查询本地数据库缺货",
        canonical_result=CanonicalResult(
            result_kind="rag_candidate_clarification",
            ok=False,
            answer="找到 inventory.xlsx，请确认。",
            projection_policy="do_not_persist",
            degraded_reason="candidate_needs_binding",
        ),
        worker_result=WorkerResult(
            worker_name="retrieval",
            binding_candidates=[
                BindingCandidate(
                    candidate_id="cand:dataset:1",
                    kind="dataset",
                    identity="knowledge/E-commerce Data/inventory.xlsx",
                )
            ],
        ),
        previous_main_context=MainContextState(active_goal="查询本地数据库缺货"),
    )

    assert projection.memory_policy == "do_not_persist"
    assert projection.task_summary_refs == []
    assert projection.candidate_refs == ["cand:dataset:1"]
    assert "active_dataset" not in projection.main_context.active_constraints


def test_degraded_result_does_not_project_summary_even_with_binding() -> None:
    projection = WorkerProjectionAdapter().project_done_event(
        query="分析库存表",
        canonical_result=CanonicalResult(
            result_kind="structured_answer",
            ok=False,
            answer="结构化数据分析未形成可展示结果。",
            bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
            projection_policy="do_not_persist",
            degraded_reason="structured_analysis_missing_answer",
        ),
        worker_result=WorkerResult(worker_name="structured_data"),
        previous_main_context=MainContextState(active_goal="分析库存表"),
    )

    assert projection.memory_policy == "do_not_persist"
    assert projection.task_summary_refs == []
    assert projection.main_context.active_constraints["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"


def main() -> None:
    test_structured_canonical_result_projects_dataset_binding_to_session_context()
    test_candidate_clarification_does_not_project_stable_task_summary()
    test_degraded_result_does_not_project_summary_even_with_binding()
    print("ALL PASSED (worker projection)")


if __name__ == "__main__":
    main()
