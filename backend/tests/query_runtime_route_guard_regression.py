from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pdf_agent import PDFCanonicalEvidence, PDFCanonicalResult
from memory.messages import MemoryMessageAdapter
from query import QueryRuntime
from query.binding_models import StructuredDatasetBinding
from query.followup_models import FollowupResolution
from query.runtime_followup import RuntimeFollowupCoordinator
from query.followup_resolver import QueryFollowupResolver
from query.models import QueryExecutionPlan, QueryPlan
from query.worker_models import CanonicalResult, WorkerExecutionPlan, WorkerRequest, WorkerResult
from runtime.model_runtime import ModelRuntimeError
from tasks import TaskCoordinator
from understanding import MemoryIntent, QueryUnderstanding


class _FakeAgent:
    def __init__(self, recorder: dict[str, object]) -> None:
        self.recorder = recorder

    async def astream(self, *_args, **_kwargs):
        if _args:
            self.recorder["last_stream_payload"] = _args[0]
        self.recorder["stream_called"] = True
        yield ("messages", (SimpleNamespace(content="route-safe answer"), {}))


class _ScriptedAgent:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self._events = events

    async def astream(self, *_args, **_kwargs):
        for item in self._events:
            yield item


class _SettingsStub:
    def __init__(self, *, rag_mode: bool) -> None:
        self._rag_mode = rag_mode

    def get_rag_mode(self) -> bool:
        return self._rag_mode


class _SessionStateStub:
    def __init__(self, **context_slots: object) -> None:
        defaults = {
            "active_pdf": "",
            "active_dataset": "",
            "active_binding_owner_task_id": "",
            "committed_pdf": "",
            "committed_pdf_owner_task_id": "",
            "committed_dataset": "",
            "committed_dataset_owner_task_id": "",
        }
        defaults.update(context_slots)
        self.context_slots = SimpleNamespace(**defaults)
        self.flow_state = SimpleNamespace(flow_type="general_problem_solving_flow", confidence=1.0)
        self.risk_flags: list[str] = []
        self.risk_notes: list[str] = []


class _ContextPackageStub:
    def __init__(self, sections: dict[str, list[str]]) -> None:
        self.sections = {name: list(items) for name, items in sections.items()}
        self.model_visible_sections = {name: list(items) for name, items in sections.items()}
        self.debug_sections = {name: list(items) for name, items in sections.items()}
        self.selected_sections = [name for name, items in self.model_visible_sections.items() if items]
        self.debug_selected_sections = [name for name, items in self.debug_sections.items() if items]

    def sections_for(self, mode: str = "model") -> dict[str, list[str]]:
        return self.debug_sections if mode == "debug" else self.model_visible_sections


class _MemoryFacadeStub:
    def __init__(
        self,
        *,
        session_state: _SessionStateStub | None = None,
        context_package: _ContextPackageStub | None = None,
    ) -> None:
        self.prefetch_queries: list[str] = []
        self.persistent_queries: list[str] = []
        self.adapter = MemoryMessageAdapter()
        self._session_state = session_state or _SessionStateStub()
        self._context_package = context_package
        self.session_memory = SimpleNamespace(
            manager=lambda _session_id: SimpleNamespace(
                load_state=lambda: self._session_state,
                preview_state=lambda _messages: self._session_state,
            )
        )

    def compact_history_for_query(self, _session_id: str, history: list[dict[str, object]]):
        return history, {"pressure_level": "normal"}

    def inspect_query_context(self, *_args, **_kwargs):
        return {}

    def build_context_package(self, *_args, **_kwargs):
        return self._context_package

    def build_persistent_memory_block(self, *, query=None, **_kwargs):
        if isinstance(query, str) and query:
            self.persistent_queries.append(query)
        return ""

    def prefetch_relevant_notes(self, query, *_args, **_kwargs):
        self.prefetch_queries.append(str(query))
        return []


class _RetrievalStub:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, query: str, *, top_k: int = 5):
        self.queries.append(query)
        return [{"text": "retrieved evidence", "top_k": top_k}]


class _PDFWorkerStub:
    def __init__(
        self,
        *,
        answer: str = "第二部分强调先划清权限边界，再明确审计归口。",
        ok: bool = True,
        degraded_reason: str = "",
    ) -> None:
        self.answer = answer
        self.ok = ok
        self.degraded_reason = degraded_reason
        self.requests: list[WorkerRequest] = []

    async def run(self, request: WorkerRequest) -> WorkerResult:
        self.requests.append(request)
        active_pdf = str(
            request.bindings.get("active_pdf")
            or request.constraints.get("active_pdf")
            or request.constraints.get("path")
            or "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
        )
        return WorkerResult(
            worker_name="pdf",
            status="ok" if self.ok else "degraded",
            canonical_result=CanonicalResult(
                result_kind="pdf_answer",
                ok=self.ok,
                answer=self.answer,
                bindings={
                    "active_pdf": active_pdf,
                    "active_pdf_pages": [3, 4],
                    "active_pdf_mode": str(request.constraints.get("mode") or "section"),
                },
                projection_policy="persist_canonical" if self.ok else "do_not_persist",
                degraded_reason="" if self.ok else self.degraded_reason or "pdf_missing_stable_answer",
                diagnostics={"answer_source": "pdf_worker"},
            ),
        )


class _ToolRuntimeStub:
    registry = None

    def __init__(self, *, direct_tools: dict[str, object] | None = None) -> None:
        self.instances = [
            SimpleNamespace(name="search_knowledge"),
            SimpleNamespace(name="web_search"),
        ]
        self._direct_tools = dict(direct_tools or {})

    def get_instance(self, name: str | None):
        return self._direct_tools.get(str(name or ""))


class _SkillRegistryStub:
    def format_active_skill_block(self, _active_skill):
        return None

    def get_by_name(self, _name):
        return None

    def match_for_query(self, **_kwargs):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or ["search_knowledge", "web_search"])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=True, reason="")


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.last_tools: list[str] = []
        self.last_payload_messages: list[dict[str, str]] = []
        self.invoke_messages_calls: list[list[dict[str, str]]] = []
        self.invoke_messages_response: str = "模型改写答案"

    def create_conversation_agent(self, **kwargs):
        self.last_tools = [getattr(tool, "name", "") for tool in kwargs.get("tools", [])]
        recorder = {"tools": self.last_tools}
        agent = _FakeAgent(recorder)
        self._recorder = recorder
        return agent

    async def invoke_messages(self, messages: list[dict[str, str]]):
        self.invoke_messages_calls.append(list(messages))
        return SimpleNamespace(content=self.invoke_messages_response)


def _promote_rag_plan_to_retrieval_worker(plan: QueryPlan) -> QueryPlan:
    request = WorkerRequest(
        request_id="worker:retrieval:test",
        session_id=plan.session_id,
        query=plan.message,
        worker_route="retrieval",
        task_frame={"route": "rag", "capability_requests": ["knowledge_lookup"]},
    )
    plan.execution_kind = "worker"
    plan.worker_plan = WorkerExecutionPlan(
        worker_route="retrieval",
        request=request,
        expected_result="evidence",
        fallback_execution_kind="none",
        cutover_mode="primary",
    )
    return plan


def _build_runtime(
    *,
    rag_mode: bool,
    direct_tools: dict[str, object] | None = None,
    task_coordinator=None,
    session_state: _SessionStateStub | None = None,
    context_package: _ContextPackageStub | None = None,
) -> tuple[QueryRuntime, _RetrievalStub, _ModelRuntimeStub, _MemoryFacadeStub]:
    retrieval = _RetrievalStub()
    model_runtime = _ModelRuntimeStub()
    memory_facade = _MemoryFacadeStub(session_state=session_state, context_package=context_package)
    runtime = QueryRuntime(
        base_dir=Path("."),
        settings_service=_SettingsStub(rag_mode=rag_mode),
        session_manager=SimpleNamespace(),
        memory_facade=memory_facade,
        retrieval_service=retrieval,
        tool_runtime=_ToolRuntimeStub(direct_tools=direct_tools),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=model_runtime,
        task_coordinator=task_coordinator or TaskCoordinator(),
    )
    return runtime, retrieval, model_runtime, memory_facade


def test_runtime_risk_gate_suppresses_weak_binding_followup() -> None:
    runtime, _, _, _ = _build_runtime(rag_mode=False)
    resolution = FollowupResolution(
        mode="binding_ref",
        target_kind="binding",
        resolved_target_kind="binding",
        binding_key="active_dataset",
        binding_kind="active_dataset",
        resolved_binding_kind="active_dataset",
        binding_identity="knowledge/e-commerce data/inventory.xlsx",
        resolved_binding_identity="knowledge/e-commerce data/inventory.xlsx",
        resolution_source="session_committed_binding",
    )

    guarded = runtime._guard_followup_resolution_by_runtime_risk(  # type: ignore[attr-defined]
        message="按部门汇总这些高薪员工。",
        followup_resolution=resolution,
        risk_snapshot={"risk_flags": ["cross_flow_slot_contamination"]},
    )

    assert guarded.mode == "none"
    assert guarded.reason == "runtime_risk_binding_suppressed"


def test_runtime_risk_gate_preserves_strong_pdf_anchor() -> None:
    runtime, _, _, _ = _build_runtime(rag_mode=False)
    resolution = FollowupResolution(
        mode="binding_ref",
        target_kind="binding",
        resolved_target_kind="binding",
        binding_key="active_pdf",
        binding_kind="active_pdf",
        resolved_binding_kind="active_pdf",
        binding_identity="knowledge/reports/ai治理报告.pdf",
        resolved_binding_identity="knowledge/reports/ai治理报告.pdf",
        resolution_source="session_committed_binding",
    )

    guarded = runtime._guard_followup_resolution_by_runtime_risk(  # type: ignore[attr-defined]
        message="回到刚才 PDF，第二部分的约束重点是什么？",
        followup_resolution=resolution,
        risk_snapshot={"risk_flags": ["cross_flow_slot_contamination"]},
    )

    assert guarded.mode == "binding_ref"
    assert guarded.resolved_binding_kind == "active_pdf"


