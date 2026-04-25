from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.evidence_adapter import build_evidence_envelope_from_retrieval
from query.models import QueryPlan
from query.planner import QueryPlanner
from query.runtime import QueryRuntime
from query.worker_models import CanonicalResult, WorkerExecutionPlan, WorkerRequest, WorkerResult
from runtime.session_store import SessionManager
from tasks import TaskCoordinator
from understanding import MemoryIntent, QueryUnderstanding


class _RegistryStub:
    def resolve_candidate_names(self, **_kwargs):
        return ["search_knowledge"]

    def select_best(self, *_args, **_kwargs):
        return None


class _ToolRuntimeStub:
    def __init__(self, *, direct_tools: dict[str, object] | None = None) -> None:
        self.registry = _RegistryStub()
        self.instances = [SimpleNamespace(name="search_knowledge")]
        self._direct_tools = dict(direct_tools or {})

    def get_instance(self, name):
        return self._direct_tools.get(str(name or ""))


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


class _RetrievalStub:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str, *, top_k: int = 5):
        self.queries.append(query)
        return [
            {
                "text": "inventory.xlsx 记录了各城市仓库库存、缺口和补货优先级，可用于判断缺货情况。",
                "source": "knowledge/E-commerce Data/inventory.xlsx",
                "score": 0.91,
                "metadata": {"block_id": "inventory-summary", "result_granularity": "block"},
            },
            {
                "text": "库存表字段包含城市、仓库、当前库存、缺口，适合继续交给结构化数据分析。",
                "source": "knowledge/E-commerce Data/inventory.xlsx",
                "score": 0.83,
                "metadata": {"block_id": "inventory-fields", "result_granularity": "block"},
            },
        ][:top_k]


class _DocumentRetrievalStub:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str, *, top_k: int = 5):
        self.queries.append(query)
        return [
            {
                "text": "2025年AI治理报告：回归现实主义.pdf 是一份可继续阅读的本地 PDF。",
                "source": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "score": 0.88,
                "metadata": {"block_id": "ai-governance-report-summary", "result_granularity": "block"},
            }
        ][:top_k]


class _TableRetrievalStub:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str, *, top_k: int = 5):
        self.queries.append(query)
        return [
            {
                "text": "inventory.xlsx 的库存表包含城市、仓库、当前库存、缺口字段。",
                "source": "knowledge/E-commerce Data/inventory.xlsx",
                "score": 0.9,
                "metadata": {
                    "block_id": "inventory-table",
                    "block_type": "table",
                    "result_granularity": "block",
                    "columns": ["城市", "仓库", "当前库存", "缺口"],
                },
            }
        ][:top_k]


class _PDFWorkerStub:
    def __init__(self) -> None:
        self.requests: list[WorkerRequest] = []

    async def run(self, request: WorkerRequest) -> WorkerResult:
        self.requests.append(request)
        active_pdf = str(request.bindings.get("active_pdf", "") or "")
        return WorkerResult(
            worker_name="pdf",
            status="ok",
            canonical_result=CanonicalResult(
                result_kind="pdf_answer",
                ok=True,
                answer="文档要点：AI 治理报告强调回归现实主义。",
                bindings={
                    "active_pdf": active_pdf,
                    "active_pdf_pages": [1],
                    "active_pdf_mode": "document",
                },
                artifact_refs=[f"{active_pdf}#page=1"],
                projection_policy="persist_canonical",
                diagnostics={"answer_source": "pdf_worker"},
            ),
        )


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.agent_created = False
        self.invoke_messages_calls: list[list[dict[str, str]]] = []

    def create_conversation_agent(self, **_kwargs):
        self.agent_created = True
        raise AssertionError("worker execution must not create main agent")

    async def invoke_messages(self, messages: list[dict[str, str]]):
        self.invoke_messages_calls.append(list(messages))
        return SimpleNamespace(content="本地资料命中了 inventory.xlsx；它包含城市、仓库、库存和缺口字段，适合继续做结构化缺货分析。")


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


