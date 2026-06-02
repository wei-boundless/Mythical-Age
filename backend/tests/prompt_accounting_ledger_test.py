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
from runtime.model_gateway import ModelRequestBuilder
from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan


def _model_input_text(packet) -> str:
    return "\n\n".join(str(message.get("content") or "") for message in packet.model_messages)


def _message_content_with_title(packet, title: str) -> str:
    marker = title + "\n"
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if marker in content:
            return content
    raise AssertionError(f"message title not found: {title}")


def test_prompt_accounting_ledger_records_prediction_provider_usage_and_cache(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    messages = [
        {"role": "system", "content": "你是一名可靠的执行代理。"},
        {"role": "user", "content": "hello"},
    ]
    segment_plan = _segment_plan("packet:test", "single_agent_turn", messages, ("cacheable_prefix", "volatile"))
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:test",
        session_id="session:test",
        task_run_id="taskrun:test",
        provider="openai",
        model="gpt-4.1-mini",
        messages=messages,
        segment_plan=segment_plan,
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
    segment_plan = _segment_plan(
        "packet:cache-key",
        "task_execution",
        messages,
        ("cacheable_prefix", "session_stable", "volatile"),
    )

    first = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:first",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
            segment_plan=segment_plan,
        )
    )
    second = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:second",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
            segment_plan=segment_plan,
        )
    )

    assert first.prefix_hash == second.prefix_hash
    assert first.cache_key == second.cache_key
    assert first.boundary_segment_id != second.boundary_segment_id