async def _seed_compound_tasks(coordinator: TaskCoordinator) -> None:
    bundle_id = "session-1-bundle-seeded"
    executions = [
        QueryExecutionPlan(
            message="总结 PDF 第三页",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="pdf_analysis", task_kind="pdf_followup_query"),
            bundle_id=bundle_id,
            bundle_item_id=f"{bundle_id}-item-1",
            bundle_item_index=1,
        ),
        QueryExecutionPlan(
            message="给我 inventory.xlsx 里最缺货的前三个仓库",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
            bundle_id=bundle_id,
            bundle_item_id=f"{bundle_id}-item-2",
            bundle_item_index=2,
        ),
        QueryExecutionPlan(
            message="补一句北京天气",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="get_weather", task_kind="weather_query"),
            bundle_id=bundle_id,
            bundle_item_id=f"{bundle_id}-item-3",
            bundle_item_index=3,
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async for _event in coordinator.run_query_tasks("session-1", executions, runner):
        pass


async def _seed_session_summary_tasks(coordinator: TaskCoordinator) -> None:
    await coordinator.run_tool_task(
        "session-1",
        "pdf_analysis",
        lambda: asyncio.sleep(0, result={"answer": "answer for 总结 PDF 第三页"}),
        query="总结 PDF 第三页",
        tool_input={"query": "总结 PDF 第三页", "path": "knowledge/report.pdf", "mode": "page"},
        task_kind="pdf",
    )
    await coordinator.run_tool_task(
        "session-1",
        "structured_data_analysis",
        lambda: asyncio.sleep(0, result={"answer": "answer for 给我 inventory.xlsx 里最缺货的前三个仓库"}),
        query="给我 inventory.xlsx 里最缺货的前三个仓库",
        tool_input={
            "query": "给我 inventory.xlsx 里最缺货的前三个仓库",
            "path": "knowledge/E-commerce Data/inventory.xlsx",
        },
        task_kind="structured_data",
    )
    await coordinator.run_tool_task(
        "session-1",
        "get_weather",
        lambda: asyncio.sleep(0, result={"answer": "answer for 补一句北京天气"}),
        query="补一句北京天气",
        tool_input={"query": "补一句北京天气", "location": "北京"},
        task_kind="weather",
    )


async def _collect_events(
    plan: QueryPlan,
    *,
    rag_mode: bool,
    direct_tools: dict[str, object] | None = None,
    use_execution_events: bool = False,
    task_coordinator=None,
    context_package: _ContextPackageStub | None = None,
) -> tuple[list[dict[str, object]], _RetrievalStub, _ModelRuntimeStub, _MemoryFacadeStub]:
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=rag_mode,
        direct_tools=direct_tools,
        task_coordinator=task_coordinator,
        context_package=context_package,
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    events: list[dict[str, object]] = []
    stream = (
        runtime._execution_events(plan.session_id, plan.message, plan.history)
        if use_execution_events
        else runtime._stream_single_execution(plan.session_id, plan.message, plan.history)
    )
    async for event in stream:
        events.append(event)
    return events, retrieval, model_runtime, memory_facade


def test_memory_route_disables_tools() -> None:
    plan = QueryPlan(
        session_id="memory-session",
        message="把今天这几个任务分成 PDF、数据表、实时查询三段总结。",
        history=[{"role": "assistant", "content": "已有上下文"}],
        subqueries=["把今天这几个任务分成 PDF、数据表、实时查询三段总结。"],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert not any(event.get("type") == "tool_start" for event in events)


def test_session_summary_route_uses_structured_ledger_and_clears_runtime_hot_window() -> None:
    coordinator = TaskCoordinator()
    asyncio.run(_seed_session_summary_tasks(coordinator))
    context_package = _ContextPackageStub(
        {
            "active_process_context": ["# Active Goal\n- 回到 inventory.xlsx，哪个仓库最该先补货？"],
            "hot_truth_window": ["user: 回到 inventory.xlsx，哪个仓库最该先补货？"],
            "warm_snapshots": ["old snapshot"],
            "retrieval_evidence": ["old retrieval"],
            "exact_durable_context": [],
            "relevant_durable_context": [],
            "static_context": [],
        }
    )
    history = [
        {"role": "user", "content": "记住：回答复杂问题先给结论。"},
        {"role": "assistant", "content": "我记住了。"},
        {"role": "assistant", "content": "之前的局部任务结果。"},
    ]
    plan = QueryPlan(
        session_id="session-1",
        message="最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论。",
        history=history,
        subqueries=["最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论。"],
        memory_intent=MemoryIntent(intent="durable_memory_query", memory_read_mode="durable_exact", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            task_kind="session_summary",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )

    events, _retrieval, model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            task_coordinator=coordinator,
            context_package=context_package,
        )
    )

    stream_messages = list(getattr(model_runtime, "_recorder", {}).get("last_stream_payload", {}).get("messages", []))
    system_text = "\n\n".join(message["content"] for message in stream_messages if message["role"] == "system")
    non_system_messages = [message for message in stream_messages if message["role"] != "system"]

    assert "## Session Recap Ledger" in system_text
    assert "### PDF" in system_text
    assert "### 数据" in system_text
    assert "### 实时" in system_text
    assert "### 长期记忆" in system_text
    assert "总结 PDF 第三页" in system_text
    assert "inventory.xlsx 里最缺货的前三个仓库" in system_text
    assert "补一句北京天气" in system_text
    assert "记住：回答复杂问题先给结论。" in system_text
    assert "回到 inventory.xlsx，哪个仓库最该先补货？" not in system_text
    assert "old retrieval" not in system_text
    assert not any(message["role"] == "assistant" for message in non_system_messages)
    assert non_system_messages == [
        {
            "role": "user",
            "content": "最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论。",
        }
    ]
    assert events[-1]["content"] == "route-safe answer"


def test_direct_tool_pdf_without_path_is_blocked_by_contract_gate() -> None:
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "should not run"})
    plan = QueryPlan(
        session_id="pdf-contract-block",
        message="第四页讲了什么？",
        history=[],
        subqueries=["第四页讲了什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "第四页讲了什么？"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(plan, rag_mode=False, direct_tools={"pdf_analysis": tool})
    )

    assert not any(event.get("type") == "tool_start" for event in events)
    done = next(event for event in events if event.get("type") == "done")
    assert done["answer_source"] == "tool_contract_gate"
    assert done["answer_fallback_reason"] == "tool_contract_blocked"
    assert "需要先明确 PDF 文件 path" in str(done["content"])


def test_direct_tool_structured_without_path_is_blocked_by_contract_gate() -> None:
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "should not run"})
    plan = QueryPlan(
        session_id="structured-contract-block",
        message="按仓库统计哪些商品缺货",
        history=[],
        subqueries=["按仓库统计哪些商品缺货"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "按仓库统计哪些商品缺货"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(plan, rag_mode=False, direct_tools={"structured_data_analysis": tool})
    )

    assert not any(event.get("type") == "tool_start" for event in events)
    done = next(event for event in events if event.get("type") == "done")
    assert done["answer_source"] == "tool_contract_gate"
    assert done["answer_fallback_reason"] == "tool_contract_blocked"
    assert "需要先明确数据文件 path" in str(done["content"])


def test_workspace_file_read_direct_route_invokes_read_file_with_normalized_path() -> None:
    recorder: list[dict[str, object]] = []

    def _invoke(tool_input: dict[str, object]) -> str:
        recorder.append(dict(tool_input))
        return "from __future__ import annotations"

    tool = SimpleNamespace(invoke=_invoke)
    plan = QueryPlan(
        session_id="workspace-read-session",
        message="打开 backend/understanding/task_understanding.py 给我看看源码",
        history=[],
        subqueries=["打开 backend/understanding/task_understanding.py 给我看看源码"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="workspace_file_read_query",
            route="tool",
            modality="code",
            tool_name="read_file",
            task_kind="workspace_file_read",
            should_skip_rag=True,
            tool_input={"path": "backend/understanding/task_understanding.py"},
        ),
        active_skill=None,
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"read_file": tool},
            use_execution_events=True,
        )
    )

    assert any(event.get("type") == "tool_start" and event.get("tool") == "read_file" for event in events)
    assert recorder == [{"path": "backend/understanding/task_understanding.py"}]
    done = next(event for event in reversed(events) if event.get("type") == "done")
    assert done["answer_source"] == "direct_tool.read_file"
    assert done["content"] == "from __future__ import annotations"


def test_non_worker_rag_route_does_not_run_direct_retrieval() -> None:
    query = "为我搜索本地的数据库，看看有没有缺货情况"
    plan = QueryPlan(
        session_id="rag-session",
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
            candidate_tools=["search_knowledge"],
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == [query]
    assert model_runtime.last_tools == []
    assert not any(event.get("type") == "retrieval" for event in events)
    assert not any(event.get("type") == "tool_start" for event in events)
    stream_messages = list(getattr(model_runtime, "_recorder", {}).get("last_stream_payload", {}).get("messages", []))
    assert stream_messages
    assert stream_messages[0]["role"] == "system"
    assert "Main Working Context" in stream_messages[0]["content"]


def test_direct_tool_route_normalizes_final_content() -> None:
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "normalized tool answer", "debug": "ignored"})
    plan = QueryPlan(
        session_id="tool-session",
        message="请直接执行工具。",
        history=[],
        subqueries=["请直接执行工具。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "请直接执行工具。"},
        structured_binding=StructuredDatasetBinding(
            dataset_path="knowledge/E-commerce Data/inventory.xlsx",
            target_object="inventory",
            source="test",
            confidence=1.0,
        ),
        execution_kind="direct_tool",
    )
    events, _retrieval, model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"structured_data_analysis": tool},
        )
    )

    assert model_runtime.last_tools == []
    assert [event["type"] for event in events if event["type"] in {"tool_start", "tool_end", "done"}] == [
        "tool_start",
        "tool_end",
        "done",
    ]
    tool_start = next(event for event in events if event.get("type") == "tool_start")
    assert tool_start["structured_binding"]["dataset_path"].endswith("inventory.xlsx")
    assert tool_start["protocol_version"] == "mcp-compatible.v1"
    assert tool_start["mcp"]["schema_identity"] == "local.tools/structured_data_analysis"
    assert tool_start["mcp"]["runtime_visibility"] == "agent_internal"
    assert tool_start["mcp"]["prompt_exposure_policy"] == "hidden"
    assert events[-2]["protocol_version"] == "mcp-compatible.v1"
    assert events[-2]["message_id"] == tool_start["message_id"]
    assert events[-1]["tool_protocol"] == "mcp-compatible.v1"
    assert events[-1]["message_id"] == tool_start["message_id"]
    assert events[-1]["content"] == "normalized tool answer"
    assert events[-2]["output"] == "normalized tool answer"
    assert str(events[-1]["task_id"]).startswith("tool-session-tool-structured_data_analysis-")
    assert isinstance(events[-1]["summary"], dict)
    assert isinstance(events[-1]["context_ref"], dict)
    assert isinstance(events[-1]["result_ref"], dict)
    assert events[-1]["main_context"]["followup_mode"] == "task_ref"
    assert events[-1]["main_context"]["followup_resolution_source"] == "task_record"
    assert events[-1]["main_context"]["followup_target_task_id"] == events[-1]["task_id"]
    assert events[-1]["main_context"]["followup_target_task_ids"] == [events[-1]["task_id"]]
    assert events[-1]["main_context"]["active_binding_identity"].endswith("inventory.xlsx")
    assert events[-1]["task_summary_refs"]
    assert str(events[-1]["task_summary_refs"][0]["task_id"]).startswith("tool-session-tool-structured_data_analysis-")


