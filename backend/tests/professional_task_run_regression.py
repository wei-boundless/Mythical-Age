from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.tool_definitions import get_tool_definition_map
from query import QueryRuntime
from task_system.services.assembly_support import build_runtime_task_intent_contract
from task_system.planning.execution_recipe_builder import build_execution_recipe
from task_system.planning.execution_shape_resolver import resolve_execution_shape
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    SingleMessageModelRuntimeStub,
    isolated_backend_root,
    model_turn_context,
)
from runtime.model_gateway.model_runtime import ModelRuntimeError
from runtime.tool_runtime.tool_result_envelope import build_tool_result_envelope


_MemoryFacadeStub = QueryRuntimeMemoryFacadeStub
_SkillRegistryStub = EmptySkillRegistryStub
_SettingsStub = PrimarySettingsStub
_PermissionStub = DefaultPermissionStub
_SessionManagerStub = InMemorySessionManagerStub
_ToolRuntimeStub = EmptyToolRuntimeStub


def _tool_message_text(messages) -> str:
    return "\n".join(
        str(getattr(item, "content", "") or "")
        for item in list(messages or [])
        if item.__class__.__name__ == "ToolMessage"
    )


def _tool_message_count(messages) -> int:
    return sum(1 for item in list(messages or []) if item.__class__.__name__ == "ToolMessage")


class _ToolRuntimeWithSearchTextStub:
    registry = None

    def __init__(self) -> None:
        self._definition_map = get_tool_definition_map()
        self._instances = [_SearchTextToolStub()]

    @property
    def definitions(self):
        return [self._definition_map["search_text"]]

    @property
    def instances(self):
        return list(self._instances)

    def get_definition(self, name):
        return self._definition_map.get(str(name or ""))

    def get_instance(self, name):
        target = str(name or "")
        return next((tool for tool in self._instances if getattr(tool, "name", "") == target), None)


class _SearchTextToolStub:
    name = "search_text"

    def invoke(self, args):
        query = str(dict(args or {}).get("query") or "")
        return f"真实工具结果：query={query}; 命中 backend/runtime/professional_runtime/driver.py"


class _ToolRuntimeWithSideEffectsStub:
    registry = None

    def __init__(self, root_dir: Path) -> None:
        self._definition_map = get_tool_definition_map()
        self._instances = [
            self._definition_map["agent_todo"].build(root_dir),
            self._definition_map["read_file"].build(root_dir),
            self._definition_map["read_structured_file"].build(root_dir),
            self._definition_map["search_text"].build(root_dir),
            self._definition_map["write_file"].build(root_dir),
            self._definition_map["edit_file"].build(root_dir),
            self._definition_map["terminal"].build(root_dir),
        ]

    @property
    def definitions(self):
        return [
            self._definition_map["agent_todo"],
            self._definition_map["read_file"],
            self._definition_map["read_structured_file"],
            self._definition_map["search_text"],
            self._definition_map["write_file"],
            self._definition_map["edit_file"],
            self._definition_map["terminal"],
        ]

    @property
    def instances(self):
        return list(self._instances)

    def get_definition(self, name):
        return self._definition_map.get(str(name or ""))

    def get_instance(self, name):
        target = str(name or "")
        return next((tool for tool in self._instances if getattr(tool, "name", "") == target), None)


class _ModelRuntimeStub(SingleMessageModelRuntimeStub):
    def __init__(self) -> None:
        super().__init__(
            "tool grounded answer：已锁定目标、按专业模式计划完成分析，并给出当前结论。"
            "限制：本轮没有执行额外工具。"
        )


class _ModelTurnDecisionAwareRuntime:
    def __init__(self, inner) -> None:
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def invoke_messages(self, messages, **kwargs):
        decision = _model_turn_decision_response_for_messages(messages)
        if decision is not None:
            return decision
        return await self.inner.invoke_messages(messages, **kwargs)

    async def invoke_messages_with_tools(self, messages, tools, **kwargs):
        invoker = getattr(self.inner, "invoke_messages_with_tools", None)
        if callable(invoker):
            return await invoker(messages, tools, **kwargs)
        return await self.inner.invoke_messages(messages, **kwargs)


def _model_turn_decision_response_for_messages(messages) -> SimpleNamespace | None:
    message_text = "\n".join(
        str(item.get("content") or "") if isinstance(item, dict) else str(getattr(item, "content", "") or "")
        for item in list(messages or [])
    )
    if "当前轮理解决策器" not in message_text and "agent_runtime.model_turn_decision" not in message_text:
        return None
    payload = _model_turn_decision_request_payload(messages)
    selection = dict(payload.get("task_selection") or {})
    user_message = str(payload.get("user_message") or "").strip()
    decision = dict(selection.get("model_turn_decision") or {})
    if not decision:
        decision = dict(
            model_turn_context(
                action_intent="read_context",
                work_mode="read_only_analysis",
                interaction_intent="inspect",
                desired_outcome=user_message,
                task_goal_type=str(selection.get("semantic_task_type") or "bounded_tool_task"),
                task_domain="analysis",
            )["model_turn_decision"]
        )
    decision["user_message"] = user_message or str(decision.get("user_message") or "")
    decision.setdefault("authority", "agent_runtime.model_turn_decision")
    decision.setdefault("decision_id", "model-turn-decision:test")
    decision.setdefault("context_binding_decision", {})
    decision.setdefault("resource_contract", {})
    decision.setdefault("confidence", 0.9)
    return SimpleNamespace(content=json.dumps(decision, ensure_ascii=False))


def _model_turn_decision_request_payload(messages) -> dict[str, object]:
    for item in reversed(list(messages or [])):
        content = str(item.get("content") or "") if isinstance(item, dict) else str(getattr(item, "content", "") or "")
        if not content.strip().startswith("{"):
            continue
        try:
            parsed = json.loads(content)
        except Exception:
            continue
        if isinstance(parsed, dict) and "task_selection" in parsed:
            return parsed
    return {}


class _ToolCallingModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0
        self.seen_tool_result = False

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        self.seen_tool_result = self.seen_tool_result or any(
            item.__class__.__name__ == "ToolMessage" for item in list(messages or [])
        )
        return SimpleNamespace(
            content=(
                "tool grounded answer：已基于真实 search_text 工具结果完成收口，定位到 professional_task_run_driver.py，"
                "专业模式可以在预算受控的真实工具观察后回答。限制：本轮只使用 search_text 观察。"
            )
        )

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "search_text" for tool in list(tools or []))
        self.seen_tool_result = self.seen_tool_result or any(
            item.__class__.__name__ == "ToolMessage" for item in list(messages or [])
        )
        if self.seen_tool_result:
            return SimpleNamespace(
                content=(
                    "tool grounded answer：已基于真实 search_text 工具结果完成收口，定位到 professional_task_run_driver.py，"
                    "专业模式可以在预算受控的真实工具观察后回答。限制：本轮只使用 search_text 观察。"
                )
            )
        return AIMessage(
            content="我需要先搜索运行时驱动实现。",
            tool_calls=[
                {
                    "id": "call-search-professional-driver",
                    "name": "search_text",
                    "args": {
                        "query": "ProfessionalTaskRunDriver",
                        "roots": ["backend"],
                        "glob": "**/*.py",
                        "max_results": 5,
                    },
                    "type": "tool_call",
                }
            ],
        )