def test_task_execution_packet_places_stable_contract_before_volatile_state() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:test",
        task_run={
            "task_run_id": "taskrun:test",
            "title": "审查监控系统",
            "diagnostics": {
                "graph_run_id": "graph:stable",
                "executor_status": "retrying",
                "recoverable_error": "tool_failed",
                "recovery_action": "retry_with_current_file",
            },
        },
        contract={"task_run_goal": "审查并修复监控系统", "completion_criteria": ["完成真实验证"]},
        observations=[
            {
                "observation_id": "obs:1",
                "content": "latest command output",
                "structured_error": {
                    "code": "tool_http_error",
                    "message": "Fetch failed for https://example.invalid/rss.xml",
                    "retryable": False,
                    "origin": "tool_provider",
                },
            }
        ],
        execution_state={"runtime_status": "running"},
        available_tools=[
            {
                "tool_name": "read_file",
                "description": "读取文件",
                "input_schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string", "description": "要读取的路径"},
                        "encoding": {"type": "string", "default": "utf-8"},
                    },
                },
            }
        ],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.test"},
        },
    )

    messages = result.packet.model_messages
    manifest = result.packet.diagnostics["prompt_manifest"]
    assert [message["role"] for message in messages][0] == "system"
    assert [message["role"] for message in messages][-1] == "system"
    assert "Task execution action schema" in messages[1]["content"]
    model_input = _model_input_text(result.packet)
    assert "当前任务执行要求" not in model_input
    assert any("本次运行边界" in str(message.get("content") or "") for message in messages)
    current_state_content = _message_content_with_title(result.packet, "Task execution current state")
    volatile_payload = json.loads(current_state_content.split("\n", 1)[1])
    assert "task_state" in volatile_payload
    assert "observations" not in volatile_payload
    assert "execution_state" not in volatile_payload
    assert "work_history" not in volatile_payload
    assert "task_run_state" not in volatile_payload
    runtime_boundary_content = _message_content_with_title(result.packet, "Task execution runtime boundary")
    assert "Task run model-visible context" not in runtime_boundary_content
    action_schema_payload = json.loads(messages[1]["content"].split("\n", 1)[1])
    task_contract_payload = json.loads(_message_content_with_title(result.packet, "Task execution task contract").split("\n", 1)[1])
    tool_index_payload = json.loads(_message_content_with_title(result.packet, "Task execution tool index").split("\n", 1)[1])
    assert "task_run" not in task_contract_payload
    assert "graph_run_id" not in _message_content_with_title(result.packet, "Task execution task contract")
    assert "task_run_id" not in _message_content_with_title(result.packet, "Task execution task contract")
    assert action_schema_payload["schema"]["action_type"] == "respond|ask_user|tool_call|block"
    assert "public_action_state" in action_schema_payload["schema"]
    assert "task_contract_seed" not in action_schema_payload["schema"]
    assert "completion_contract" not in action_schema_payload["schema"]
    assert "permission_request" not in action_schema_payload["schema"]
    assert "runtime_profile" not in task_contract_payload["task_contract"]
    assert "created_from_packet_ref" not in task_contract_payload["task_contract"]
    assert "source_contract_ref" not in task_contract_payload["task_contract"]
    assert "origin" not in task_contract_payload["task_contract"]
    assert "graph_slot" not in task_contract_payload["task_contract"]
    assert task_contract_payload["task_contract"]["task_run_goal"] == "审查并修复监控系统"
    assert task_contract_payload["task_contract"]["completion_criteria"] == ["完成真实验证"]
    assert tool_index_payload["tool_catalog_hash"].startswith("sha256:")
    assert "input_schema" not in tool_index_payload["available_tools"][0]
    assert tool_index_payload["available_tools"][0]["input_schema_ref"].startswith("sha256:")
    assert tool_index_payload["available_tools"][0]["input_schema_summary"]["properties"]["path"] == "string"
    assert tool_index_payload["available_tools"][0]["input_schema_summary"]["required"] == ["path"]
    assert volatile_payload["task_state"]["task_run_state"]["diagnostics"] == {
        "executor_status": "retrying",
        "recoverable_error": "tool_failed",
        "recovery_action": "retry_with_current_file",
    }
    assert volatile_payload["task_state"]["latest_tool_results"][0]["structured_error"] == {
        "code": "tool_http_error",
        "message": "Fetch failed for https://example.invalid/rss.xml",
        "retryable": False,
        "origin": "tool_provider",
    }
    dynamic_report = manifest["dynamic_context_report"]
    assert dynamic_report["section_reports"]
    assert all(item["volatility_reason"] for item in dynamic_report["section_reports"])

    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:task",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=result.packet.segment_plan,
    )

    assert [segment.kind for segment in segment_map.segments] == [
        "global_static",
        "action_schema_static",
        "environment_stable",
        "artifact_scope_stable",
        "tool_index_stable",
        "task_contract_stable",
        "dynamic_projection",
        "volatile_task_state",
    ]
    assert [segment.cache_role for segment in segment_map.segments] == [
        "cacheable_prefix",
        "session_stable",
        "session_stable",
        "session_stable",
        "session_stable",
        "session_stable",
        "volatile",
        "volatile",
    ]
    assert not any(
        segment.cache_role in {"cacheable_prefix", "session_stable"}
        and dict(segment.metadata or {}).get("cache_impact") == "volatile"
        for segment in segment_map.segments
    )
    cache_record = PromptCachePlanner().plan(segment_map)
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:task",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=result.packet.segment_plan,
    )
    assert model_request.task_prefix_hash == cache_record.prefix_hash
    assert cache_record.diagnostics["prefix_key_tier"] == "task"
    assert model_request.provider_global_prefix_hash != cache_record.prefix_hash
    assert cache_record.diagnostics["stable_prefix_segment_count"] == 6
    assert cache_record.diagnostics["provider_global_prefix_segment_count"] == 1
    assert cache_record.diagnostics["task_prefix_segment_count"] == 6
    assert manifest["token_estimate"]["assembly_prompt_chars"] == manifest["token_estimate"]["prompt_chars"]
    assert manifest["token_estimate"]["model_visible_chars"] == sum(len(message["content"]) for message in messages)
    assert manifest["token_estimate"]["cacheable_prefix_chars"] > manifest["token_estimate"]["assembly_prompt_chars"]