def test_direct_tool_route_materializes_structured_subset_protocol() -> None:
    tool_output = (
        "数据源：employees.xlsx\n"
        "筛选条件：无\n"
        "查询模式：记录排序\n"
        "排序字段：薪水\n\n"
        "前 5 条记录：\n"
        "姓名    薪水\n"
        "罗凯    34900\n"
        "唐琳    34800\n"
        "许晨    34700\n"
        "刘洋    34600\n"
        "张敏    34500"
    )
    tool = SimpleNamespace(invoke=lambda _tool_input: tool_output)
    plan = QueryPlan(
        session_id="tool-subset-session",
        message="找出薪资前五的人。",
        history=[],
        subqueries=["找出薪资前五的人。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            task_kind="structured_followup_query",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "找出薪资前五的人。"},
        structured_binding=StructuredDatasetBinding(
            dataset_path="knowledge/E-commerce Data/employees.xlsx",
            target_object="employees",
            source="test",
            confidence=1.0,
        ),
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"structured_data_analysis": tool},
        )
    )

    done = next(event for event in reversed(events) if event.get("type") == "done")
    result_ref = dict(done["result_ref"])
    main_context = dict(done["main_context"])

    assert result_ref["subset_handle_id"].startswith("subset:selection:")
    assert result_ref["subset_filter_column"] == "name"
    assert result_ref["subset_labels"] == ["罗凯", "唐琳", "许晨", "刘洋", "张敏"]
    assert "姓名" not in result_ref["subset_labels"]
    assert "subset_hint_query" not in result_ref
    assert main_context["active_subset_handle_id"] == result_ref["subset_handle_id"]


def test_binding_followup_from_direct_tool_owner_passes_subset_constraints_structurally() -> None:
    coordinator = TaskCoordinator()
    top_n_output = (
        "数据源：employees.xlsx\n"
        "筛选条件：无\n"
        "查询模式：记录排序\n"
        "排序字段：薪水\n\n"
        "前 5 条记录：\n"
        "姓名    薪水\n"
        "罗凯    34900\n"
        "唐琳    34800\n"
        "许晨    34700\n"
        "刘洋    34600\n"
        "张敏    34500"
    )

    async def _seed() -> None:
        await coordinator.run_tool_task(
            "session-1",
            "structured_data_analysis",
            lambda: asyncio.sleep(0, result=top_n_output),
            query="找出薪资前五的人。",
            tool_input={
                "query": "找出薪资前五的人。",
                "path": "knowledge/E-commerce Data/employees.xlsx",
            },
            task_kind="structured_followup_query",
        )

    asyncio.run(_seed())
    owner_task = coordinator.list_tasks(session_id="session-1")[0]
    followup = RuntimeFollowupCoordinator(task_coordinator=coordinator)

    execution = followup.binding_execution_from_resolution(
        session_id="session-1",
        message="按部门汇总这些高薪员工。",
        history=[],
        followup_resolution=FollowupResolution(
            mode="binding_ref",
            binding_kind="active_dataset",
            resolved_binding_kind="active_dataset",
            binding_identity="knowledge/e-commerce data/employees.xlsx",
            resolved_binding_identity="knowledge/e-commerce data/employees.xlsx",
            binding_owner_task_id=owner_task.task_id,
            resolved_binding_owner_task_id=owner_task.task_id,
            task_id=owner_task.task_id,
            resolved_task_id=owner_task.task_id,
            result_handle_id=str(getattr(owner_task.result_ref, "primary_result_handle_id", "") or ""),
            result_handle_ids=list(getattr(owner_task.result_ref, "result_handle_ids", []) or []),
            subset_handle_id=str(getattr(owner_task.result_ref, "subset_handle_id", "") or ""),
        ),
    )

    assert execution is not None
    assert execution.worker_plan is not None
    request = execution.worker_plan.request
    assert execution.target_handle_kind == "subset"
    assert request.query == "按部门汇总这些高薪员工。"
    assert request.constraints["subset_filter_column"] == "name"
    assert request.constraints["subset_labels"] == ["罗凯", "唐琳", "许晨", "刘洋", "张敏"]
    assert "subset_hint_query" not in request.constraints
    assert request.bindings["active_dataset"].endswith("employees.xlsx")


def test_pdf_binding_followup_from_page_owner_does_not_inherit_page_mode_without_page_reference() -> None:
    coordinator = TaskCoordinator()

    async def _seed() -> None:
        await coordinator.run_tool_task(
            "session-1",
            "pdf_analysis",
            lambda: asyncio.sleep(0, result={"answer": "第九页没有稳定正文。"}),
            query="第九页讲了什么？",
            tool_input={"query": "第九页讲了什么？", "path": "knowledge/demo.pdf", "mode": "page"},
            task_kind="pdf_followup_query",
        )

    asyncio.run(_seed())
    owner_task = coordinator.list_tasks(session_id="session-1")[0]
    followup = RuntimeFollowupCoordinator(task_coordinator=coordinator)

    execution = followup.binding_execution_from_resolution(
        session_id="session-1",
        message="把这份 PDF 的核心结论压成三条行动建议。",
        history=[],
        followup_resolution=FollowupResolution(
            mode="binding_ref",
            binding_kind="active_pdf",
            resolved_binding_kind="active_pdf",
            binding_identity="knowledge/demo.pdf",
            resolved_binding_identity="knowledge/demo.pdf",
            binding_owner_task_id=owner_task.task_id,
            resolved_binding_owner_task_id=owner_task.task_id,
            task_id=owner_task.task_id,
            resolved_task_id=owner_task.task_id,
            result_handle_id=str(getattr(owner_task.result_ref, "primary_result_handle_id", "") or ""),
            result_handle_ids=list(getattr(owner_task.result_ref, "result_handle_ids", []) or []),
        ),
    )

    assert execution is not None
    assert execution.worker_plan is not None
    request = execution.worker_plan.request
    assert request.constraints["mode"] == "document"
    assert "page" not in request.constraints


def test_pdf_binding_followup_from_section_owner_preserves_section_scope() -> None:
    coordinator = TaskCoordinator()

    async def _seed() -> None:
        await coordinator.run_tool_task(
            "session-1",
            "pdf_analysis",
            lambda: asyncio.sleep(0, result={"answer": "第二部分强调权限边界与审计归口。"}),
            query="回到刚才 PDF，第二部分强调的约束是什么？",
            tool_input={
                "query": "回到刚才 PDF，第二部分强调的约束是什么？",
                "path": "knowledge/demo.pdf",
                "mode": "section",
            },
            task_kind="pdf_followup_query",
        )

    asyncio.run(_seed())
    owner_task = coordinator.list_tasks(session_id="session-1")[0]
    owner_task.context_ref.constraints.pdf_mode = "section"
    owner_task.context_ref.constraints.pdf_section = "第二部分"
    owner_task.context_ref.constraints.pdf_focus_pages = [2, 3]
    followup = RuntimeFollowupCoordinator(task_coordinator=coordinator)

    execution = followup.binding_execution_from_resolution(
        session_id="session-1",
        message="再用两句话说清楚。",
        history=[],
        followup_resolution=FollowupResolution(
            mode="binding_ref",
            binding_kind="active_pdf",
            resolved_binding_kind="active_pdf",
            binding_identity="knowledge/demo.pdf",
            resolved_binding_identity="knowledge/demo.pdf",
            binding_owner_task_id=owner_task.task_id,
            resolved_binding_owner_task_id=owner_task.task_id,
            task_id=owner_task.task_id,
            resolved_task_id=owner_task.task_id,
            result_handle_id=str(getattr(owner_task.result_ref, "primary_result_handle_id", "") or ""),
            result_handle_ids=list(getattr(owner_task.result_ref, "result_handle_ids", []) or []),
        ),
    )

    assert execution is not None
    assert execution.worker_plan is not None
    request = execution.worker_plan.request
    assert request.constraints["mode"] == "section"
    assert request.constraints["pdf_section"] == "第二部分"
    assert request.constraints["pdf_section_key"] == "第二部分"
    assert request.constraints["pdf_focus_pages"] == [2, 3]


def test_runtime_does_not_promote_session_committed_dataset_binding_without_strong_anchor() -> None:
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "已按仓库汇总前五。"})
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"structured_data_analysis": tool},
        session_state=_SessionStateStub(
            committed_dataset="knowledge/E-commerce Data/inventory.xlsx",
            committed_dataset_owner_task_id="dataset-task",
            active_object_handle_id="source:dataset:inventory",
            active_result_handle_id="result:structured:inventory:primary",
            active_subset_handle_id="subset:selection:inventory:primary",
        ),
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events("session-1", "按仓库汇总前五。", []):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert not any(event.get("type") == "worker_start" for event in events)
    assert done["type"] == "done"
    assert done["answer_source"] != "structured_data_worker"
    assert "structured_data_analysis" not in model_runtime.last_tools
    assert model_runtime.last_tools == ["web_search"]


