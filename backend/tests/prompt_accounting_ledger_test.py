from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptAccountingLedger,
    PromptCacheBaselineTracker,
    PromptCachePlanner,
    PromptCacheRecord,
    PromptSegment,
    PromptSegmentMap,
    extract_provider_usage,
)
from runtime.model_gateway import ModelRequestBuilder
from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.environment_prompt_controller import build_base_prompt_mount_plan, prompt_mount_plan_for_invocation
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_library.environment_lifecycle_prompts import ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT


def _model_input_text(packet) -> str:
    return "\n\n".join(str(message.get("content") or "") for message in packet.model_messages)


def _message_content_with_title(packet, title: str) -> str:
    marker = title + "\n"
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if marker in content:
            return content
    raise AssertionError(f"message title not found: {title}")


def _message_payload_with_title(packet, title: str) -> dict[str, object]:
    content = _message_content_with_title(packet, title)
    return json.loads(content.split("\n", 1)[1])


def _message_content_for_source(packet, source_ref: str) -> str:
    for segment in packet.segment_plan["segments"]:
        if segment["source_ref"] != source_ref:
            continue
        return packet.model_messages[segment["model_message_index"]]["content"]
    raise AssertionError(f"segment source not found: {source_ref}")


def _segment_by_source(packet, source_ref: str) -> dict[str, object]:
    for segment in packet.segment_plan["segments"]:
        if segment["source_ref"] == source_ref:
            return dict(segment)
    raise AssertionError(f"segment source not found: {source_ref}")


def _segment_by_kind(packet, kind: str) -> dict[str, object]:
    for segment in packet.segment_plan["segments"]:
        if segment["kind"] == kind:
            return dict(segment)
    raise AssertionError(f"segment kind not found: {kind}")


def _stable_prompt_text(packet) -> str:
    stable_indexes = {
        int(segment["model_message_index"])
        for segment in packet.segment_plan["segments"]
        if segment.get("cache_role") in {"cacheable_prefix", "session_stable"}
    }
    return "\n\n".join(
        str(message.get("content") or "")
        for index, message in enumerate(packet.model_messages)
        if index in stable_indexes
    )


def _cache_record_for_packet(packet, *, request_id: str = "modelreq:prompt-matrix"):
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id=request_id,
        messages=packet.model_messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=packet.segment_plan,
    )
    return PromptCachePlanner().plan(segment_map)


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


def test_prompt_accounting_ledger_filters_session_scoped_reads_before_json_projection(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:target:provider_usage",
            request_id="modelreq:target",
            session_id="session:target",
            run_id="run:target",
            source="provider_usage",
            prompt_tokens=100,
            total_tokens=110,
            created_at=1.0,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:other:provider_usage",
            request_id="modelreq:other",
            session_id="session:other",
            run_id="run:other",
            source="provider_usage",
            prompt_tokens=900,
            total_tokens=990,
            created_at=2.0,
        )
    )
    ledger.record_prompt_cache(
        PromptCacheRecord(
            cache_record_id="pcache:target",
            request_id="modelreq:target",
            session_id="session:target",
            run_id="run:target",
            status="hit",
            cached_tokens=80,
            cache_savings_tokens=80,
            created_at=1.0,
        )
    )
    ledger.record_prompt_cache(
        PromptCacheRecord(
            cache_record_id="pcache:other",
            request_id="modelreq:other",
            session_id="session:other",
            run_id="run:other",
            status="hit",
            cached_tokens=800,
            cache_savings_tokens=800,
            created_at=2.0,
        )
    )

    session_summary = ledger.summarize_session("session:target")
    run_summary = ledger.summarize_run("run:target")

    assert session_summary["total_tokens"] == 110
    assert session_summary["cache_savings_tokens"] == 80
    assert run_summary["total_tokens"] == 110
    assert [record.request_id for record in ledger.list_prompt_cache(session_id="session:target")] == ["modelreq:target"]


def test_prompt_accounting_ledger_summary_index_serves_scoped_summaries_when_raw_ledger_is_large(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:indexed:local_prediction",
            request_id="modelreq:indexed",
            task_run_id="taskrun:indexed",
            session_id="session:indexed",
            source="local_prediction",
            prompt_tokens=300,
            total_tokens=300,
            created_at=1.0,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:indexed:provider_usage",
            request_id="modelreq:indexed",
            task_run_id="taskrun:indexed",
            session_id="session:indexed",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            created_at=2.0,
            diagnostics={"large": "diagnostics should not be copied into summary index"},
        )
    )
    ledger.record_prompt_cache(
        PromptCacheRecord(
            cache_record_id="pcache:indexed",
            request_id="modelreq:indexed",
            task_run_id="taskrun:indexed",
            session_id="session:indexed",
            status="hit",
            cached_tokens=50,
            cache_savings_tokens=50,
            created_at=2.0,
            diagnostics={"large": "diagnostics should not be copied into summary index"},
        )
    )
    (ledger.ledger_dir / "segment_maps.jsonl").write_text("x" * (ledger.SUMMARY_SCAN_MAX_BYTES + 1), encoding="utf-8")

    indexed = ledger.summarize_tasks(["taskrun:indexed", "taskrun:missing"])
    summaries = ledger.list_run_summaries(limit=10)

    assert indexed["taskrun:indexed"]["total_tokens"] == 120
    assert indexed["taskrun:indexed"]["predicted_total_tokens"] == 300
    assert indexed["taskrun:indexed"]["cache_savings_tokens"] == 50
    assert indexed["taskrun:missing"]["record_count"] == 0
    assert summaries[0]["summary"]["total_tokens"] == 120
    summary_payload = next(
        payload
        for payload in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in ledger.summary_index_dir.glob("*.json")
        )
        if payload["key"] == "taskrun:indexed"
    )
    assert "diagnostics" not in next(iter(summary_payload["usage_records"].values()))
    assert "diagnostics" not in next(iter(summary_payload["cache_records"].values()))