def test_task_prompt_contract_requires_explicit_prompt_contract() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:explicit-prompt-contract",
        task_run={"task_run_id": "taskrun:explicit-prompt-contract", "title": "普通标题"},
        contract={
            "contract_id": "contract:explicit-prompt-contract",
            "task_run_goal": "普通合同目标只属于结构化合同。",
            "completion_criteria": ["普通验收只属于结构化合同"],
            "prompt_contract": {
                "role_prompt": "你是一名运行时提示审查员。",
                "task_instruction": "只审查 prompt contract 显式给出的职责。",
                "definition_of_done": ["输出审查结论"],
            },
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    model_input = _model_input_text(result.packet)
    requirement_content = next(str(message.get("content") or "") for message in result.packet.model_messages if "当前任务执行要求" in str(message.get("content") or ""))
    task_contract_content = _message_content_with_title(result.packet, "Task execution task contract")

    assert "你是一名运行时提示审查员" in requirement_content
    assert "只审查 prompt contract 显式给出的职责" in requirement_content
    assert "普通合同目标只属于结构化合同" not in requirement_content
    assert "普通验收只属于结构化合同" not in requirement_content
    assert "普通合同目标只属于结构化合同" in task_contract_content
    assert model_input.count("你是一名运行时提示审查员") == 1


def test_task_execution_stable_prefix_is_unchanged_across_runtime_state_updates() -> None:
    base_kwargs = {
        "session_id": "session:append-only",
        "task_run": {
            "task_run_id": "taskrun:append-only",
            "task_id": "task:dungeon",
            "task_contract_ref": "contract:dungeon",
            "diagnostics": {
                "graph_run_id": "graph:dungeon",
                "executor_status": "running",
                "recoverable_error": "old tool failure",
            },
        },
        "contract": {
            "contract_id": "contract:dungeon",
            "task_run_goal": "开发五层地下塔肉鸽游戏",
            "completion_criteria": ["生成可运行游戏", "完成基本验证"],
        },
        "runtime_assembly": {
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    }
    first = RuntimeCompiler().compile_task_execution_packet(
        **base_kwargs,
        invocation_index=1,
        observations=[{"observation_id": "obs:first", "content": "first observation"}],
        execution_state={"step": 1, "status": "debugging"},
    )
    second = RuntimeCompiler().compile_task_execution_packet(
        **base_kwargs,
        invocation_index=2,
        observations=[
            {"observation_id": "obs:first", "content": "first observation"},
            {"observation_id": "obs:second", "content": "second observation"},
        ],
        execution_state={"step": 2, "status": "verifying"},
    )

    first_messages = first.packet.model_messages
    second_messages = second.packet.model_messages
    assert first_messages[:-2] == second_messages[:-2]
    assert first_messages[-2] == second_messages[-2]
    assert first_messages[-1] != second_messages[-1]

    first_request = ModelRequestBuilder().build(
        request_id="modelreq:first-append-only",
        messages=first_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=first.packet.segment_plan,
    )
    second_request = ModelRequestBuilder().build(
        request_id="modelreq:second-append-only",
        messages=second_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=second.packet.segment_plan,
    )
    assert first_request.stable_prefix_hash == second_request.stable_prefix_hash
    assert first_request.diagnostics["segment_bindings_match_planned_messages"] is True
    assert second_request.diagnostics["segment_bindings_match_planned_messages"] is True


def test_model_request_reports_segment_plan_binding_mismatch() -> None:
    planned_messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "system", "content": "stable contract"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = _segment_plan(
        "packet:mismatch",
        "turn_action",
        planned_messages,
        ("cacheable_prefix", "session_stable", "volatile"),
    )
    actual_messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "system", "content": "mutated stable contract"},
        {"role": "user", "content": "current request"},
    ]

    model_request = ModelRequestBuilder().build(
        request_id="modelreq:mismatch",
        messages=actual_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
    )

    assert model_request.diagnostics["segment_bindings_match_planned_messages"] is False
    assert model_request.diagnostics["segment_binding_content_mismatch_count"] == 1
    assert model_request.segment_bindings[1].planned_model_message_hash.startswith("sha256:")
    assert model_request.segment_bindings[1].planned_model_message_hash != model_request.segment_bindings[1].request_content_hash