def test_runtime_uses_session_committed_pdf_binding_for_tool_promotion() -> None:
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(
        rag_mode=False,
        session_state=_SessionStateStub(
            committed_pdf="knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            committed_pdf_owner_task_id="pdf-task",
            active_object_handle_id="source:pdf:governance",
            active_result_handle_id="result:pdf_summary:governance:primary",
        ),
    )
    pdf_worker = _PDFWorkerStub(answer="第二部分强调先划清权限边界，再明确审计归口。")
    runtime.evidence_orchestrator.pdf_worker = pdf_worker

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events("session-1", "回到刚才那份 PDF，第二部分强调的约束是什么？", []):
            events.append(event)
        return events

    events = asyncio.run(_run())
    worker_start = next(event for event in events if event.get("type") == "worker_start")
    done = events[-1]

    assert worker_start["worker"] == "pdf"
    assert pdf_worker.requests
    assert str(pdf_worker.requests[0].bindings["active_pdf"]).endswith(".pdf")
    assert pdf_worker.requests[0].target_handle_kind == "result"
    assert pdf_worker.requests[0].target_handle_id == "result:pdf_summary:governance:primary"
    assert pdf_worker.requests[0].constraints["mode"] == "section"
    assert pdf_worker.requests[0].constraints["pdf_section"] == "第二部分"
    assert pdf_worker.requests[0].constraints["pdf_section_key"] == "第二部分"
    assert done["answer_source"] == "pdf_worker"
    assert done["answer_fallback_reason"] == ""
    assert "权限边界" in str(done["content"])
    assert done["main_context"]["active_constraints"]["active_pdf"].endswith(".pdf")
    assert len(model_runtime.invoke_messages_calls) == 0


def test_pdf_direct_tool_facade_returns_canonical_summary_without_runtime_finalization() -> None:
    pdf_output = PDFCanonicalResult(
        status="ok",
        source="AI治理报告.pdf",
        requested_mode="document",
        effective_mode="document",
        summary="文档要点：先建立规则，再补审计，最后明确责任归口。",
        pages=[3, 5],
        evidence=[
            PDFCanonicalEvidence(page_number=3, score=7.1, snippet="建议先建立规则边界。"),
            PDFCanonicalEvidence(page_number=5, score=6.8, snippet="后续补充审计与责任归口。"),
        ],
    ).to_tool_output()
    tool = SimpleNamespace(invoke=lambda _tool_input: pdf_output)
    plan = QueryPlan(
        session_id="pdf-tool-session",
        message="把这份 PDF 的核心结论压成三条行动建议。",
        history=[],
        subqueries=["把这份 PDF 的核心结论压成三条行动建议。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            should_skip_rag=True,
            task_kind="pdf_followup_query",
        ),
        active_skill=None,
        tool_input={
            "query": "把这份 PDF 的核心结论压成三条行动建议。",
            "path": "knowledge/demo.pdf",
            "mode": "document",
        },
        execution_kind="direct_tool",
    )
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"pdf_analysis": tool},
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = [event for event in events if event["type"] == "done"][-1]

    assert model_runtime.invoke_messages_calls == []
    assert done["answer_source"] == "direct_tool.pdf_analysis"
    assert done["content"] == "文档要点：先建立规则，再补审计，最后明确责任归口。"
    assert done["summary"]["response"].startswith("文档要点")
    assert done["context_ref"]["summary"].startswith("文档要点")
    assert done["task_summary_refs"][0]["summary"].startswith("文档要点")
    assert events[-2]["output"] == "文档要点：先建立规则，再补审计，最后明确责任归口。"


def test_pdf_direct_tool_route_skips_model_finalization_for_degraded_result() -> None:
    pdf_output = PDFCanonicalResult(
        status="degraded",
        source="AI治理报告.pdf",
        requested_mode="page",
        effective_mode="page",
        summary="",
        degraded_reason="target_page_has_no_stable_text",
        pages=[9],
    ).to_tool_output()
    tool = SimpleNamespace(invoke=lambda _tool_input: pdf_output)
    plan = QueryPlan(
        session_id="pdf-degraded-session",
        message="第九页讲了什么？",
        history=[],
        subqueries=["第九页讲了什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            should_skip_rag=True,
            task_kind="pdf_followup_query",
        ),
        active_skill=None,
        tool_input={"query": "第九页讲了什么？", "path": "knowledge/demo.pdf", "mode": "page"},
        execution_kind="direct_tool",
    )
    events, _retrieval, model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"pdf_analysis": tool},
        )
    )

    done = [event for event in events if event["type"] == "done"][-1]
    assert model_runtime.invoke_messages_calls == []
    assert done["task_summary_refs"]
    assert "没有稳定可提取的正文" in done["content"]


def test_pdf_direct_tool_facade_does_not_model_finalize_degraded_page_evidence() -> None:
    pdf_output = PDFCanonicalResult(
        status="degraded",
        source="AI治理报告.pdf",
        requested_mode="page",
        effective_mode="page",
        summary="",
        degraded_reason="target_page_text_quality_low",
        pages=[3],
        evidence=[
            PDFCanonicalEvidence(
                page_number=3,
                score=1.0,
                snippet="回归现实主义2025年AI治理报告 腾讯研究院",
            )
        ],
    ).to_tool_output()
    tool = SimpleNamespace(invoke=lambda _tool_input: pdf_output)
    plan = QueryPlan(
        session_id="pdf-page-evidence-session",
        message="第三页具体讲了什么？",
        history=[],
        subqueries=["第三页具体讲了什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            should_skip_rag=True,
            task_kind="pdf_followup_query",
        ),
        active_skill=None,
        tool_input={"query": "第三页具体讲了什么？", "path": "knowledge/demo.pdf", "mode": "page"},
        execution_kind="direct_tool",
    )
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"pdf_analysis": tool},
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = [event for event in events if event["type"] == "done"][-1]

    assert model_runtime.invoke_messages_calls == []
    assert done["content"].startswith("已定位到 P3")
    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "fallback_policy"
    assert done["answer_fallback_reason"] == "pdf_target_page_text_quality_low"
    assert done["summary"]["response"].startswith("已定位到 P3")
    assert done["context_ref"]["summary"].startswith("已定位到 P3")
    assert done["task_summary_refs"]
    assert done["task_summary_refs"][0]["summary"].startswith("已定位到 P3")
    assert events[-2]["output"].startswith("已定位到 P3")


