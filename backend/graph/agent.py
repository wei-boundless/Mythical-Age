from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

try:
    from langchain_deepseek import ChatDeepSeek
except ImportError:  # pragma: no cover - optional dependency at runtime
    ChatDeepSeek = None

from config import get_settings, runtime_config
from RAG.router import RAGQueryRouter
from graph.memory_bridge import GraphMemoryBridge
from graph.memory_indexer import memory_indexer
from graph.prompt_builder import build_system_prompt
from graph.session_manager import SessionManager
from pdf_analysis import PdfAnalysisCatalog
from skill_system import SkillDefinition, SkillRegistry
from structured_data import StructuredDataCatalog
from structured_memory import ConsolidationConfig, ConsolidationReport, ConsolidationScheduler
from tools import get_all_tools
from tools.skills_scanner import refresh_snapshot
from tools.tool_registry import ToolRegistry, refresh_tool_registry
from understanding import (
    MemoryIntent,
    QueryUnderstanding,
    analyze_memory_intent,
    analyze_query_understanding,
    split_compound_query,
)


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


class AgentManager:
    def __init__(self) -> None:
        self.base_dir: Path | None = None
        self.session_manager: SessionManager | None = None
        self.memory_bridge: GraphMemoryBridge | None = None
        self.consolidation_scheduler: ConsolidationScheduler | None = None
        self.rag_router: RAGQueryRouter | None = None
        self.skill_registry: SkillRegistry | None = None
        self.tool_registry: ToolRegistry | None = None
        self.tools = []
        self.max_tool_steps = 8

    def _tool_step_failure_message(self) -> str:
        return "调用工具失败"

    def _should_skip_rag_for_query(self, message: str) -> bool:
        lowered = message.lower()
        tool_first_markers = (
            "weather",
            "forecast",
            "temperature",
            "rain",
            "wind speed",
            "\u5929\u6c14",
            "\u6c14\u6e29",
            "\u6e29\u5ea6",
            "\u964d\u96e8",
            "\u4e0b\u96e8",
            "\u53f0\u98ce",
            "\u7a7a\u6c14\u8d28\u91cf",
            "\u91d1\u4ef7",
            "\u9ec4\u91d1\u4ef7\u683c",
            "\u73b0\u8d27\u9ec4\u91d1",
            "\u671f\u8d27\u4ef7\u683c",
            "\u6c47\u7387",
            "\u80a1\u4ef7",
            "\u80a1\u7968\u4ef7\u683c",
            "btc",
            "eth",
            "\u6bd4\u7279\u5e01\u4ef7\u683c",
            "\u65b0\u95fb",
            "\u6700\u65b0\u6d88\u606f",
            "\u5b9e\u65f6",
            "\u4eca\u65e5",
            "\u4eca\u5929",
        )
        return any(marker in lowered for marker in tool_first_markers)

    def _find_tool(self, name: str):
        for tool in self.tools:
            if getattr(tool, "name", "") == name:
                return tool
        return None

    def _resolve_tool_input_from_history(
        self,
        query_understanding: QueryUnderstanding,
        message: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        tool_input = dict(query_understanding.tool_input or {"query": message})
        if (
            query_understanding.tool_name == "structured_data_analysis"
            and self.base_dir is not None
            and not str(tool_input.get("path", "") or "").strip()
        ):
            # Only inherit the previous dataset for weak follow-up turns.
            # Explicit new structured-data requests should be re-resolved from the current query.
            if (
                query_understanding.intent != "structured_followup_query"
                and query_understanding.target_object is not None
            ):
                return tool_input
            resolved = StructuredDataCatalog.resolve_dataset_path_from_history(self.base_dir, history)
            if resolved is not None:
                tool_input["path"] = StructuredDataCatalog.relative_path(self.base_dir, resolved)
        return tool_input

    def _promote_contextual_pdf_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        query_understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if self.base_dir is None:
            return query_understanding
        if query_understanding.route == "tool":
            return query_understanding
        if not self._looks_like_pdf_followup(message):
            return query_understanding
        resolved = PdfAnalysisCatalog.resolve_pdf_path_from_history(self.base_dir, history)
        if resolved is None:
            return query_understanding
        return QueryUnderstanding(
            intent="pdf_page_followup_query",
            modality="pdf",
            route="tool",
            tool_name="pdf_analysis",
            tool_input={
                "query": message,
                "mode": "page_read",
                "path": PdfAnalysisCatalog.relative_path(self.base_dir, resolved),
            },
            should_skip_rag=True,
            reasons=["pdf_followup_context"],
        )

    def _looks_like_pdf_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if re.search(r"第\s*\d+\s*页", message):
            return True
        if re.search(r"第\s*[零一二三四五六七八九十百千两\d]+\s*页", message):
            return True
        if re.search(r"page\s*\d+", normalized):
            return True
        followup_markers = ("这一页", "那一页", "上一页", "下一页", "这页", "那页")
        return any(marker in message for marker in followup_markers)

    def _promote_contextual_structured_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        query_understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        if self.base_dir is None:
            return query_understanding
        if query_understanding.route == "tool":
            return query_understanding
        if not self._looks_like_structured_followup(message):
            return query_understanding
        resolved = StructuredDataCatalog.resolve_dataset_path_from_history(self.base_dir, history)
        if resolved is None:
            return query_understanding
        return QueryUnderstanding(
            intent="structured_followup_query",
            modality="table",
            route="tool",
            tool_name="structured_data_analysis",
            tool_input={
                "query": message,
                "analysis_type": "auto",
                "path": StructuredDataCatalog.relative_path(self.base_dir, resolved),
            },
            should_skip_rag=True,
            reasons=["structured_followup_context"],
        )

    def _looks_like_structured_followup(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if len(normalized) > 24:
            return False
        followup_markers = (
            "再",
            "那",
            "呢",
            "按",
            "前五",
            "前十",
            "top",
            "排名",
            "排行",
            "最高",
            "最低",
            "汇总",
            "分布",
            "按地区",
            "按部门",
            "按仓库",
            "按品类",
        )
        if any(marker in message for marker in followup_markers):
            return True
        return bool(re.search(r"(top\s*\d+|第?\d+名)", normalized))

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        refresh_snapshot(base_dir)
        refresh_tool_registry(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.memory_bridge = GraphMemoryBridge(base_dir)
        self.skill_registry = SkillRegistry(base_dir)
        self.tool_registry = ToolRegistry(base_dir)
        self.consolidation_scheduler = ConsolidationScheduler(
            base_dir / "durable_memory",
            config=ConsolidationConfig(
                min_saved_notes_between_runs=3,
                min_seconds_between_runs=1800,
            ),
            on_completed=self._on_durable_memory_consolidated,
        )
        self.rag_router = RAGQueryRouter(base_dir)
        self.tools = get_all_tools(base_dir)
        self.memory_bridge.set_durable_memory_saved_callback(self._on_durable_memory_saved)

    def _resolve_active_skill(
        self,
        message: str,
        query_understanding: QueryUnderstanding,
    ) -> SkillDefinition | None:
        if self.skill_registry is None:
            return None
        if query_understanding.skill_name:
            existing = self.skill_registry.get_by_name(query_understanding.skill_name)
            if existing is not None:
                return existing
        skill = self.skill_registry.match_for_query(
            message=message,
            route=query_understanding.route,
            modality=query_understanding.modality,
            tool_name=query_understanding.tool_name,
        )
        if skill is not None:
            query_understanding.skill_name = skill.name
        return skill

    def _on_durable_memory_saved(self, saved_count: int) -> None:
        if saved_count <= 0:
            return
        memory_indexer.rebuild_index()
        if self.base_dir is not None and self.rag_router is not None:
            try:
                self.rag_router.registry.rebuild("durable_memory")
            except Exception:
                pass
        if self.consolidation_scheduler is not None:
            self.consolidation_scheduler.notify_saved(saved_count)

    def _on_durable_memory_consolidated(self, report: ConsolidationReport) -> None:
        if report.status != "ok":
            return
        memory_indexer.rebuild_index()
        if self.base_dir is not None and self.rag_router is not None:
            try:
                self.rag_router.registry.rebuild("durable_memory")
            except Exception:
                pass

    def _build_chat_model(self):
        settings = get_settings()

        if settings.llm_provider == "deepseek":
            if ChatDeepSeek is None:
                raise RuntimeError("langchain-deepseek is not installed")
            if not settings.llm_api_key:
                raise RuntimeError("Missing API key for provider deepseek")
            return ChatDeepSeek(
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                temperature=0,
            )

        if not settings.llm_api_key:
            raise RuntimeError(f"Missing API key for provider {settings.llm_provider}")

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
        )

    def build_system_prompt_for_session(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: MemoryIntent | None = None,
        relevant_memory_notes: list[Any] | None = None,
        active_skill: SkillDefinition | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> str:
        if self.base_dir is None:
            raise RuntimeError("AgentManager is not initialized")

        context_package = None
        session_memory = None
        persistent_memory = None
        if session_id and self.memory_bridge is not None:
            context_package = self.memory_bridge.build_context_package(
                session_id,
                history=history,
                pending_user_message=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
                retrieval_results=retrieval_results,
                rebuild_reason="prompt_assembly",
            )
        if self.memory_bridge is not None:
            persistent_memory = self.memory_bridge.build_persistent_memory_block(
                query=pending_user_message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
            )
        return build_system_prompt(
            self.base_dir,
            runtime_config.get_rag_mode(),
            persistent_memory=persistent_memory,
            session_memory=session_memory,
            context_package=context_package,
            active_skill=self.skill_registry.format_active_skill_block(active_skill)
            if self.skill_registry is not None
            else None,
        )

    def _build_agent(
        self,
        session_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: MemoryIntent | None = None,
        relevant_memory_notes: list[Any] | None = None,
        active_skill: SkillDefinition | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ):
        system_prompt = self.build_system_prompt_for_session(
            session_id,
            history=history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_memory_notes=relevant_memory_notes,
            active_skill=active_skill,
            retrieval_results=retrieval_results,
        )
        return create_agent(
            model=self._build_chat_model(),
            tools=self._filter_tools_for_skill(active_skill),
            system_prompt=system_prompt,
        )

    def _filter_tools_for_skill(self, active_skill: SkillDefinition | None):
        if active_skill is None or not active_skill.allowed_tools:
            return self.tools
        allowed = {tool_name.strip() for tool_name in active_skill.allowed_tools if tool_name.strip()}
        filtered = [tool for tool in self.tools if getattr(tool, "name", "") in allowed]
        return filtered or self.tools

    def _build_messages(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for item in history:
            role = item.get("role")
            if role not in {"system", "user", "assistant"}:
                continue
            messages.append({"role": role, "content": str(item.get("content", ""))})
        return messages

    async def _astream_single(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
    ):
        if self.base_dir is None:
            raise RuntimeError("AgentManager is not initialized")

        rag_mode = runtime_config.get_rag_mode()
        augmented_history = list(history)
        memory_intent = analyze_memory_intent(message)
        query_understanding = analyze_query_understanding(
            message,
            memory_intent,
            skill_registry=self.skill_registry,
            tool_registry=self.tool_registry,
        )
        query_understanding = self._promote_contextual_pdf_query(
            message,
            history,
            query_understanding,
        )
        query_understanding = self._promote_contextual_structured_query(
            message,
            history,
            query_understanding,
        )
        active_skill = self._resolve_active_skill(message, query_understanding)
        context_compaction: dict[str, Any] | None = None
        retrievals: list[dict[str, Any]] = []
        if self.memory_bridge is not None:
            augmented_history, context_compaction = self.memory_bridge.compact_history_for_agent(
                session_id,
                augmented_history,
            )
            yield {"type": "context_management", "context": context_compaction}
        relevant_memory_task: asyncio.Task[list[Any]] | None = None
        if query_understanding.route == "tool" and query_understanding.tool_name:
            if (
                active_skill is not None
                and active_skill.allowed_tools
                and query_understanding.tool_name not in active_skill.allowed_tools
            ):
                yield {
                    "type": "done",
                    "content": (
                        f"技能 {active_skill.name} 不允许调用工具 {query_understanding.tool_name}。"
                    ),
                }
                return
            tool = self._find_tool(query_understanding.tool_name)
            if tool is not None:
                tool_input = self._resolve_tool_input_from_history(
                    query_understanding,
                    message,
                    history,
                )
                yield {"type": "tool_start", "tool": query_understanding.tool_name, "input": tool_input}
                output = await asyncio.to_thread(tool.invoke, tool_input)
                tool_content = str(output)
                yield {"type": "tool_end", "tool": query_understanding.tool_name, "output": tool_content}
                yield {"type": "done", "content": tool_content}
                return
        if self.memory_bridge is not None:
            relevant_memory_task = asyncio.create_task(
                asyncio.to_thread(
                    self.memory_bridge.prefetch_relevant_notes,
                    message,
                    memory_intent,
                    limit=3,
                )
            )
        if (
            rag_mode
            and not self._should_skip_rag_for_query(message)
            and not memory_intent.should_skip_rag
            and not query_understanding.should_skip_rag
        ):
            if self.rag_router is not None:
                retrievals = self.rag_router.retrieve(message, top_k=5)
            else:
                retrievals = memory_indexer.retrieve(message, top_k=3)
            yield {"type": "retrieval", "query": message, "results": retrievals}

        relevant_memory_notes: list[Any] | None = None
        if relevant_memory_task is not None:
            try:
                relevant_memory_notes = await relevant_memory_task
            except Exception:
                relevant_memory_notes = None

        if self.memory_bridge is not None:
            memory_trace = self.memory_bridge.inspect_memory_context(
                session_id,
                history=history,
                pending_user_message=message,
                memory_intent=memory_intent,
                relevant_notes=relevant_memory_notes,
                context_compaction=context_compaction,
                retrieval_results=retrievals,
            )
            yield {"type": "memory_context", "memory": memory_trace}

        agent = self._build_agent(
            session_id,
            history=history,
            pending_user_message=message,
            memory_intent=memory_intent,
            relevant_memory_notes=relevant_memory_notes,
            active_skill=active_skill,
            retrieval_results=retrievals,
        )
        messages = self._build_messages(augmented_history)
        messages.append({"role": "user", "content": message})

        final_content_parts: list[str] = []
        last_ai_message = ""
        pending_tools: dict[str, dict[str, str]] = {}
        tool_step_count = 0

        async for mode, payload in agent.astream(
            {"messages": messages},
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                chunk, _metadata = payload
                text = _stringify_content(getattr(chunk, "content", ""))
                if text:
                    final_content_parts.append(text)
                    yield {"type": "token", "content": text}
                continue

            if mode != "updates":
                continue

            for update in payload.values():
                for agent_message in update.get("messages", []):
                    message_type = getattr(agent_message, "type", "")
                    tool_calls = getattr(agent_message, "tool_calls", []) or []

                    if message_type == "ai" and not tool_calls:
                        candidate = _stringify_content(getattr(agent_message, "content", ""))
                        if candidate:
                            last_ai_message = candidate

                    if tool_calls:
                        for tool_call in tool_calls:
                            tool_step_count += 1
                            if tool_step_count > self.max_tool_steps:
                                yield {"type": "done", "content": self._tool_step_failure_message()}
                                return
                            call_id = str(tool_call.get("id") or tool_call.get("name"))
                            tool_name = str(tool_call.get("name", "tool"))
                            tool_args = tool_call.get("args", "")
                            if not isinstance(tool_args, str):
                                tool_args = json.dumps(tool_args, ensure_ascii=False)
                            pending_tools[call_id] = {
                                "tool": tool_name,
                                "input": str(tool_args),
                            }
                            yield {
                                "type": "tool_start",
                                "tool": tool_name,
                                "input": str(tool_args),
                            }

                    if message_type == "tool":
                        tool_call_id = str(getattr(agent_message, "tool_call_id", ""))
                        pending = pending_tools.pop(
                            tool_call_id,
                            {"tool": getattr(agent_message, "name", "tool"), "input": ""},
                        )
                        output = _stringify_content(getattr(agent_message, "content", ""))
                        yield {
                            "type": "tool_end",
                            "tool": pending["tool"],
                            "output": output,
                        }
                        yield {"type": "new_response"}

        final_content = "".join(final_content_parts).strip() or last_ai_message.strip()
        yield {"type": "done", "content": final_content}

    async def astream(
        self,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
    ):
        if self.base_dir is None:
            raise RuntimeError("AgentManager is not initialized")
        subqueries = split_compound_query(message)
        if len(subqueries) > 1:
            results: list[tuple[str, str]] = []
            for index, subquery in enumerate(subqueries, start=1):
                yield {"type": "subtask_start", "index": index, "query": subquery}
                final_subcontent = ""
                async for event in self._astream_single(session_id, subquery, history):
                    event_type = event.get("type")
                    if event_type == "token":
                        continue
                    if event_type == "done":
                        final_subcontent = str(event.get("content", "") or "")
                        continue
                    forwarded = dict(event)
                    forwarded["subtask_index"] = index
                    forwarded["subtask_query"] = subquery
                    yield forwarded
                results.append((subquery, final_subcontent))
                yield {"type": "subtask_end", "index": index, "query": subquery}

            sections = []
            for index, (subquery, answer) in enumerate(results, start=1):
                answer_text = answer.strip() or "未能生成结果。"
                sections.append(f"{index}. {subquery}\n{answer_text}")
            yield {"type": "done", "content": "\n\n".join(sections)}
            return

        async for event in self._astream_single(session_id, message, history):
            yield event

    def refresh_session_memory(self, session_id: str) -> str:
        if self.session_manager is None or self.memory_bridge is None:
            raise RuntimeError("Agent manager is not initialized")
        messages = self.session_manager.load_session(session_id)
        summary = self.memory_bridge.refresh_session_memory(session_id, messages)
        if self.base_dir is not None and self.rag_router is not None:
            try:
                self.rag_router.registry.rebuild("session_memory")
            except Exception:
                pass
        return summary

    def extract_durable_memories(self, session_id: str) -> int:
        if self.session_manager is None or self.memory_bridge is None:
            raise RuntimeError("Agent manager is not initialized")
        messages = self.session_manager.load_session(session_id)
        return self.memory_bridge.submit_durable_memory_extraction(session_id, messages)

    async def generate_title(self, first_user_message: str) -> str:
        prompt = (
            "请根据用户的第一条消息生成一个中文会话标题。"
            "要求不超过 10 个汉字，不要带引号，不要解释。"
        )
        try:
            response = await self._build_chat_model().ainvoke(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": first_user_message},
                ]
            )
            title = _stringify_content(getattr(response, "content", "")).strip()
            return title[:10] or "新会话"
        except Exception:
            return (first_user_message.strip() or "新会话")[:10]

    async def summarize_history(self, messages: list[dict[str, Any]]) -> str:
        prompt = (
            "请将以下对话压缩成中文摘要，控制在 500 字以内。"
            "重点保留用户目标、已完成步骤、重要结论和未解决事项。"
        )
        lines: list[str] = []
        for item in messages:
            role = item.get("role", "assistant")
            content = str(item.get("content", "") or "")
            if content:
                lines.append(f"{role}: {content}")
        transcript = "\n".join(lines)

        try:
            response = await self._build_chat_model().ainvoke(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": transcript},
                ]
            )
            summary = _stringify_content(getattr(response, "content", "")).strip()
            return summary[:500]
        except Exception:
            return transcript[:500]


agent_manager = AgentManager()