def test_model_request_and_segment_map_canonical_hash_ignore_diagnostic_metadata() -> None:
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    first_request = ModelRequestBuilder().build(
        request_id="modelreq:canonical:1",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"compressed_summary_hash": "sha256:a"}}},
    )
    second_request = ModelRequestBuilder().build(
        request_id="modelreq:canonical:2",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"compressed_summary_hash": "sha256:b"}}},
    )
    serializer = CanonicalPromptSerializer()
    first_map = serializer.build_segment_map(
        request_id="modelreq:canonical:1",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"compressed_summary_hash": "sha256:a"}}},
    )
    second_map = serializer.build_segment_map(
        request_id="modelreq:canonical:2",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"compressed_summary_hash": "sha256:b"}}},
    )

    assert first_request.canonical_hash == second_request.canonical_hash
    assert first_map.canonical_hash == second_map.canonical_hash


def test_prompt_accounting_marks_deepseek_reasoning_content_without_storing_raw_text() -> None:
    messages = [
        {"role": "user", "content": "Need weather."},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "hidden DeepSeek native reasoning",
            "tool_calls": [{"id": "call:1", "name": "get_weather", "args": {}}],
        },
        {"role": "tool", "tool_call_id": "call:1", "content": "Cloudy."},
    ]

    request = ModelRequestBuilder().build(
        request_id="modelreq:deepseek-reasoning-accounting",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
    )
    normalized_assistant = request.messages[1]
    normalized_json = json.dumps(normalized_assistant, ensure_ascii=False, sort_keys=True)

    assert normalized_assistant["reasoning_content_present"] is True
    assert normalized_assistant["reasoning_content_chars"] == len("hidden DeepSeek native reasoning")
    assert normalized_assistant["reasoning_content_estimated_tokens"] > 0
    assert str(normalized_assistant["reasoning_content_hash"]).startswith("sha256:")
    assert "hidden DeepSeek native reasoning" not in normalized_json

    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:deepseek-reasoning-accounting",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        model_request=request,
    )
    assistant_segment = segment_map.segments[1]

    assert assistant_segment.metadata["reasoning_content_predicted_tokens"] == normalized_assistant["reasoning_content_estimated_tokens"]
    assert assistant_segment.predicted_tokens >= normalized_assistant["reasoning_content_estimated_tokens"]


def test_runtime_prompt_uses_assembly_projection_not_mode_instruction() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:projection",
        turn_id="turn:projection",
        agent_invocation_id="aginvoke:projection",
        user_message="请帮我做一个需要交付物的小工具",
        history=[],
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "task_lifecycle_policy": {
                    "request_task_run": True,
                    "requires_completion_evidence": True,
                    "artifact_evidence_required": True,
                },
                "planning_policy": {"todo_required_when_task_run": True},
                "self_review_policy": {"enabled": True, "checkpoints": ["before_final"]},
                "step_summary_policy": {"enabled": True, "detail": "stepwise"},
                "permission_policy": {"permission_scope": "agent_profile_ceiling"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {
                "allowed_operations": ["op.model_response", "op.write_file"],
            },
            "control_capabilities": {
                "may_request_task_run": True,
                "may_control_active_work": False,
            },
        },
    )

    model_input = _model_input_text(result.packet)
    stable_payload = json.loads(result.packet.model_messages[1]["content"].split("\n", 1)[1])
    dynamic_payload = _payload_after_title(_message_content_with_title(result.packet, "Single agent turn dynamic runtime"), "Single agent turn dynamic runtime")
    projection = dynamic_payload["runtime_context"]["agent_visible_runtime_projection"]

    assert "当前 runtime 是 professional 模式" not in model_input
    assert "当前 runtime 是 standard 模式" not in model_input
    assert "当前 runtime 是 role 模式" not in model_input
    assert "本次运行边界" in model_input
    assert "可以请求进入持续处理流程" in model_input
    assert "每次输出 JSON 时必须填写 public_action_state" not in model_input
    assert "最终完成声明必须基于合同、真实观察、真实产物或验证证据" in model_input
    assert projection["authority"] == "harness.runtime.agent_visible_runtime_projection"
    assert projection["task_lifecycle"]["request_task_run_allowed"] is True
    assert projection["task_lifecycle"]["artifact_evidence_required"] is True
    assert projection["planning"]["todo_required_when_task_run"] is True


