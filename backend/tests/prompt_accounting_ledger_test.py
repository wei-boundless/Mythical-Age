from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptAccountingLedger,
    PromptCachePlanner,
    extract_provider_usage,
)
from harness.runtime.compiler import RuntimeCompiler


def test_prompt_accounting_ledger_records_prediction_provider_usage_and_cache(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:test",
        session_id="session:test",
        task_run_id="taskrun:test",
        provider="openai",
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "你是一名可靠的执行代理。"},
            {"role": "user", "content": "hello"},
        ],
    )
    cache_record = PromptCachePlanner().plan(segment_map)
    provider_usage = ModelTokenUsageRecord(
        usage_id="tokuse:modelreq:test:provider_usage",
        request_id="modelreq:test",
        session_id="session:test",
        task_run_id="taskrun:test",
        provider="openai",
        model="gpt-4.1-mini",
        source="provider_usage",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=4,
        cache_read_tokens=4,
        total_tokens=15,
        created_at=2.0,
    )

    ledger.record_segment_map(segment_map)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:test:local_prediction",
            request_id="modelreq:test",
            session_id="session:test",
            task_run_id="taskrun:test",
            provider="openai",
            model="gpt-4.1-mini",
            source="local_prediction",
            prompt_tokens=segment_map.predicted_prompt_tokens,
            total_tokens=segment_map.predicted_prompt_tokens,
            created_at=1.0,
        )
    )
    ledger.record_token_usage(provider_usage)
    ledger.record_prompt_cache(PromptCachePlanner().with_provider_usage(cache_record, provider_usage))

    summary = ledger.summarize_task("taskrun:test")
    segment_maps = ledger.list_segment_maps(task_run_id="taskrun:test")
    cache_records = ledger.list_prompt_cache(task_run_id="taskrun:test")

    assert len(segment_maps) == 1
    assert segment_maps[0]["request_id"] == "modelreq:test"
    assert summary["exact_total_tokens"] == 15
    assert summary["effective_total_tokens"] == 15
    assert summary["predicted_total_tokens"] == segment_map.predicted_prompt_tokens
    assert summary["cached_tokens"] == 4
    assert summary["cache_savings_tokens"] == 4
    assert cache_records[-1].status == "hit"


def test_provider_usage_extractor_handles_openai_anthropic_and_deepseek_shapes() -> None:
    openai_response = SimpleNamespace(
        content="ok",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 20,
                "completion_tokens": 7,
                "total_tokens": 27,
                "prompt_tokens_details": {"cached_tokens": 8},
            }
        },
    )
    anthropic_response = SimpleNamespace(
        content="ok",
        usage_metadata={
            "input_tokens": 11,
            "output_tokens": 3,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 2,
        },
    )
    deepseek_response = SimpleNamespace(
        content="ok",
        usage_metadata={
            "completion_tokens": 4,
            "prompt_cache_hit_tokens": 4352,
            "prompt_cache_miss_tokens": 33000,
        },
    )

    openai_usage = extract_provider_usage(openai_response, request_id="modelreq:openai")
    anthropic_usage = extract_provider_usage(anthropic_response, request_id="modelreq:anthropic")
    deepseek_usage = extract_provider_usage(deepseek_response, request_id="modelreq:deepseek")

    assert openai_usage is not None
    assert openai_usage.prompt_tokens == 20
    assert openai_usage.cached_tokens == 8
    assert openai_usage.total_tokens == 27
    assert anthropic_usage is not None
    assert anthropic_usage.prompt_tokens == 11
    assert anthropic_usage.completion_tokens == 3
    assert anthropic_usage.cache_read_tokens == 5
    assert anthropic_usage.cache_creation_tokens == 2
    assert anthropic_usage.total_tokens == 14
    assert deepseek_usage is not None
    assert deepseek_usage.prompt_tokens == 37352
    assert deepseek_usage.cached_tokens == 4352
    assert deepseek_usage.cache_read_tokens == 4352
    assert deepseek_usage.completion_tokens == 4
    assert deepseek_usage.total_tokens == 37356


def test_prompt_cache_key_is_stable_across_request_ids_for_same_prefix() -> None:
    serializer = CanonicalPromptSerializer()
    messages = [
        {"role": "system", "content": "你是一名可靠的执行代理。"},
        {"role": "system", "content": "Task execution stable contract\n{\"schema\":{\"action_type\":\"respond\"}}"},
        {"role": "user", "content": "Task execution current state\n{\"observations\":[]}"},
    ]

    first = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:first",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
        )
    )
    second = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:second",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
        )
    )

    assert first.prefix_hash == second.prefix_hash
    assert first.cache_key == second.cache_key
    assert first.boundary_segment_id != second.boundary_segment_id


