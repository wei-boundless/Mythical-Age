from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from .maintenance_models import (
    DurableMemoryWritePlan,
    MemoryMaintenanceRequest,
    MemoryMaintenanceResult,
    SessionMemoryMaintenanceDraft,
)


MessageInvoker = Callable[[list[dict[str, str]]], Awaitable[object]]


class MemoryMaintenanceAgent:
    """Model-backed agent:1 implementation for session and durable memory lanes."""

    def __init__(self, *, message_invoker: MessageInvoker | None = None) -> None:
        self._message_invoker = message_invoker

    def set_message_invoker(self, message_invoker: MessageInvoker | None) -> None:
        self._message_invoker = message_invoker

    async def maintain(self, request: MemoryMaintenanceRequest) -> MemoryMaintenanceResult:
        if self._message_invoker is None:
            raise RuntimeError("memory maintenance model invoker is not configured")
        response = await self._message_invoker(
            [
                {"role": "system", "content": self.system_prompt()},
                {"role": "user", "content": self._user_payload(request)},
            ]
        )
        payload = self._extract_json(self._response_text(response))
        return self._result_from_payload(payload)

    def system_prompt(self) -> str:
        return (
            "你是一名记忆管理员。\n"
            "你只负责整理当前会话中对后续继续工作有帮助的信息，并判断是否存在值得跨会话保存的稳定记忆。\n"
            "你不回答用户，不推进任务，不修复问题，也不替主 Agent 做任务决策。\n"
            "你需要区分会话恢复信息和跨会话长期记忆。\n"
            "Session Memory 只服务当前会话的 compact/recovery，要记录当前目标、工作状态、关键文件、结果、纠错和下一步。\n"
            "Durable Memory 只保存跨会话仍然有价值、稳定、非显而易见的信息，分类只能是 user、feedback、project、reference。\n"
            "不要把临时运行状态、工具失败、调度限制、runtime 诊断、可从当前文件或索引重新推导的信息写入长期记忆。\n"
            "不要保存代码模式、Git 历史、调试方案、已存在于项目指令中的规则，或只对本轮任务有用的过程记录。\n"
            "如果没有可靠的长期记忆，durable_memory.actions 返回空数组，并说明 skipped_reason。\n"
            "每条长期记忆写入都必须包含 evidence_excerpt 和 source_message_refs。\n"
            "你只能输出 JSON，不要输出 Markdown、解释或给用户看的回答。"
        )

    def _user_payload(self, request: MemoryMaintenanceRequest) -> str:
        schema_hint = {
            "session_memory": {
                "session_title": "短标题",
                "active_goal": "当前用户目标",
                "flow_state": ["当前流程状态"],
                "context_slots": ["当前有效上下文绑定，只记录当前仍有用的事实"],
                "current_task_state": ["正在处理或刚完成的事项"],
                "warm_context": ["继续工作时仍有帮助的短上下文"],
                "key_user_requests": ["用户明确提出且当前会话仍适用的要求"],
                "files_and_functions": ["相关文件、模块、函数"],
                "conventions_and_constraints": ["当前会话约束"],
                "errors_and_corrections": ["需要避免重复的问题或纠正"],
                "decisions_and_learnings": ["本会话形成的结论"],
                "key_results": ["本轮或当前阶段的关键结果"],
                "historical_results": ["旧结果，仅调试或恢复时参考"],
                "risk_watch": ["仍需注意的风险"],
                "next_step": ["自然继续时的下一步"],
                "worklog": ["简短事件记录"],
            },
            "durable_memory": {
                "actions": [
                    {
                        "action": "create | update | merge",
                        "note_id": "新建时可给稳定短 id",
                        "target_note_id": "更新或合并目标",
                        "merge_note_ids": ["合并来源"],
                        "memory_type": "user | feedback | project | reference",
                        "memory_class": "work | preference",
                        "title": "记忆标题",
                        "canonical_statement": "稳定事实",
                        "summary": "简短摘要",
                        "retrieval_hints": ["召回提示"],
                        "confidence": "low | medium | high",
                        "reason": "为什么值得长期保存",
                        "how_to_apply": "以后如何使用",
                        "evidence_excerpt": "来自本轮消息的证据摘录",
                        "source_message_refs": ["message:最后消息索引等来源引用"],
                    }
                ],
                "skipped_reason": "没有写入时说明原因",
                "reasoning_summary": "极短内部判断摘要",
            },
        }
        payload = {
            "request": request.model_dump(),
            "output_schema": schema_hint,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _result_from_payload(self, payload: dict[str, Any]) -> MemoryMaintenanceResult:
        session_payload = payload.get("session_memory")
        if not isinstance(session_payload, dict):
            session_payload = payload.get("session_memory_draft")
        if not isinstance(session_payload, dict):
            raise ValueError("memory maintenance response missing session_memory object")
        durable_payload = payload.get("durable_memory")
        if not isinstance(durable_payload, dict):
            durable_payload = payload.get("durable_memory_write_plan")
        if not isinstance(durable_payload, dict):
            durable_payload = {}
        return MemoryMaintenanceResult(
            session_memory=SessionMemoryMaintenanceDraft.model_validate(session_payload),
            durable_memory=DurableMemoryWritePlan.model_validate(durable_payload),
            diagnostics={
                "response_keys": sorted(str(key) for key in payload.keys()),
                "agent_id": "agent:1",
                "agent_profile_id": "memory_system_agent",
            },
        )

    def _response_text(self, response: object) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content or "")

    def _extract_json(self, text: str) -> dict[str, Any]:
        stripped = str(text or "").strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            payload = json.loads(stripped)
        else:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("No JSON object found in memory maintenance response")
            payload = json.loads(stripped[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("Memory maintenance response must be a JSON object")
        return payload