class _TriageModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_structured_report = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        if not list(tools or []):
            return SimpleNamespace(content="规划：继续在同一个目标目录内完成验证。")
        tool_text = _tool_message_text(messages)
        self.seen_structured_report = self.seen_structured_report or (
            "failing_sixty_turn_summary.json" in tool_text
            or "fixture-professional-triage" in tool_text
            or _tool_message_count(messages) > 0
        )
        if not self.seen_structured_report:
            assert any(getattr(tool, "name", "") == "read_structured_file" for tool in list(tools or []))
            return AIMessage(
                content="我先读取测试报告，抽取失败项。",
                tool_calls=[
                    {
                        "id": "call-read-professional-triage-report",
                        "name": "read_structured_file",
                        "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(
            content=(
                "失败归类：output boundary 和 tool loop 交界处丢失稳定最终答案。\n"
                "结构性根因：语义交付物没有在工具观察之后进入统一验证，导致长任务收口依赖模型自觉，不是孤立失败。\n"
                "回归测试：补充专业模式长跑测试，断言读取报告、证据包、交付验证和最终回答都出现。\n"
                "证据边界：本轮只读取了指定失败报告，没有执行完整端到端重跑。"
            )
        )


class _BudgetCloseoutModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        tool_text = _tool_message_text(messages)
        assert "fixture-professional-budget" in tool_text
        return SimpleNamespace(
            content=(
                "失败归类：timeout/budget 后的最终答案提交不稳定。\n"
                "结构性根因：专业任务预算耗尽后必须触发强制收口，否则长任务会空转。\n"
                "回归测试：覆盖预算耗尽后基于已有证据形成最终答案。\n"
                "证据边界：只基于已读取报告，没有重跑全量测试。"
            )
        )

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        assert any(getattr(tool, "name", "") == "read_structured_file" for tool in list(tools or []))
        return AIMessage(
            content="继续补充证据。",
            tool_calls=[
                {
                    "id": f"call-read-budget-{self.tool_enabled_calls}",
                    "name": "read_structured_file",
                    "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                    "type": "tool_call",
                }
            ],
        )


class _SandboxWriteModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_tool_result = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = _tool_message_text(messages)
        self.seen_tool_result = self.seen_tool_result or "Write succeeded" in tool_text
        if self.seen_tool_result:
            return SimpleNamespace(
                content=(
                    "completion status：已完成。产物文件：backend/sandbox_probe.txt。"
                    "限制：该文件只写入 sandbox overlay，真实工程未直接修改。"
                )
            )
        assert any(getattr(tool, "name", "") == "write_file" for tool in list(tools or []))
        return AIMessage(
            content="我先在沙箱里写一个探针文件验证隔离边界。",
            tool_calls=[
                {
                    "id": "call-write-sandbox-probe",
                    "name": "write_file",
                    "args": {
                        "path": "backend/sandbox_probe.txt",
                        "content": "sandbox-only",
                    },
                    "type": "tool_call",
                }
            ],
        )


class _SandboxTerminalModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_sandbox_cwd = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = _tool_message_text(messages)
        normalized = tool_text.replace("\\", "/")
        self.seen_sandbox_cwd = self.seen_sandbox_cwd or (
            "/output/sandbox_runs/" in normalized and normalized.endswith("/workspace")
        )
        if self.seen_sandbox_cwd:
            return SimpleNamespace(
                content=(
                    "tool grounded answer：terminal 已在 sandbox workspace 内运行。"
                    "限制：本轮只验证工作目录，没有修改文件。"
                )
            )
        assert any(getattr(tool, "name", "") == "terminal" for tool in list(tools or []))
        return AIMessage(
            content="我需要确认命令运行目录是否被隔离。",
            tool_calls=[
                {
                    "id": "call-terminal-pwd",
                    "name": "terminal",
                    "args": {"command": "Get-Location | Select-Object -ExpandProperty Path"},
                    "type": "tool_call",
                }
            ],
        )


class _SandboxContinuationModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_readback = False
        self.finalized_first_write = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = _tool_message_text(messages)
        user_text = "\n".join(
            str(item.get("content") or "") if isinstance(item, dict) else str(getattr(item, "content", "") or "")
            for item in list(messages or [])
        )
        tool_names = {str(getattr(tool, "name", "") or "") for tool in list(tools or [])}
        is_continuation = "读回" in user_text or "继续验收" in user_text
        self.seen_readback = self.seen_readback or "first-pass" in tool_text
        if (is_continuation or self.finalized_first_write) and not self.seen_readback and "read_file" in tool_names:
            return AIMessage(
                content="我先读回上一轮文件。",
                tool_calls=[
                    {
                        "id": "call-read-continuation-game",
                        "name": "read_file",
                        "args": {"path": "frontend/public/games/arcane_dungeon_studio/game.js"},
                        "type": "tool_call",
                    }
                ],
            )
        if self.seen_readback:
            return SimpleNamespace(
                content=(
                    "验证：sandbox continuation 已完成。"
                    "changed files：frontend/public/games/arcane_dungeon_studio/game.js。"
                    "限制：仅验证同目录续跑。"
                )
            )
        if "Write succeeded" in tool_text:
            self.finalized_first_write = True
            return SimpleNamespace(
                content=(
                    "验证：sandbox continuation 第一轮写入完成。"
                    "changed files：frontend/public/games/arcane_dungeon_studio/game.js。"
                )
            )
        assert "write_file" in tool_names
        return AIMessage(
            content="我先写入第一轮文件。",
            tool_calls=[
                {
                    "id": "call-write-continuation-game",
                    "name": "write_file",
                    "args": {
                        "path": "frontend/public/games/arcane_dungeon_studio/game.js",
                        "content": "const marker = 'first-pass';",
                    },
                    "type": "tool_call",
                }
            ],
        )


class _RecoverableTimeoutModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.recovery_prompt_seen = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [], **_kwargs)

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_names = {str(getattr(tool, "name", "") or "") for tool in list(tools or [])}
        message_text = "\n".join(
            str(item.get("content") or "") if isinstance(item, dict) else str(getattr(item, "content", "") or "")
            for item in list(messages or [])
        )
        self.recovery_prompt_seen = self.recovery_prompt_seen or (
            "runtime_timeout_observation" in message_text
            and "frontend/public/games/arcane_dungeon_studio/game.js" in message_text
        )
        if self.tool_enabled_calls == 1:
            assert "write_file" in tool_names
            return AIMessage(
                content="先写入口文件。",
                tool_calls=[
                    {
                        "id": "call-write-timeout-index",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/arcane_dungeon_studio/index.html",
                            "content": '<!doctype html><script src="game.js"></script>',
                        },
                        "type": "tool_call",
                    }
                ],
            )
        if self.tool_enabled_calls == 2:
            raise ModelRuntimeError(
                code="timeout",
                provider="deepseek",
                model="deepseek-v4-pro",
                detail="TimeoutError",
                retryable=True,
                user_message="模型请求超时，请稍后重试。",
            )
        if self.tool_enabled_calls == 3:
            assert self.recovery_prompt_seen is True
            assert "write_file" in tool_names
            return AIMessage(
                content="从超时处继续补齐缺失文件。",
                tool_calls=[
                    {
                        "id": "call-write-timeout-game",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/arcane_dungeon_studio/game.js",
                            "content": "const player = { hp: 3 };",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(
            content=(
                "完成状态：已完成，两个产物已写入。\n"
                "修改：补齐超时后缺失的浏览器小游戏文件。\n"
                "文件：frontend/public/games/arcane_dungeon_studio/index.html、"
                "frontend/public/games/arcane_dungeon_studio/game.js。\n"
                "产物路径：frontend/public/games/arcane_dungeon_studio/。\n"
                "验证：write_file 已返回成功。限制：本测试只验证超时恢复链路。"
            )
        )


class _TodoThenWriteModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_todo = False
        self.tool_names_by_call: list[list[str]] = []

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [], **_kwargs)

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        self.tool_names_by_call.append(tool_names)
        tool_text = _tool_message_text(messages)
        self.seen_todo = self.seen_todo or '"plan_id"' in tool_text or "agent-todo:" in tool_text
        if not self.seen_todo:
            assert "agent_todo" in tool_names
            return AIMessage(
                content="我先建立任务待办。",
                tool_calls=[
                    {
                        "id": "call-agent-todo-game-slice",
                        "name": "agent_todo",
                        "args": {
                            "operation": "replace",
                            "session_id": "session-professional-todo",
                            "task_id": "task-professional-todo",
                            "items": [
                                {
                                    "todo_id": "skeleton",
                                    "content": "写入游戏工程骨架文件",
                                    "status": "in_progress",
                                    "evidence_expectations": ["write_file"],
                                },
                                {
                                    "todo_id": "gameplay",
                                    "content": "分段补齐 game.js 玩法系统",
                                    "status": "pending",
                                    "evidence_expectations": ["edit_file"],
                                },
                            ],
                        },
                        "type": "tool_call",
                    }
                ],
            )
        if "Write succeeded" in tool_text:
            return SimpleNamespace(
                content=(
                    "完成状态：已完成骨架产物。\n"
                    "修改：已根据 todo 写入第一份文件。\n"
                    "文件：frontend/public/games/arcane_dungeon_studio/index.html。\n"
                    "产物路径：frontend/public/games/arcane_dungeon_studio/。\n"
                    "验证：write_file 已返回成功。限制：本测试只验证 todo 启动链路。"
                )
            )
        assert "write_file" in tool_names
        return AIMessage(
            content="按待办先写入骨架入口文件。",
            tool_calls=[
                {
                    "id": "call-write-todo-index",
                    "name": "write_file",
                    "args": {
                        "path": "frontend/public/games/arcane_dungeon_studio/index.html",
                        "content": '<!doctype html><script src="game.js"></script>',
                    },
                    "type": "tool_call",
                }
            ],
        )


class _WriteAfterReadModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_contract = False
        self.seen_write = False
        self.tool_call_options_by_call: list[object] = []

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        self.tool_call_options_by_call.append(_kwargs.get("tool_call_options"))
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        tool_text = _tool_message_text(messages)
        self.seen_contract = self.seen_contract or (
            "node_status_filter_contract.json" in tool_text
            or "status_filter" in tool_text
            or _tool_message_count(messages) > 0
        )
        self.seen_write = self.seen_write or "Write succeeded" in tool_text
        if self.seen_write:
            return SimpleNamespace(
                content=(
                    "修改：已写入功能草案。\n"
                    "文件：output/professional_feature_slice/status-filter-plan.md。\n"
                    "验证：本轮写入已由 write_file 返回成功；未运行端到端测试。"
                )
            )
        if self.seen_contract:
            assert "write_file" in tool_names
            assert "read_file" in tool_names
            return AIMessage(
                content="我已经读到契约，下一步写入草案文件。",
                tool_calls=[
                    {
                        "id": "call-write-feature-slice",
                        "name": "write_file",
                        "args": {
                            "path": "output/professional_feature_slice/status-filter-plan.md",
                            "content": "后端：提供 status 参数筛选节点。\n前端：增加状态筛选控件。\n测试：覆盖全部状态和空结果。",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        assert "read_file" in tool_names
        return AIMessage(
            content="我先读取功能契约。",
            tool_calls=[
                {
                    "id": "call-read-feature-contract",
                    "name": "read_file",
                    "args": {"path": "tests/fixtures/professional_task_suite/node_status_filter_contract.json"},
                    "type": "tool_call",
                }
            ],
        )


class _TerminalBeforeEditModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_code = False
        self.seen_edit = False
        self.seen_pytest = False
        self.blocked_terminal_attempted = False
        self.tool_names_by_call: list[list[str]] = []

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [], **_kwargs)

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        self.tool_names_by_call.append(tool_names)
        tool_text = _tool_message_text(messages)
        system_text = "\n".join(
            str(dict(item).get("content") or "") if isinstance(item, dict) else str(getattr(item, "content", "") or "")
            for item in list(messages or [])
            if (
                isinstance(item, dict)
                and str(dict(item).get("role") or "") == "system"
            )
            or item.__class__.__name__ == "SystemMessage"
        )
        self.seen_code = self.seen_code or "def total" in tool_text
        self.seen_edit = self.seen_edit or "Edit succeeded" in tool_text
        self.seen_pytest = self.seen_pytest or "PYTEST_OK" in tool_text
        self.blocked_terminal_attempted = self.blocked_terminal_attempted or "Runtime blocked this tool request before execution" in tool_text
        self.blocked_terminal_attempted = self.blocked_terminal_attempted or "建议优先补齐：edit_file" in system_text
        if self.seen_pytest:
            return SimpleNamespace(
                content=(
                    "修改：已修正 total 累加逻辑。\n"
                    "文件：backend/order_pipeline.py。\n"
                    "验证：已运行 python 断言命令，结果 PYTEST_OK。\n"
                    "边界：本轮只覆盖最小订单流水线用例。"
                )
            )
        if self.seen_edit:
            assert "terminal" in tool_names
            return AIMessage(
                content="修改完成，运行验证。",
                tool_calls=[
                    {
                        "id": "call-run-order-pipeline-pytest",
                        "name": "terminal",
                        "args": {"command": "python -c \"from backend.order_pipeline import total; assert total([1, 2]) == 3; print('PYTEST_OK')\""},
                        "type": "tool_call",
                    }
                ],
            )
        if self.seen_code:
            assert "edit_file" in tool_names
            return AIMessage(
                content="我按契约先修改代码。",
                tool_calls=[
                    {
                        "id": "call-edit-order-pipeline",
                        "name": "edit_file",
                        "args": {
                            "path": "backend/order_pipeline.py",
                            "old_text": "return 0",
                            "new_text": "return sum(values)",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        assert "read_file" in tool_names
        return AIMessage(
            content="我先读取代码。",
            tool_calls=[
                {
                    "id": "call-read-order-pipeline",
                    "name": "read_file",
                    "args": {"path": "backend/order_pipeline.py"},
                    "type": "tool_call",
                }
            ],
        )


class _RepairThenVerifyModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_report = False
        self.seen_write = False
        self.seen_pytest = False
        self.tool_names_by_call: list[list[str]] = []

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        self.tool_names_by_call.append(tool_names)
        tool_text = _tool_message_text(messages)
        self.seen_report = self.seen_report or (
            "failing_sixty_turn_summary.json" in tool_text
            or "fixture-professional-repair" in tool_text
            or _tool_message_count(messages) > 0
        )
        self.seen_write = self.seen_write or "Write succeeded" in tool_text or "Edit succeeded" in tool_text
        self.seen_pytest = self.seen_pytest or "PYTEST_OK" in tool_text
        if self.seen_pytest:
            return SimpleNamespace(
                content=(
                    "失败归类：output boundary 在长任务收口时丢失稳定最终答案，失败原因是执行义务没有进入强制修复链路。\n"
                    "结构性根因：执行义务没有强制写入和验证，导致 triage 原型压住了修复动作。\n"
                    "回归测试：保留 triage+修复+验证的长任务回归，断言必须出现写入观察和验证观察。\n"
                    "修改：已写入 backend/fixed_counter.py。\n"
                    "文件：backend/fixed_counter.py。\n"
                    "验证：已运行 python 导入断言命令，结果 PYTEST_OK。\n"
                    "证据边界：仅覆盖本轮最小复现测试。"
                )
            )
        if self.seen_write:
            assert "terminal" in tool_names
            assert "read_file" not in tool_names
            return AIMessage(
                content="我已经完成修改，下一步运行 Python 断言验证。",
                tool_calls=[
                    {
                        "id": "call-run-pytest-after-repair",
                        "name": "terminal",
                        "args": {"command": "python -c \"import sys; sys.path.insert(0, 'backend'); from fixed_counter import inc; assert inc(1) == 2; print('PYTEST_OK')\""},
                        "type": "tool_call",
                    }
                ],
            )
        if self.seen_report:
            assert "write_file" in tool_names or "edit_file" in tool_names
            assert "read_file" not in tool_names
            return AIMessage(
                content="我已经读到失败报告，下一步写入结构性修复。",
                tool_calls=[
                    {
                        "id": "call-write-repair",
                        "name": "write_file",
                        "args": {
                            "path": "backend/fixed_counter.py",
                            "content": "def inc(value):\n    return value + 1\n",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        assert "read_structured_file" in tool_names or "read_file" in tool_names
        return AIMessage(
            content="我先读取失败报告。",
            tool_calls=[
                {
                    "id": "call-read-repair-report",
                    "name": "read_structured_file",
                    "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                    "type": "tool_call",
                }
            ],
        )


class _ToolMarkupLeakModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0

    async def invoke_messages(self, _messages, **_kwargs):
        self.plain_calls += 1
        return SimpleNamespace(
            content=(
                "我需要读取文件。\n"
                "name=\"read_file\">\n"
                "<｜｜DSML｜｜parameter name=\"path\">tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"
            )
        )

    async def invoke_messages_with_tools(self, _messages, _tools, **_kwargs):
        self.tool_enabled_calls += 1
        return SimpleNamespace(
            content=(
                "name=\"read_file\">\n"
                "<｜｜DSML｜｜parameter name=\"path\">tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"
            )
        )


class _EvidenceCloseoutLeakModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_structured_report = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = _tool_message_text(messages)
        self.seen_structured_report = self.seen_structured_report or (
            "failing_sixty_turn_summary.json" in tool_text
            or "fixture-professional-evidence-closeout" in tool_text
            or _tool_message_count(messages) > 0
        )
        if not self.seen_structured_report:
            assert any(getattr(tool, "name", "") == "read_file" for tool in list(tools or []))
            return AIMessage(
                content="我先读取测试报告，抽取失败项。",
                tool_calls=[
                    {
                        "id": "call-read-evidence-closeout-report",
                        "name": "read_file",
                        "args": {"path": "tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json"},
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(
            content=(
                "name=\"read_file\" string=\"true\">\n"
                "<｜｜DSML｜｜parameter name=\"path\">backend/runtime/shared/tool_adoption.py"
            )
        )


class _MaterialSynthesisLeakModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_material = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [], **_kwargs)

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = _tool_message_text(messages)
        self.seen_material = self.seen_material or (
            "inventory_note.md" in tool_text
            or "inventory" in tool_text.lower()
            or _tool_message_count(messages) > 0
        )
        if not self.seen_material:
            assert any(getattr(tool, "name", "") == "read_file" for tool in list(tools or []))
            return AIMessage(
                content="我先读取库存材料。",
                tool_calls=[
                    {
                        "id": "call-read-material-synthesis",
                        "name": "read_file",
                        "args": {"path": "tests/fixtures/professional_task_suite/inventory_note.md"},
                        "type": "tool_call",
                    }
                ],
            )
        return SimpleNamespace(
            content=(
                "name=\"search_files\" string=\"true\">\n"
                "<｜｜DSML｜｜parameter name=\"query\">inventory"
            )
        )


class _ArtifactDeliveryMissingTermModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.plain_calls = 0
        self.seen_contract = False
        self.seen_write = False

    async def invoke_messages(self, messages, **_kwargs):
        self.plain_calls += 1
        return SimpleNamespace(content="已完成，输出文件见草案。")

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_text = _tool_message_text(messages)
        self.seen_contract = self.seen_contract or (
            "node_status_filter_contract.json" in tool_text
            or "status_filter" in tool_text
            or _tool_message_count(messages) > 0
        )
        self.seen_write = self.seen_write or "Write succeeded" in tool_text
        if self.seen_write:
            return SimpleNamespace(content="已完成，输出文件见草案。")
        if self.seen_contract:
            assert "write_file" in [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
            return AIMessage(
                content="我写入草案文件。",
                tool_calls=[
                    {
                        "id": "call-write-missing-term-draft",
                        "name": "write_file",
                        "args": {
                            "path": "output/professional_feature_slice/status-filter-plan.md",
                            "content": "后端：GET /api/nodes?status=ready\n前端：状态筛选控件\n测试：ready 和 blocked",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        assert any(getattr(tool, "name", "") == "read_file" for tool in list(tools or []))
        return AIMessage(
            content="我读取契约。",
            tool_calls=[
                {
                    "id": "call-read-missing-term-contract",
                    "name": "read_file",
                    "args": {"path": "tests/fixtures/professional_task_suite/node_status_filter_contract.json"},
                    "type": "tool_call",
                }
            ],
        )


class _VerificationThenReadModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_terminal = False
        self.seen_json = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [], **_kwargs)

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        tool_text = _tool_message_text(messages)
        self.seen_terminal = self.seen_terminal or "/workspace" in tool_text.replace("\\", "/")
        self.seen_json = self.seen_json or "timeout_ms" in tool_text
        if self.seen_terminal and self.seen_json:
            return SimpleNamespace(
                content=(
                    "原因：服务超时来自 timeout_ms 配置过低和启动期健康检查阻塞。\n"
                    "修复建议：提高 timeout_ms，并把健康检查移到后台预热。\n"
                    "验证步骤：先用只读命令确认工作目录，再读取配置快照复核 timeout_ms，最后在真实服务环境重放超时请求。\n"
                    "限制：本轮只读取本地快照和运行只读目录命令，没有访问真实服务。"
                )
            )
        if self.seen_terminal:
            assert "read_file" in tool_names
            return AIMessage(
                content="我已确认目录，继续读取快照。",
                tool_calls=[
                    {
                        "id": "call-read-after-terminal",
                        "name": "read_file",
                        "args": {"path": "tests/fixtures/professional_task_suite/ops_incident_snapshot.json"},
                        "type": "tool_call",
                    }
                ],
            )
        assert "terminal" in tool_names
        return AIMessage(
            content="我先运行只读命令确认工作目录。",
            tool_calls=[
                {
                    "id": "call-terminal-before-read",
                    "name": "terminal",
                    "args": {"command": "Get-Location | Select-Object -ExpandProperty Path"},
                    "type": "tool_call",
                }
            ],
        )


class _ProgressPolicyCorrectionModelRuntimeStub:
    def __init__(self) -> None:
        self.tool_enabled_calls = 0
        self.seen_progress_rejection = False
        self.seen_write = False

    async def invoke_messages(self, messages, **_kwargs):
        return await self.invoke_messages_with_tools(messages, [])

    async def invoke_messages_with_tools(self, messages, tools, **_kwargs):
        self.tool_enabled_calls += 1
        tool_names = [str(getattr(tool, "name", "") or "") for tool in list(tools or [])]
        tool_text = _tool_message_text(messages)
        self.seen_progress_rejection = self.seen_progress_rejection or "tool_policy_rejection" in tool_text
        self.seen_write = self.seen_write or "Write succeeded" in tool_text
        if self.seen_write:
            return SimpleNamespace(
                content=(
                    "完成状态：已完成。\n"
                    "文件：frontend/public/games/progress_probe/game.js。\n"
                    "验证：write_file 已返回成功。限制：本测试只验证 progress policy 纠错链路。"
                )
            )
        if self.seen_progress_rejection:
            assert "write_file" in tool_names
            return AIMessage(
                content="我收到进度策略反馈，改为写入缺失产物。",
                tool_calls=[
                    {
                        "id": "call-write-after-progress-rejection",
                        "name": "write_file",
                        "args": {
                            "path": "frontend/public/games/progress_probe/game.js",
                            "content": "const progressProbe = true;",
                        },
                        "type": "tool_call",
                    }
                ],
            )
        assert "search_text" in tool_names
        return AIMessage(
            content="我先继续搜索已有目录线索。",
            tool_calls=[
                {
                    "id": f"call-search-progress-{self.tool_enabled_calls}",
                    "name": "search_text",
                    "args": {
                        "query": "progress_probe",
                        "roots": ["."],
                        "glob": "**/*.md",
                        "max_results": 5,
                    },
                    "type": "tool_call",
                }
            ],
        )


def _isolated_backend_root() -> Path:
    return isolated_backend_root("professional-task-run-")


def _professional_task_selection(
    *,
    max_tool_rounds: int | None = None,
    semantic_task_type: str | None = "bounded_tool_task",
) -> dict[str, object]:
    decision_goal_type = str(semantic_task_type or "bounded_tool_task")
    action_intent = "edit_workspace" if decision_goal_type in {
        "artifact_delivery",
        "frontend_app_delivery",
        "game_vertical_slice_delivery",
        "code_fix_execution",
        "test_report_triage",
    } else "read_context"
    interaction_intent = "create" if decision_goal_type in {
        "artifact_delivery",
        "frontend_app_delivery",
        "game_vertical_slice_delivery",
    } else "modify" if decision_goal_type == "code_fix_execution" else "inspect"
    deliverables = (
        ["runnable_artifact_refs", "verification_evidence"]
        if decision_goal_type in {"artifact_delivery", "frontend_app_delivery", "game_vertical_slice_delivery"}
        else ["change_summary", "changed_files", "verification_result_or_limitation"]
        if decision_goal_type == "code_fix_execution"
        else ["tool_grounded_answer"]
    )
    selection: dict[str, object] = {
        **model_turn_context(
            action_intent=action_intent,
            work_mode="implementation" if action_intent == "edit_workspace" else "read_only_analysis",
            interaction_intent=interaction_intent,
            desired_outcome="professional task test selection",
            deliverables=deliverables,
            planning_required=action_intent == "edit_workspace",
            todo_required=action_intent == "edit_workspace",
            task_goal_type=decision_goal_type,
            task_domain="development" if action_intent == "edit_workspace" else "analysis",
        ),
        "interaction_mode": "professional_mode",
        "mode_policy": {
            "execution_strategy": "professional_task_run",
            "interaction_mode": "professional_mode",
            "runtime_lane": "professional_task",
        },
    }
    if max_tool_rounds is not None:
        selection["mode_policy"] = {
            **dict(selection["mode_policy"]),
            "interaction_mode": "professional_mode",
            "tool_policy": {
                "max_tool_rounds_per_task_run": max_tool_rounds,
                "max_tool_calls_per_task_run": max_tool_rounds,
                "max_tool_calls_per_round": 1,
            },
        }
    if semantic_task_type:
        selection["semantic_task_type"] = semantic_task_type
    return selection


async def _collect_runtime_events(runtime: QueryRuntime, *, session_id: str, message: str, task_selection: dict[str, object] | None = None):
    from query.models import QueryRequest

    events: list[dict[str, object]] = []
    async for event in runtime.astream(
        QueryRequest(
            session_id=session_id,
            message=message,
            history=[],
            task_selection=dict(task_selection or {}),
        )
    ):
        events.append(event)
    started = next(event for event in events if event["type"] == "runtime_loop_started")
    task_run_id = str(dict(started["task_run"]).get("task_run_id") or "")
    runtime_events = [
        dict(event.get("event") or {})
        for event in events
        if event.get("type") == "runtime_loop_event"
    ]
    done = next(event for event in events if event.get("type") == "done")
    return events, runtime_events, done, task_run_id


def _runtime(
    *,
    base_dir: Path | None = None,
    model_runtime=None,
    tool_runtime=None,
) -> QueryRuntime:
    resolved_model_runtime = model_runtime or _ModelRuntimeStub()
    resolved_model_runtime = _ModelTurnDecisionAwareRuntime(resolved_model_runtime)
    return QueryRuntime(
        base_dir=base_dir or _isolated_backend_root(),
        settings_service=_SettingsStub(),
        session_manager=_SessionManagerStub(),
        memory_facade=_MemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=tool_runtime or _ToolRuntimeStub(),
        skill_registry=_SkillRegistryStub(),
        permission_service=_PermissionStub(),
        model_runtime=resolved_model_runtime,
    )


def _event_types(runtime_events: list[dict[str, object]]) -> list[str]:
    return [str(event.get("event_type") or "") for event in runtime_events]


def _latest_event(runtime_events: list[dict[str, object]], event_type: str) -> dict[str, object]:
    return next(event for event in reversed(runtime_events) if event.get("event_type") == event_type)


def test_professional_recipe_is_selected_from_code_fix_intent_strategy() -> None:
    current_turn_context = {
        **model_turn_context(
            action_intent="edit_workspace",
            work_mode="implementation",
            interaction_intent="modify",
            desired_outcome="追踪问题、修复代码并验证结果",
            deliverables=["code_changes", "verification_report"],
            planning_required=True,
            todo_required=True,
            task_goal_type="code_fix_execution",
            task_domain="development",
        ),
    }
    contract = build_runtime_task_intent_contract(
        session_id="session-professional-shape",
        task_id="taskinst:professional-shape",
        user_goal="追踪这个问题并修复，最好一次性执行完计划。",
        query_understanding={},
        current_turn_context=current_turn_context,
    )

    shape = resolve_execution_shape(
        task_intent_contract=contract,
        query_understanding={},
        current_turn_context=current_turn_context,
    )
    recipe = build_execution_recipe(base_dir=_isolated_backend_root(), execution_shape=shape)
    metadata = dict(recipe.metadata)

    assert shape.recipe_id == "runtime.recipe.professional_task"
    assert shape.execution_kind == "professional_mode"
    assert "interaction_mode:professional_mode" in shape.resolution_reasons
    assert metadata["runtime_driver"] == "professional_task_run"
    assert metadata["interaction_mode"] == "professional_mode"
    assert metadata["runtime_lane_hint"] == "professional_task"
    assert "op.shell" in set(metadata["tool_execution_policy"]["allowed_operation_refs"])
    assert "edit_file" in set(metadata["tool_execution_policy"]["allowed_tool_names"])
    retired_mode_key = "_".join(("autonomy", "mode"))
    assert retired_mode_key not in metadata


def test_query_runtime_runs_professional_driver_without_coordination_run() -> None:
    runtime = _runtime()

    events, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-driver",
            message="帮我只读追踪这个问题并给出结论，最好一次性执行完计划。",
            task_selection=_professional_task_selection(),
        )
    )
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    event_types = _event_types(runtime_events)

    assert "professional_task_started" in event_types
    assert "professional_task_semantic_plan_drafted" in event_types
    assert "professional_task_evidence_packet_built" in event_types
    assert "professional_task_deliverable_validation_checked" in event_types
    assert done["terminal_reason"] == "completed"
    assert trace is not None
    assert trace["coordination_runs"] == []
    assert not any(event.get("type") in {"mcp_start", "mcp_end", "mcp_evidence"} for event in events)


def test_professional_mode_adds_semantic_plan_steps_and_monitor_summary() -> None:
    runtime = _runtime()

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-plan",
            message="帮我只读追踪这个问题并给出结论，最好一次性执行完计划。",
            task_selection=_professional_task_selection(),
        )
    )
    plan_event = _latest_event(runtime_events, "professional_task_semantic_plan_drafted")
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    plan_payload = dict(plan_event.get("payload") or {})
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    ledger = dict(done.get("task_run_ledger") or {})
    step_ids = [str(dict(step).get("step_id") or "") for step in list(ledger.get("step_runs") or [])]
    monitor = runtime.task_run_loop.get_task_run_live_monitor(task_run_id)

    assert plan_payload["interaction_mode"] == "professional_mode"
    assert plan_payload["plan_source"] == "task_requirement_contract"
    assert any(dict(item).get("plan_item_id") == "professional.mode_policy" for item in plan_payload["plan_items"])
    assert any(dict(item).get("plan_item_id") == "professional.validate_deliverable" for item in plan_payload["plan_items"])
    assert "professional.mode_policy" in step_ids
    assert "professional.validate_deliverable" in step_ids
    assert verification["interaction_mode"] == "professional_mode"
    assert monitor is not None
    assert monitor["has_coordination"] is False
    summary = dict(monitor["professional_task_summary"] or {})
    assert summary["runtime_driver"] == "professional_task_run"
    assert summary["interaction_mode"] == "professional_mode"
    assert summary["verification"]["status"] == "passed"


def test_professional_mode_runs_budgeted_tool_observation() -> None:
    model_runtime = _ToolCallingModelRuntimeStub()
    runtime = _runtime(model_runtime=model_runtime, tool_runtime=_ToolRuntimeWithSearchTextStub())

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-tool",
            message="追踪一下 ProfessionalTaskRunDriver 的专业模式工具闭环。",
            task_selection=_professional_task_selection(),
        )
    )
    event_types = _event_types(runtime_events)
    executor_event = next(
        event
        for event in runtime_events
        if event.get("event_type") == "executor_started"
        and dict(event.get("payload") or {}).get("runtime_channel") == "professional_task_run"
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    checks = dict(verification.get("checks") or {})
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)

    assert dict(executor_event.get("payload") or {})["allowed_tool_names"] == ["search_text"]
    assert "tool_call_requested" in event_types
    assert "tool_result_received" in event_types
    assert "executor_observation_received" in event_types
    assert checks["tool_call_count"] == 1
    assert checks["tool_observation_count"] == 1
    assert done["terminal_reason"] == "completed"
    assert "真实 search_text 工具结果" in str(done.get("content") or "")
    assert model_runtime.tool_enabled_calls == 2
    assert model_runtime.plain_calls == 0
    assert model_runtime.seen_tool_result is True
    assert trace is not None
    assert trace["coordination_runs"] == []


def test_professional_test_report_triage_builds_evidence_packet_and_strict_validation() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-triage","total_turns":60,"failed_turns":1,'
            '"failures":[{"turn":17,"check":"output_boundary","symptom":"final answer was empty",'
            '"evidence":"tool loop returned observation but stable answer was not committed"}]}'
        ),
        encoding="utf-8",
    )
    model_runtime = _TriageModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-triage",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json "
                "里的失败，输出失败归类、结构性根因、回归测试和证据边界。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None, max_tool_rounds=3),
        )
    )
    evidence_event = _latest_event(runtime_events, "professional_task_evidence_packet_built")
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    evidence = dict(dict(evidence_event.get("payload") or {}).get("evidence_packet") or {})
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    validation = dict(verification.get("deliverable_validation") or {})

    assert evidence["facts"]
    assert evidence["classifications"]
    assert validation["passed"] is True
    assert verification["passed"] is True
    assert done["terminal_reason"] == "completed"
    assert "失败归类" in str(done.get("content") or "")
    assert "结构性根因" in str(done.get("content") or "")
    assert "回归测试" in str(done.get("content") or "")
    assert model_runtime.seen_structured_report is True


def test_professional_triage_prompt_cannot_suppress_repair_and_pytest_obligations() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-repair","failed_turns":1,'
            '"failures":[{"turn":21,"check":"output_boundary","symptom":"repair obligation was skipped"}]}'
        ),
        encoding="utf-8",
    )
    model_runtime = _RepairThenVerifyModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-triage-repair",
            message=(
                "追踪 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json 的失败原因，"
                "修复代码，然后运行 pytest 或等价 Python 断言验证。"
            ),
            task_selection=_professional_task_selection(semantic_task_type="test_report_triage", max_tool_rounds=4),
        )
    )
    plan_event = _latest_event(runtime_events, "professional_task_semantic_plan_drafted")
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    plan_payload = dict(plan_event.get("payload") or {})
    plan_ids = [str(dict(item).get("plan_item_id") or "") for item in list(plan_payload.get("plan_items") or [])]
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    checks = dict(verification.get("checks") or {})
    state = dict(verification.get("professional_run_state") or {})
    observation_ledger = dict(verification.get("tool_observation_ledger") or {})
    observation_summary_event = _latest_event(runtime_events, "professional_tool_observation_ledger_updated")
    session_event = _latest_event(runtime_events, "professional_run_session_updated")
    monitor = runtime.task_run_loop.get_task_run_live_monitor(task_run_id)
    monitor_summary = dict((monitor or {}).get("professional_task_summary") or {})
    monitor_run_state = dict(monitor_summary.get("professional_run_state") or {})
    monitor_tool_ledger = dict(monitor_summary.get("tool_observation_ledger") or {})
    monitor_tool_summary = dict(monitor_tool_ledger.get("summary") or {})
    monitor_session = dict(monitor_summary.get("professional_run_session") or {})

    assert "professional.produce_output" in plan_ids
    assert "professional.verify_output" in plan_ids
    assert checks["write_observation_count"] >= 1
    assert checks["verification_command_count"] >= 1
    assert state["state"] == "complete"
    assert len(observation_ledger["records"]) >= 3
    assert dict(observation_summary_event.get("payload") or {})["summary"]["write_count"] >= 1
    assert dict(session_event.get("payload") or {})["professional_run_state"]["state"] == "complete"
    assert monitor_summary["state"] == "complete"
    assert monitor_run_state["state"] == "complete"
    assert monitor_tool_summary["write_count"] >= 1
    assert monitor_tool_summary["verification_count"] >= 1
    assert monitor_tool_ledger["latest_record"]["tool_name"] == "terminal"
    assert monitor_session["interaction_mode"] == "professional_mode"
    assert monitor_session["tool_observation_ledger_ref"] == observation_ledger["ledger_id"]
    assert (backend_root / "fixed_counter.py").exists() is False
    assert "PYTEST_OK" in str(done.get("content") or "")
    assert model_runtime.seen_report is True
    assert model_runtime.seen_write is True
    assert model_runtime.seen_pytest is True


def test_professional_task_sandbox_redirects_write_file_side_effects() -> None:
    backend_root = _isolated_backend_root()
    project_root = backend_root.parent
    model_runtime = _SandboxWriteModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-sandbox-write",
            message="请在隔离环境里写一个探针文件，并说明它不会误伤真实工程。",
            task_selection={
                **_professional_task_selection(semantic_task_type="artifact_delivery"),
            },
        )
    )
    sandbox_event = _latest_event(runtime_events, "runtime_sandbox_prepared")
    sandbox_policy = dict(dict(sandbox_event.get("payload") or {}).get("sandbox_policy") or {})
    sandbox_root = Path(str(sandbox_policy.get("sandbox_root") or ""))
    real_probe = project_root / "backend" / "sandbox_probe.txt"
    sandbox_probe = sandbox_root / "backend" / "sandbox_probe.txt"

    assert sandbox_policy["enabled"] is True
    assert sandbox_policy["real_workspace_access"] == "read_only"
    assert real_probe.exists() is False
    assert sandbox_probe.read_text(encoding="utf-8") == "sandbox-only"
    assert done["terminal_reason"] == "completed"
    assert model_runtime.tool_enabled_calls == 2
    assert model_runtime.seen_tool_result is True
    trace = runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)
    artifact_refs = [
        str(ref)
        for result in list(trace["agent_run_results"] or [])
        for ref in list(dict(result).get("artifact_refs") or [])
    ]

    assert trace["coordination_runs"] == []
    assert any("backend/sandbox_probe.txt" in ref for ref in artifact_refs)


def test_professional_task_sandbox_runs_terminal_inside_overlay_workspace() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _SandboxTerminalModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-sandbox-terminal",
            message="请在隔离环境里运行一个命令，确认 terminal 的工作目录。",
            task_selection={
                **_professional_task_selection(semantic_task_type="bounded_tool_task"),
            },
        )
    )
    sandbox_event = _latest_event(runtime_events, "runtime_sandbox_prepared")
    sandbox_root = str(dict(dict(sandbox_event.get("payload") or {}).get("sandbox_policy") or {}).get("sandbox_root") or "")
    tool_result_event = _latest_event(runtime_events, "tool_result_received")
    observation = dict(dict(tool_result_event.get("payload") or {}).get("observation") or {})
    observation_payload = dict(observation.get("payload") or {})

    assert sandbox_root
    assert str(observation_payload.get("tool_name") or "") == "terminal"
    assert str(observation_payload.get("result") or "").strip() == sandbox_root
    assert model_runtime.tool_enabled_calls == 2
    assert model_runtime.seen_sandbox_cwd is True
    assert done["terminal_reason"] == "completed"