def test_semantic_memory_signal_prefetches_durable_without_runtime_rag_fallback() -> None:
    plan = QueryPlan(
        session_id="semantic-memory-signal",
        message="我们项目当前重点是什么？",
        history=[],
        subqueries=["我们项目当前重点是什么？"],
        memory_intent=MemoryIntent(
            intent="memory_read_signal",
            memory_read_mode="durable_exact",
            should_skip_rag=False,
            preferred_types=["project"],
            preferred_memory_classes=["work"],
        ),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == ["我们项目当前重点是什么？"]
    assert model_runtime.last_tools == []
    assert not any(event.get("type") == "retrieval" for event in events)
    memory_index = next(i for i, event in enumerate(events) if event.get("type") == "memory_context")
    assert memory_index >= 0


def test_general_memory_adjacent_query_still_prefetches_durable_context() -> None:
    plan = QueryPlan(
        session_id="general-memory-adjacent",
        message="以后我问复杂问题时，你应该先怎么回答？",
        history=[],
        subqueries=["以后我问复杂问题时，你应该先怎么回答？"],
        memory_intent=MemoryIntent(
            intent="general",
            memory_read_mode="none",
            should_skip_rag=False,
        ),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    events, retrieval, model_runtime, memory_facade = asyncio.run(_collect_events(plan, rag_mode=True))

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == ["以后我问复杂问题时，你应该先怎么回答？"]
    assert model_runtime.last_tools == []
    assert any(event.get("type") == "memory_context" for event in events)


def test_execution_events_reuses_built_plan_for_subtasks() -> None:
    execution_a = QueryExecutionPlan(
        message="a",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
    )
    execution_b = QueryExecutionPlan(
        message="b",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
    )
    plan = QueryPlan(
        session_id="compound-session",
        message="a/b",
        history=[],
        subqueries=["a", "b"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="explicit_fanout_query",
            route="explicit_fanout",
            modality="general",
            should_skip_rag=False,
        ),
        execution_mode="explicit_fanout",
        active_skill=None,
        executions=[execution_a, execution_b],
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    planner_calls = {"count": 0}

    def _build_plan(*, session_id, message, history):
        planner_calls["count"] += 1
        return plan

    runtime.planner.build_plan = _build_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert planner_calls["count"] == 1
    subtask_end = [event for event in events if event.get("type") == "subtask_end"]
    assert len(subtask_end) == 2
    assert all(isinstance(event.get("summary"), dict) for event in subtask_end)
    assert all(isinstance(event.get("context_ref"), dict) for event in subtask_end)
    assert all(isinstance(event.get("result_ref"), dict) for event in subtask_end)
    assert events[-1]["type"] == "done"
    assert isinstance(events[-1].get("main_context"), dict)
    assert events[-1]["main_context"]["active_work_item"] == "explicit_fanout"
    assert "1. a" in str(events[-1]["content"])
    assert "2. b" in str(events[-1]["content"])


def test_memory_route_does_not_promote_fake_tool_call_into_task_summary() -> None:
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    execution = QueryExecutionPlan(
        message="回忆一下之前的内容。",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
    )

    summary_refs = runtime._build_single_execution_task_summaries(
        execution,
        "<tool_call>structured_data_analysis(query='inventory.xlsx')</tool_call>",
    )

    assert summary_refs == []


def test_followup_task_ref_is_answered_without_replanning() -> None:
    coordinator = TaskCoordinator()
    asyncio.run(_seed_compound_tasks(coordinator))
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=True,
        task_coordinator=coordinator,
    )

    def _unexpected_plan(**_kwargs):
        raise AssertionError("planner should not run for direct follow-up task assembly")

    runtime.planner.build_plan = _unexpected_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "session-1",
            "只展开第二个子任务，给我仓库和缺货量。",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert [event["type"] for event in events] == ["done"]
    done = events[0]
    assert done["main_context"]["active_work_item"] == "followup_bundle_item_result"
    assert done["main_context"]["followup_target_task_ids"] == ["session-1-subtask-2"]
    assert "inventory.xlsx" in str(done["content"])


def test_binding_followup_executes_from_owner_task_without_replanning() -> None:
    coordinator = TaskCoordinator()
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "三条行动建议：先立规则，再建审计，最后做责任归口。"})
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"pdf_analysis": tool},
        task_coordinator=coordinator,
    )
    pdf_worker = _PDFWorkerStub(answer="三条行动建议：先立规则，再建审计，最后做责任归口。")
    runtime.evidence_orchestrator.pdf_worker = pdf_worker

    initial_plan = QueryPlan(
        session_id="binding-session",
        message="现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
        history=[],
        subqueries=["现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_overview_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="pdf",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={
            "query": "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
            "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
        },
        execution_kind="direct_tool",
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: initial_plan  # type: ignore[method-assign]

    async def _seed() -> None:
        async for _event in runtime._execution_events(
            "binding-session",
            initial_plan.message,
            [],
        ):
            pass

    asyncio.run(_seed())

    followup_plan = QueryPlan(
        session_id="binding-session",
        message="把这份 PDF 的核心结论压成三条行动建议。",
        history=[],
        subqueries=["把这份 PDF 的核心结论压成三条行动建议。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_followup_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="pdf",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "把这份 PDF 的核心结论压成三条行动建议。"},
        execution_kind="direct_tool",
    )
    plan_calls = {"count": 0}

    def _planned_followup(**_kwargs):
        plan_calls["count"] += 1
        return followup_plan

    runtime.planner.build_plan = _planned_followup  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "binding-session",
            "把这份 PDF 的核心结论压成三条行动建议。",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert plan_calls["count"] == 1
    assert "worker_start" in [event["type"] for event in events]
    done = next(event for event in reversed(events) if event.get("type") == "done")
    assert done["followup_mode"] == "binding_ref"
    assert done["main_context"]["active_work_item"] == "followup_task_binding_execution"
    assert done["main_context"]["followup_mode"] == "binding_ref"
    assert done["main_context"]["followup_resolution_source"] == "task_registry_binding"
    assert done["main_context"]["followup_binding_key"] == "active_pdf"
    assert done["main_context"]["followup_binding_identity"].endswith(".pdf")
    assert done["main_context"]["active_binding_identity"].endswith(".pdf")
    assert done["main_context"]["followup_target_task_id"]
    assert done["main_context"]["active_constraints"]["active_pdf"].endswith(".pdf")
    assert pdf_worker.requests
    assert pdf_worker.requests[0].owner_task_id
    assert pdf_worker.requests[0].target_handle_kind in {"task", "object", "result"}
    assert done["task_summary_refs"]
    assert done["task_summary_refs"][0]["task_id"] == done["main_context"]["followup_target_task_id"]


def test_binding_followup_candidate_yields_to_memory_plan_when_route_conflicts() -> None:
    coordinator = TaskCoordinator()
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "unused"})
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"pdf_analysis": tool},
        task_coordinator=coordinator,
    )

    initial_plan = QueryPlan(
        session_id="binding-session-memory-cutover",
        message="现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
        history=[],
        subqueries=["现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_overview_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="pdf",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={
            "query": "现在打开 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf，给我一个全文总览。",
            "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
        },
        execution_kind="direct_tool",
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: initial_plan  # type: ignore[method-assign]

    async def _seed() -> None:
        async for _event in runtime._execution_events(
            "binding-session-memory-cutover",
            initial_plan.message,
            [],
        ):
            pass

    asyncio.run(_seed())

    owner_task_id = next(iter(coordinator._tasks.keys()))
    normalized_path = "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf".replace("\\", "/").lower()
    runtime.followup_resolver.resolve = lambda **_kwargs: FollowupResolution(  # type: ignore[method-assign]
        mode="binding_ref",
        target_kind="binding",
        resolved_target_kind="binding",
        task_id=owner_task_id,
        resolved_task_id=owner_task_id,
        binding_key="active_pdf",
        binding_kind="active_pdf",
        resolved_binding_kind="active_pdf",
        binding_owner_task_id=owner_task_id,
        resolved_binding_owner_task_id=owner_task_id,
        binding_identity=normalized_path,
        resolved_binding_identity=normalized_path,
        resolved_binding_ref=normalized_path,
        resolution_source="task_registry_binding_hint",
        confidence=0.45,
        reason="binding_reference",
    )

    memory_plan = QueryPlan(
        session_id="binding-session-memory-cutover",
        message="把今天这几个任务分成 PDF、数据表、实时查询三段总结。",
        history=[{"role": "assistant", "content": "已有上下文"}],
        subqueries=["把今天这几个任务分成 PDF、数据表、实时查询三段总结。"],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    plan_calls = {"count": 0}

    def _memory_plan(**_kwargs):
        plan_calls["count"] += 1
        return memory_plan

    runtime.planner.build_plan = _memory_plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "binding-session-memory-cutover",
            memory_plan.message,
            memory_plan.history,
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert plan_calls["count"] == 1
    assert retrieval.queries == []
    assert memory_facade.prefetch_queries == []
    assert model_runtime.last_tools == []
    assert not any(event.get("type") == "tool_start" for event in events)
    done = next(event for event in reversed(events) if event.get("type") == "done")
    assert done["main_context"]["active_work_item"] == "session_summary_query"
    assert done["main_context"]["followup_mode"] == ""
    assert done["content"]


def test_ambiguous_binding_followup_no_longer_hijacks_planning() -> None:
    coordinator = TaskCoordinator()
    tool = SimpleNamespace(invoke=lambda _tool_input: {"answer": "unused"})
    runtime, retrieval, model_runtime, memory_facade = _build_runtime(
        rag_mode=False,
        direct_tools={"structured_data_analysis": tool},
        task_coordinator=coordinator,
    )

    async def _seed_tasks() -> None:
        executions = [
            QueryExecutionPlan(
                message="给我 inventory.xlsx 里最缺货的前三个仓库",
                history=[],
                memory_intent=MemoryIntent(),
                query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
            ),
            QueryExecutionPlan(
                message="给我 employees.xlsx 里薪资最高的前三个人",
                history=[],
                memory_intent=MemoryIntent(),
                query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
            ),
        ]

        async def runner(execution: QueryExecutionPlan):
            yield {"type": "done", "content": f"answer for {execution.message}"}

        async for _event in coordinator.run_query_tasks("ambiguous-binding-session", executions, runner):
            pass

    asyncio.run(_seed_tasks())
    plan_calls = {"count": 0}
    runtime.planner.build_plan = lambda *, session_id, message, history: (
        plan_calls.__setitem__("count", plan_calls["count"] + 1) or QueryPlan(
            session_id=session_id,
            message=message,
            history=history,
            subqueries=[message],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(
                intent="general_query",
                route="agent",
                modality="general",
                should_skip_rag=False,
            ),
            active_skill=None,
        )
    )  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "ambiguous-binding-session",
            "把那个表按仓库展开一下。",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert plan_calls["count"] == 1
    assert retrieval.queries == []
    assert any(event["type"] == "memory_context" for event in events)
    done = next(event for event in reversed(events) if event.get("type") == "done")
    assert done["type"] == "done"


def test_session_committed_pdf_binding_breaks_registry_ambiguity() -> None:
    def _task(task_id: str, pdf_path: str):
        return SimpleNamespace(
            task_id=task_id,
            query=f"read {pdf_path}",
            context_ref=SimpleNamespace(
                task_kind="pdf_followup_query",
                bindings=SimpleNamespace(
                    active_pdf=pdf_path,
                    active_dataset="",
                ),
            ),
        )

    resolver = QueryFollowupResolver(
        SimpleNamespace(
            list_tasks=lambda session_id: [
                _task("task-a", "knowledge/reports/a.pdf"),
                _task("task-b", "knowledge/reports/b.pdf"),
            ]
        ),
        session_state_loader=lambda session_id: {
            "committed_pdf": "knowledge/reports/b.pdf",
            "committed_pdf_owner_task_id": "task-b",
            "committed_dataset": "",
            "committed_dataset_owner_task_id": "",
        },
    )

    resolution = resolver.resolve(
        session_id="ambiguous-pdf-session",
        message="把这份 PDF 的核心结论压成三条行动建议。",
    )

    assert resolution.mode == "binding_ref"
    assert resolution.resolution_source == "session_committed_binding"
    assert resolution.resolved_binding_identity.endswith("b.pdf")
    assert resolution.resolved_binding_owner_task_id == "task-b"


def test_runtime_output_boundary_strips_internal_protocol_from_streamed_answer() -> None:
    plan = QueryPlan(
        session_id="protocol-session",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我来检索本地知识库。</think>**工具调用:**\n```json\n"
                            "[{\"name\":\"search_knowledge\"}]\n```\n\n---\n\n"
                            "**工具输出:**\n[搜索结果 失败]\n\n"
                            "**结论：本地知识库当前为空，无法基于知识库回答该问题。**\n\n"
                            "岩，目前 knowledge 目录下没有任何文档。"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    token_text = "".join(str(event.get("content", "")) for event in events if event.get("type") == "token")
    done_text = str(events[-1]["content"])
    assert "</think>" not in token_text
    assert "**工具调用:**" not in token_text
    assert "<tool_call" not in done_text
    assert "**工具输出:**" not in done_text
    assert "本地知识库当前为空" in done_text


def test_runtime_output_boundary_keeps_final_stream_answer_when_ai_update_is_partial() -> None:
    plan = QueryPlan(
        session_id="protocol-stream-wins",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我需要先检索本地知识库中的相关内容，然后再给出结论。",
                                tool_calls=[],
                            )
                        ]
                    }
                },
            ),
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我来检索本地知识库。</think>**工具调用:**\n```json\n"
                            "[{\"name\":\"search_knowledge\"}]\n```\n\n---\n\n"
                            "**工具输出:**\n[搜索结果 失败]\n\n"
                            "**结论：本地知识库当前为空，无法基于知识库回答该问题。**\n\n"
                            "岩，目前 knowledge 目录下没有任何文档。"
                        )
                    ),
                    {},
                ),
            ),
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert done_text
    assert "本地知识库当前为空" in done_text
    assert "我需要先检索本地知识库中的相关内容" not in done_text