def test_prompt_accounting_retention_compacts_old_details_into_token_stats(tmp_path) -> None:
    now = 2_000_000.0
    old = now - 20 * 24 * 60 * 60
    hot = now - 2 * 24 * 60 * 60
    ledger = PromptAccountingLedger(tmp_path)
    segment = PromptSegment(
        segment_id="seg:old",
        request_id="modelreq:old",
        task_run_id="taskrun:old",
        session_id="session:old",
        created_at=old,
    )
    ledger.record_segment_map(
        PromptSegmentMap(
            request_id="modelreq:old",
            task_run_id="taskrun:old",
            session_id="session:old",
            segments=(segment,),
            created_at=old,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:old:local_prediction",
            request_id="modelreq:old",
            task_run_id="taskrun:old",
            session_id="session:old",
            source="local_prediction",
            prompt_tokens=300,
            total_tokens=300,
            created_at=old,
            diagnostics={"large": "must not be retained"},
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:old:provider_usage",
            request_id="modelreq:old",
            task_run_id="taskrun:old",
            session_id="session:old",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            created_at=old + 1,
            diagnostics={"large": "must not be retained"},
        )
    )
    ledger.record_prompt_cache(
        PromptCacheRecord(
            cache_record_id="pcache:old",
            request_id="modelreq:old",
            task_run_id="taskrun:old",
            session_id="session:old",
            status="hit",
            cached_tokens=50,
            cache_savings_tokens=50,
            created_at=old + 1,
            diagnostics={"large": "must not be retained"},
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:hot:provider_usage",
            request_id="modelreq:hot",
            task_run_id="taskrun:hot",
            session_id="session:hot",
            source="provider_usage",
            prompt_tokens=30,
            completion_tokens=10,
            total_tokens=40,
            created_at=hot,
        )
    )

    preview = ledger.build_retention_preview(cutoff_days=15, now=now)
    dry_run = ledger.compact_before(cutoff_days=15, dry_run=True, now=now)

    assert preview["files"]["token_usage.jsonl"]["compactable_rows"] == 2
    assert preview["files"]["prompt_cache.jsonl"]["compactable_rows"] == 1
    assert preview["files"]["segment_maps.jsonl"]["compactable_rows"] == 1
    assert preview["files"]["segments.jsonl"]["compactable_rows"] == 1
    assert dry_run["mode"] == "dry_run"
    assert len(ledger.list_token_usage(task_run_id="taskrun:old")) == 2
    assert len(ledger.list_segment_maps(task_run_id="taskrun:old")) == 1

    result = ledger.compact_before(cutoff_days=15, dry_run=False, now=now)
    retained_stats = json.loads(ledger.retained_token_stats_path.read_text(encoding="utf-8"))
    retained_old = next(item for item in retained_stats["run_summaries"] if item["key"] == "taskrun:old")

    assert result["mode"] == "execute"
    assert result["rewrite_results"]["deleted_counts"]["token_usage"] == 2
    assert result["rewrite_results"]["deleted_counts"]["prompt_cache"] == 1
    assert ledger.list_token_usage(task_run_id="taskrun:old") == []
    assert ledger.list_prompt_cache(task_run_id="taskrun:old") == []
    assert ledger.list_segment_maps(task_run_id="taskrun:old") == []
    assert ledger.summarize_task("taskrun:old")["total_tokens"] == 120
    assert ledger.summarize_task("taskrun:old")["predicted_total_tokens"] == 300
    assert ledger.summarize_task("taskrun:old")["cache_savings_tokens"] == 50
    assert ledger.summarize_task("taskrun:hot")["total_tokens"] == 40
    assert retained_old["summary"]["total_tokens"] == 120
    assert "usage_records" not in retained_old
    assert "diagnostics" not in json.dumps(retained_stats, ensure_ascii=False)
    assert {item["key"] for item in ledger.list_run_summaries(limit=10)} >= {"taskrun:old", "taskrun:hot"}


def test_prompt_accounting_retention_keeps_protected_old_details(tmp_path) -> None:
    now = 2_000_000.0
    old = now - 20 * 24 * 60 * 60
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:active:provider_usage",
            request_id="modelreq:active",
            task_run_id="taskrun:active",
            session_id="session:active",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            created_at=old,
        )
    )

    result = ledger.compact_before(
        cutoff_days=15,
        dry_run=False,
        now=now,
        protected_task_run_ids=["taskrun:active"],
        protected_session_ids=["session:active"],
    )

    assert result["files"]["token_usage.jsonl"]["compactable_rows"] == 0
    assert result["retained_token_stats"]["run_summary_count"] == 0
    assert ledger.list_token_usage(task_run_id="taskrun:active")[-1].total_tokens == 120
    assert ledger.summarize_task("taskrun:active")["total_tokens"] == 120


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
    cache_read_only_response = SimpleNamespace(
        content="ok",
        usage_metadata={
            "input_tokens": 1000,
            "output_tokens": 5,
            "input_token_details": {"cache_read": 125},
        },
    )

    openai_usage = extract_provider_usage(openai_response, request_id="modelreq:openai")
    anthropic_usage = extract_provider_usage(anthropic_response, request_id="modelreq:anthropic")
    deepseek_usage = extract_provider_usage(deepseek_response, request_id="modelreq:deepseek")
    cache_read_only_usage = extract_provider_usage(cache_read_only_response, request_id="modelreq:cache-read")

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
    assert deepseek_usage.cache_miss_tokens == 33000
    assert deepseek_usage.diagnostics["provider_cache_hit_rate"] == 0.1165
    assert deepseek_usage.diagnostics["provider_cache_hit_rate_source"] == "provider_hit_miss_tokens"
    assert deepseek_usage.completion_tokens == 4
    assert deepseek_usage.total_tokens == 37356
    assert cache_read_only_usage is not None
    assert cache_read_only_usage.prompt_tokens == 1000
    assert cache_read_only_usage.cached_tokens == 125
    assert cache_read_only_usage.cache_miss_tokens == 0
    assert cache_read_only_usage.diagnostics["provider_cache_hit_rate"] == 0.125
    assert cache_read_only_usage.diagnostics["provider_cache_hit_rate_source"] == "prompt_tokens"
    assert cache_read_only_usage.diagnostics["prompt_cache_read_ratio"] == 0.125