def test_runtime_projection_blocks_task_run_without_mode_instruction_text() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:conversation-projection",
        turn_id="turn:conversation-projection",
        agent_invocation_id="aginvoke:conversation-projection",
        user_message="陪我聊一下这个角色",
        history=[],
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "task_lifecycle_policy": {"request_task_run": False},
                "permission_policy": {"permission_scope": "conversation_readonly"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
            "control_capabilities": {
                "may_request_task_run": False,
                "may_control_active_work": False,
            },
        },
    )

    model_input = _model_input_text(result.packet)
    stable_payload = json.loads(result.packet.model_messages[1]["content"].split("\n", 1)[1])
    dynamic_payload = _payload_after_title(_message_content_with_title(result.packet, "Single agent turn dynamic runtime"), "Single agent turn dynamic runtime")
    projection = dynamic_payload["runtime_context"]["agent_visible_runtime_projection"]

    assert "当前 runtime 是 role 模式" not in model_input
    assert "可以请求进入持续处理流程" not in model_input
    assert projection["task_lifecycle"]["request_task_run_allowed"] is False
    assert projection["permission_boundary"]["permission_scope"] == "conversation_readonly"


def test_task_execution_public_action_state_authority_lives_in_action_schema() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-public-state",
        task_run={"task_run_id": "taskrun:task-public-state", "diagnostics": {"executor_status": "running"}},
        contract={"task_run_goal": "验证公开行动状态要求", "completion_criteria": ["完成验证"]},
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    model_input = _model_input_text(result.packet)
    action_schema_payload = json.loads(_message_content_with_title(result.packet, "Task execution action schema").split("\n", 1)[1])
    runtime_boundary_content = _message_content_with_title(result.packet, "Task execution runtime boundary")

    assert "public_action_state" in action_schema_payload["schema"]
    assert "public_progress_note" in action_schema_payload["schema"]
    assert "每次输出 JSON 时必须填写 public_action_state" not in model_input
    assert "public_progress_note 必须是 public_action_state" not in runtime_boundary_content


def test_task_execution_prompt_directs_long_artifacts_into_tool_actions() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-long-output",
        task_run={"task_run_id": "taskrun:task-long-output", "diagnostics": {"executor_status": "running"}},
        contract={
            "task_run_goal": "创建一个较长的单文件 HTML 产物",
            "completion_criteria": ["必须真实写入文件"],
            "required_artifacts": [{"path": "artifacts/game/index.html", "kind": "html_document"}],
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response", "op.write_file", "op.shell"]},
        },
    )

    model_input = _model_input_text(result.packet)

    assert "每一轮只能提交一个 action JSON" in model_input
    assert "不要在 JSON 外继续输出正文、代码块、解释或产物内容" in model_input
    assert "优先调用 write_file 或 terminal" in model_input
    assert "先写入一个完整可运行的紧凑版本" in model_input


def _segment_plan(
    packet_id: str,
    invocation_kind: str,
    messages: list[dict[str, str]],
    cache_roles: tuple[str, ...],
) -> dict[str, object]:
    return build_prompt_segment_plan(
        packet_id=packet_id,
        invocation_kind=invocation_kind,
        message_specs=[
            {
                "role": message["role"],
                "content": message["content"],
                "kind": "global_static" if index == 0 else ("volatile_user" if message["role"] == "user" else "task_stable"),
                "source_ref": f"test:{index}",
                "cache_scope": "session" if index else "global",
                "cache_role": cache_roles[index],
                "compression_role": "preserve" if cache_roles[index] != "volatile" else "summarize",
            }
            for index, message in enumerate(messages)
        ],
    ).to_dict()


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert marker in content
    return json.loads(content.split(marker, 1)[1])