def test_professional_task_reuses_sandbox_for_same_session_output_scope() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _SandboxContinuationModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )
    session_id = "session-professional-sandbox-continuation"
    target_message = (
        "请用专业模式在 sandbox overlay 中完成浏览器小游戏工程，目录必须是 "
        "frontend/public/games/arcane_dungeon_studio/。必须写入 game.js。"
    )

    _, first_events, first_done, _first_task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id=session_id,
            message=target_message,
            task_selection=_professional_task_selection(semantic_task_type="artifact_delivery"),
        )
    )
    _, second_events, second_done, _second_task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id=session_id,
            message="继续验收这个小游戏工程，请读回 game.js 确认上一轮写入内容。",
            task_selection=_professional_task_selection(semantic_task_type="artifact_delivery"),
        )
    )
    first_sandbox = Path(
        str(
            dict(dict(_latest_event(first_events, "runtime_sandbox_prepared").get("payload") or {}).get("sandbox_policy") or {}).get(
                "sandbox_root"
            )
            or ""
        )
    )
    second_sandbox = Path(
        str(
            dict(dict(_latest_event(second_events, "runtime_sandbox_prepared").get("payload") or {}).get("sandbox_policy") or {}).get(
                "sandbox_root"
            )
            or ""
        )
    )

    assert first_sandbox == second_sandbox
    assert (second_sandbox / "frontend/public/games/arcane_dungeon_studio/game.js").read_text(encoding="utf-8") == "const marker = 'first-pass';"
    assert str(first_done.get("terminal_reason") or "") in {"completed", "partial_contract_failed"}
    assert str(second_done.get("terminal_reason") or "") in {"completed", "partial_contract_failed"}
    assert model_runtime.seen_readback is True


