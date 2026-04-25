from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.models import QueryPlan
from query.runtime import QueryRuntime
from query.worker_models import WorkerExecutionPlan, WorkerRequest
from tasks import TaskCoordinator
from understanding import MemoryIntent, QueryUnderstanding


class _RegistryStub:
    def resolve_candidate_names(self, **_kwargs):
        return ["search_knowledge"]

    def select_best(self, *_args, **_kwargs):
        return None


class _ToolRuntimeStub:
    def __init__(self, *, structured_tool=None) -> None:
        self.registry = _RegistryStub()
        self.instances = [SimpleNamespace(name="search_knowledge")]
        self.structured_tool = structured_tool

    def get_instance(self, name):
        if name == "structured_data_analysis":
            return self.structured_tool
        return None


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return True


class _MemoryFacadeStub:
    def compact_history_for_query(self, _session_id, history):
        return history, {"pressure_level": "normal"}

    def inspect_query_context(self, *_args, **_kwargs):
        return {}

    def build_context_package(self, *_args, **_kwargs):
        return None

    def build_persistent_memory_block(self, **_kwargs):
        return ""


class _ModelRuntimeStub:
    def create_conversation_agent(self, **_kwargs):
        raise AssertionError("worker execution must not create main agent")

    async def invoke_messages(self, _messages):
        return SimpleNamespace(content="")


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=True, reason="")


class _SkillRegistryStub:
    def format_active_skill_block(self, _active_skill):
        return None

    def get_by_name(self, _name):
        return None


class _PdfTableRetrievalStub:
    def __init__(self, *, table_text: str) -> None:
        self.table_text = table_text

    def retrieve(self, _query: str, *, top_k: int = 5):
        return [
            {
                "text": self.table_text,
                "source": "knowledge/reports/inventory-report.pdf",
                "score": 0.87,
                "metadata": {
                    "block_id": "pdf-table-block",
                    "block_type": "table",
                    "page": 3,
                    "columns": ["城市", "缺口"],
                },
            }
        ][:top_k]


def _runtime(*, retrieval, structured_tool=None) -> QueryRuntime:
    return QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(structured_tool=structured_tool),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
        task_coordinator=TaskCoordinator(),
    )


def _install_plan(runtime: QueryRuntime, *, session_id: str, first_query: str) -> None:
    def _plan_for(message: str) -> QueryPlan:
        if message == first_query:
            return QueryPlan(
                session_id=session_id,
                message=first_query,
                history=[],
                subqueries=[first_query],
                memory_intent=MemoryIntent(),
                query_understanding=QueryUnderstanding(
                    intent="knowledge_lookup_query",
                    route="rag",
                    modality="general",
                    should_skip_rag=False,
                    execution_posture="direct_rag",
                    capability_requests=["knowledge_lookup"],
                ),
                execution_kind="worker",
                worker_plan=WorkerExecutionPlan(
                    worker_route="retrieval",
                    request=WorkerRequest(
                        request_id="worker:retrieval:main",
                        session_id=session_id,
                        query=first_query,
                        worker_route="retrieval",
                        task_frame={"route": "rag", "capability_requests": ["knowledge_lookup"]},
                    ),
                    expected_result="evidence",
                ),
            )
        return QueryPlan(
            session_id=session_id,
            message=message,
            history=[],
            subqueries=[message],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(
                intent="general_query",
                route="agent",
                execution_posture="bounded_agent",
                capability_requests=["knowledge_lookup"],
            ),
        )

    runtime.planner.build_plan = lambda *, session_id, message, history, **_kwargs: _plan_for(message)  # type: ignore[method-assign]


async def _run(runtime: QueryRuntime, *, session_id: str, message: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    async for event in runtime._stream_single_execution(session_id, message, []):
        events.append(event)
    return events


def test_pdf_table_candidate_materializes_csv_before_structured_worker() -> None:
    session_id = "pdf-table-materialize-session"
    first_query = "分析 PDF 第三页表格的缺货城市"
    structured_calls: list[dict[str, object]] = []

    def _structured_invoke(tool_input: dict[str, object]) -> str:
        structured_calls.append(dict(tool_input))
        path = BACKEND_DIR / str(tool_input["path"])
        assert path.exists()
        assert "武汉" in path.read_text(encoding="utf-8-sig")
        return "数据源：PDF 表格 缺货城市：武汉、上海。"

    runtime = _runtime(
        retrieval=_PdfTableRetrievalStub(
            table_text="| 城市 | 缺口 |\n| --- | --- |\n| 武汉 | 12 |\n| 上海 | 8 |"
        ),
        structured_tool=SimpleNamespace(invoke=_structured_invoke),
    )
    _install_plan(runtime, session_id=session_id, first_query=first_query)

    try:
        first_events = asyncio.run(_run(runtime, session_id=session_id, message=first_query))
        first_done = next(event for event in reversed(first_events) if event.get("type") == "done")
        events = asyncio.run(_run(runtime, session_id=session_id, message="cand:table:1"))
        done = next(event for event in reversed(events) if event.get("type") == "done")

        assert "cand:table:1" in first_done["binding_candidate_refs"]
        assert len(structured_calls) == 1
        assert str(structured_calls[0]["path"]).startswith("output/evidence_artifacts/tables/")
        assert structured_calls[0]["query"] == first_query
        assert done["answer_source"] == "structured_data_worker"
        assert done["committed_bindings"]["active_table"] == "pdf-table-block"
        assert done["committed_bindings"]["active_dataset"] == structured_calls[0]["path"]
        assert done["main_context"]["active_constraints"]["active_dataset"] == structured_calls[0]["path"]
    finally:
        shutil.rmtree(BACKEND_DIR / "output" / "evidence_artifacts" / "tables" / session_id, ignore_errors=True)


def test_pdf_table_candidate_without_table_rows_fails_closed() -> None:
    session_id = "pdf-table-unmaterialized-session"
    first_query = "分析 PDF 表格"

    def _structured_invoke(_tool_input: dict[str, object]) -> str:
        raise AssertionError("unmaterialized pdf table must not invoke structured worker tool")

    runtime = _runtime(
        retrieval=_PdfTableRetrievalStub(table_text="这一段只说明 PDF 中可能存在表格，但没有可物化的行列内容。"),
        structured_tool=SimpleNamespace(invoke=_structured_invoke),
    )
    _install_plan(runtime, session_id=session_id, first_query=first_query)

    first_events = asyncio.run(_run(runtime, session_id=session_id, message=first_query))
    first_done = next(event for event in reversed(first_events) if event.get("type") == "done")
    events = asyncio.run(_run(runtime, session_id=session_id, message="cand:table:1"))
    done = next(event for event in reversed(events) if event.get("type") == "done")

    assert "cand:table:1" in first_done["binding_candidate_refs"]
    assert done["answer_source"] == "structured_data_worker"
    assert done["answer_persist_policy"] == "do_not_persist"
    assert done["committed_bindings"]["active_table"] == "pdf-table-block"
    assert "还没有可直接分析的数据文件" in str(done["content"])


def main() -> None:
    test_pdf_table_candidate_materializes_csv_before_structured_worker()
    test_pdf_table_candidate_without_table_rows_fails_closed()
    print("ALL PASSED (pdf table to structured worker regression)")


if __name__ == "__main__":
    main()