def test_prompt_cache_key_is_stable_across_request_ids_for_same_prefix() -> None:
    serializer = CanonicalPromptSerializer()
    messages = [
        {"role": "system", "content": "你是一名可靠的执行代理。"},
        {"role": "system", "content": "Task execution stable contract\n{\"schema\":{\"action_type\":\"respond\"}}"},
        {"role": "user", "content": "Task execution current state\n{\"observations\":[]}"},
    ]
    first_segment_plan = _segment_plan(
        "packet:cache-key:first",
        "task_execution",
        messages,
        ("cacheable_prefix", "session_stable", "volatile"),
    )
    second_segment_plan = _segment_plan(
        "packet:cache-key:second",
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
            segment_plan=first_segment_plan,
        )
    )
    second = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:second",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
            segment_plan=second_segment_plan,
        )
    )

    assert first.prefix_hash == second.prefix_hash
    assert first.cache_key == second.cache_key
    assert first.boundary_segment_id != second.boundary_segment_id

    first_model_request = ModelRequestBuilder().build(
        request_id="modelreq:first",
        provider="deepseek",
        model="deepseek-v4-pro",
        messages=messages,
        segment_plan=first_segment_plan,
        metadata={"cache_relevant_params": {"response_format": {"type": "json_object"}}},
    )
    second_model_request = ModelRequestBuilder().build(
        request_id="modelreq:second",
        provider="deepseek",
        model="deepseek-v4-pro",
        messages=messages,
        segment_plan=second_segment_plan,
        metadata={"cache_relevant_params": {"response_format": {"type": "json_object"}}},
    )
    first_provider_record = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:first",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
            segment_plan=first_segment_plan,
            model_request=first_model_request,
        ),
        provider="deepseek",
        model="deepseek-v4-pro",
        model_request=first_model_request,
    )
    second_provider_record = PromptCachePlanner().plan(
        serializer.build_segment_map(
            request_id="modelreq:second",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            messages=messages,
            segment_plan=second_segment_plan,
            model_request=second_model_request,
        ),
        provider="deepseek",
        model="deepseek-v4-pro",
        model_request=second_model_request,
    )

    assert first_provider_record.prefix_hash == second_provider_record.prefix_hash
    assert first_provider_record.cache_key == second_provider_record.cache_key
    assert first_provider_record.boundary_segment_id != second_provider_record.boundary_segment_id
    assert first_provider_record.diagnostics["cache_sensitive_params_hash"] == second_provider_record.diagnostics["cache_sensitive_params_hash"]


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
    model_input = _model_input_text(result.packet)
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

    segment_kinds = [segment.kind for segment in segment_map.segments]
    for required_kind in (
        "global_static",
        "action_schema_static",
        "environment_stable",
        "project_instructions_stable",
        "tool_index_stable",
        "task_contract_stable",
        "task_runtime_boundary_dynamic",
        "volatile_task_state",
    ):
        assert required_kind in segment_kinds
    assert segment_kinds.index("global_static") < segment_kinds.index("action_schema_static")
    assert segment_kinds.index("action_schema_static") < segment_kinds.index("environment_stable")
    assert segment_kinds.index("environment_stable") < segment_kinds.index("task_runtime_boundary_dynamic")
    cache_role_by_kind = {segment.kind: segment.cache_role for segment in segment_map.segments}
    prefix_tier_by_kind = {segment.kind: segment.prefix_tier for segment in segment_map.segments}
    assert cache_role_by_kind["global_static"] == "cacheable_prefix"
    assert cache_role_by_kind["environment_stable"] == "session_stable"
    assert cache_role_by_kind["task_contract_stable"] == "session_stable"
    assert cache_role_by_kind["task_runtime_boundary_dynamic"] == "volatile"
    assert cache_role_by_kind["volatile_task_state"] == "volatile"
    assert prefix_tier_by_kind["global_static"] == "provider_global"
    assert prefix_tier_by_kind["environment_stable"] == "session"
    assert prefix_tier_by_kind["task_runtime_boundary_dynamic"] == "volatile"
    assert not any(
        segment.cache_role in {"cacheable_prefix", "session_stable"}
        and dict(segment.metadata or {}).get("cache_impact") == "volatile"
        for segment in segment_map.segments
    )
    project_segment = next(segment for segment in segment_map.segments if segment.kind == "project_instructions_stable")
    assert project_segment.prefix_tier == "session"
    assert dict(project_segment.metadata or {})["cache_impact"] == "project_prefix_stable"
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
    assert cache_record.diagnostics["provider_global_prefix_segment_count"] == 1
    assert manifest["token_estimate"]["assembly_prompt_chars"] == manifest["token_estimate"]["prompt_chars"]
    assert manifest["token_estimate"]["model_visible_chars"] == sum(len(message["content"]) for message in messages)
    assert manifest["token_estimate"]["cacheable_prefix_chars"] > manifest["token_estimate"]["assembly_prompt_chars"]


def test_task_execution_memory_payload_stays_volatile_when_memory_lifecycle_mounts() -> None:
    base_kwargs = {
        "session_id": "session:memory-prefix",
        "task_run": {"task_run_id": "taskrun:memory-prefix", "diagnostics": {"executor_status": "running"}},
        "contract": {
            "task_run_goal": "检查 prompt cache 稳定前缀",
            "completion_criteria": ["memory payload 不进入 environment stable prompt"],
            "plan_ref": "plan:memory-prefix",
        },
        "observations": [],
        "execution_state": {"runtime_status": "running"},
            "runtime_assembly": {
                "profile": {"profile_ref": "main_interactive_agent"},
                "task_environment": {
                    "environment_id": "env.coding.vibe_workspace",
                    "environment_boundary": {
                        "lifecycle_prompt_defaults": ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT[
                            "env.coding.vibe_workspace"
                        ],
                    },
                },
            },
        }
    without_memory = RuntimeCompiler().compile_task_execution_packet(**base_kwargs)
    with_memory = RuntimeCompiler().compile_task_execution_packet(
        **base_kwargs,
        memory_context={
            "model_visible_sections": {
                "relevant_durable_context": ["durable memory marker for prefix regression"],
            },
            "selected_sections": ["relevant_durable_context"],
            "memory_runtime_view_ref": "memview:prefix-regression",
        },
    )

    without_environment = _segment_by_kind(without_memory.packet, "environment_stable")
    with_environment = _segment_by_kind(with_memory.packet, "environment_stable")
    assert without_environment["cache_role"] == "session_stable"
    assert with_environment["cache_role"] == "session_stable"

    environment_content = _message_content_with_title(with_memory.packet, "Task execution environment boundary")
    runtime_boundary_content = _message_content_with_title(with_memory.packet, "Task execution runtime boundary")
    without_refs = without_memory.packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_prompt_refs"]
    with_refs = with_memory.packet.diagnostics["prompt_manifest"]["prompt_mount_plan"]["lifecycle_prompt_refs"]

    assert "environment.coding.lifecycle.memory_read_context" not in without_refs
    assert "environment.coding.lifecycle.memory_read_context" in with_refs
    assert "durable memory marker for prefix regression" not in environment_content
    assert "durable memory marker for prefix regression" in runtime_boundary_content
    runtime_segment = _segment_by_kind(with_memory.packet, "task_runtime_boundary_dynamic")
    assert runtime_segment["cache_role"] == "volatile"
    assert runtime_segment["prefix_tier"] == "volatile"


def test_lifecycle_prompt_selection_changes_only_on_memory_context_structure() -> None:
    lifecycle_defaults = ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT["env.coding.vibe_workspace"]
    base_plan = build_base_prompt_mount_plan(
        selected_environment={
            "environment_id": "env.coding.vibe_workspace",
            "environment_boundary": {
                "lifecycle_prompt_defaults": lifecycle_defaults,
            },
        }
    )
    without_memory = prompt_mount_plan_for_invocation(
        base_plan,
        invocation_kind="task_execution",
        allowed_actions=("tool_call",),
        memory_context=None,
    )
    with_memory = prompt_mount_plan_for_invocation(
        base_plan,
        invocation_kind="task_execution",
        allowed_actions=("tool_call",),
        memory_context={
            "model_visible_sections": {
                "relevant_durable_context": ["memory marker"],
            }
        },
    )
    with_different_memory_text = prompt_mount_plan_for_invocation(
        base_plan,
        invocation_kind="task_execution",
        allowed_actions=("tool_call",),
        memory_context={
            "model_visible_sections": {
                "relevant_durable_context": ["different volatile memory marker"],
            }
        },
    )

    assert lifecycle_defaults["memory_read_context"] not in without_memory.lifecycle_prompt_refs
    assert lifecycle_defaults["memory_read_context"] in with_memory.lifecycle_prompt_refs
    assert with_memory.lifecycle_prompt_refs == with_different_memory_text.lifecycle_prompt_refs
    assert with_memory.lifecycle_prompt_keys == with_different_memory_text.lifecycle_prompt_keys