def test_evidence_adapter_promotes_retrieval_source_to_dataset_candidate() -> None:
    envelope = build_evidence_envelope_from_retrieval(
        query="查询缺货情况",
        retrieval_results=[
            {
                "text": "库存缺口数据来自 inventory.xlsx。",
                "source": "knowledge/E-commerce Data/inventory.xlsx",
                "score": 0.9,
                "metadata": {"block_id": "inventory-summary"},
            }
        ],
    )

    assert len(envelope.dataset_candidates) == 1
    assert envelope.dataset_candidates[0].path == "knowledge/E-commerce Data/inventory.xlsx"
    assert envelope.dataset_candidates[0].artifact_id == "inventory-summary"
    assert envelope.source_objects[0].object_type == "dataset"
    assert envelope.derived_artifacts[0].artifact_type == "dataset_summary"


def test_planner_promotes_direct_rag_to_worker_execution_plan() -> None:
    planner = QueryPlanner(
        base_dir=BACKEND_DIR,
        skill_registry=None,
        tool_runtime=_ToolRuntimeStub(),
    )
    plan = planner.build_plan(
        session_id="planner-worker-session",
        message="你可以查询本地数据库里面，有哪些城市缺货嘛",
        history=[],
    )
    execution = plan.iter_executions()[0]

    assert execution.execution_kind == "worker"
    assert execution.worker_plan is not None
    assert execution.worker_plan.worker_route == "retrieval"
    assert execution.worker_plan.request is not None
    assert execution.worker_plan.request.query == "你可以查询本地数据库里面，有哪些城市缺货嘛"


def test_runtime_worker_branch_runs_retrieval_without_main_agent_or_search_tool() -> None:
    query = "你可以查询本地数据库里面，有哪些城市缺货嘛"
    retrieval = _RetrievalStub()
    model_runtime = _ModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=TaskCoordinator(),
    )
    worker_request = WorkerRequest(
        request_id="worker:retrieval:main",
        query=query,
        worker_route="retrieval",
        task_frame={"route": "rag", "capability_requests": ["knowledge_lookup"]},
    )
    plan = QueryPlan(
        session_id="runtime-worker-session",
        message=query,
        history=[],
        subqueries=[query],
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
            request=worker_request,
            expected_result="evidence",
            fallback_execution_kind="agent",
            cutover_mode="primary",
        ),
    )
    runtime.planner.build_plan = lambda *, session_id, message, history, **_kwargs: plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = next(event for event in reversed(events) if event.get("type") == "done")

    assert retrieval.queries == [query]
    assert model_runtime.agent_created is False
    assert any(event.get("type") == "worker_evidence" for event in events)
    assert any(event.get("type") == "worker_artifacts" for event in events)
    assert done["answer_source"] == "rag_answer_finalization"
    assert "inventory.xlsx" in str(done["content"])
    assert done["binding_candidate_refs"] == ["cand:dataset:1"]
    assert done["binding_candidates"][0]["identity"] == "knowledge/E-commerce Data/inventory.xlsx"