def test_task_execution_packet_places_stable_contract_before_volatile_state() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:test",
        task_run={"task_run_id": "taskrun:test", "title": "审查监控系统"},
        contract={"task_run_goal": "审查并修复监控系统", "completion_criteria": ["完成真实验证"]},
        observations=[{"observation_id": "obs:1", "content": "latest command output"}],
        execution_state={"runtime_status": "running"},
        available_tools=[{"name": "read_file", "description": "读取文件"}],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.test"},
        },
    )

    messages = result.packet.model_messages
    assert [message["role"] for message in messages] == ["system", "system", "user"]
    assert "Task execution stable contract" in messages[1]["content"]
    assert "task_contract" in messages[1]["content"]
    assert "available_tools" in messages[1]["content"]
    assert "Task execution current state" in messages[2]["content"]
    assert "observations" in messages[2]["content"]

    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:task",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
    )

    assert [segment.kind for segment in segment_map.segments] == ["system_static", "system_session", "volatile_turn"]
    assert [segment.cache_role for segment in segment_map.segments] == ["cacheable_prefix", "session_stable", "volatile"]
    cache_record = PromptCachePlanner().plan(segment_map)
    assert cache_record.diagnostics["stable_prefix_segment_count"] == 2


def test_runtime_prompt_uses_assembly_projection_not_mode_instruction() -> None:
    result = RuntimeCompiler().compile_turn_action_packet(
        session_id="session:projection",
        turn_id="turn:projection",
        agent_invocation_id="aginvoke:projection",
        user_message="请帮我做一个需要交付物的小工具",
        history=[],
        available_tools=[{"tool_name": "write_file", "description": "写入文件"}],
        runtime_assembly={
            "profile": {
                "mode": "professional",
                "task_lifecycle_policy": {
                    "request_task_run": True,
                    "requires_completion_evidence": True,
                    "artifact_evidence_required": True,
                },
                "planning_policy": {"todo_required_when_task_run": True},
                "self_review_policy": {"enabled": True, "checkpoints": ["before_final"]},
                "step_summary_policy": {"enabled": True, "detail": "stepwise"},
                "permission_policy": {"permission_scope": "professional_agent_profile_ceiling"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {
                "allowed_operations": ["op.model_response", "op.write_file"],
            },
        },
    )

    system_prompt = result.packet.system_instructions
    stable_payload = json.loads(result.packet.model_messages[1]["content"].split("\n", 1)[1])
    projection = stable_payload["runtime_context"]["agent_visible_runtime_projection"]

    assert "当前 runtime 是 professional 模式" not in system_prompt
    assert "当前 runtime 是 standard 模式" not in system_prompt
    assert "当前 runtime 是 role 模式" not in system_prompt
    assert "本次运行边界" in system_prompt
    assert "可以请求正式 TaskRun" in system_prompt
    assert "最终完成声明必须基于合同、真实观察、真实产物或验证证据" in system_prompt
    assert projection["authority"] == "harness.runtime.agent_visible_runtime_projection"
    assert projection["task_lifecycle"]["request_task_run_allowed"] is True
    assert projection["task_lifecycle"]["artifact_evidence_required"] is True
    assert projection["planning"]["todo_required_when_task_run"] is True


def test_role_runtime_projection_blocks_task_run_without_mode_instruction_text() -> None:
    result = RuntimeCompiler().compile_turn_action_packet(
        session_id="session:role-projection",
        turn_id="turn:role-projection",
        agent_invocation_id="aginvoke:role-projection",
        user_message="陪我聊一下这个角色",
        history=[],
        runtime_assembly={
            "profile": {
                "mode": "role",
                "task_lifecycle_policy": {"request_task_run": False},
                "permission_policy": {"permission_scope": "role_conversation_readonly"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    system_prompt = result.packet.system_instructions
    stable_payload = json.loads(result.packet.model_messages[1]["content"].split("\n", 1)[1])
    projection = stable_payload["runtime_context"]["agent_visible_runtime_projection"]

    assert "当前 runtime 是 role 模式" not in system_prompt
    assert "本次装配不允许开启正式 TaskRun" in system_prompt
    assert projection["task_lifecycle"]["request_task_run_allowed"] is False
    assert projection["permission_boundary"]["permission_scope"] == "role_conversation_readonly"