def test_lifecycle_selector_omits_state_slots_without_structural_state() -> None:
    lifecycle_defaults = ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT["env.general.workspace"]
    base_plan = build_base_prompt_mount_plan(
        selected_environment={
            "environment_id": "env.general.workspace",
            "environment_boundary": {
                "lifecycle_prompt_defaults": lifecycle_defaults,
            },
        }
    )

    plan = prompt_mount_plan_for_invocation(
        base_plan,
        invocation_kind="single_agent_turn",
        allowed_actions=("respond", "ask_user", "request_task_run", "tool_call", "block"),
        visible_tools=({"tool_name": "read_file"},),
        active_work_context=None,
        memory_context=None,
        session_context={},
    )

    assert plan.lifecycle_prompt_keys == (
        "context_intake",
        "request_judgment",
        "environment_capability_alignment",
        "action_selection",
        "task_run_handoff",
        "tool_dispatch",
        "finalization",
    )
    assert "work_relation" not in plan.lifecycle_prompt_keys
    assert "user_steer_contract_revision" not in plan.lifecycle_prompt_keys
    assert "memory_read_context" not in plan.lifecycle_prompt_keys
    assert "compaction_handoff" not in plan.lifecycle_prompt_keys
    assert list(plan.lifecycle_trigger_reasons) == list(plan.lifecycle_prompt_refs)


def test_lifecycle_selector_mounts_state_slots_from_structural_state() -> None:
    lifecycle_defaults = ENVIRONMENT_LIFECYCLE_PROMPT_DEFAULTS_BY_ENVIRONMENT["env.general.workspace"]
    base_plan = build_base_prompt_mount_plan(
        selected_environment={
            "environment_id": "env.general.workspace",
            "environment_boundary": {
                "lifecycle_prompt_defaults": lifecycle_defaults,
            },
        }
    )

    plan = prompt_mount_plan_for_invocation(
        base_plan,
        invocation_kind="single_agent_turn",
        allowed_actions=("respond", "ask_user", "request_task_run", "tool_call", "active_work_control", "block"),
        visible_tools=({"tool_name": "read_file"},),
        active_work_context={"task_run_id": "taskrun:active", "status": "running"},
        memory_context={"model_visible_sections": {"relevant_durable_context": ["memory marker"]}},
        session_context={"compaction": {"handoff_ref": "compaction:1"}},
    )

    assert "work_relation" in plan.lifecycle_prompt_keys
    assert "active_work_control" in plan.lifecycle_prompt_keys
    assert "user_steer_contract_revision" in plan.lifecycle_prompt_keys
    assert "memory_read_context" in plan.lifecycle_prompt_keys
    assert "compaction_handoff" in plan.lifecycle_prompt_keys


def test_task_execution_replay_entries_are_volatile_before_current_state() -> None:
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
    first_replay_messages = [
        message for message in first_messages if str(message["content"]).startswith("Task execution replayed state evidence")
    ]
    second_replay_messages = [
        message for message in second_messages if str(message["content"]).startswith("Task execution replayed state evidence")
    ]
    assert len(first_replay_messages) == 1
    assert len(second_replay_messages) == 2
    assert first_replay_messages[0] == second_replay_messages[0]

    second_kinds = [segment["kind"] for segment in second.packet.segment_plan["segments"]]
    assert second_kinds.index("task_state_replay_entry") < second_kinds.index("volatile_task_state")
    for segment in second.packet.segment_plan["segments"]:
        if segment["kind"] in {"task_state_replay_entry", "task_runtime_boundary_dynamic", "volatile_task_state"}:
            assert segment["cache_role"] == "volatile"

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
    assert first_request.provider_global_prefix_hash == second_request.provider_global_prefix_hash
    assert first_request.session_prefix_hash == second_request.session_prefix_hash
    assert first_request.task_prefix_hash == second_request.task_prefix_hash
    assert first_request.stable_prefix_hash == second_request.stable_prefix_hash
    assert "task_state_replay_entry" not in second_request.provider_payload_manifest.cache_boundary["tier_prefixes"]["task"]["kinds"]
    assert "task_runtime_boundary_dynamic" not in second_request.provider_payload_manifest.cache_boundary["tier_prefixes"]["task"]["kinds"]
    assert first_request.diagnostics["segment_bindings_match_planned_messages"] is True
    assert second_request.diagnostics["segment_bindings_match_planned_messages"] is True


def test_task_execution_replay_prefix_keeps_observations_beyond_current_state_cursor() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:replay-prefix-budget",
        invocation_index=3,
        task_run={
            "task_run_id": "taskrun:replay-prefix-budget",
            "task_id": "task:replay-prefix-budget",
            "task_contract_ref": "contract:replay-prefix-budget",
            "diagnostics": {"executor_status": "running"},
        },
        contract={
            "contract_id": "contract:replay-prefix-budget",
            "task_run_goal": "验证 replay 前缀不会被 current state cursor 截断",
            "completion_criteria": ["replay prefix keeps older observations"],
        },
        observations=[
            {
                "observation_id": f"obs:{index:02d}",
                "payload": {
                    "result_envelope": {
                        "tool_name": "read_file",
                        "status": "ok",
                        "summary": f"read result {index}",
                        "text": f"read result {index}",
                    }
                },
            }
            for index in range(1, 11)
        ],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    )

    replay_sources = [
        segment["source_ref"]
        for segment in result.packet.segment_plan["segments"]
        if segment["kind"] == "task_state_replay_entry"
    ]
    volatile_payload = _message_payload_with_title(result.packet, "Task execution current state")
    latest_cursor_results = volatile_payload["task_state"]["latest_tool_results"]

    assert replay_sources[0] == "task_state_replay:obs:01"
    assert replay_sources[-1] == "task_state_replay:obs:10"
    assert len(replay_sources) == 10
    assert [item["observation_ref"] for item in latest_cursor_results] == ["obs:09", "obs:10"]