def test_professional_task_recovers_provider_timeout_with_missing_output_paths() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _RecoverableTimeoutModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-provider-timeout-recovery",
            message=(
                "请用专业模式在 sandbox overlay 中完成浏览器小游戏工程，目录必须是 "
                "frontend/public/games/arcane_dungeon_studio/。必须写入 index.html、game.js。"
            ),
            task_selection=_professional_task_selection(
                semantic_task_type="artifact_delivery",
                max_tool_rounds=5,
            ),
        )
    )
    event_types = _event_types(runtime_events)
    timeout_recovery_event = next(
        event
        for event in runtime_events
        if dict(event.get("payload") or {}).get("error") == "professional_task_model_timeout_recoverable"
    )
    recovery_payload = dict(timeout_recovery_event.get("payload") or {})
    sandbox_root = Path(
        str(
            dict(dict(_latest_event(runtime_events, "runtime_sandbox_prepared").get("payload") or {}).get("sandbox_policy") or {}).get(
                "sandbox_root"
            )
            or ""
        )
    )

    assert "tool_result_received" in event_types
    assert "write_file" in recovery_payload["suggested_tool_names"]
    assert model_runtime.recovery_prompt_seen is True
    assert model_runtime.tool_enabled_calls >= 4
    assert done["terminal_reason"] == "completed"
    assert (sandbox_root / "frontend/public/games/arcane_dungeon_studio/index.html").exists()
    assert (sandbox_root / "frontend/public/games/arcane_dungeon_studio/game.js").exists()


