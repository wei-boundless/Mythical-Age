from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from execution.model_runtime import ModelRuntimeError
from query import QueryRuntime
from understanding.query_understanding import analyze_query_understanding
from orchestration import RuntimeActionRequest, RuntimeLoopLimits
from orchestration.runtime_loop.safety import build_task_safety_validators
from orchestration.runtime_loop.task_run_loop import _builtin_tool_lane_answer_from_observation
from orchestration.runtime_loop.observation_aggregator import ObservationAggregator
from context_management.projection import projection_from_file_work
from orchestration.runtime_loop.tool_adoption import build_tool_request_runtime_adoption
from orchestration import ResourceDecision, ResourcePolicy, OperationGatePipelineContext
from capability_system import build_default_operation_registry


def _task_run_id_from_events(events: list[dict[str, object]]) -> str:
    started = next(event for event in events if event["type"] == "runtime_loop_started")
    return str(dict(started["task_run"]).get("task_run_id") or "")


def _runtime_event_payload(events: list[dict[str, object]], event_type: str) -> dict[str, object]:
    event = next(
        dict(item.get("event") or {})
        for item in events
        if item.get("type") == "runtime_loop_event"
        and dict(item.get("event") or {}).get("event_type") == event_type
    )
    return dict(event.get("payload") or {})


class _SettingsStub:
    def get_rag_mode(self) -> bool:
        return False

    def get_orchestration_plan_mode(self) -> str:
        return "primary"


class _MemoryFacadeStub:
    session_memory = SimpleNamespace(manager=lambda _session_id: SimpleNamespace(load_state=lambda: None))

    def __init__(self, state_snapshot: dict[str, object] | None = None) -> None:
        self._state_snapshot = dict(state_snapshot or {})

    def compact_history_for_query(self, _session_id, history):
        return history, {"pressure_level": "normal"}

    def inspect_query_context(self, *_args, **_kwargs):
        return {}

    def build_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_context_package(self, *_args, **_kwargs):
        return None

    def build_memory_runtime_view(self, *_args, **_kwargs):
        return {"state_snapshot": dict(self._state_snapshot)}

    def build_persistent_memory_block(self, *_args, **_kwargs):
        return ""

    def prefetch_relevant_notes(self, *_args, **_kwargs):
        return []

    def refresh_session_memory(self, *_args, **_kwargs):
        return ""

    def refresh_session_memory_from_context_state(self, *_args, **_kwargs):
        return ""

    def commit_durable_memory_extraction(self, *_args, **_kwargs):
        return 0


class _ToolRuntimeStub:
    registry = None
    definitions = []
    instances = []

    def get_instance(self, _name):
        return None


class _LoopToolRuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        from capability_system.tool_definitions import build_tool_instances, get_tool_definition_map

        self.instances = build_tool_instances(base_dir)
        self.definition_map = get_tool_definition_map()
        self.registry = None
        self.definitions = []

    def get_instance(self, _name):
        for item in self.instances:
            if getattr(item, "name", "") == _name:
                return item
        return None

    def get_definition(self, name):
        return self.definition_map.get(name)


class _SkillRegistryStub:
    skills = []

    def format_active_skill_block(self, _active_skill):
        return None

    def get_by_name(self, _name):
        return None

    def match_for_query(self, **_kwargs):
        return None


class _PermissionStub:
    def allowed_tool_names(self, *, allowed_tools=None):
        return list(allowed_tools or [])

    def can_invoke_tool(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=False, reason="not_authorized")


class _ModelRuntimeStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def invoke_messages(self, messages):
        self.messages = list(messages)
        return SimpleNamespace(content="single-agent runtime directive answer")


class _ToolLoopModelRuntimeStub:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_enabled_calls = 0
        self.last_tools: list[object] = []
        self.last_messages: list[object] = []

    async def invoke_messages(self, messages):
        self.calls += 1
        return SimpleNamespace(content="summary after tools")

    async def invoke_messages_with_tools(self, messages, tools):
        self.calls += 1
        self.tool_enabled_calls += 1
        self.last_messages = list(messages)
        self.last_tools = list(tools)
        if self.tool_enabled_calls > 1:
            return SimpleNamespace(content="summary after tools")
        return SimpleNamespace(
            content="",
            additional_kwargs={"reasoning_content": "I should inspect the file first."},
            tool_calls=[
                {
                    "id": f"tool-call-{self.calls}",
                    "name": "read_file",
                    "args": {"path": "backend/soul/agent_core/CORE.md"},
                    "type": "tool_call",
                }
            ],
        )


class _BoundAnswerModelRuntimeStub:
    async def invoke_messages(self, messages):
        return SimpleNamespace(content="这份 PDF 的结论可以压成三条行动建议：聚焦产业落地、补齐治理规则、持续评估风险。")


class _RagAnswerModelRuntimeStub:
    async def invoke_messages(self, messages):
        joined = "\n".join(str(dict(item).get("content") or "") for item in list(messages or []))
        if "当前检索证据" in joined:
            return SimpleNamespace(content="基于当前知识库证据，可以归纳出三类常见风险：模型滥用、数据与隐私风险，以及治理责任不清。")
        return SimpleNamespace(content="single-agent runtime directive answer")


class _RepeatingToolModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0

    async def invoke_messages(self, messages):
        return SimpleNamespace(content="summary")

    async def invoke_messages_with_tools(self, messages, tools):
        self.tool_enabled_calls += 1
        return SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": f"repeat-call-{self.tool_enabled_calls}",
                    "name": "mcp_pdf",
                    "args": {
                        "query": "第二部分的约束重点是什么？",
                        "path": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                        "mode": "section",
                    },
                    "type": "tool_call",
                }
            ],
        )


class _SessionManagerStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def load_session_record(self, _session_id):
        return {"messages": list(self.messages)}

    def load_session_for_agent(self, _session_id, *, include_compressed_context: bool = False):
        return list(self.messages)

    def load_session(self, _session_id):
        return list(self.messages)

    def save_message(self, _session_id, role, content):
        self.messages.append({"role": role, "content": content})

    def append_messages(self, _session_id, messages):
        self.messages.extend(messages)
        return list(messages)

    def set_title(self, _session_id, _title):
        return None


class _GameFileModelRuntimeStub:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_enabled_calls = 0
        self.last_tools: list[object] = []

    async def invoke_messages(self, messages):
        self.calls += 1
        return SimpleNamespace(content="已完成小游戏文件生成。")

    async def invoke_messages_with_tools(self, messages, tools):
        self.calls += 1
        self.tool_enabled_calls += 1
        self.last_tools = list(tools)
        if self.tool_enabled_calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-search-game-file",
                        "name": "search_files",
                        "args": {"query": "frontend/public/games"},
                        "type": "tool_call",
                    }
                ],
            )
        if self.tool_enabled_calls == 2:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-write-game-file",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/agent_generated_snake.html",
                            "content": "<!doctype html><html><head><meta charset='utf-8'><title>Agent Snake</title></head><body><h1>Agent Snake</h1><p>generated by runtime</p></body></html>",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(content="小游戏文件已生成到 frontend/public/games/agent_generated_snake.html")