def test_runtime_output_boundary_strips_inline_pseudo_tool_calls_from_visible_answer() -> None:
    plan = QueryPlan(
        session_id="pseudo-tool-call",
        message="把这三类风险改写成适合周会汇报的三条。",
        history=[],
        subqueries=["把这三类风险改写成适合周会汇报的三条。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我需要先检索本地知识库中关于 AI 治理风险的内容，然后为您改写成周会汇报格式。"
                            "search_knowledge(query=\"AI 治理 风险 类型\", top_k=5)"
                            "search_knowledge(query=\"人工智能 治理 常见风险\", top_k=5)"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert done_text
    assert "search_knowledge(" not in done_text
    assert "我需要先检索本地知识库中关于 AI 治理风险的内容" not in done_text
    assert "当前没有可验证的执行结果。" == done_text
    assert events[-1]["answer_fallback_reason"] == "no_receipt_tool_claim"


def test_runtime_output_boundary_salvages_nonempty_answer_when_only_procedural_text_remains() -> None:
    plan = QueryPlan(
        session_id="protocol-salvage",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "我来检索本地知识库中关于 AI 治理风险的相关内容。\n\n"
                            "我将使用 search_knowledge 工具查询本地知识库。</think>"
                            "**工具调用:**\n```json\n[{\"name\":\"search_knowledge\"}]\n```"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert done_text
    assert "</think>" not in done_text
    assert "**工具调用:**" not in done_text
    assert "我来检索本地知识库中关于 AI 治理风险的相关内容" not in done_text
    assert "当前没有可验证的执行结果。" == done_text
    assert events[-1]["answer_fallback_reason"] == "no_receipt_tool_claim"


def test_runtime_memory_visible_gate_rejects_procedural_segment_answer() -> None:
    plan = QueryPlan(
        session_id="memory-visible-pollution",
        message="回忆一下我们刚才的推进情况。",
        history=[],
        subqueries=["回忆一下我们刚才的推进情况。"],
        memory_intent=MemoryIntent(
            intent="session_continuity_query",
            memory_read_mode="session_state",
            should_skip_rag=True,
        ),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content="让我先回顾一下之前的会话内容，再整理一个正式回答。</think>"
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "fallback_policy"
    assert done["answer_fallback_reason"] == "memory_visible_pollution"
    assert str(done["content"]) == "当前没有足够稳定的会话内容可直接回答这个问题。"


def test_runtime_memory_visible_gate_keeps_stable_memory_answer() -> None:
    plan = QueryPlan(
        session_id="memory-visible-stable",
        message="回忆一下我们刚才的推进情况。",
        history=[],
        subqueries=["回忆一下我们刚才的推进情况。"],
        memory_intent=MemoryIntent(
            intent="session_continuity_query",
            memory_read_mode="session_state",
            should_skip_rag=True,
        ),
        query_understanding=QueryUnderstanding(
            intent="session_summary_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content="我们刚才主要推进了三件事：收紧 follow-up 边界、补齐 RAG 收口、开始处理输出层稳定化。"
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_channel"] == "answer_candidate"
    assert done["answer_source"] == "segment.visible_text"
    assert done["answer_fallback_reason"] == ""
    assert "收紧 follow-up 边界" in str(done["content"])


def test_runtime_durable_memory_write_uses_direct_ack_and_skips_model() -> None:
    plan = QueryPlan(
        session_id="durable-memory-write-direct",
        message="记住：回答我时可以直接称呼我岩。",
        history=[
            {"role": "user", "content": "回到 report.pdf 第二部分，继续分析约束重点。"},
            {"role": "assistant", "content": "第二部分主要收紧了模型部署和审计要求。"},
        ],
        subqueries=["记住：回答我时可以直接称呼我岩。"],
        memory_intent=MemoryIntent(
            intent="durable_memory_statement",
            memory_write_mode="durable_fact",
            should_skip_rag=True,
            explicit_write_request=True,
        ),
        query_understanding=QueryUnderstanding(
            intent="durable_memory_statement",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_channel"] == "answer_candidate"
    assert done["answer_source"] == "memory_write_ack"
    assert done["answer_fallback_reason"] == ""
    assert "长期记忆保留" in str(done["content"])
    assert "称呼我岩" in str(done["content"])
    assert not hasattr(model_runtime, "_recorder")


def test_runtime_durable_memory_query_drops_prior_history_from_model_payload() -> None:
    plan = QueryPlan(
        session_id="durable-memory-query-isolated",
        message="你刚才帮我长期记住了什么？",
        history=[
            {"role": "user", "content": "回到 report.pdf 第二部分，继续分析约束重点。"},
            {"role": "assistant", "content": "第二部分主要收紧了模型部署和审计要求。"},
        ],
        subqueries=["你刚才帮我长期记住了什么？"],
        memory_intent=MemoryIntent(
            intent="durable_memory_query",
            memory_read_mode="durable_exact",
            should_skip_rag=True,
            explicit_read_inventory=True,
        ),
        query_understanding=QueryUnderstanding(
            intent="durable_memory_query",
            route="memory",
            modality="memory",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    asyncio.run(_run())
    payload = model_runtime._recorder["last_stream_payload"]
    messages = list(payload["messages"])

    assert messages[-1] == {"role": "user", "content": "你刚才帮我长期记住了什么？"}
    assert not any("report.pdf" in str(item.get("content", "")) for item in messages[:-1])


def test_runtime_rag_answer_finalizer_rewrites_missing_answer_from_evidence_pack() -> None:
    plan = _promote_rag_plan_to_retrieval_worker(QueryPlan(
        session_id="rag-finalizer-success",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    ))
    runtime, retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    retrieval.retrieve = lambda query, *, top_k=5: [  # type: ignore[method-assign]
        {
            "text": "常见风险一是数据质量与口径不一致，导致模型输入失真，进而带来业务判断偏差和治理失真。",
            "source": "knowledge/ai_governance.md",
            "page": 3,
            "score": 0.92,
        },
        {
            "text": "常见风险二是责任边界不清，模型出错后缺少明确的审批、复核、归责与升级机制。",
            "source": "knowledge/ai_governance.md",
            "page": 5,
            "score": 0.88,
        },
        {
            "text": "常见风险三是监控和审计不足，系统上线后无法持续发现漂移、误用以及合规异常。",
            "source": "knowledge/ai_governance.md",
            "page": 7,
            "score": 0.85,
        },
    ]
    model_runtime.invoke_messages_response = (
        "最常见的三类风险可以概括为三点："
        "一是数据质量与口径失真，二是责任边界不清，三是监控和审计不足。"
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content="我来先检索本地知识库，再整理答案。</think>"
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_source"] == "rag_answer_finalization"
    assert done["answer_channel"] == "answer_candidate"
    assert done["answer_fallback_reason"] == ""
    assert "数据质量与口径失真" in str(done["content"])
    assert len(model_runtime.invoke_messages_calls) == 1
    assert "ai_governance.md" in model_runtime.invoke_messages_calls[0][1]["content"]


def test_runtime_rag_output_boundary_trims_trailing_protocol_tail_from_visible_answer() -> None:
    plan = QueryPlan(
        session_id="rag-tail-trim",
        message="基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    )
    runtime, retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    retrieval.retrieve = lambda query, *, top_k=5: [  # type: ignore[method-assign]
        {
            "text": "常见风险一是数据质量与口径不一致，导致模型输入失真，进而带来业务判断偏差和治理失真。",
            "source": "knowledge/ai_governance.md",
            "page": 3,
            "score": 0.92,
        },
        {
            "text": "常见风险二是责任边界不清，模型出错后缺少明确的审批、复核、归责与升级机制。",
            "source": "knowledge/ai_governance.md",
            "page": 5,
            "score": 0.88,
        },
        {
            "text": "常见风险三是监控和审计不足，系统上线后无法持续发现漂移、误用以及合规异常。",
            "source": "knowledge/ai_governance.md",
            "page": 7,
            "score": 0.85,
        },
    ]
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content="根据检索到的知识库内容，我先用业务语言给出结论：AI 治理中最常见的三类风险是：合规风险、应用风险、安全风险。\n\n---\n\n让我进一步)"
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_source"] == "segment.visible_text"
    assert done["answer_fallback_reason"] == ""
    assert str(done["content"]) == "根据检索到的知识库内容，我先用业务语言给出结论：AI 治理中最常见的三类风险是：合规风险、应用风险、安全风险。"
    assert "让我进一步" not in str(done["content"])
    assert len(model_runtime.invoke_messages_calls) == 0


def test_runtime_rag_output_boundary_rejects_tool_arg_json_and_uses_finalizer() -> None:
    plan = _promote_rag_plan_to_retrieval_worker(QueryPlan(
        session_id="rag-json-protocol",
        message="基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    ))
    runtime, retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    retrieval.retrieve = lambda query, *, top_k=5: [  # type: ignore[method-assign]
        {
            "text": "常见风险一是数据质量与口径不一致，导致模型输入失真，进而带来业务判断偏差和治理失真。",
            "source": "knowledge/ai_governance.md",
            "page": 3,
            "score": 0.92,
        },
        {
            "text": "常见风险二是责任边界不清，模型出错后缺少明确的审批、复核、归责与升级机制。",
            "source": "knowledge/ai_governance.md",
            "page": 5,
            "score": 0.88,
        },
        {
            "text": "常见风险三是监控和审计不足，系统上线后无法持续发现漂移、误用以及合规异常。",
            "source": "knowledge/ai_governance.md",
            "page": 7,
            "score": 0.85,
        },
    ]
    model_runtime.invoke_messages_response = (
        "AI 治理里最常见的三类风险可以概括为："
        "合规风险、应用风险和安全风险。"
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            '{"query": "AI治理 风险类型 分类 三类", "top_k": 10}\n```\n\n'
                            '{"query": "人工智能 风险 类型 常见", "top_k": 10}\n```\n\n'
                            "注：此工具调用为系统自动补全示例，实际调用参数以模型生成的为准。"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_source"] == "rag_answer_finalization"
    assert done["answer_fallback_reason"] == ""
    assert "合规风险、应用风险和安全风险" in str(done["content"])
    assert "top_k" not in str(done["content"])
    assert len(model_runtime.invoke_messages_calls) == 1


def test_runtime_rag_output_boundary_rejects_invoke_tail_protocol_and_uses_finalizer() -> None:
    plan = _promote_rag_plan_to_retrieval_worker(QueryPlan(
        session_id="rag-invoke-protocol",
        message="基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，先用业务语言告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    ))
    runtime, retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    retrieval.retrieve = lambda query, *, top_k=5: [  # type: ignore[method-assign]
        {
            "text": "常见风险一是数据质量与口径不一致，导致模型输入失真，进而带来业务判断偏差和治理失真。",
            "source": "knowledge/ai_governance.md",
            "page": 3,
            "score": 0.92,
        },
        {
            "text": "常见风险二是责任边界不清，模型出错后缺少明确的审批、复核、归责与升级机制。",
            "source": "knowledge/ai_governance.md",
            "page": 5,
            "score": 0.88,
        },
        {
            "text": "常见风险三是监控和审计不足，系统上线后无法持续发现漂移、误用以及合规异常。",
            "source": "knowledge/ai_governance.md",
            "page": 7,
            "score": 0.85,
        },
    ]
    model_runtime.invoke_messages_response = (
        "AI 治理里最常见的三类风险是："
        "合规风险、应用风险和安全风险。"
    )
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content=(
                            "岩，我先检索一下本地知识库中关于 AI 治理风险分类的具体内容。\n"
                            "query: AI治理 风险类型 分类 三类\n"
                            "top_k: 10\n"
                            "\\end{invoke>"
                        )
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_source"] == "rag_answer_finalization"
    assert done["answer_fallback_reason"] == ""
    assert "合规风险、应用风险和安全风险" in str(done["content"])
    assert "query:" not in str(done["content"])
    assert "top_k" not in str(done["content"])
    assert len(model_runtime.invoke_messages_calls) == 1


def test_runtime_rag_answer_finalizer_rejects_procedural_rewrite_and_keeps_fallback() -> None:
    plan = _promote_rag_plan_to_retrieval_worker(QueryPlan(
        session_id="rag-finalizer-reject",
        message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
        history=[],
        subqueries=["基于本地知识库，告诉我 AI 治理里最常见的三类风险。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="knowledge_lookup_query",
            route="rag",
            modality="general",
            should_skip_rag=False,
        ),
        active_skill=None,
    ))
    runtime, retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=True)
    retrieval.retrieve = lambda query, *, top_k=5: [  # type: ignore[method-assign]
        {
            "text": "常见风险一是数据质量与口径不一致，导致模型输入失真，进而带来业务判断偏差和治理失真。",
            "source": "knowledge/ai_governance.md",
            "page": 3,
            "score": 0.92,
        },
        {
            "text": "常见风险二是责任边界不清，模型出错后缺少明确的审批、复核、归责与升级机制。",
            "source": "knowledge/ai_governance.md",
            "page": 5,
            "score": 0.88,
        },
    ]
    model_runtime.invoke_messages_response = "我来先根据这些证据整理答案。"
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "messages",
                (
                    SimpleNamespace(
                        content="我来先检索本地知识库，再整理答案。</think>"
                    ),
                    {},
                ),
            )
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_source"] == "fallback_policy"
    assert done["answer_fallback_reason"] == "rag_missing_answer"
    assert str(done["content"]) == "已检索到相关资料，但当前模型尚未产出可直接展示的结论。"
    assert len(model_runtime.invoke_messages_calls) == 1


def test_runtime_pdf_tool_output_boundary_no_longer_model_finalizes_tool_output() -> None:
    plan = QueryPlan(
        session_id="pdf-finalizer-success",
        message="第三页具体讲了什么？",
        history=[],
        subqueries=["第三页具体讲了什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_page_followup_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    canonical = PDFCanonicalResult(
        status="degraded",
        source="AI治理报告.pdf",
        requested_mode="page",
        effective_mode="page",
        summary="",
        degraded_reason="target_page_text_quality_low",
        pages=[3],
        evidence=[
            PDFCanonicalEvidence(page_number=3, score=1.0, snippet="回归现实主义2025年AI治理报告 腾讯研究院"),
        ],
    ).to_tool_output()
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我先读取第三页，再给你结论。",
                                tool_calls=[
                                    {
                                        "id": "call-1",
                                        "name": "pdf_analysis",
                                        "args": {"path": "knowledge/demo.pdf", "page": 3},
                                    }
                                ],
                            )
                        ]
                    }
                },
            ),
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="tool",
                                tool_call_id="call-1",
                                name="pdf_analysis",
                                content=canonical,
                            )
                        ]
                    }
                },
            ),
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "fallback_policy"
    assert done["answer_fallback_reason"] == "pdf_target_page_text_quality_low"
    assert "页面文本质量不稳定" in str(done["content"])
    assert len(model_runtime.invoke_messages_calls) == 0


def test_runtime_pdf_tool_output_boundary_keeps_fallback_without_model_rewrite() -> None:
    plan = QueryPlan(
        session_id="pdf-finalizer-reject",
        message="第三页具体讲了什么？",
        history=[],
        subqueries=["第三页具体讲了什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_page_followup_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    canonical = PDFCanonicalResult(
        status="degraded",
        source="AI治理报告.pdf",
        requested_mode="page",
        effective_mode="page",
        summary="",
        degraded_reason="target_page_text_quality_low",
        pages=[3],
        evidence=[
            PDFCanonicalEvidence(page_number=3, score=1.0, snippet="回归现实主义2025年AI治理报告 腾讯研究院"),
        ],
    ).to_tool_output()
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我先读取第三页，再给你结论。",
                                tool_calls=[
                                    {
                                        "id": "call-1",
                                        "name": "pdf_analysis",
                                        "args": {"path": "knowledge/demo.pdf", "page": 3},
                                    }
                                ],
                            )
                        ]
                    }
                },
            ),
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="tool",
                                tool_call_id="call-1",
                                name="pdf_analysis",
                                content=canonical,
                            )
                        ]
                    }
                },
            ),
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "fallback_policy"
    assert done["answer_fallback_reason"] == "pdf_target_page_text_quality_low"
    assert "页面文本质量不稳定" in str(done["content"])
    assert len(model_runtime.invoke_messages_calls) == 0