def test_professional_task_exposes_agent_todo_before_write_contract_gate() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _TodoThenWriteModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-todo",
            message=(
                "请用专业模式在 sandbox overlay 中完成浏览器小游戏工程，目录必须是 "
                "frontend/public/games/arcane_dungeon_studio/。必须写入 index.html。"
            ),
            task_selection=_professional_task_selection(
                semantic_task_type="artifact_delivery",
                max_tool_rounds=4,
            ),
        )
    )
    event_types = _event_types(runtime_events)
    sandbox_root = Path(
        str(
            dict(dict(_latest_event(runtime_events, "runtime_sandbox_prepared").get("payload") or {}).get("sandbox_policy") or {}).get(
                "sandbox_root"
            )
            or ""
        )
    )

    assert "tool_result_received" in event_types
    assert "agent_todo" in model_runtime.tool_names_by_call[0]
    assert model_runtime.seen_todo is True
    assert any(
        str(dict(dict(event.get("payload") or {}).get("observation") or {}).get("payload") or {}).find("agent_todo") >= 0
        or "agent_todo" in str(event.get("payload") or "")
        for event in runtime_events
    )
    assert done["terminal_reason"] == "completed"
    assert (sandbox_root / "frontend/public/games/arcane_dungeon_studio/index.html").exists()