def test_task_execution_replay_entries_keep_source_content_stable_when_new_failure_is_projected_first() -> None:
    base_kwargs = {
        "session_id": "session:stable-replay-order",
        "task_run": {
            "task_run_id": "taskrun:stable-replay-order",
            "task_id": "task:stable-replay-order",
            "task_contract_ref": "contract:stable-replay-order",
            "diagnostics": {"executor_status": "running"},
        },
        "contract": {
            "contract_id": "contract:stable-replay-order",
            "task_run_goal": "验证 replay 稳定前缀",
            "completion_criteria": ["稳定段只追加"],
        },
        "runtime_assembly": {
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    }
    old_result = {
        "observation_ref": "toolobs:path-exists",
        "tool_name": "path_exists",
        "status": "ok",
        "summary": "false",
        "event_offset": 20,
    }
    new_failure = {
        "observation_ref": "rtobs:model-action-invalid",
        "tool_name": "model_action_protocol",
        "status": "error",
        "summary": "model action request failed protocol validation",
        "error": {"code": "model_action_invalid", "message": "invalid action", "retryable": True},
        "event_offset": 30,
    }
    first = RuntimeCompiler().compile_task_execution_packet(
        **base_kwargs,
        invocation_index=1,
        observations=[],
        execution_state={"system_projection": {"last_action_receipts": [old_result]}},
    )
    second = RuntimeCompiler().compile_task_execution_packet(
        **base_kwargs,
        invocation_index=2,
        observations=[],
        execution_state={
            "system_projection": {
                "last_action_receipts": [new_failure, old_result],
                "active_failures": [new_failure],
            }
        },
    )

    old_source = "task_state_replay:toolobs:path-exists"
    new_source = "task_state_replay:rtobs:model-action-invalid"
    first_old_content = _message_content_for_source(first.packet, old_source)
    second_old_content = _message_content_for_source(second.packet, old_source)
    assert first_old_content == second_old_content

    second_sources = [
        segment["source_ref"]
        for segment in second.packet.segment_plan["segments"]
        if segment["kind"] == "task_state_replay_entry"
    ]
    assert second_sources.index(old_source) < second_sources.index(new_source)


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
        metadata={"prompt_manifest": {"context_window": {"context_recovery_package_hash": "sha256:a"}}},
    )
    second_request = ModelRequestBuilder().build(
        request_id="modelreq:canonical:2",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"context_recovery_package_hash": "sha256:b"}}},
    )
    serializer = CanonicalPromptSerializer()
    first_map = serializer.build_segment_map(
        request_id="modelreq:canonical:1",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"context_recovery_package_hash": "sha256:a"}}},
    )
    second_map = serializer.build_segment_map(
        request_id="modelreq:canonical:2",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-pro",
        metadata={"prompt_manifest": {"context_window": {"context_recovery_package_hash": "sha256:b"}}},
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

    assert projection["authority"] == "harness.runtime.agent_visible_runtime_projection"
    assert projection["model_decision_contract"]["authority"] == "harness.runtime.model_decision_contract"
    assert projection["model_decision_contract"]["prompt_authority"] == "developer_prompt_contract"
    assert projection["model_decision_contract"]["task_entry_rule"]["must_choose_request_task_run_when_task_entry_conditions_hold"] is True
    task_entry_rule = projection["model_decision_contract"]["task_entry_rule"]
    assert any("审查、评估、排查" in str(item) and "多文件链路" in str(item) for item in task_entry_rule["task_entry_conditions"])
    assert "不要用连续读取大量文件来代替 request_task_run" in task_entry_rule["single_turn_tool_call_boundary"]
    assert projection["service_surface"]["authority"] == "harness.runtime.service_surface"
    assert projection["execution_boundary"]["authority"] == "harness.runtime.execution_boundary"
    assert projection["execution_boundary"]["safety_authority"] == "runtime.tooling.supervisor"
    assert projection["task_lifecycle"]["request_task_run_allowed"] is True
    assert projection["task_lifecycle"]["artifact_evidence_required"] is True
    assert projection["planning"]["todo_required_when_task_run"] is True


def test_single_turn_task_scoped_tool_routes_are_dynamic_not_tool_index() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:task-memory-route",
        turn_id="turn:task-memory-route",
        agent_invocation_id="aginvoke:task-memory-route",
        user_message="结合之前留下的记忆，为我梳理一份新的升级计划",
        history=[],
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "task_lifecycle_policy": {"request_task_run": True},
                "permission_policy": {"permission_scope": "agent_profile_ceiling"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "available_tools": [
                {"tool_name": "agent_todo", "operation_id": "op.agent_todo", "owner_scope": "state"},
                {"tool_name": "memory_search", "operation_id": "op.memory_read", "owner_scope": "task_memory"},
                {"tool_name": "read_file", "operation_id": "op.read_file", "owner_scope": "none"},
            ],
            "operation_authorization": {
                "allowed_operations": ["op.model_response", "op.agent_todo", "op.memory_read", "op.read_file"],
            },
            "control_capabilities": {
                "may_call_tools": True,
                "may_request_task_run": True,
                "may_control_active_work": False,
            },
        },
    )

    tool_index = _message_payload_with_title(result.packet, "Single agent turn tool index")
    dynamic_payload = _payload_after_title(
        _message_content_with_title(result.packet, "Single agent turn dynamic runtime"),
        "Single agent turn dynamic runtime",
    )
    projection = dynamic_payload["runtime_context"]["agent_visible_runtime_projection"]
    routes = projection["tool_boundary"]["task_scoped_tool_routes"]
    unmounted = {
        item["tool_name"]: item
        for item in projection["service_surface"]["unmounted_services"]
    }
    tool_names = [item["tool_name"] for item in tool_index["available_tools"]]
    stable_boundary = _message_content_with_title(result.packet, "Single agent turn stable boundary")

    assert tool_names == ["read_file"]
    assert routes == [
        {
            "tool_name": "agent_todo",
            "operation_id": "op.agent_todo",
            "owner_scope": "state",
            "required_action": "request_task_run",
        },
        {
            "tool_name": "memory_search",
            "operation_id": "op.memory_read",
            "owner_scope": "task_memory",
            "required_action": "request_task_run",
        }
    ]
    assert "agent_todo" not in json.dumps(tool_index, ensure_ascii=False)
    assert unmounted["agent_todo"]["category"] == "requires_task_run"
    assert unmounted["agent_todo"]["required_action"] == "request_task_run"
    assert unmounted["memory_search"]["category"] == "requires_task_run"
    assert "agent_todo" not in stable_boundary
    assert "agent_todo" in _message_content_with_title(result.packet, "Single agent turn dynamic runtime")
    assert "memory_search" in _message_content_with_title(result.packet, "Single agent turn dynamic runtime")
    assert "request_task_run" in _message_content_with_title(result.packet, "Single agent turn dynamic runtime")