class _ArcadeBundleModelRuntimeStub:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_enabled_calls = 0
        self.last_tools: list[object] = []

    async def invoke_messages(self, messages):
        self.calls += 1
        return SimpleNamespace(content="复合小游戏包已生成。")

    async def invoke_messages_with_tools(self, messages, tools):
        self.calls += 1
        self.tool_enabled_calls += 1
        self.last_tools = list(tools)
        if self.tool_enabled_calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-search-arcade-root",
                        "name": "search_files",
                        "args": {"query": "frontend/public/games/arcade_bundle"},
                        "type": "tool_call",
                    }
                ],
            )
        if self.tool_enabled_calls == 2:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-write-arcade-index",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/arcade_bundle/index.html",
                            "content": "<!doctype html><html><head><meta charset='utf-8'><title>Arcade Bundle</title><link rel='stylesheet' href='style.css'></head><body><main><h1>Arcade Bundle</h1><canvas id='game' width='480' height='320'></canvas><p id='status'>Press start.</p><button id='start'>Start</button><script src='game.js'></script></main></body></html>",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        if self.tool_enabled_calls == 3:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-write-arcade-style",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/arcade_bundle/style.css",
                            "content": "body{margin:0;font-family:Arial,sans-serif;background:#111827;color:#f3f4f6;display:grid;place-items:center;min-height:100vh}main{display:grid;gap:12px;justify-items:center}canvas{background:#0f172a;border:2px solid #334155}button{padding:10px 18px;background:#22c55e;border:none;color:#08130d;font-weight:700;cursor:pointer}",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        if self.tool_enabled_calls == 4:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-write-arcade-game",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/arcade_bundle/game.js",
                            "content": "const canvas=document.getElementById('game');const ctx=canvas.getContext('2d');const statusEl=document.getElementById('status');const startBtn=document.getElementById('start');let running=false;let x=24;let y=160;let vx=2;let score=0;function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#38bdf8';ctx.fillRect(x,y,24,24);ctx.fillStyle='#f59e0b';for(let i=0;i<5;i+=1){ctx.fillRect(60+i*72,40+i*18,18,18);}ctx.fillStyle='#f8fafc';ctx.fillText('Score: '+score,12,20);}function tick(){if(!running)return;x+=vx;if(x>canvas.width){x=-24;score+=1;statusEl.textContent='Loop cleared '+score+' times.';}draw();requestAnimationFrame(tick);}startBtn.addEventListener('click',()=>{if(running)return;running=true;statusEl.textContent='Running';tick();});draw();",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(content="多文件小游戏包已生成到 frontend/public/games/arcade_bundle/")


class _ArtifactClaimThenRepairModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0

    async def invoke_messages(self, messages):
        return SimpleNamespace(content="写入路径：`docs/系统规划/任务系统实测记录/artifacts/test/project_spec.md`\n\n验收状态：通过。")

    async def invoke_messages_with_tools(self, messages, tools):
        self.tool_enabled_calls += 1
        if self.tool_enabled_calls == 1:
            return SimpleNamespace(
                content=(
                    "写入路径：`docs/系统规划/任务系统实测记录/artifacts/test/project_spec.md`\n\n"
                    "任务阶段：项目立项。\n\n验收状态：通过。"
                )
            )
        return SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "id": "tool-call-required-artifact-repair",
                    "name": "write_file",
                    "args": {
                        "path": "docs/系统规划/任务系统实测记录/artifacts/test/project_spec.md",
                        "content": "# 项目规格\n\n项目目标：百万字长篇小说。\n\n1000000 字拆解：5卷，每卷40章，每章5000字。\n\n验收：必须逐阶段验收。\n\n禁止：不得伪造全本完成声明。",
                    },
                    "type": "tool_call",
                }
            ],
        )


class _ArtifactWriteThenFollowupProviderErrorModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0

    async def invoke_messages(self, messages):
        return SimpleNamespace(content="fallback")

    async def invoke_messages_with_tools(self, messages, tools):
        self.tool_enabled_calls += 1
        if self.tool_enabled_calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-write-artifact-before-provider-error",
                        "name": "write_file",
                        "args": {
                            "path": "docs/系统规划/任务系统实测记录/artifacts/test/volume_01_plan.md",
                            "content": "# 第一卷卷纲\n\n第一卷目标明确。\n\n40章拆解已建立。\n\n人物弧线、伏笔、第二卷入口均已规划。",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        raise ModelRuntimeError(
            code="provider_unavailable",
            provider="test",
            model="test-model",
            detail="Connection error.",
            retryable=True,
            user_message="模型服务暂时不可用，请稍后重试。",
        )


def _isolated_backend_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="query-runtime-regression-")) / "backend"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _build_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=SimpleNamespace(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )


def _build_stream_runtime() -> QueryRuntime:
    return QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )


def _build_tool_loop_runtime(tmp_path: Path) -> QueryRuntime:
    work_root = tmp_path / "backend"
    work_root.mkdir(parents=True, exist_ok=True)
    runtime = QueryRuntime(
        base_dir=work_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(work_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ToolLoopModelRuntimeStub(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=3)
    return runtime


def _build_bound_answer_runtime() -> QueryRuntime:
    memory_facade = _MemoryFacadeStub(
        state_snapshot={
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "committed_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            }
        }
    )
    runtime = QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=memory_facade,
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_BoundAnswerModelRuntimeStub(),
    )
    return runtime


def _build_repeating_pdf_runtime(tmp_path: Path) -> QueryRuntime:
    work_root = tmp_path / "backend"
    work_root.mkdir(parents=True, exist_ok=True)
    memory_facade = _MemoryFacadeStub(
        state_snapshot={
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "committed_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            }
        }
    )
    runtime = QueryRuntime(
        base_dir=work_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=memory_facade,
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(work_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_RepeatingToolModelRuntimeStub(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=8, max_turns=8)
    return runtime


def _build_game_generation_runtime(tmp_path: Path) -> QueryRuntime:
    work_root = tmp_path / "backend"
    work_root.mkdir(parents=True, exist_ok=True)
    runtime = QueryRuntime(
        base_dir=work_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(work_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_GameFileModelRuntimeStub(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=6, max_turns=6)
    return runtime


def _build_arcade_bundle_runtime(tmp_path: Path) -> QueryRuntime:
    work_root = tmp_path / "backend"
    work_root.mkdir(parents=True, exist_ok=True)
    runtime = QueryRuntime(
        base_dir=work_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(work_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ArcadeBundleModelRuntimeStub(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=8, max_turns=8)
    return runtime


def _build_rag_runtime() -> QueryRuntime:
    class _RetrievalServiceStub:
        def retrieve(self, query, top_k=5):
            return [
                {
                    "source": "knowledge/rag/ai_governance.md",
                    "text": "AI 治理中的常见风险通常包括模型滥用、数据与隐私风险，以及责任归属与治理流程不清。",
                    "score": 0.92,
                },
                {
                    "source": "knowledge/rag/ai_governance_faq.md",
                    "text": "在落地场景里，组织往往还会把合规审计和外部披露视为治理的一部分，但核心仍是滥用、数据、责任三类。",
                    "score": 0.81,
                },
            ]

    runtime = QueryRuntime(
        base_dir=_isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=_RetrievalServiceStub(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_RagAnswerModelRuntimeStub(),
    )
    return runtime


def _build_pdf_mcp_runtime() -> QueryRuntime:
    class _RetrievalServiceStub:
        def retrieve(self, query, top_k=5):
            return []

    memory_facade = _MemoryFacadeStub(
        state_snapshot={
            "context_slots": {
                "active_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
                "committed_pdf": "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf",
            }
        }
    )
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=memory_facade,
        retrieval_service=_RetrievalServiceStub(),
        tool_runtime=_LoopToolRuntimeStub(BACKEND_DIR),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_BoundAnswerModelRuntimeStub(),
    )
    return runtime


def _build_structured_data_mcp_runtime() -> QueryRuntime:
    class _RetrievalServiceStub:
        def retrieve(self, query, top_k=5):
            return []

    memory_facade = _MemoryFacadeStub(
        state_snapshot={
            "context_slots": {
                "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                "committed_dataset": "knowledge/E-commerce Data/inventory.xlsx",
            }
        }
    )
    runtime = QueryRuntime(
        base_dir=BACKEND_DIR,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=memory_facade,
        retrieval_service=_RetrievalServiceStub(),
        tool_runtime=_LoopToolRuntimeStub(BACKEND_DIR),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )
    return runtime


def _build_required_artifact_repair_runtime(tmp_path: Path) -> QueryRuntime:
    work_root = tmp_path / "backend"
    work_root.mkdir(parents=True, exist_ok=True)
    runtime = QueryRuntime(
        base_dir=work_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(work_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ArtifactClaimThenRepairModelRuntimeStub(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=8, max_turns=8)
    return runtime


def _build_artifact_followup_error_runtime(tmp_path: Path) -> QueryRuntime:
    work_root = tmp_path / "backend"
    work_root.mkdir(parents=True, exist_ok=True)
    runtime = QueryRuntime(
        base_dir=work_root,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_LoopToolRuntimeStub(work_root),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ArtifactWriteThenFollowupProviderErrorModelRuntimeStub(),
    )
    runtime.task_run_loop.limits = RuntimeLoopLimits(max_runtime_seconds=300.0, max_model_calls=8, max_turns=8)
    return runtime


def test_execution_events_use_runtime_stream() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(
            "session-runtime-events",
            "修改任务系统文档，然后检查有没有前后矛盾",
            [],
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]

    assert "runtime_directive" in event_types
    assert "operation_gate" in event_types
    assert "done" in event_types
    assert not any(str(event_type).endswith("_preview") for event_type in event_types)


def test_astream_executes_only_model_response_runtime_directive() -> None:
    runtime = _build_stream_runtime()

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-runtime-directive",
                message="给我一个简短结论",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]
    directive_event = next(event for event in events if event["type"] == "runtime_directive")
    gate_event = next(event for event in events if event["type"] == "operation_gate")
    input_commit_event = next(event for event in events if event["type"] == "input_commit_gate")
    done_event = next(event for event in events if event["type"] == "done")

    assert not any(str(event_type).endswith("_preview") for event_type in event_types)
    assert "input_commit_gate" in event_types
    assert "runtime_directive" in event_types
    assert "operation_gate" in event_types
    assert "answer_candidate" in event_types
    assert "output_boundary" in event_types
    assert "runtime_commit_gate" in event_types
    assert "done" in event_types
    assert not any(
        event.get("type") == "error" and event.get("answer_source") == "control_kernel"
        for event in events
    )
    assert input_commit_event["commit_gate"]["commit_allowed"] is True
    assert input_commit_event["commit_gate"]["commit_candidate"]["payload"]["role"] == "user"
    assert input_commit_event["commit_gate"]["diagnostics"]["assistant_write_allowed"] is False
    assert directive_event["directive"]["executor_type"] == "model"
    assert "op.model_response" in directive_event["directive"]["operation_refs"]
    assert directive_event["resource_policy"]["adopted"] is True
    assert directive_event["resource_policy"]["runtime_executable"] is True
    assert "op.model_response" in directive_event["resource_policy"]["allowed_operations"]
    assert gate_event["gate"]["allowed"] is True
    assert gate_event["gate"]["operation_id"] == "op.model_response"
    output_event = next(event for event in events if event["type"] == "output_boundary")
    runtime_commit_gate_event = next(event for event in events if event["type"] == "runtime_commit_gate")
    assert output_event["output"]["canonical_answer"] == "single-agent runtime directive answer"
    assert runtime_commit_gate_event["commit_gate"]["status"] == "blocked"
    assert runtime_commit_gate_event["commit_gate"]["commit_allowed"] is False
    assert runtime_commit_gate_event["commit_gate"]["reason"] == "commit_gate_blocked"
    assert all(
        candidate["allowed"] is False
        for candidate in runtime_commit_gate_event["commit_gate"]["commit_candidates"]
    )
    assert done_event["answer_source"] == "runtime_directive:model_response"
    assert done_event["persist_policy"] == "committed"
    assert done_event["commit_gate"]["commit_allowed"] is True
    assert done_event["content"] == "single-agent runtime directive answer"
    assert done_event["output_commit"]["assistant_commit_applied"] is True
    projection_event = next(
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "stage_projection_built"
    )
    projection = dict(dict(projection_event["event"]).get("payload", {}).get("stage_projection") or {})
    sections = list(dict(projection.get("soul_runtime_view") or {}).get("sections") or [])
    section_ids = {str(dict(section).get("section_id") or "") for section in sections}
    assert "resource_section" not in section_ids
    assert "guardrail_section" not in section_ids
    context_event = next(
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "context_snapshot_built"
    )
    snapshot = dict(dict(context_event["event"]).get("payload", {}).get("context_snapshot") or {})
    system_prompt = str(list(snapshot.get("model_messages") or [{}])[0].get("content") or "")
    assert "resource_section" not in system_prompt
    assert "guardrail_section" not in system_prompt
    task_contract_event = next(
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_contract_built"
    )
    task_contract_payload = dict(dict(task_contract_event["event"]).get("payload", {}) or {})
    task_result = dict(done_event.get("task_result") or {})
    task_run_ledger = dict(done_event.get("task_run_ledger") or {})
    step_entered_events = [
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "step_entered"
    ]
    step_completed_events = [
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "step_completed"
    ]
    ledger_events = [
        event
        for event in events
        if event["type"] == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "task_run_ledger_updated"
    ]
    assert task_contract_payload["task_spec"]["task_spec_ref"] == task_contract_payload["task_contract"]["task_spec_ref"]
    assert task_contract_payload["task_run_ledger"]["task_spec_ref"] == task_contract_payload["task_spec"]["task_spec_ref"]
    assert task_result["authority"] == "task_system.task_result"
    assert task_result["task_spec_ref"] == task_contract_payload["task_spec"]["task_spec_ref"]
    assert task_result["template_id"] == task_contract_payload["selected_template"]["template_id"]
    assert task_result["requested_outputs"] == ["final_answer"]
    assert task_run_ledger["authority"] == "task_system.task_run_ledger"
    assert task_run_ledger["task_spec_ref"] == task_result["task_spec_ref"]
    assert step_entered_events
    assert step_completed_events
    assert ledger_events
    assert dict(step_entered_events[0]["event"]["payload"]["step_run"])["status"] == "running"
    assert dict(step_completed_events[-1]["event"]["payload"]["step_run"])["status"] == "completed"
    assert dict(ledger_events[-1]["event"]["payload"]["task_run_ledger"])["status"] == "completed"
    assert any(step["status"] == "completed" for step in task_result["step_runs"])
    assert done_event["task_result_commit"]["commit_candidate"]["payload"]["task_result"]["result_id"] == task_result["result_id"]


def test_astream_runs_rag_via_mcp_retrieval_phase() -> None:
    runtime = _build_rag_runtime()

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-rag-mcp",
                message="基于本地知识库，告诉我 AI 治理里最常见的三类风险。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]
    done_event = next(event for event in events if event["type"] == "done")

    assert "mcp_start" in event_types
    assert "mcp_evidence" in event_types
    assert "mcp_end" in event_types
    assert done_event["answer_source"] == "mcp.retrieval_local"
    assert "模型滥用" in done_event["content"]
    assert "runtime_directive" in event_types


def test_astream_runs_pdf_via_mcp_phase() -> None:
    runtime = _build_pdf_mcp_runtime()

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-pdf-mcp",
                message="把 knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf 的结论压成三条行动建议。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]
    done_event = next(event for event in events if event["type"] == "done")
    mcp_end_event = next(event for event in events if event["type"] == "mcp_end")

    assert "mcp_start" in event_types
    assert "mcp_evidence" in event_types
    assert "mcp_end" in event_types
    assert dict(mcp_end_event.get("result") or {}).get("result_kind") == "pdf_answer"
    assert done_event["answer_source"] == "mcp.pdf_local"
    assert done_event["main_context"]["active_work_item"] == "pdf"
    assert done_event["main_context"]["followup_binding_key"] == "active_pdf"
    assert done_event["main_context"]["active_constraints"]["active_pdf"].endswith(".pdf")


def test_astream_runs_structured_data_via_mcp_phase() -> None:
    runtime = _build_structured_data_mcp_runtime()

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-structured-mcp",
                message="分析 knowledge/E-commerce Data/inventory.xlsx，按仓库汇总前五。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    event_types = [event["type"] for event in events]
    done_event = next(event for event in events if event["type"] == "done")
    mcp_end_event = next(event for event in events if event["type"] == "mcp_end")

    assert "mcp_start" in event_types
    assert "mcp_evidence" in event_types
    assert "mcp_end" in event_types
    assert dict(mcp_end_event.get("result") or {}).get("result_kind") == "structured_answer"
    assert done_event["answer_source"] == "mcp.structured_data_local"
    assert done_event["main_context"]["active_work_item"] == "structured_data"
    assert done_event["main_context"]["followup_binding_key"] == "active_dataset"
    assert done_event["main_context"]["active_constraints"]["active_dataset"].endswith(".xlsx")


def test_astream_exposes_only_adopted_main_runtime_tools_to_model_lane(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
                QueryRequest(
                    session_id="session-budget-exhausted",
                    message="读取 backend/soul/agent_core/CORE.md 并总结",
                    history=[],
                )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    assistant_commit_event = next(event for event in events if event["type"] == "runtime_assistant_session_commit")
    directive_event = next(event for event in events if event["type"] == "runtime_directive")
    tool_names = {getattr(tool, "name", "") for tool in runtime.model_runtime.last_tools}

    assert runtime.model_runtime.tool_enabled_calls >= 1
    assert {"search_files", "search_text", "read_file"}.issubset(tool_names)
    assert "terminal" not in tool_names
    assert "python_repl" not in tool_names
    assert "op.read_file" in directive_event["resource_policy"]["allowed_operations"]
    assert "tool_call_requested" in [event.get("type") for event in events]
    assert "tool_result_received" in [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    assert assistant_commit_event["commit_applied"] is True


def test_astream_keeps_hidden_and_unrequested_tools_out_of_model_lane(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-hidden-tools",
                message="读取 backend/soul/agent_core/CORE.md 并检查内容",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    tool_names = {getattr(tool, "name", "") for tool in runtime.model_runtime.last_tools}
    directive_event = next(event for event in events if event["type"] == "runtime_directive")

    assert "read_file" in tool_names
    assert "terminal" not in tool_names
    assert "python_repl" not in tool_names
    assert "pdf_analysis" not in tool_names
    assert "op.shell" not in directive_event["resource_policy"]["allowed_operations"]
    assert "op.python_repl" not in directive_event["resource_policy"]["allowed_operations"]


def test_runtime_trace_includes_execution_records_and_checkpoint_summary(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-trace-execution",
                message="读取 backend/soul/agent_core/CORE.md 并总结",
                history=[],
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        task_run_id = str(dict(started["task_run"]).get("task_run_id") or "")
        return events, task_run_id

    events, task_run_id = asyncio.run(_collect())
    trace = runtime.task_run_loop.get_trace(task_run_id)


def test_astream_specific_light_web_game_task_can_write_new_file(tmp_path: Path) -> None:
    runtime = _build_game_generation_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-agent-game",
                message="生成一个简单网页贪吃蛇小游戏",
                history=[],
                task_selection={"selected_task_id": "task.dev.light_web_game"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    target = tmp_path / "frontend" / "public" / "games" / "agent_generated_snake.html"
    directive_event = next(event for event in events if event["type"] == "runtime_directive")
    done_event = next(event for event in events if event["type"] == "done")
    started_event = next(event for event in events if event["type"] == "runtime_loop_started")
    task_run_id = str(dict(started_event["task_run"]).get("task_run_id") or "")
    trace = runtime.task_run_loop.get_trace(task_run_id)
    runtime_event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]

    assert target.exists()
    assert "generated by runtime" in target.read_text(encoding="utf-8")
    assert "op.write_file" in directive_event["resource_policy"]["allowed_operations"]
    assert "tool_call_requested" in [event.get("type") for event in events]
    assert "tool_result_received" in runtime_event_types
    assert done_event["content"]

    assert trace is not None
    event_types = [str(item.get("event_type") or "") for item in list(trace.get("events") or [])]
    latest_checkpoint = dict(trace.get("latest_checkpoint") or {})

    assert "execution_record_created" in event_types
    assert "execution_dispatch_started" in event_types
    assert "execution_result_recorded" in event_types
    assert dict(latest_checkpoint.get("execution_summary") or {}).get("execution_count", 0) >= 1
    assert list(latest_checkpoint.get("execution_refs") or [])
    assert not any(
        str(dict(event.get("event") or {}).get("event_type") or "") == "replay_guard_triggered"
        for event in events
        if event.get("type") == "runtime_loop_event"
    )


def test_astream_arcade_game_bundle_task_can_write_multiple_files_within_bounded_root(tmp_path: Path) -> None:
    runtime = _build_arcade_bundle_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-agent-arcade",
                message="生成一个包含开始界面、游戏脚本和样式文件的网页小游戏包",
                history=[],
                task_selection={"selected_task_id": "task.dev.arcade_game_bundle"},
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    bundle_root = tmp_path / "frontend" / "public" / "games" / "arcade_bundle"
    index_file = bundle_root / "index.html"
    style_file = bundle_root / "style.css"
    game_file = bundle_root / "game.js"
    directive_event = next(event for event in events if event["type"] == "runtime_directive")

    assert index_file.exists()
    assert style_file.exists()
    assert game_file.exists()
    assert "Arcade Bundle" in index_file.read_text(encoding="utf-8")
    assert "canvas" in game_file.read_text(encoding="utf-8")
    assert "op.write_file" in directive_event["resource_policy"]["allowed_operations"]


def test_required_artifact_task_repairs_claim_without_write_file_into_real_tool_evidence(tmp_path: Path) -> None:
    runtime = _build_required_artifact_repair_runtime(tmp_path)

    async def _collect() -> tuple[list[dict[str, object]], str]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-required-artifact-repair",
                message=(
                    "按正式长篇小说项目立项任务启动。必须调用 write_file 写入 "
                    "docs/系统规划/任务系统实测记录/artifacts/test/project_spec.md，"
                    "内容包含项目目标、1000000字拆解、5卷结构、验收、禁止伪造全本完成声明。"
                ),
                history=[],
                task_selection={"selected_task_id": "task.writing.longform_novel_project"},
            )
        ):
            events.append(event)
        return events, _task_run_id_from_events(events)

    events, task_run_id = asyncio.run(_collect())
    target = tmp_path / "docs" / "系统规划" / "任务系统实测记录" / "artifacts" / "test" / "project_spec.md"
    runtime_event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    validation_payload = _runtime_event_payload(events, "task_artifact_validation_checked")
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)

    assert target.exists()
    assert "1000000" in target.read_text(encoding="utf-8")
    assert "required_artifact_write_repair_started" in runtime_event_types
    assert "tool_result_received" in runtime_event_types
    assert dict(validation_payload["validation"])["passed"] is True
    assert trace is not None
    assert any(
        dict(dict(event).get("payload") or {}).get("validation", {}).get("passed") is True
        for event in trace["events"]
        if dict(event).get("event_type") == "task_artifact_validation_checked"
    )


def test_required_artifact_task_completes_when_followup_model_fails_after_write(tmp_path: Path) -> None:
    from query.models import QueryRequest

    runtime = _build_artifact_followup_error_runtime(tmp_path)

    async def _collect() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-artifact-followup-provider-error",
                message=(
                    "按正式卷规划任务生成第一卷卷纲。必须调用 write_file 写入 "
                    "docs/系统规划/任务系统实测记录/artifacts/test/volume_01_plan.md，"
                    "内容包含第一卷目标、40章段落拆解、人物弧线、伏笔投放回收、第二卷入口。"
                ),
                history=[],
                task_selection={"selected_task_id": "task.writing.volume_planning"},
            )
        ):
            events.append(event)
        return events, _task_run_id_from_events(events)

    events, task_run_id = asyncio.run(_collect())
    target = tmp_path / "docs" / "系统规划" / "任务系统实测记录" / "artifacts" / "test" / "volume_01_plan.md"
    runtime_event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    done_event = next(event for event in events if event["type"] == "done")
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)

    assert target.exists()
    assert "40章" in target.read_text(encoding="utf-8")
    assert "artifact_success_fallback_finalized" in runtime_event_types
    assert done_event["terminal_reason"] == "completed"
    assert done_event["answer_fallback_reason"] == "artifact_success_fallback"
    assert trace is not None
    assert trace["task_run"]["status"] == "completed"
    assert trace["coordination_runs"]
    coordination_run = trace["coordination_runs"][0]
    assert coordination_run["status"] == "completed"
    assert coordination_run["latest_merge_result"] is not None


def test_arcade_game_bundle_blocks_write_outside_bounded_root(tmp_path: Path) -> None:
    runtime = _build_arcade_bundle_runtime(tmp_path)
    safety_validators = build_task_safety_validators(
        root_dir=tmp_path,
        safety_envelope={
            "safety_class": "S1_bounded_artifact_write",
            "write_mode": "bounded_create",
            "write_roots": ["frontend/public/games/arcade_bundle"],
            "forbidden_paths": ["backend", "storage", ".env"],
        },
    )
    gate_result = runtime.task_run_loop.operation_gate.check(
        "op.write_file",
        resource_policy=ResourcePolicy(
            policy_id="respol:test:arcade",
            task_id="task.dev.arcade_game_bundle",
            allowed_operations=("op.write_file",),
            denied_operations=(),
            requires_approval_operations=(),
            not_executable_operations=(),
            adopted=True,
            runtime_executable=True,
            runtime_view_only=False,
        ),
        directive_ref="runtime-directive:test",
        context=OperationGatePipelineContext(
            operation_input={"path": "backend/unsafe.py", "content": "print('nope')"},
            validators=safety_validators,
        ),
    )

    assert gate_result.allowed is False
    assert "outside task write roots" in gate_result.reason or "blocked by task safety envelope" in gate_result.reason


def test_followup_after_tool_result_stays_tool_capable_until_final_answer(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-followup-synthesis",
                message="读取 backend/soul/agent_core/CORE.md 并总结",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done_event = next(event for event in events if event["type"] == "done")
    tool_request_events = [
        event
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "tool_call_requested"
    ]
    loop_control_events = [
        event
        for event in events
        if event.get("type") == "runtime_loop_event"
        and dict(event.get("event") or {}).get("event_type") == "loop_control_checked"
    ]

    assert runtime.model_runtime.tool_enabled_calls == 2
    assert len(tool_request_events) == 1
    assert len(loop_control_events) >= 2
    assert done_event["content"] == "summary after tools"
    assert done_event["answer_source"] == "runtime_directive:model_response"


def test_followup_replays_deepseek_reasoning_content_after_tool_result(tmp_path: Path) -> None:
    runtime = _build_tool_loop_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-deepseek-reasoning-roundtrip",
                message="读取 backend/soul/agent_core/CORE.md 并总结",
                history=[],
            )
        ):
            events.append(event)
        return events

    asyncio.run(_collect())

    assistant_messages = [
        message
        for message in runtime.model_runtime.last_messages
        if message.__class__.__name__ == "AIMessage"
    ]
    assert assistant_messages
    assert (
        assistant_messages[-1].additional_kwargs.get("reasoning_content")
        == "I should inspect the file first."
    )


def test_legacy_pdf_tool_result_no_longer_finalizes_directly() -> None:
    answer = _builtin_tool_lane_answer_from_observation(
        user_message="打开这份 PDF，给我一个全文总览",
        observation_payload={
            "tool_name": "pdf_analysis",
            "tool_args": {
                "query": "全文总览",
                "path": "knowledge/AI Knowledge/report.pdf",
                "mode": "document",
            },
            "result": (
                'PDF_CANONICAL_RESULT::{"status":"ok","source":"knowledge/AI Knowledge/report.pdf",'
                '"requested_mode":"document","effective_mode":"document",'
                '"summary":"这份 PDF 的核心结论是 AI 治理正在从抽象风险转向现实产业落地。",'
                '"degraded_reason":"","pages":[3],'
                '"evidence":[{"page_number":3,"score":1.0,"snippet":"AI 治理正在回归现实主义。"}],'
                '"error":"","metadata":{"query":"全文总览","target_page":3}}'
            ),
        },
    )

    assert answer is None


def test_web_search_raw_json_result_no_longer_finalizes_directly() -> None:
    answer = _builtin_tool_lane_answer_from_observation(
        user_message="帮我查一下黄金现在的价格",
        observation_payload={
            "tool_name": "web_search",
            "tool_args": {"query": "黄金价格 今日 2026"},
            "result": (
                '{'
                '"ok": true, '
                '"query": "黄金价格 今日 2026", '
                '"response_time": 0.96, '
                '"request_id": "abc", '
                '"results": ['
                '{"title": "Gold price today", "content": "Gold opened at $4569.30 and rose to $4711.90."}'
                "]"
                "}"
            ),
        },
    )

    assert answer is None


def test_observation_aggregator_merges_multiple_tool_projections() -> None:
    aggregator = ObservationAggregator()
    pdf_projection = projection_from_file_work(
        {
            "active_work_item": "pdf",
            "active_object_handle_id": "source:pdf:a",
            "active_result_handle_id": "result:pdf:a",
            "active_constraints": {"active_pdf": "knowledge/AI/report.pdf", "source_kind": "pdf"},
        },
        [{"task_id": "result:pdf:a", "query": "第三页", "summary": "第三页摘要", "task_kind": "pdf"}],
    )
    dataset_projection = projection_from_file_work(
        {
            "active_work_item": "structured_data",
            "active_object_handle_id": "source:dataset:b",
            "active_result_handle_id": "result:data:b",
            "active_constraints": {"active_dataset": "knowledge/E-commerce Data/inventory.xlsx", "source_kind": "dataset"},
        },
        [{"task_id": "result:data:b", "query": "前三仓库", "summary": "前三仓库摘要", "task_kind": "structured_data"}],
    )

    aggregation = aggregator.add_projection(pdf_projection, tool_name="mcp_pdf")
    aggregation = aggregator.add_projection(dataset_projection, tool_name="mcp_structured_data")

    assert aggregation.is_compound is True
    assert len(aggregation.projection.task_summary_refs) == 2
    assert set(aggregation.tool_names) == {"mcp_pdf", "mcp_structured_data"}


def test_bound_pdf_answer_writes_followup_context_without_new_tool_result() -> None:
    runtime = _build_bound_answer_runtime()

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-bound-pdf-answer",
                message="把这份 PDF 的结论压成三条行动建议。",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done_event = next(event for event in events if event["type"] == "done")

    assert done_event["followup_mode"] == "binding_ref"
    assert done_event["followup_target_task_id"]
    assert done_event["main_context"]["active_constraints"]["active_pdf"] == "knowledge/AI Knowledge/2025年AI治理报告：回归现实主义.pdf"
    assert done_event["output_commit"]["file_work_context_writeback"] is True
    assert done_event["task_summary_refs"]


def test_repeated_pdf_tool_calls_force_loop_to_stop_before_budget_exhaustion(tmp_path: Path) -> None:
    runtime = _build_repeating_pdf_runtime(tmp_path)

    async def _collect() -> list[dict[str, object]]:
        from query.models import QueryRequest

        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-repeated-pdf-guard",
                message="回到刚才 PDF，第二部分的约束重点是什么？",
                history=[],
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    done_event = next(event for event in events if event["type"] == "done")

    assert runtime.model_runtime.tool_enabled_calls <= 3
    assert done_event["answer_fallback_reason"] != "runtime_budget_exhausted"
    assert done_event["content"]
    assert done_event["followup_mode"] == "binding_ref"


def test_bundle_answer_projection_creates_ordinal_refs_for_model_synthesized_parts() -> None:
    from context_management.projection import projection_from_bundle_answer

    projection = projection_from_bundle_answer(
        content=(
            "### 一、PDF 第三页总结\n第三页是封面。\n\n"
            "---\n\n"
            "### 二、inventory.xlsx 最缺货的前三个仓库\n深圳仓、广州仓、成都仓最需要补货。\n\n"
            "---\n\n"
            "### 三、北京天气\n北京阴天。"
        ),
        bundle_items=[
            {
                "bundle_id": "bundle:task-bundle",
                "item_id": "bundle:task-bundle:item:1",
                "ordinal": 1,
                "user_text": "总结 PDF 第三页",
                "template_id": "template.pdf.document_analysis",
                "capability_kind": "pdf",
                "required_tool": "",
            },
            {
                "bundle_id": "bundle:task-bundle",
                "item_id": "bundle:task-bundle:item:2",
                "ordinal": 2,
                "user_text": "inventory.xlsx 最缺货的前三个仓库",
                "template_id": "template.data.structured_analysis",
                "capability_kind": "structured_data",
                "required_tool": "",
            },
            {
                "bundle_id": "bundle:task-bundle",
                "item_id": "bundle:task-bundle:item:3",
                "ordinal": 3,
                "user_text": "补一句北京天气",
                "template_id": "template.search.information_search",
                "capability_kind": "realtime_network",
                "required_tool": "web_search",
            },
        ],
    )

    assert projection.main_context["followup_mode"] == "bundle_ref"
    assert len(projection.bundle_summary_refs) == 3
    assert projection.bundle_summary_refs[1]["ordinal"] == 2
    assert projection.bundle_summary_refs[1]["bundle_id"] == "bundle:task-bundle"
    assert projection.bundle_summary_refs[1]["item_id"] == "bundle:task-bundle:item:2"
    assert projection.bundle_summary_refs[1]["template_id"] == "template.data.structured_analysis"
    assert "深圳仓" in projection.bundle_summary_refs[1]["summary"]
    assert projection.bundle_summary_refs[1]["required_tool"] == ""


def test_bundle_answer_projection_only_projects_executed_ordinals() -> None:
    from context_management.projection import projection_from_bundle_answer

    projection = projection_from_bundle_answer(
        content="第三页摘要。",
        bundle_items=[
            {"ordinal": 1, "user_text": "总结 PDF 第三页", "capability_kind": "pdf", "required_tool": ""},
            {
                "ordinal": 2,
                "user_text": "inventory.xlsx 最缺货的前三个仓库",
                "capability_kind": "structured_data",
                "required_tool": "",
            },
            {"ordinal": 3, "user_text": "补一句北京天气", "capability_kind": "realtime_network", "required_tool": "web_search"},
        ],
        existing_task_summary_refs=[
            {"task_id": "result:pdf:a", "query": "第三页", "summary": "第三页摘要。", "task_kind": "pdf"}
        ],
        executed_ordinals=[1],
    )

    assert [item["ordinal"] for item in projection.bundle_summary_refs] == [1]
    assert len(projection.task_summary_refs) == 2


def test_file_work_projection_only_creates_bundle_refs_for_matching_items() -> None:
    projection = projection_from_file_work(
        {
            "active_work_item": "pdf",
            "active_object_handle_id": "source:pdf:a",
            "active_result_handle_id": "result:pdf:a",
            "active_constraints": {"active_pdf": "knowledge/AI/report.pdf", "source_kind": "pdf"},
        },
        [
            {
                "task_id": "result:pdf:a",
                "query": "第三页",
                "summary": "第三页摘要",
                "task_kind": "pdf",
                "key_points": ["pdf=knowledge/AI/report.pdf"],
            }
        ],
        bundle_items=[
            {
                "ordinal": 1,
                "user_text": "总结 PDF 第三页",
                "capability_kind": "pdf",
                "required_tool": "",
                "target_binding": {"file_kind": "pdf", "metadata": {"path": "knowledge/AI/report.pdf"}},
            },
            {
                "ordinal": 2,
                "user_text": "inventory.xlsx 最缺货的前三个仓库",
                "capability_kind": "structured_data",
                "required_tool": "",
                "target_binding": {"file_kind": "dataset", "metadata": {"path": "knowledge/E-commerce Data/inventory.xlsx"}},
            },
        ],
    )

    assert [item["ordinal"] for item in projection.bundle_summary_refs] == [1]


def test_realtime_weather_intent_overrides_bound_dataset_followup() -> None:
    understanding = analyze_query_understanding(
        "再看一下北京今天天气。",
        active_bindings={"active_dataset": "knowledge/E-commerce Data/inventory.xlsx"},
        tool_registry=_LoopToolRuntimeStub(Path.cwd()).registry,
    )

    assert understanding.intent == "weather_query"
    assert understanding.capability_requests == ["weather", "latest_information"]
    assert understanding.should_skip_rag is True


def test_tool_request_adoption_cannot_self_authorize_against_adopted_policy() -> None:
    registry = build_default_operation_registry()
    action_request = RuntimeActionRequest(
        request_id="rtact-test",
        task_run_id="taskrun-test",
        request_type="tool_call",
        operation_id="read_file",
        payload={"tool_name": "read_file", "tool_call": {"name": "read_file", "args": {}}},
    )
    adopted_policy = ResourcePolicy(
        policy_id="respol-test-adopted-runtime",
        task_id="task-test",
        allowed_operations=("op.model_response",),
        adopted=True,
        runtime_executable=True,
        runtime_view_only=False,
        decisions=(
            ResourceDecision(
                operation_id="op.model_response",
                decision="allow",
                reason="test policy only allows model response",
            ),
        ),
    )

    _directive, tool_policy = build_tool_request_runtime_adoption(
        action_request=action_request,
        task_id="task-test",
        task_operation={},
        operation_id="op.read_file",
        operation_descriptor=registry.get_operation("op.read_file"),
        adopted_resource_policy=adopted_policy,
    )

    assert tool_policy.allowed_operations == ()
    assert tool_policy.denied_operations == ("op.read_file",)
    assert tool_policy.decisions[0].decision == "deny"
    assert tool_policy.decisions[0].reason == "tool request is not allowed by adopted resource policy"


def test_runtime_trace_exposes_worker_spawn_and_coordination_objects_for_specific_task(tmp_path: Path) -> None:
    from tasks import TaskFlowRegistry
    from query.models import QueryRequest

    base_dir = _isolated_backend_root()
    registry = TaskFlowRegistry(base_dir)
    registry.upsert_task_agent_adoption_plan(
        task_id="task.dev.light_web_game",
        adoption_mode="adopt_with_projection",
        default_agent_id="agent:0",
        allowed_agent_categories=("main_agent", "worker_sub_agent"),
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.dev.prototype",
        worker_agent_naming_rule="game-worker-{n}",
        notes="trace visibility test",
    )
    registry.upsert_coordination_task(
        coordination_task_id="coord.dev.parallel_story",
        title="小游戏协同",
        coordination_mode="review_merge",
        coordinator_agent_id="agent:0",
        participant_agent_ids=("agent:6",),
        topology_template_id="topology.dev.parallel_story",
        handoff_policy="structured_handoff",
        output_merge_policy="coordinator_final_merge",
        enabled=True,
    )
    registry.upsert_topology_template(
        template_id="topology.dev.parallel_story",
        title="小游戏协同拓扑",
        nodes=(
            {"node_id": "worker_lane", "agent_id": "agent:6", "lane": "game_delivery", "role": "worker_participant"},
            {"node_id": "merge_lane", "agent_id": "agent:0", "lane": "final_integration", "role": "coordinator"},
        ),
        edges=(
            {"from": "worker_lane", "to": "merge_lane", "policy": "structured_handoff"},
        ),
        enabled=True,
    )
    registry.upsert_task_communication_protocol(
        protocol_id="protocol.dev.parallel_story",
        title="小游戏协同协议",
        message_types=("draft_result", "final_merge_request"),
        payload_contracts=("LightWebGameResult",),
        signal_rules=("worker_to_coordinator",),
        handoff_rules=("structured_handoff",),
        enabled=True,
    )

    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-trace-worker-coordination",
                message="开发一个轻量网页小游戏。",
                history=[],
                task_selection={
                    "task_id": "task.dev.light_web_game",
                    "task_mode": "light_web_game",
                    "coordination_task_id": "coord.dev.parallel_story",
                },
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    events, task_run_id = asyncio.run(_collect())
    trace = runtime.task_run_loop.get_trace(task_run_id)
    event_types = [
        dict(event.get("event") or {}).get("event_type")
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]

    assert trace is not None
    assert "worker_agent_spawn_requested" in event_types
    assert "worker_agent_spawn_completed" in event_types
    assert "coordination_node_run_created" in event_types
    assert trace["worker_spawn_requests"]
    assert trace["worker_spawn_results"]
    assert len(trace["coordination_runs"]) == 1
    assert trace["coordination_runs"][0]["node_runs"]
    assert trace["coordination_runs"][0]["handoff_envelopes"]


def test_runtime_trace_exposes_coordination_flow_and_agent_run_results(tmp_path: Path) -> None:
    from tasks import TaskFlowRegistry
    from query.models import QueryRequest

    base_dir = _isolated_backend_root()
    registry = TaskFlowRegistry(base_dir)
    registry.upsert_coordination_task(
        coordination_task_id="coord.writing.short_story_pipeline",
        title="短篇小说协作流水线",
        coordination_mode="staged_review_loop",
        coordinator_agent_id="agent:0",
        participant_agent_ids=("agent:4", "agent:5"),
        topology_template_id="topology.writing.short_story_pipeline",
        handoff_policy="stage_contract_handoff",
        output_merge_policy="acceptance_then_final_merge",
        enabled=True,
        metadata={
            "max_revision_cycles": 1,
            "required_revision_cycles": 1,
            "stage_sequence": [
                {"stage_id": "idea_proposal", "node_id": "idea_worker", "role": "participant", "message_type": "idea_proposal"},
                {"stage_id": "idea_review", "node_id": "idea_review", "role": "participant", "message_type": "idea_review"},
                {"stage_id": "approval_signal", "node_id": "approval_gate", "role": "coordinator", "message_type": "approval_signal"},
                {"stage_id": "draft_submission", "node_id": "draft_writer", "role": "participant", "message_type": "draft_submission"},
                {"stage_id": "content_issue", "node_id": "content_check", "role": "participant", "message_type": "content_issue"},
                {"stage_id": "revision_request", "node_id": "revision_loop", "role": "participant", "message_type": "revision_request", "loop_kind": "revision_loop"},
                {"stage_id": "acceptance_result", "node_id": "acceptance", "role": "coordinator", "message_type": "acceptance_result"},
            ],
        },
    )
    registry.upsert_topology_template(
        template_id="topology.writing.short_story_pipeline",
        title="短篇小说协作拓扑",
        nodes=(
            {"node_id": "idea_worker", "agent_id": "agent:5", "lane": "creative_ideation", "role": "participant"},
            {"node_id": "idea_review", "agent_id": "agent:4", "lane": "content_review", "role": "participant"},
            {"node_id": "approval_gate", "agent_id": "agent:0", "lane": "coordination_gate", "role": "coordinator"},
            {"node_id": "draft_writer", "agent_id": "agent:5", "lane": "story_drafting", "role": "participant"},
            {"node_id": "content_check", "agent_id": "agent:4", "lane": "content_inspection", "role": "participant"},
            {"node_id": "revision_loop", "agent_id": "agent:5", "lane": "story_revision", "role": "participant"},
            {"node_id": "acceptance", "agent_id": "agent:0", "lane": "final_acceptance", "role": "coordinator"},
        ),
        edges=(
            {"from": "idea_worker", "to": "idea_review", "policy": "stage_contract_handoff"},
            {"from": "idea_review", "to": "approval_gate", "policy": "stage_contract_handoff"},
            {"from": "approval_gate", "to": "draft_writer", "policy": "stage_contract_handoff"},
            {"from": "draft_writer", "to": "content_check", "policy": "stage_contract_handoff"},
            {"from": "content_check", "to": "revision_loop", "policy": "stage_contract_handoff"},
            {"from": "revision_loop", "to": "acceptance", "policy": "stage_contract_handoff"},
        ),
        enabled=True,
    )
    registry.upsert_task_communication_protocol(
        protocol_id="protocol.writing.short_story_pipeline",
        title="短篇小说协作协议",
        message_types=(
            "idea_proposal",
            "idea_review",
            "approval_signal",
            "draft_submission",
            "content_issue",
            "revision_request",
            "acceptance_result",
        ),
        payload_contracts=("StoryIdeaProposal", "StoryAcceptanceResult"),
        signal_rules=("participant_report_to_coordinator", "coordinator_stage_gate"),
        handoff_rules=("stage_refs_only",),
        enabled=True,
    )

    runtime = QueryRuntime(
        base_dir=base_dir,
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=_ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=_ModelRuntimeStub(),
    )

    async def _collect() -> tuple[list[dict[str, object]], str]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            QueryRequest(
                session_id="session-trace-story-coordination",
                message="请用多 Agent 协调模式创作一篇短篇小说。",
                history=[],
                task_selection={
                    "selected_task_id": "task.writing.short_story",
                    "task_id": "task.writing.short_story",
                    "task_mode": "short_story",
                    "coordination_task_id": "coord.writing.short_story_pipeline",
                    "communication_protocol_id": "protocol.writing.short_story_pipeline",
                },
            )
        ):
            events.append(event)
        started = next(event for event in events if event["type"] == "runtime_loop_started")
        return events, str(dict(started["task_run"]).get("task_run_id") or "")

    _events, task_run_id = asyncio.run(_collect())
    trace = runtime.task_run_loop.get_trace(task_run_id)

    assert trace is not None
    assert trace["agent_run_results"]
    coordination_run = trace["coordination_runs"][0]
    flow = dict(coordination_run["diagnostics"].get("coordination_flow") or {})
    assert flow["accepted"] is True
    assert flow["revision_loop_enabled"] is True
    assert flow["completed_revision_cycles"] == 1
    assert any(str(node.get("diagnostics", {}).get("stage_status") or "") == "completed" for node in coordination_run["node_runs"])