def test_professional_task_budget_exhaustion_forces_model_closeout() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-budget","failed_turns":1,'
            '"failures":[{"turn":33,"check":"timeout","symptom":"tool rounds exhausted before final answer"}]}'
        ),
        encoding="utf-8",
    )
    model_runtime = _BudgetCloseoutModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-budget-closeout",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json，"
                "找结构性根因并给回归测试。"
            ),
            task_selection=_professional_task_selection(max_tool_rounds=1, semantic_task_type=None),
        )
    )
    event_types = _event_types(runtime_events)
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    checks = dict(dict(dict(verify_event.get("payload") or {}).get("verification") or {}).get("checks") or {})

    assert "professional_task_budget_closeout_started" in event_types
    assert checks["tool_budget_exhausted"] is True
    assert done["terminal_reason"] == "completed"
    assert "结构性根因" in str(done.get("content") or "")
    assert "回归测试" in str(done.get("content") or "")
    assert model_runtime.plain_calls == 1
    assert runtime.task_run_loop.get_trace(task_run_id, include_payloads=True)["coordination_runs"] == []


def test_professional_task_keeps_full_tool_pool_after_material_review_and_model_selects_write() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "node_status_filter_contract.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text('{"feature":"status_filter","states":["ready","blocked"]}', encoding="utf-8")
    model_runtime = _WriteAfterReadModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-write-after-read",
            message=(
                "请用专业模式根据 tests/fixtures/professional_task_suite/node_status_filter_contract.json，"
                "在 sandbox overlay 中写入一份状态筛选功能草案，并说明验证结果。"
            ),
            task_selection=_professional_task_selection(semantic_task_type="artifact_delivery", max_tool_rounds=3),
        )
    )
    event_types = _event_types(runtime_events)
    content = str(done.get("content") or "")

    assert "tool_result_received" in event_types
    assert done["terminal_reason"] == "completed"
    assert model_runtime.seen_contract is True
    assert model_runtime.seen_write is True
    write_call_options = model_runtime.tool_call_options_by_call[1]
    assert getattr(write_call_options, "tool_choice", None) is None
    assert getattr(write_call_options, "parallel_tool_calls", None) is False
    assert "修改" in content
    assert "文件" in content
    assert "验证" in content