def test_real_task_prompt_assembly_keeps_prompt_service_and_safety_boundaries_separate() -> None:
    result = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:real-task-control-chain",
        turn_id="turn:real-task-control-chain",
        agent_invocation_id="aginvoke:real-task-control-chain",
        user_message="开始执行 110 计划书，优化 prompts 装配和控制链路，确保控制精准、运行顺畅、覆盖全面。",
        history=[
            {
                "role": "assistant",
                "content": "已完成计划书，下一步可以按计划实施。",
            }
        ],
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "task_lifecycle_policy": {
                    "request_task_run": True,
                    "requires_completion_evidence": True,
                },
                "planning_policy": {"todo_required_when_task_run": True},
                "permission_policy": {"permission_scope": "agent_profile_ceiling"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "available_tools": [
                {"tool_name": "agent_todo", "operation_id": "op.agent_todo", "owner_scope": "state"},
                {"tool_name": "read_file", "operation_id": "op.read_file", "owner_scope": "none"},
                {"tool_name": "write_file", "operation_id": "op.write_file", "owner_scope": "none"},
            ],
            "operation_authorization": {
                "allowed_operations": ["op.model_response", "op.agent_todo", "op.read_file", "op.write_file"],
            },
            "control_capabilities": {
                "may_call_tools": True,
                "may_request_task_run": True,
                "may_control_active_work": False,
            },
        },
    )

    model_input = _model_input_text(result.packet)
    dynamic_payload = _payload_after_title(
        _message_content_with_title(result.packet, "Single agent turn dynamic runtime"),
        "Single agent turn dynamic runtime",
    )
    projection = dynamic_payload["runtime_context"]["agent_visible_runtime_projection"]
    decision_contract = projection["model_decision_contract"]
    service_surface = projection["service_surface"]
    execution_boundary = projection["execution_boundary"]

    assert decision_contract["prompt_authority"] == "developer_prompt_contract"
    assert "request_task_run" in decision_contract["semantic_actions"]
    assert decision_contract["task_entry_rule"]["must_choose_request_task_run_when_task_entry_conditions_hold"] is True
    assert any(
        "审查、评估、排查" in str(item) and "多文件链路" in str(item)
        for item in decision_contract["task_entry_rule"]["task_entry_conditions"]
    )
    assert "不要用连续读取大量文件来代替 request_task_run" in decision_contract["task_entry_rule"]["single_turn_tool_call_boundary"]
    assert service_surface["unmounted_services"][0]["category"] == "requires_task_run"
    assert service_surface["unmounted_services"][0]["required_action"] == "request_task_run"
    assert execution_boundary["safety_authority"] == "runtime.tooling.supervisor"
    assert projection["authority"] == "harness.runtime.agent_visible_runtime_projection"
    assert service_surface["authority"] == "harness.runtime.service_surface"
    assert ("Prompt " + "不能强制") not in model_input
    assert "latest resumable executor checkpoint" not in model_input


def test_single_turn_prompt_cache_keeps_current_request_out_of_stable_prefix() -> None:
    runtime_assembly = {
        "profile": {
            "profile_ref": "main_interactive_agent",
            "task_lifecycle_policy": {"request_task_run": True},
            "permission_policy": {"permission_scope": "agent_profile_ceiling"},
        },
        "task_environment": {"environment_id": "env.general.workspace"},
        "available_tools": [
            {"tool_name": "read_file", "operation_id": "op.read_file", "owner_scope": "none"},
        ],
        "operation_authorization": {"allowed_operations": ["op.model_response", "op.read_file"]},
        "control_capabilities": {"may_call_tools": True, "may_request_task_run": True},
    }
    first = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:cache-current-request",
        turn_id="turn:cache-current-request:1",
        agent_invocation_id="aginvoke:cache-current-request:1",
        user_message="开始执行 110 计划书。",
        history=[],
        runtime_assembly=runtime_assembly,
    )
    second = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:cache-current-request",
        turn_id="turn:cache-current-request:2",
        agent_invocation_id="aginvoke:cache-current-request:2",
        user_message="启动同一个优化计划，但先检查 prompt cache。",
        history=[],
        runtime_assembly=runtime_assembly,
    )

    first_cache = _cache_record_for_packet(first.packet, request_id="modelreq:cache-current-request:1")
    second_cache = _cache_record_for_packet(second.packet, request_id="modelreq:cache-current-request:2")

    assert _segment_by_source(first.packet, "single_agent_turn_runtime_delta")["cache_scope"] == "none"
    assert _segment_by_source(first.packet, "single_agent_turn_current_request")["cache_scope"] == "none"
    assert "开始执行 110 计划书" not in _stable_prompt_text(first.packet)
    assert "启动同一个优化计划" not in _stable_prompt_text(second.packet)
    assert first_cache.prefix_hash == second_cache.prefix_hash


def test_active_work_prompt_cache_keeps_current_work_state_volatile() -> None:
    runtime_assembly = {
        "profile": {
            "profile_ref": "main_interactive_agent",
            "task_lifecycle_policy": {"request_task_run": True},
            "permission_policy": {"permission_scope": "agent_profile_ceiling"},
        },
        "task_environment": {"environment_id": "env.general.workspace"},
        "control_capabilities": {"may_request_task_run": True, "may_control_active_work": True},
    }
    base_active_work = {
        "status": "running",
        "control_state": "running",
        "user_visible_goal": "修复 prompt 控制链路。",
        "resumable": True,
        "running": True,
        "continuation_kind": "same_run_resume",
    }
    first = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:cache-active-work",
        turn_id="turn:cache-active-work:1",
        agent_invocation_id="aginvoke:cache-active-work:1",
        user_message="继续。",
        history=[],
        active_work_context={**base_active_work, "latest_progress": "已完成第一段 prompt 审查。"},
        runtime_assembly=runtime_assembly,
    )
    second = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:cache-active-work",
        turn_id="turn:cache-active-work:2",
        agent_invocation_id="aginvoke:cache-active-work:2",
        user_message="继续。",
        history=[],
        active_work_context={**base_active_work, "latest_progress": "已完成第二段 cache 审查。"},
        runtime_assembly=runtime_assembly,
    )

    first_dynamic = _payload_after_title(
        _message_content_with_title(first.packet, "Single agent turn dynamic runtime"),
        "Single agent turn dynamic runtime",
    )
    first_cache = _cache_record_for_packet(first.packet, request_id="modelreq:cache-active-work:1")
    second_cache = _cache_record_for_packet(second.packet, request_id="modelreq:cache-active-work:2")

    assert first_dynamic["active_work_context"]["latest_progress"] == "已完成第一段 prompt 审查。"
    assert _segment_by_source(first.packet, "single_agent_turn_runtime_delta")["cache_scope"] == "none"
    assert "已完成第一段 prompt 审查" not in _stable_prompt_text(first.packet)
    assert "已完成第二段 cache 审查" not in _stable_prompt_text(second.packet)
    assert first_cache.prefix_hash == second_cache.prefix_hash
    semantic_actions = first_dynamic["runtime_context"]["agent_visible_runtime_projection"]["model_decision_contract"]["semantic_actions"]
    assert "active_work_control" not in semantic_actions


