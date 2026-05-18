from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from memory_system import MemoryFacade
from memory_system.maintenance_agent import MemoryMaintenanceAgent


def _agent_payload(*, durable_actions=None):
    return {
        "session_memory": {
            "session_title": "记忆系统接线",
            "active_goal": "接通记忆管理 Agent",
            "flow_state": ["记忆维护已进入提交后整理"],
            "current_task_state": ["已生成 agent draft"],
            "key_user_requests": ["记忆语义判断交给记忆管理 Agent"],
            "decisions_and_learnings": ["模型失败时不写长期记忆"],
            "key_results": ["Session Memory 由 agent:1 维护"],
            "worklog": ["完成一次记忆维护"],
        },
        "durable_memory": {
            "actions": durable_actions or [],
            "skipped_reason": "" if durable_actions else "no_cross_session_memory",
            "reasoning_summary": "只保留稳定跨会话信息",
        },
    }


def _fake_invoker(payload):
    async def invoke(_messages):
        return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    return invoke


def test_memory_maintenance_agent_prompt_is_natural_role_instruction() -> None:
    prompt = MemoryMaintenanceAgent().system_prompt()

    assert "你是一名记忆管理员" in prompt
    assert "你不回答用户" in prompt
    assert "runtime 节点" not in prompt
    assert "根据任务图执行" not in prompt


def test_memory_maintenance_coordinator_writes_session_and_durable_via_agent(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "memory-agent-boundary",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "记忆管理 Agent 负责记忆整理",
                        "canonical_statement": "记忆整理由 agent:1 在提交后统一执行。",
                        "summary": "agent:1 统一维护 session 与 durable memory。",
                        "retrieval_hints": ["记忆管理", "agent:1"],
                        "confidence": "high",
                        "reason": "这是系统架构层面的稳定约定。",
                        "how_to_apply": "后续调整记忆链路时保持主链与记忆整理解耦。",
                        "evidence_excerpt": "把记忆管理agent接通，要求真能按照设计原则来工作",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-memory-maintenance",
        messages=[
            {"role": "user", "content": "把记忆管理agent接通"},
            {"role": "assistant", "content": "已经接通"},
        ],
        turn_id="turn:session-memory-maintenance:1",
    )

    assert receipt.status == "succeeded"
    assert receipt.session_memory_succeeded is True
    assert receipt.durable_memory_succeeded is True
    assert receipt.durable_write_count == 1
    assert "接通记忆管理 Agent" in facade.session_memory.manager("session-memory-maintenance").load()
    assert facade.memory_manager.note_path("memory-agent-boundary").exists()


def test_memory_maintenance_model_failure_does_not_fallback_write_durable(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    async def failing_invoker(_messages):
        raise RuntimeError("model unavailable")

    facade.set_model_invoker(failing_invoker)

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-memory-failure",
        messages=[
            {"role": "user", "content": "请记住：我偏好复杂问题先讲结论。"},
            {"role": "assistant", "content": "好的。"},
        ],
    )

    assert receipt.status == "failed"
    assert receipt.durable_write_count == 0
    assert facade.memory_manager.list_notes() == []


def test_memory_maintenance_rejects_durable_action_without_evidence(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.set_model_invoker(
        _fake_invoker(
            _agent_payload(
                durable_actions=[
                    {
                        "action": "create",
                        "note_id": "missing-evidence",
                        "memory_type": "project",
                        "memory_class": "work",
                        "title": "缺少证据",
                        "canonical_statement": "这条长期记忆缺少来源证据。",
                        "summary": "缺少证据",
                        "source_message_refs": ["message:1"],
                    }
                ]
            )
        )
    )

    receipt = facade.run_memory_maintenance_after_commit(
        session_id="session-memory-reject",
        messages=[
            {"role": "user", "content": "测试"},
            {"role": "assistant", "content": "测试完成"},
        ],
    )

    assert receipt.status == "succeeded"
    assert receipt.session_memory_succeeded is True
    assert receipt.durable_memory_succeeded is False
    assert receipt.durable_write_count == 0
    assert receipt.diagnostics["durable_error"]
    assert facade.memory_manager.list_notes() == []