def test_professional_task_blocks_terminal_until_required_code_edit_is_observed() -> None:
    backend_root = _isolated_backend_root()
    target = backend_root.parent / "backend" / "order_pipeline.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def total(values):\n    return 0\n", encoding="utf-8")
    model_runtime = _TerminalBeforeEditModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-terminal-before-edit",
            message=(
                "请修复 backend/order_pipeline.py 的订单流水线逻辑，"
                "先阅读代码，在 sandbox overlay 中修改文件，然后运行 pytest 或等价 Python 断言验证通过。"
            ),
            task_selection=_professional_task_selection(semantic_task_type="code_fix_execution", max_tool_rounds=6),
        )
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    checks = dict(verification.get("checks") or {})
    blocked_events = [
        event
        for event in runtime_events
        if dict(event.get("payload") or {}).get("error") == "professional_task_goal_contract_requires_write"
    ]

    assert blocked_events == []
    assert model_runtime.blocked_terminal_attempted is False
    assert model_runtime.seen_edit is True
    assert model_runtime.seen_pytest is True
    assert "edit_file" in model_runtime.tool_names_by_call[1]
    assert "terminal" in model_runtime.tool_names_by_call[2]
    assert checks["write_observation_count"] >= 1
    assert checks["verification_command_count"] >= 1
    assert verification["passed"] is True
    assert done["terminal_reason"] == "completed"
    assert "PYTEST_OK" in str(done.get("content") or "")


def test_professional_task_tool_markup_leak_cannot_pass_validation() -> None:
    model_runtime = _ToolMarkupLeakModelRuntimeStub()
    runtime = _runtime(model_runtime=model_runtime)

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-tool-markup-leak",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json，"
                "找结构性根因并给出回归测试。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None),
        )
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    content = str(done.get("content") or "")

    assert verification["passed"] is False
    assert verification["protocol_leak_detected"] is True or "read_material" in verification["missing_required_actions"]
    assert "name=\"read_file\"" not in content
    assert "<｜｜DSML" not in content
    assert done["terminal_reason"] in {"tool_call_markup_leaked", "partial_contract_failed"}
    completion = dict(done.get("completion") or {})
    assert completion["completed"] is False
    assert completion["status"] in {"partial", "failed"}
    assert completion["terminal_reason"] == done["terminal_reason"]


def test_professional_task_uses_evidence_closeout_after_final_markup_leak() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "failing_sixty_turn_summary.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        (
            '{"run_id":"fixture-professional-evidence-closeout","failed_turns":4,'
            '"failures":['
            '{"turn":17,"check":"response.nonempty","symptom":"answer was cut after a tool observation",'
            '"evidence":["tool_result_received","final_content_chars=0"]},'
            '{"turn":18,"check":"runtime.timeout","symptom":"memory maintenance blocked foreground response",'
            '"evidence":["memory_maintenance_attempted=true","duration_ms=1800000"]},'
            '{"turn":31,"check":"main.active_dataset.nonempty","symptom":"delegated table result did not write active_dataset",'
            '"evidence":["context_writeback_hints.source_kind=dataset","final_outputs.main_context={}"]},'
            '{"turn":42,"check":"trace.artifact.contains","symptom":"write_file requested but no artifact ref was committed",'
            '"evidence":["tool_requires_approval=true","artifact_refs=[]"]}'
            ']}'
        ),
        encoding="utf-8",
    )
    model_runtime = _EvidenceCloseoutLeakModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-evidence-closeout",
            message=(
                "分析 tests/fixtures/professional_task_suite/failing_sixty_turn_summary.json，"
                "把失败归类，找出结构性根因，并给出应该补的回归测试。"
            ),
            task_selection=_professional_task_selection(semantic_task_type=None),
        )
    )
    event_types = _event_types(runtime_events)
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    validation = dict(verification.get("deliverable_validation") or {})
    content = str(done.get("content") or "")

    assert "professional_task_evidence_closeout_applied" in event_types
    assert verification["passed"] is True
    assert validation["passed"] is True
    assert done["terminal_reason"] == "completed"
    assert content
    assert "失败归类" in content
    assert "结构性根因" in content
    assert "回归测试" in content
    assert "证据边界" in content
    assert "artifact/writeback" in content
    assert "name=\"read_file\"" not in content
    assert "<｜｜DSML" not in content


def test_professional_material_synthesis_uses_evidence_closeout_after_dsml_leak() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "inventory_note.md"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("inventory risk: ready stock is below reorder level in warehouse A.", encoding="utf-8")
    model_runtime = _MaterialSynthesisLeakModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-material-synthesis-leak",
            message=(
                "请用专业模式结合 tests/fixtures/professional_task_suite/inventory_note.md，"
                "写一份风险与行动建议。需要分别说明治理风险、库存风险和优先行动。"
            ),
            task_selection=_professional_task_selection(semantic_task_type="material_synthesis"),
        )
    )
    event_types = _event_types(runtime_events)
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    content = str(done.get("content") or "")

    assert "professional_task_evidence_closeout_applied" in event_types
    assert verification["passed"] is True
    assert done["terminal_reason"] == "completed"
    assert "治理" in content
    assert "库存" in content
    assert "行动" in content
    assert "name=\"search_files\"" not in content
    assert "<｜｜DSML" not in content
    assert model_runtime.seen_material is True


def test_professional_verification_blocks_complete_when_required_terms_are_missing() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "node_status_filter_contract.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text('{"feature":"status_filter","states":["ready","blocked"]}', encoding="utf-8")
    model_runtime = _ArtifactDeliveryMissingTermModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-missing-response-terms",
            message=(
                "请用专业模式根据 tests/fixtures/professional_task_suite/node_status_filter_contract.json，"
                "在 sandbox overlay 中完成一个最小端到端功能草案：后端筛选接口说明、前端状态筛选交互、以及至少两个测试点。"
                "需要写入一份实施草案文件并说明验证结果。"
            ),
            task_selection=_professional_task_selection(semantic_task_type="artifact_delivery", max_tool_rounds=3),
        )
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    run_state = dict(verification.get("professional_run_state") or {})

    assert verification["passed"] is False
    assert "后端" in verification["missing_response_terms"]
    assert "前端" in verification["missing_response_terms"]
    assert "测试" in verification["missing_response_terms"]
    assert run_state["state"] == "blocked"
    assert done["terminal_reason"] == "partial_contract_failed"
    assert model_runtime.seen_write is True
    completion = dict(done.get("completion") or {})
    assert completion["completed"] is False
    assert completion["status"] == "partial"
    assert "后端" in str(completion)