def test_plan_mode_prompt_cache_changes_with_permission_boundary() -> None:
    base_assembly = {
        "profile": {
            "profile_ref": "main_interactive_agent",
            "task_lifecycle_policy": {"request_task_run": True},
            "permission_policy": {"permission_scope": "agent_profile_ceiling"},
        },
        "task_environment": {"environment_id": "env.general.workspace"},
        "available_tools": [
            {"tool_name": "read_file", "operation_id": "op.read_file", "owner_scope": "none"},
            {"tool_name": "write_file", "operation_id": "op.write_file", "owner_scope": "none"},
        ],
        "operation_authorization": {"allowed_operations": ["op.model_response", "op.read_file", "op.write_file"]},
        "control_capabilities": {"may_call_tools": True, "may_request_task_run": True},
    }
    default_packet = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:cache-plan-mode",
        turn_id="turn:cache-plan-mode:default",
        agent_invocation_id="aginvoke:cache-plan-mode:default",
        user_message="检查方案并开始改。",
        history=[],
        runtime_assembly={**base_assembly, "permission_mode": "default"},
    )
    plan_packet = RuntimeCompiler().compile_single_agent_turn_packet(
        session_id="session:cache-plan-mode",
        turn_id="turn:cache-plan-mode:plan",
        agent_invocation_id="aginvoke:cache-plan-mode:plan",
        user_message="检查方案并开始改。",
        history=[],
        runtime_assembly={**base_assembly, "permission_mode": "plan"},
    )

    default_cache = _cache_record_for_packet(default_packet.packet, request_id="modelreq:cache-plan-mode:default")
    plan_cache = _cache_record_for_packet(plan_packet.packet, request_id="modelreq:cache-plan-mode:plan")
    plan_input = _model_input_text(plan_packet.packet)
    plan_projection = _payload_after_title(
        _message_content_with_title(plan_packet.packet, "Single agent turn dynamic runtime"),
        "Single agent turn dynamic runtime",
    )["runtime_context"]["agent_visible_runtime_projection"]

    assert default_cache.prefix_hash != plan_cache.prefix_hash
    assert plan_projection["planning"]["plan_mode_active"] is True
    assert plan_projection["execution_boundary"]["permission_mode"] == "plan"
    assert "permission_mode" in plan_input
    assert _segment_by_source(plan_packet.packet, "single_agent_turn_runtime_delta")["cache_scope"] == "none"