def test_runtime_output_boundary_does_not_promote_plain_tool_output_to_done_content() -> None:
    plan = QueryPlan(
        session_id="tool-output-leak-guard",
        message="把库存表按缺货量给我看结果。",
        history=[],
        subqueries=["把库存表按缺货量给我看结果。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            should_skip_rag=True,
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]
    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ScriptedAgent(  # type: ignore[method-assign]
        [
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我先读取库存表，再整理答案。",
                                tool_calls=[
                                    {
                                        "id": "call-1",
                                        "name": "structured_data_analysis",
                                        "args": {"path": "knowledge/E-commerce Data/inventory.xlsx"},
                                    }
                                ],
                            )
                        ]
                    }
                },
            ),
            (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="tool",
                                tool_call_id="call-1",
                                name="structured_data_analysis",
                                content="warehouse,shortage\nEast,12\nNorth,9",
                            )
                        ]
                    }
                },
            ),
        ]
    )

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())

    done_text = str(events[-1]["content"])
    assert "warehouse,shortage" not in done_text
    assert "East,12" not in done_text
    assert "工具 `structured_data_analysis` 已执行，但当前结果尚未形成可直接展示的答案。" == done_text


def test_runtime_stream_ignores_tool_message_chunks_before_provider_error() -> None:
    plan = QueryPlan(
        session_id="tool-message-leak-session",
        message="把 PDF 部分压成两条行动项。",
        history=[],
        subqueries=["把 PDF 部分压成两条行动项。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="general_query",
            route="agent",
            modality="general",
            execution_posture="bounded_agent",
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    class _ToolChunkThenErrorAgent:
        async def astream(self, *_args, **_kwargs):
            yield ("messages", (SimpleNamespace(type="ai", content="我先读取 PDF。"), {}))
            yield (
                "messages",
                (
                    SimpleNamespace(
                        type="tool",
                        content=(
                            "PDF_CANONICAL_RESULT::{\"status\":\"degraded\"}\n"
                            "Read failed: path is a directory."
                        ),
                    ),
                    {},
                ),
            )
            raise ModelRuntimeError(
                code="provider_error",
                provider="test",
                model="test-model",
                detail="simulated stream failure",
                retryable=False,
                user_message="模型调用失败，请稍后重试。",
            )

    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ToolChunkThenErrorAgent()  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    streamed_text = "".join(str(event.get("content", "") or "") for event in events if event.get("type") == "token")
    done = events[-1]

    assert "我先读取 PDF。" in streamed_text
    assert "PDF_CANONICAL_RESULT::" not in streamed_text
    assert "Read failed:" not in streamed_text
    assert done["type"] == "done"
    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "runtime_error_fallback"
    assert done["answer_fallback_reason"] == "model_runtime_provider_error"
    assert "生成最终答案时中断了" in str(done["content"])


def test_runtime_stream_timeout_becomes_nonempty_done_fallback() -> None:
    plan = QueryPlan(
        session_id="tool-timeout-session",
        message="把 PDF 部分压成两条行动项。",
        history=[],
        subqueries=["把 PDF 部分压成两条行动项。"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(
            intent="general_query",
            route="agent",
            modality="general",
            execution_posture="bounded_agent",
        ),
        active_skill=None,
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda *, session_id, message, history: plan  # type: ignore[method-assign]

    class _ToolStartThenTimeoutAgent:
        async def astream(self, *_args, **_kwargs):
            yield (
                "updates",
                {
                    "node": {
                        "messages": [
                            SimpleNamespace(
                                type="ai",
                                content="我先读取 PDF。",
                                tool_calls=[
                                    {
                                        "id": "call-1",
                                        "name": "pdf_analysis",
                                        "args": {"path": "knowledge/demo.pdf", "query": "第3页讲了什么"},
                                    }
                                ],
                            )
                        ]
                    }
                },
            )
            raise ModelRuntimeError(
                code="timeout",
                provider="test",
                model="test-model",
                detail="simulated timeout",
                retryable=False,
                user_message="模型请求超时，请稍后重试。",
            )

    runtime.model_runtime.create_conversation_agent = lambda **_kwargs: _ToolStartThenTimeoutAgent()  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._stream_single_execution(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    done = events[-1]

    assert any(event.get("type") == "tool_start" and event.get("tool") == "pdf_analysis" for event in events)
    assert done["type"] == "done"
    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "runtime_error_fallback"
    assert done["answer_fallback_reason"] == "model_runtime_timeout"
    assert "整理最终答案时超时了" in str(done["content"])
    assert "pdf_analysis" in str(done["content"])


def test_direct_tool_pdf_raw_dump_does_not_become_done_content() -> None:
    raw_pdf_dump = (
        "Source: knowledge/test.pdf\n"
        "Mode: PDF browse\n"
        "Relevant pages:\n"
        "[P12] score=0.91\n"
        "[P18] score=0.84\n"
        "Page snippet: raw dump should not be exposed directly."
    )
    tool = SimpleNamespace(invoke=lambda _tool_input: raw_pdf_dump)
    plan = QueryPlan(
        session_id="pdf-dump-session",
        message="打开这份 PDF，告诉我结论。",
        history=[],
        subqueries=["打开这份 PDF，告诉我结论。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_overview_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="pdf",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "打开这份 PDF，告诉我结论。", "path": "knowledge/test.pdf"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"pdf_analysis": tool},
        )
    )

    done_text = str(events[-1]["content"])
    assert "Source:" not in done_text
    assert "Mode: PDF browse" not in done_text
    assert "P12" not in done_text
    assert "P18" not in done_text
    assert done_text == "已读取这份 PDF，但当前工具尚未形成可直接展示的摘要。"
    assert events[-1]["answer_channel"] == "fallback_answer"


def test_direct_tool_degraded_pdf_facade_projects_generic_fallback_state() -> None:
    canonical = PDFCanonicalResult(
        status="degraded",
        source="test.pdf",
        requested_mode="page",
        effective_mode="page",
        degraded_reason="target_page_text_quality_low",
        pages=[8],
        metadata={
            "target_page": 8,
            "document_total_pages": 16,
            "readable_pages": 12,
            "usable_pages": 10,
        },
    ).to_tool_output()
    tool = SimpleNamespace(invoke=lambda _tool_input: canonical)
    plan = QueryPlan(
        session_id="pdf-degraded-session",
        message="回到刚才 PDF，第8页讲了什么？",
        history=[],
        subqueries=["回到刚才 PDF，第8页讲了什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_page_followup_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="document_page",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "回到刚才 PDF，第8页讲了什么？", "path": "knowledge/test.pdf"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"pdf_analysis": tool},
        )
    )

    done = events[-1]
    assert done["answer_channel"] == "fallback_answer"
    assert done["answer_source"] == "fallback_policy"
    assert done["answer_fallback_reason"] == "pdf_target_page_text_quality_low"
    assert done["content"] == "已定位到 P8，但页面文本质量不稳定，当前无法可靠给出页级结论。"
    assert done["task_summary_refs"]
    assert done["summary"]["response"] == done["content"]
    assert done["summary"]["key_points"] == ["page=8", "pdf_mode=page", "pdf=knowledge/test.pdf"]
    assert done["context_ref"]["summary"] == done["content"]
    assert done["main_context"]["active_constraints"]["page"] == 8
    assert done["main_context"]["active_constraints"]["pdf_mode"] == "page"
    assert done["main_context"]["active_constraints"]["active_pdf"] == "knowledge/test.pdf"
    assert "total_pages" not in done["main_context"]["active_constraints"]
    assert "readable_pages" not in done["main_context"]["active_constraints"]
    assert "usable_pages" not in done["main_context"]["active_constraints"]


def test_direct_tool_pdf_canonical_facade_projects_minimal_binding_state() -> None:
    canonical = PDFCanonicalResult(
        status="ok",
        source="test.pdf",
        requested_mode="document",
        effective_mode="section",
        summary="已定位到第二部分的约束重点。",
        pages=[8, 9],
        metadata={
            "target_section": "第二部分",
            "target_page": 8,
            "readable_pages": 14,
            "usable_pages": 12,
            "document_total_pages": 16,
        },
    ).to_tool_output()
    tool = SimpleNamespace(invoke=lambda _tool_input: canonical)
    plan = QueryPlan(
        session_id="pdf-canonical-session",
        message="回到刚才 PDF，第二部分强调的约束是什么？",
        history=[],
        subqueries=["回到刚才 PDF，第二部分强调的约束是什么？"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="pdf_followup_query",
            route="tool",
            modality="pdf",
            tool_name="pdf_analysis",
            task_kind="document_section",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "回到刚才 PDF，第二部分强调的约束是什么？", "path": "knowledge/test.pdf"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"pdf_analysis": tool},
        )
    )

    done = events[-1]
    context_ref = dict(done["context_ref"])
    constraints = dict(context_ref["constraints"])
    main_constraints = dict(done["main_context"]["active_constraints"])
    summary_key_points = list(done["summary"]["key_points"])
    assert constraints["pdf_mode"] == "section"
    assert constraints["pdf_section"] == "第二部分"
    assert constraints["page"] is None
    assert constraints["pdf_focus_pages"] == []
    assert main_constraints["pdf_mode"] == "section"
    assert main_constraints["pdf_section"] == "第二部分"
    assert "page" not in main_constraints
    assert "readable_pages" not in main_constraints
    assert "usable_pages" not in main_constraints
    assert done["answer_source"] == "direct_tool.pdf_analysis"
    assert done["content"] == "已定位到第二部分的约束重点。"
    assert "pdf_mode=section" in summary_key_points
    assert "pdf_section=第二部分" in summary_key_points


def test_direct_tool_plain_table_dump_does_not_become_done_content() -> None:
    raw_table_dump = "warehouse,shortage\nEast,12\nNorth,9"
    tool = SimpleNamespace(invoke=lambda _tool_input: raw_table_dump)
    plan = QueryPlan(
        session_id="table-dump-session",
        message="直接执行库存表工具。",
        history=[],
        subqueries=["直接执行库存表工具。"],
        memory_intent=MemoryIntent(should_skip_rag=True),
        query_understanding=QueryUnderstanding(
            intent="tool_query",
            route="tool",
            modality="table",
            tool_name="structured_data_analysis",
            task_kind="structured_followup_query",
            should_skip_rag=True,
        ),
        active_skill=None,
        tool_input={"query": "直接执行库存表工具。", "path": "knowledge/E-commerce Data/inventory.xlsx"},
        execution_kind="direct_tool",
    )
    events, _retrieval, _model_runtime, _memory_facade = asyncio.run(
        _collect_events(
            plan,
            rag_mode=False,
            direct_tools={"structured_data_analysis": tool},
        )
    )

    done_text = str(events[-1]["content"])
    assert "warehouse,shortage" not in done_text
    assert "East,12" not in done_text
    assert "工具 `structured_data_analysis` 已执行，但当前结果尚未形成可直接展示的答案。" == done_text


def test_assistant_message_persistence_uses_canonical_visible_content() -> None:
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)

    messages = runtime._build_assistant_messages(
        [
            {
                "content": (
                    "好的，开始处理。</think><tool_call>terminal::run_command</tool_call>\n"
                    "**结论：先检查 workspace 的安全边界。**"
                ),
                "tool_calls": [],
            }
        ]
    )

    assert len(messages) == 1
    assert "</think>" not in messages[0]["content"]
    assert "<tool_call" not in messages[0]["content"]
    assert "先检查 workspace 的安全边界" in messages[0]["content"]


def test_output_boundary_strips_search_protocol_tail_from_visible_answer() -> None:
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)

    messages = runtime._build_assistant_messages(
        [
            {
                "content": (
                    "岩，上一轮我并没有给出三类风险。\n\n"
                    "现在我再检索一次本地知识库，看是否有 AI 治理相关内容："
                    "search_knowledge 查询本地知识库中关于 AI 治理风险的内容。"
                    "{\n\"query\": \"AI 治理 风险 类型 分类\",\n\"top_k\": 5\n}"
                ),
                "tool_calls": [],
            }
        ]
    )

    assert len(messages) == 1
    assert "search_knowledge" not in messages[0]["content"]
    assert "\"top_k\"" not in messages[0]["content"]
    assert "上一轮我并没有给出三类风险" in messages[0]["content"]


def main() -> None:
    test_memory_route_disables_tools()
    test_direct_tool_pdf_without_path_is_blocked_by_contract_gate()
    test_direct_tool_structured_without_path_is_blocked_by_contract_gate()
    test_workspace_file_read_direct_route_invokes_read_file_with_normalized_path()
    test_non_worker_rag_route_does_not_run_direct_retrieval()
    test_direct_tool_route_normalizes_final_content()
    test_runtime_uses_session_committed_dataset_binding_for_tool_promotion()
    test_runtime_uses_session_committed_pdf_binding_for_tool_promotion()
    test_pdf_direct_tool_facade_returns_canonical_summary_without_runtime_finalization()
    test_pdf_direct_tool_route_skips_model_finalization_for_degraded_result()
    test_pdf_direct_tool_facade_does_not_model_finalize_degraded_page_evidence()
    test_semantic_memory_signal_prefetches_durable_without_runtime_rag_fallback()
    test_execution_events_reuses_built_plan_for_subtasks()
    test_memory_route_does_not_promote_fake_tool_call_into_task_summary()
    test_followup_task_ref_is_answered_without_replanning()
    test_binding_followup_executes_from_owner_task_without_replanning()
    test_pdf_binding_followup_from_page_owner_does_not_inherit_page_mode_without_page_reference()
    test_binding_followup_candidate_yields_to_memory_plan_when_route_conflicts()
    test_ambiguous_binding_followup_requests_clarification_without_replanning()
    test_session_committed_pdf_binding_breaks_registry_ambiguity()
    test_runtime_output_boundary_strips_internal_protocol_from_streamed_answer()
    test_runtime_output_boundary_keeps_final_stream_answer_when_ai_update_is_partial()
    test_runtime_output_boundary_strips_inline_pseudo_tool_calls_from_visible_answer()
    test_runtime_output_boundary_salvages_nonempty_answer_when_only_procedural_text_remains()
    test_runtime_memory_visible_gate_rejects_procedural_segment_answer()
    test_runtime_memory_visible_gate_keeps_stable_memory_answer()
    test_runtime_rag_answer_finalizer_rewrites_missing_answer_from_evidence_pack()
    test_runtime_rag_answer_finalizer_rejects_procedural_rewrite_and_keeps_fallback()
    test_runtime_pdf_tool_output_boundary_no_longer_model_finalizes_tool_output()
    test_runtime_pdf_tool_output_boundary_keeps_fallback_without_model_rewrite()
    test_runtime_output_boundary_does_not_promote_plain_tool_output_to_done_content()
    test_runtime_stream_ignores_tool_message_chunks_before_provider_error()
    test_runtime_stream_timeout_becomes_nonempty_done_fallback()
    test_direct_tool_pdf_raw_dump_does_not_become_done_content()
    test_direct_tool_degraded_pdf_facade_projects_generic_fallback_state()
    test_direct_tool_pdf_canonical_facade_projects_minimal_binding_state()
    test_direct_tool_plain_table_dump_does_not_become_done_content()
    test_assistant_message_persistence_uses_canonical_visible_content()
    test_output_boundary_strips_search_protocol_tail_from_visible_answer()
    print("ALL PASSED (query runtime route guard regression)")


if __name__ == "__main__":
    main()