def test_professional_goal_contract_expands_output_directory_file_list() -> None:
    from runtime.professional_runtime.goal_contract import _goal_contract_from_semantic_contract

    goal_contract = _goal_contract_from_semantic_contract(
        task_run_id="taskrun:multifile-contract",
        user_message=(
            "请在 sandbox overlay 中完成多文件网页工程，目录必须是 frontend/public/games/snake_plus/。"
            "必须写入 index.html、styles.css、game.js、README.md。"
        ),
        semantic_contract={"task_goal_type": "artifact_delivery"},
    )

    assert goal_contract.required_output_paths == [
        "frontend/public/games/snake_plus/index.html",
        "frontend/public/games/snake_plus/styles.css",
        "frontend/public/games/snake_plus/game.js",
        "frontend/public/games/snake_plus/README.md",
    ]
    assert goal_contract.requires_write_output is True


def test_professional_obligation_requires_all_explicit_output_paths() -> None:
    from runtime.contracts.obligation_validation import validate_obligations
    from runtime.professional_runtime.goal_contract import _goal_contract_from_semantic_contract
    from runtime.memory.tool_observation_ledger import (
        ToolObservationLedger,
        build_tool_observation_record,
    )

    goal_contract = _goal_contract_from_semantic_contract(
        task_run_id="taskrun:multifile-obligation",
        user_message=(
            "请在 sandbox overlay 中完成多文件网页工程，目录必须是 frontend/public/games/snake_plus/。"
            "必须写入 index.html、styles.css、game.js、README.md。"
        ),
        semantic_contract={"task_goal_type": "artifact_delivery"},
    )
    ledger = ToolObservationLedger(
        ledger_id="ledger:multifile-obligation",
        task_run_id="taskrun:multifile-obligation",
    )
    for path in goal_contract.required_output_paths[:2]:
        envelope = build_tool_result_envelope(
            tool_name="write_file",
            tool_args={"path": path},
            result={
                "text": f"Write succeeded: {path}",
                "structured_payload": {
                    "observed_paths": [path],
                    "artifact_refs": [{"path": path, "kind": "file", "source": "write_file"}],
                },
            },
        )
        ledger = ledger.append(
            build_tool_observation_record(
                observation_ref=f"obs:{path}",
                tool_name="write_file",
                tool_args={"path": path},
                result={"result_envelope": envelope.to_dict()},
            )
        )

    validation = validate_obligations(
        execution_obligation={},
        semantic_contract={"task_goal_type": "artifact_delivery"},
        goal_contract=goal_contract,
        tool_observation_ledger=ledger,
        final_content="已完成：文件 index.html、styles.css。验证：未运行。",
        deliverable_validation={"passed": True},
        terminal_reason="completed",
        tool_execution_enabled=True,
        tool_observation_count=2,
    )

    assert validation.passed is False
    assert "write_output" in validation.missing_required_actions
    assert validation.missing_output_paths == (
        "frontend/public/games/snake_plus/game.js",
        "frontend/public/games/snake_plus/README.md",
    )


def test_professional_deliverable_progress_selects_next_missing_path_and_state_obligations() -> None:
    from runtime.professional_runtime.goal_contract import _goal_contract_from_semantic_contract
    from runtime.professional_runtime.deliverable_progress import build_deliverable_progress
    from runtime.professional_runtime.state_machine import initial_professional_run_state
    from runtime.memory.tool_observation_ledger import (
        ToolObservationLedger,
        build_tool_observation_record,
    )

    goal_contract = _goal_contract_from_semantic_contract(
        task_run_id="taskrun:deliverable-progress",
        user_message=(
            "请在 sandbox overlay 中完成多文件网页工程，目录必须是 frontend/public/games/snake_plus/。"
            "必须写入 index.html、styles.css、game.js、README.md，并创建 assets/ 目录。"
        ),
        semantic_contract={"task_goal_type": "artifact_delivery"},
    )
    ledger = ToolObservationLedger(
        ledger_id="ledger:deliverable-progress",
        task_run_id="taskrun:deliverable-progress",
    )
    for path in goal_contract.required_output_paths[:2]:
        envelope = build_tool_result_envelope(
            tool_name="write_file",
            tool_args={"path": path},
            result={
                "text": f"Write succeeded: {path}",
                "structured_payload": {
                    "observed_paths": [path],
                    "artifact_refs": [{"path": path, "kind": "file", "source": "write_file"}],
                },
            },
        )
        ledger = ledger.append(
            build_tool_observation_record(
                observation_ref=f"obs:{path}",
                tool_name="write_file",
                tool_args={"path": path},
                result={"result_envelope": envelope.to_dict()},
            )
        )

    progress = build_deliverable_progress(goal_contract=goal_contract, tool_observation_ledger=ledger)
    state = initial_professional_run_state("taskrun:deliverable-progress")
    state = state.advance("mode_policy_bound", reason="mode")
    state = state.advance("obligation_bound", reason="obligation", unsatisfied_obligations=progress.missing_obligations())

    assert progress.next_missing_deliverable is not None
    assert progress.next_missing_deliverable.path == "frontend/public/games/snake_plus/game.js"
    assert progress.suggested_tool_names() == ("write_file",)
    assert "write_output:frontend/public/games/snake_plus/game.js" in state.unsatisfied_obligations
    assert "ensure_dir:frontend/public/games/snake_plus/assets" in progress.missing_obligations()


def test_professional_state_cycle_allows_terminal_then_read_before_closeout() -> None:
    backend_root = _isolated_backend_root()
    fixture = backend_root / "tests" / "fixtures" / "professional_task_suite" / "ops_incident_snapshot.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text('{"service":"local-api","timeout_ms":100,"symptom":"request timeout"}', encoding="utf-8")
    model_runtime = _VerificationThenReadModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-terminal-then-read",
            message=(
                "请用专业模式排查 tests/fixtures/professional_task_suite/ops_incident_snapshot.json "
                "里的本地服务超时问题。你需要运行一个只读命令确认当前工作目录，再给出原因、修复建议和验证步骤。"
            ),
            task_selection=_professional_task_selection(semantic_task_type="bounded_tool_task", max_tool_rounds=3),
        )
    )
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})
    state = dict(verification.get("professional_run_state") or {})
    content = str(done.get("content") or "")

    assert verification["passed"] is True
    assert state["state"] == "complete"
    assert done["terminal_reason"] == "completed"
    assert model_runtime.seen_terminal is True
    assert "原因" in content
    assert "修复建议" in content
    assert "验证步骤" in content


def test_professional_progress_policy_rejection_returns_to_model_as_tool_result() -> None:
    backend_root = _isolated_backend_root()
    model_runtime = _ProgressPolicyCorrectionModelRuntimeStub()
    runtime = _runtime(
        base_dir=backend_root,
        model_runtime=model_runtime,
        tool_runtime=_ToolRuntimeWithSideEffectsStub(backend_root),
    )

    _, runtime_events, done, _task_run_id = asyncio.run(
        _collect_runtime_events(
            runtime,
            session_id="session-professional-progress-policy-correction",
            message=(
                "请用专业模式在 sandbox overlay 中完成浏览器小游戏工程，目录必须是 "
                "frontend/public/games/progress_probe/。必须写入 game.js。"
            ),
            task_selection=_professional_task_selection(
                semantic_task_type="artifact_delivery",
                max_tool_rounds=7,
            ),
        )
    )
    event_types = _event_types(runtime_events)
    blocked_event = _latest_event(runtime_events, "tool_call_blocked_by_progress_policy")
    stage_summary_events = [
        event for event in runtime_events if event.get("event_type") == "professional_task_stage_summary"
    ]
    verify_event = _latest_event(runtime_events, "professional_task_deliverable_validation_checked")
    verification = dict(dict(verify_event.get("payload") or {}).get("verification") or {})

    assert "tool_call_blocked_by_progress_policy" in event_types
    assert dict(blocked_event.get("payload") or {})["tool_name"] == "search_text"
    assert model_runtime.seen_progress_rejection is True
    assert model_runtime.seen_write is True
    assert stage_summary_events
    assert verification["passed"] is True
    assert done["terminal_reason"] == "completed"