def test_task_execution_prompt_matrix_has_no_task_entry_conflict_and_keeps_state_volatile() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:task-exec-matrix",
        task_run={
            "task_run_id": "taskrun:prompt-matrix",
            "title": "执行 110 控制链路优化",
            "diagnostics": {"executor_epoch": 1, "executor_status": "running"},
        },
        contract={
            "task_run_goal": "执行 110 控制链路优化",
            "completion_criteria": ["prompt 装配矩阵通过", "cache 分区正确"],
            "working_scope": {"target_objects": ["backend/harness/runtime/compiler.py"]},
        },
        observations=[
            {"observation_id": "obs:prompt-matrix:1", "content": "已完成 admission 分类。"},
        ],
        execution_state={
            "runtime_status": "running",
            "system_projection": {
                "pending_user_steers": [
                    {
                        "steer_id": "steer:cache",
                        "task_run_id": "taskrun:prompt-matrix",
                        "content": "把 prompt cache 也纳入检查。",
                    }
                ]
            },
        },
        available_tools=[
            {"tool_name": "agent_todo", "operation_id": "op.agent_todo", "owner_scope": "state"},
            {"tool_name": "read_file", "operation_id": "op.read_file", "owner_scope": "none"},
            {"tool_name": "write_file", "operation_id": "op.write_file", "owner_scope": "none"},
        ],
        runtime_assembly={
            "profile": {
                "profile_ref": "main_interactive_agent",
                "task_lifecycle_policy": {"requires_completion_evidence": True},
                "permission_policy": {"permission_scope": "task_run_execution"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {
                "allowed_operations": ["op.model_response", "op.agent_todo", "op.read_file", "op.write_file"],
            },
        },
    )

    runtime_payload = _payload_after_title(
        _message_content_with_title(result.packet, "Task execution runtime boundary"),
        "Task execution runtime boundary",
    )
    projection = runtime_payload["runtime_context"]
    decision_contract = projection["model_decision_contract"]
    mounted_tool_names = {item["tool_name"] for item in projection["service_surface"]["mounted_tools"]}
    stable_text = _stable_prompt_text(result.packet)

    assert decision_contract["semantic_actions"] == ["respond", "ask_user", "tool_call", "block"]
    assert "request_task_run" not in decision_contract["semantic_actions"]
    assert "agent_todo" in mounted_tool_names
    assert not any(
        item["tool_name"] == "agent_todo" and item["category"] == "requires_task_run"
        for item in projection["service_surface"]["unmounted_services"]
    )
    assert _segment_by_kind(result.packet, "task_runtime_boundary_dynamic")["cache_scope"] == "none"
    assert _segment_by_kind(result.packet, "volatile_task_state")["cache_scope"] == "none"
    assert _segment_by_kind(result.packet, "user_steering_updates")["cache_scope"] == "none"
    assert _segment_by_kind(result.packet, "task_contract_stable")["cache_scope"] == "task"
    assert "把 prompt cache 也纳入检查" not in stable_text
    assert "已完成 admission 分类" not in stable_text


def test_observation_followup_prompt_matrix_keeps_tool_observations_volatile() -> None:
    runtime_assembly = {
        "profile": {
            "profile_ref": "main_interactive_agent",
            "task_lifecycle_policy": {"request_task_run": True},
            "permission_policy": {"permission_scope": "agent_profile_ceiling"},
        },
        "task_environment": {"environment_id": "env.general.workspace"},
        "available_tools": [
            {"tool_name": "read_file", "operation_id": "op.read_file", "owner_scope": "none"},
            {"tool_name": "write_file", "operation_id": "op.write_file", "owner_scope": "none"},
        ],
        "operation_authorization": {"allowed_operations": ["op.model_response", "op.read_file", "op.write_file"]},
        "control_capabilities": {"may_call_tools": True, "may_request_task_run": True},
    }
    first = RuntimeCompiler().compile_observation_followup_packet(
        session_id="session:observation-followup-matrix",
        turn_id="turn:observation-followup-matrix:1",
        agent_invocation_id="aginvoke:observation-followup-matrix:1",
        user_message="继续分析工具结果。",
        history=[{"role": "user", "content": "先读文件。"}],
        observations=[
            {
                "observation_id": "obs:followup:read",
                "tool_name": "read_file",
                "status": "ok",
                "content": "第一轮读取结果：prompt A。",
            }
        ],
        runtime_assembly=runtime_assembly,
    )
    second = RuntimeCompiler().compile_observation_followup_packet(
        session_id="session:observation-followup-matrix",
        turn_id="turn:observation-followup-matrix:1",
        agent_invocation_id="aginvoke:observation-followup-matrix:2",
        user_message="继续分析工具结果。",
        history=[{"role": "user", "content": "先读文件。"}],
        observations=[
            {
                "observation_id": "obs:followup:search",
                "tool_name": "search_text",
                "status": "ok",
                "content": "第二轮搜索结果：prompt cache B。",
            }
        ],
        runtime_assembly=runtime_assembly,
    )

    dynamic_payload = _payload_after_title(
        _message_content_with_title(first.packet, "Observation followup dynamic runtime"),
        "Observation followup dynamic runtime",
    )
    current_request_payload = _payload_after_title(
        _message_content_with_title(first.packet, "Observation followup current request"),
        "Observation followup current request",
    )
    projection = dynamic_payload["runtime_context"]["agent_visible_runtime_projection"]
    first_cache = _cache_record_for_packet(first.packet, request_id="modelreq:observation-followup-matrix:1")
    second_cache = _cache_record_for_packet(second.packet, request_id="modelreq:observation-followup-matrix:2")
    stable_text = _stable_prompt_text(first.packet) + "\n" + _stable_prompt_text(second.packet)

    assert projection["model_decision_contract"]["prompt_authority"] == "developer_prompt_contract"
    assert projection["service_surface"]["authority"] == "harness.runtime.service_surface"
    assert projection["execution_boundary"]["safety_authority"] == "runtime.tooling.supervisor"
    assert _segment_by_source(first.packet, "agent_visible_runtime_projection")["cache_scope"] == "none"
    assert _segment_by_source(first.packet, "observation_followup_current_request")["cache_scope"] == "none"
    assert current_request_payload["observations"]["latest_observations"][0]["observation_id"] == "obs:followup:read"
    assert "第一轮读取结果" not in stable_text
    assert "第二轮搜索结果" not in stable_text
    assert first_cache.prefix_hash == second_cache.prefix_hash


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
    reporting = action_schema_payload["schema"]["public_response_obligation"]["tool_observation_reporting"]
    assert any("多个工具批次" in item for item in reporting["must_explain_when"])
    assert "不允许长时间任务只剩工具列表" in reporting["explanation_shape"]


def test_prompt_cache_baseline_tracks_memory_tier_and_reset_generation(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    tracker = PromptCacheBaselineTracker()
    serializer = CanonicalPromptSerializer()
    first_messages = [
        {"role": "system", "content": "global runtime"},
        {"role": "system", "content": "Session memory\n用户强调当前会话要保护 cache。"},
        {"role": "system", "content": "task contract"},
        {"role": "user", "content": "current request"},
    ]
    second_messages = [
        first_messages[0],
        {"role": "system", "content": "Session memory\n用户强调当前会话要保护 cache，并且 compact 后要 reset baseline。"},
        first_messages[2],
        first_messages[3],
    ]
    first_plan = _baseline_segment_plan("packet:baseline:1", first_messages)
    second_plan = _baseline_segment_plan("packet:baseline:2", second_messages)
    first_request = ModelRequestBuilder().build(
        request_id="modelreq:baseline:1",
        messages=first_messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=first_plan,
    )
    first_map = serializer.build_segment_map(
        request_id="modelreq:baseline:1",
        session_id="session:baseline",
        task_run_id="taskrun:baseline",
        provider="deepseek",
        model="deepseek-v4-flash",
        messages=first_messages,
        segment_plan=first_plan,
        model_request=first_request,
        created_at=1.0,
        metadata={"source": "turn_action"},
    )
    first_baseline = tracker.build_active_record(
        segment_map=first_map,
        model_request=first_request,
        previous_records=[],
        created_at=1.0,
    )
    ledger.record_prompt_cache_baseline(first_baseline)

    second_request = ModelRequestBuilder().build(
        request_id="modelreq:baseline:2",
        messages=second_messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=second_plan,
    )
    second_map = serializer.build_segment_map(
        request_id="modelreq:baseline:2",
        session_id="session:baseline",
        task_run_id="taskrun:baseline",
        provider="deepseek",
        model="deepseek-v4-flash",
        messages=second_messages,
        segment_plan=second_plan,
        model_request=second_request,
        created_at=2.0,
        metadata={"source": "turn_action"},
    )
    second_baseline = tracker.build_active_record(
        segment_map=second_map,
        model_request=second_request,
        previous_records=ledger.list_prompt_cache_baselines(task_run_id="taskrun:baseline"),
        created_at=2.0,
    )
    ledger.record_prompt_cache_baseline(second_baseline)
    reset = ledger.reset_prompt_cache_baseline(
        request_id="pcachebaseline-reset:test",
        task_run_id="taskrun:baseline",
        session_id="session:baseline",
        reason="context_compaction:full_compact",
        reset_ref="compact-receipt:test",
        created_at=3.0,
    )
    third_baseline = tracker.build_active_record(
        segment_map=second_map,
        model_request=second_request,
        previous_records=ledger.list_prompt_cache_baselines(task_run_id="taskrun:baseline"),
        created_at=4.0,
    )

    assert first_baseline.diagnostics["baseline_segments"]["memory"]["segment_count"] == 1
    assert first_baseline.provider_global_prefix_hash
    assert first_baseline.session_prefix_hash
    assert first_baseline.task_prefix_hash
    assert "memory" in second_baseline.changed_tiers
    assert second_baseline.previous_baseline_ref == first_baseline.baseline_id
    assert reset.status == "invalidated"
    assert reset.previous_baseline_ref == second_baseline.baseline_id
    assert third_baseline.generation == reset.generation
    assert third_baseline.previous_baseline_ref == ""
    assert third_baseline.diagnostics["reset_seen"] is True


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


def _baseline_segment_plan(packet_id: str, messages: list[dict[str, str]]) -> dict[str, object]:
    specs = [
        {
            "role": messages[0]["role"],
            "content": messages[0]["content"],
            "kind": "global_static",
            "source_ref": "runtime.global",
            "cache_scope": "global",
            "cache_role": "cacheable_prefix",
            "prefix_tier": "provider_global",
            "compression_role": "preserve",
        },
        {
            "role": messages[1]["role"],
            "content": messages[1]["content"],
            "kind": "session_memory_stable",
            "source_ref": "memory.session_emphasis",
            "cache_scope": "session",
            "cache_role": "session_stable",
            "prefix_tier": "session",
            "compression_role": "preserve",
        },
        {
            "role": messages[2]["role"],
            "content": messages[2]["content"],
            "kind": "task_stable",
            "source_ref": "contract.task",
            "cache_scope": "task",
            "cache_role": "session_stable",
            "prefix_tier": "task",
            "compression_role": "preserve",
        },
        {
            "role": messages[3]["role"],
            "content": messages[3]["content"],
            "kind": "volatile_user",
            "source_ref": "turn.current",
            "cache_scope": "none",
            "cache_role": "volatile",
            "prefix_tier": "volatile",
            "compression_role": "summarize",
        },
    ]
    return build_prompt_segment_plan(
        packet_id=packet_id,
        invocation_kind="turn_action",
        message_specs=specs,
    ).to_dict()


def _payload_after_title(content: str, title: str) -> dict[str, object]:
    marker = title + "\n"
    assert marker in content
    return json.loads(content.split(marker, 1)[1])