def test_candidate_confirmation_turn_runs_structured_worker_from_previous_retrieval_candidate() -> None:
    first_query = "你可以查询本地数据库里面，有哪些城市缺货嘛"
    structured_calls: list[dict[str, object]] = []

    def _structured_invoke(tool_input: dict[str, object]) -> str:
        structured_calls.append(dict(tool_input))
        return "数据源：inventory.xlsx 缺货城市：武汉、上海、深圳。"

    retrieval = _RetrievalStub()
    model_runtime = _ModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(direct_tools={"structured_data_analysis": SimpleNamespace(invoke=_structured_invoke)}),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=TaskCoordinator(),
    )

    def _plan_for(message: str) -> QueryPlan:
        if message == first_query:
            return QueryPlan(
                session_id="candidate-session",
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
                        query=first_query,
                        worker_route="retrieval",
                        task_frame={"route": "rag", "capability_requests": ["knowledge_lookup"]},
                    ),
                    expected_result="evidence",
                ),
            )
        return QueryPlan(
            session_id="candidate-session",
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

    async def _run(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution("candidate-session", message, []):
            events.append(event)
        return events

    asyncio.run(_run(first_query))
    events = asyncio.run(_run("是销售数据库"))
    done = next(event for event in reversed(events) if event.get("type") == "done")
    structured_evidence = next(
        event
        for event in events
        if event.get("type") == "worker_evidence" and event.get("worker") == "structured_data"
    )
    structured_artifacts = next(
        event
        for event in events
        if event.get("type") == "worker_artifacts"
        and event.get("graph_delta", {}).get("artifacts", [{}])[0].get("artifact_type") == "dataset_analysis"
    )

    assert structured_calls == [
        {
            "query": first_query,
            "path": "knowledge/E-commerce Data/inventory.xlsx",
        }
    ]
    assert structured_evidence["evidence"]["source_objects"][0]["object_type"] == "dataset"
    assert structured_artifacts["graph_delta"]["artifacts"][0]["artifact_type"] == "dataset_analysis"
    assert done["answer_source"] == "structured_data_worker"
    assert "缺货城市" in str(done["content"])
    assert done["committed_bindings"]["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"
    assert done["main_context"]["active_constraints"]["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"
    assert done["main_context"]["followup_binding_key"] == "active_dataset"
    assert done["task_summary_refs"][0]["task_kind"] == "structured_data"
    assert "dataset=knowledge/E-commerce Data/inventory.xlsx" in done["task_summary_refs"][0]["key_points"]
    assert done["memory_policy"] == "session_context_only"


def test_document_candidate_confirmation_turn_runs_pdf_worker_from_previous_retrieval_candidate() -> None:
    first_query = "帮我找一下 AI 治理报告"
    retrieval = _DocumentRetrievalStub()
    model_runtime = _ModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=TaskCoordinator(),
    )
    pdf_worker = _PDFWorkerStub()
    runtime.evidence_orchestrator.pdf_worker = pdf_worker

    def _plan_for(message: str) -> QueryPlan:
        if message == first_query:
            return QueryPlan(
                session_id="document-candidate-session",
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
                        query=first_query,
                        worker_route="retrieval",
                        task_frame={"route": "rag", "capability_requests": ["knowledge_lookup"]},
                    ),
                    expected_result="evidence",
                ),
            )
        return QueryPlan(
            session_id="document-candidate-session",
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

    async def _run(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution("document-candidate-session", message, []):
            events.append(event)
        return events

    first_events = asyncio.run(_run(first_query))
    first_done = next(event for event in reversed(first_events) if event.get("type") == "done")
    events = asyncio.run(_run("knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"))
    done = next(event for event in reversed(events) if event.get("type") == "done")

    assert first_done["binding_candidate_refs"] == ["cand:document:1"]
    assert len(pdf_worker.requests) == 1
    assert pdf_worker.requests[0].worker_route == "pdf"
    assert pdf_worker.requests[0].bindings["active_pdf"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    assert done["answer_source"] == "pdf_worker"
    assert "AI 治理报告" in str(done["content"])
    assert done["committed_bindings"]["active_pdf"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    assert done["main_context"]["followup_binding_key"] == "active_pdf"
    assert done["main_context"]["active_constraints"]["active_pdf_mode"] == "document"
    assert done["task_summary_refs"][0]["task_kind"] == "pdf"
    assert done["memory_policy"] == "session_context_only"


def test_table_candidate_confirmation_turn_runs_structured_worker_with_resolved_dataset_source() -> None:
    first_query = "本地库存表里哪些城市缺货"
    structured_calls: list[dict[str, object]] = []

    def _structured_invoke(tool_input: dict[str, object]) -> str:
        structured_calls.append(dict(tool_input))
        return "数据源：inventory.xlsx 缺货城市：武汉、上海。"

    retrieval = _TableRetrievalStub()
    model_runtime = _ModelRuntimeStub()
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(direct_tools={"structured_data_analysis": SimpleNamespace(invoke=_structured_invoke)}),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=TaskCoordinator(),
    )

    def _plan_for(message: str) -> QueryPlan:
        if message == first_query:
            return QueryPlan(
                session_id="table-candidate-session",
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
                        query=first_query,
                        worker_route="retrieval",
                        task_frame={"route": "rag", "capability_requests": ["knowledge_lookup"]},
                    ),
                    expected_result="evidence",
                ),
            )
        return QueryPlan(
            session_id="table-candidate-session",
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

    async def _run(message: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution("table-candidate-session", message, []):
            events.append(event)
        return events

    first_events = asyncio.run(_run(first_query))
    first_done = next(event for event in reversed(first_events) if event.get("type") == "done")
    events = asyncio.run(_run("cand:table:1"))
    done = next(event for event in reversed(events) if event.get("type") == "done")

    assert "cand:dataset:1" in first_done["binding_candidate_refs"]
    assert "cand:table:1" in first_done["binding_candidate_refs"]
    assert structured_calls == [
        {
            "query": first_query,
            "path": "knowledge/E-commerce Data/inventory.xlsx",
        }
    ]
    assert done["answer_source"] == "structured_data_worker"
    assert done["committed_bindings"]["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"
    assert done["committed_bindings"]["active_table"] == "inventory-table"
    assert done["main_context"]["active_constraints"]["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"
    assert done["main_context"]["active_constraints"]["active_table"] == "inventory-table"
    assert "table=inventory-table" in done["task_summary_refs"][0]["key_points"]


def test_candidate_and_graph_state_restore_from_session_runtime_state() -> None:
    first_query = "你可以查询本地数据库里面，有哪些城市缺货嘛"
    structured_calls: list[dict[str, object]] = []

    def _structured_invoke(tool_input: dict[str, object]) -> str:
        structured_calls.append(dict(tool_input))
        return "数据源：inventory.xlsx 缺货城市：武汉、上海。"

    with tempfile.TemporaryDirectory() as tmp:
        session_manager = SessionManager(Path(tmp))
        session_id = "candidate-runtime-state-session"
        runtime1 = QueryRuntime(
            base_dir=BACKEND_DIR,
            settings_service=_SettingsStub(),
            session_manager=session_manager,
            memory_facade=_MemoryFacadeStub(),
            retrieval_service=_RetrievalStub(),
            tool_runtime=_ToolRuntimeStub(),
            skill_registry=_SkillRegistryStub(),
            permission_service=_PermissionStub(),
            model_runtime=_ModelRuntimeStub(),
            task_coordinator=TaskCoordinator(),
        )
        runtime2 = QueryRuntime(
            base_dir=BACKEND_DIR,
            settings_service=_SettingsStub(),
            session_manager=session_manager,
            memory_facade=_MemoryFacadeStub(),
            retrieval_service=_RetrievalStub(),
            tool_runtime=_ToolRuntimeStub(direct_tools={"structured_data_analysis": SimpleNamespace(invoke=_structured_invoke)}),
            skill_registry=_SkillRegistryStub(),
            permission_service=_PermissionStub(),
            model_runtime=_ModelRuntimeStub(),
            task_coordinator=TaskCoordinator(),
        )

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

        runtime1.planner.build_plan = lambda *, session_id, message, history, **_kwargs: _plan_for(message)  # type: ignore[method-assign]
        runtime2.planner.build_plan = lambda *, session_id, message, history, **_kwargs: _plan_for(message)  # type: ignore[method-assign]

        async def _run(runtime: QueryRuntime, message: str) -> list[dict[str, object]]:
            events: list[dict[str, object]] = []
            async for event in runtime._stream_single_execution(session_id, message, []):
                events.append(event)
            return events

        asyncio.run(_run(runtime1, first_query))
        persisted = session_manager.get_runtime_state(session_id, "evidence_state")
        assert persisted["binding_candidates"]["candidates"][0]["candidate_id"] == "cand:dataset:1"
        assert persisted["evidence_graph"]["artifacts"]

        events = asyncio.run(_run(runtime2, "是销售数据库"))
        done = next(event for event in reversed(events) if event.get("type") == "done")

        assert structured_calls == [{"query": first_query, "path": "knowledge/E-commerce Data/inventory.xlsx"}]
        assert done["answer_source"] == "structured_data_worker"
        assert done["committed_bindings"]["active_dataset"] == "knowledge/E-commerce Data/inventory.xlsx"


def main() -> None:
    test_evidence_adapter_promotes_retrieval_source_to_dataset_candidate()
    test_planner_promotes_direct_rag_to_worker_execution_plan()
    test_runtime_worker_branch_runs_retrieval_without_main_agent_or_search_tool()
    test_candidate_confirmation_turn_runs_structured_worker_from_previous_retrieval_candidate()
    test_document_candidate_confirmation_turn_runs_pdf_worker_from_previous_retrieval_candidate()
    test_table_candidate_confirmation_turn_runs_structured_worker_with_resolved_dataset_source()
    test_candidate_and_graph_state_restore_from_session_runtime_state()
    print("ALL PASSED (evidence worker runtime regression)")


if __name__ == "__main__":
    main()
