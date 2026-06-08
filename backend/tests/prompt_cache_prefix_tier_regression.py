from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime.compiler import RuntimeCompiler
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from runtime.model_gateway.model_request import ModelRequestBuilder
from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    CompressionBudgetPlanner,
    PromptCacheBaselineTracker,
    PromptCachePlanner,
    PromptSegment,
    stable_text_hash,
)


def test_different_task_nodes_keep_global_prefix_but_change_task_prefix() -> None:
    compiler = RuntimeCompiler()
    assembly = {
        "profile": {"profile_ref": "main_interactive_agent"},
        "task_environment": {"environment_id": "env.general.workspace"},
    }
    first = compiler.compile_task_execution_packet(
        session_id="session:tier",
        task_run={"task_run_id": "taskrun:tier:a", "task_id": "task:tier:a"},
        contract={"contract_id": "contract:tier:a", "task_run_goal": "执行 A 节点", "completion_criteria": ["A 完成"]},
        observations=[],
        runtime_assembly=assembly,
    ).packet
    second = compiler.compile_task_execution_packet(
        session_id="session:tier",
        task_run={"task_run_id": "taskrun:tier:b", "task_id": "task:tier:b"},
        contract={"contract_id": "contract:tier:b", "task_run_goal": "执行 B 节点", "completion_criteria": ["B 完成"]},
        observations=[],
        runtime_assembly=assembly,
    ).packet

    first_request = ModelRequestBuilder().build(
        request_id="modelreq:tier:a",
        messages=first.model_messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=first.segment_plan,
    )
    second_request = ModelRequestBuilder().build(
        request_id="modelreq:tier:b",
        messages=second.model_messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=second.segment_plan,
    )

    assert first_request.provider_global_prefix_hash == second_request.provider_global_prefix_hash
    assert first_request.task_prefix_hash != second_request.task_prefix_hash
    assert first_request.stable_prefix_hash != second_request.stable_prefix_hash


def test_runtime_compiler_rejects_invalid_prompt_pack_ref() -> None:
    compiler = RuntimeCompiler()

    with pytest.raises(ValueError, match="runtime prompt pack assembly rejected refs"):
        compiler.compile_task_execution_packet(
            session_id="session:bad-pack",
            task_run={"task_run_id": "taskrun:bad-pack", "task_id": "task:bad-pack"},
            contract={"contract_id": "contract:bad-pack", "task_run_goal": "执行", "completion_criteria": ["完成"]},
            observations=[],
            runtime_assembly={
                "profile": {
                    "profile_ref": "main_interactive_agent",
                    "prompt_pack_refs": ["runtime.pack.missing"],
                },
                "task_environment": {"environment_id": "env.general.workspace"},
            },
        )


def test_task_execution_runtime_instance_context_stays_out_of_stable_prefix() -> None:
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:runtime-instance",
        task_run={
            "task_run_id": "taskrun:runtime-instance",
            "task_id": "task:runtime-instance",
            "task_contract_ref": "rtobj:contract:runtime-instance",
            "diagnostics": {
                "origin": {
                    "origin_ref": "model-action:runtime-instance",
                    "parent_run_ref": "turn:runtime-instance",
                },
                "executor_status": "waiting_executor",
            },
        },
        contract={
            "contract_id": "contract:runtime-instance",
            "task_run_goal": "执行真实任务",
            "completion_criteria": ["任务完成"],
        },
        observations=[],
        runtime_assembly={
            "profile": {"profile_ref": "main_interactive_agent"},
            "task_environment": {"environment_id": "env.general.workspace"},
        },
    ).packet

    stable_indices = [
        int(segment["model_message_index"])
        for segment in packet.segment_plan["segments"]
        if segment.get("cache_role") in {"cacheable_prefix", "session_stable"}
    ]
    assert stable_indices
    stable_text = "\n".join(packet.model_messages[index]["content"] for index in stable_indices)
    assert "taskrun:runtime-instance" not in stable_text


def test_prompt_cache_planner_uses_longest_stable_prefix_key_for_automatic_cache() -> None:
    messages = [
        {"role": "system", "content": "global runtime"},
        {"role": "system", "content": "task contract A"},
        {"role": "user", "content": "current state"},
    ]
    segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "model_message_index": 1,
                "kind": "task_stable",
                "source_ref": "contract.test",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
            },
            {
                "model_message_index": 2,
                "kind": "volatile_user",
                "source_ref": "state.test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ]
    }
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:planner-tier",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=segment_plan,
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:planner-tier",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=segment_plan,
        model_request=model_request,
    )

    cache_record = PromptCachePlanner().plan(segment_map, provider="deepseek", model="deepseek-v4-flash")

    assert cache_record.prefix_hash == model_request.task_prefix_hash
    assert cache_record.prefix_hash == model_request.stable_prefix_hash
    assert cache_record.prefix_hash != model_request.provider_global_prefix_hash
    assert cache_record.diagnostics["prefix_key_tier"] == "task"
    assert cache_record.diagnostics["provider_global_prefix_segment_count"] == 1
    assert cache_record.diagnostics["task_prefix_segment_count"] == 2


def test_prompt_cache_planner_carries_prompt_manifest_cache_fingerprints() -> None:
    messages = [
        {"role": "system", "content": "global runtime"},
        {"role": "user", "content": "current state"},
    ]
    segment_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "model_message_index": 1,
                "kind": "volatile_user",
                "source_ref": "state.test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ]
    }
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:planner-manifest-fingerprints",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=segment_plan,
        metadata={
            "prompt_manifest": {
                "manifest_id": "rtprompt:cache-fingerprint",
                "cache_boundary": {
                    "assembly_request_fingerprint": "sha256:assembly-request",
                    "section_fingerprint": "sha256:sections",
                },
                "prompt_composition": {
                    "manifest_id": "pcomp:cache-fingerprint",
                    "diagnostics": {
                        "cache_boundary": {
                            "status": "warning",
                            "prefix_tier_sequence": ["provider_global", "volatile"],
                            "layer_cache_policy_violations": [{"code": "slot_prefix_tier_outside_layer_policy"}],
                            "segment_prefix_violations": [
                                {"code": "stable_segment_after_volatile_boundary"},
                                {"code": "stable_segment_after_volatile_boundary"},
                            ],
                        }
                    },
                },
            }
        },
    )

    cache_record = PromptCachePlanner().plan(segment_map, provider="deepseek", model="deepseek-v4-flash")

    assert cache_record.diagnostics["prompt_manifest_ref"] == "rtprompt:cache-fingerprint"
    assert cache_record.diagnostics["assembly_request_fingerprint"] == "sha256:assembly-request"
    assert cache_record.diagnostics["section_fingerprint"] == "sha256:sections"
    assert cache_record.diagnostics["prompt_composition_manifest_ref"] == "pcomp:cache-fingerprint"
    assert cache_record.diagnostics["prompt_composition_cache_boundary_status"] == "warning"
    assert cache_record.diagnostics["prompt_composition_prefix_tier_sequence"] == ["provider_global", "volatile"]
    assert cache_record.diagnostics["prompt_composition_layer_violation_count"] == 1
    assert cache_record.diagnostics["prompt_composition_segment_violation_count"] == 2


def test_compression_budget_reports_tiered_cache_impact() -> None:
    decision = CompressionBudgetPlanner().plan(
        [
            PromptSegment(
                segment_id="seg:global",
                request_id="modelreq:budget-tier",
                cache_role="volatile",
                prefix_tier="provider_global",
                compression_role="summarize",
                predicted_tokens=100,
            ),
            PromptSegment(
                segment_id="seg:task",
                request_id="modelreq:budget-tier",
                cache_role="volatile",
                prefix_tier="task",
                compression_role="summarize",
                predicted_tokens=100,
            ),
            PromptSegment(
                segment_id="seg:tail",
                request_id="modelreq:budget-tier",
                cache_role="volatile",
                prefix_tier="volatile",
                compression_role="summarize",
                predicted_tokens=800,
            ),
        ],
        context_window_tokens=500,
        reserved_output_tokens=100,
    )

    assert decision.cache_impact == "global_invalidated"
    assert decision.cache_impact_tiers["provider_global"] == "global_invalidated"
    assert decision.cache_impact_tiers["task"] == "task_rebuilt"
    assert decision.cache_impact_tiers["volatile"] == "volatile_preserved"


def test_stable_prefix_rejects_runtime_instance_fields() -> None:
    with pytest.raises(ValueError, match="runtime instance fields"):
        build_prompt_segment_plan(
            packet_id="packet:bad-runtime-field",
            invocation_kind="task_execution",
            message_specs=[
                {
                    "role": "system",
                    "content": "Stable\n" + json.dumps({"task_run_id": "taskrun:hidden"}, ensure_ascii=False),
                    "kind": "task_stable",
                    "cache_scope": "task",
                    "cache_role": "session_stable",
                    "prefix_tier": "task",
                    "compression_role": "preserve",
                }
            ],
        )


def test_stable_prefix_allows_runtime_field_names_inside_protocol_schema() -> None:
    plan = build_prompt_segment_plan(
        packet_id="packet:protocol-schema",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": "Stable\n"
                + json.dumps(
                    {
                        "schema": {"task_run_id": "runtime may require this field name"},
                        "available_tools": [
                            {
                                "tool_name": "read_task",
                                "input_schema_summary": {
                                    "properties": {"task_run_id": "string"},
                                    "required": ["task_run_id"],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                "kind": "task_stable",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
            }
        ],
    )

    assert plan.segments[0].prefix_tier == "task"


def test_session_prefix_allows_task_field_names_inside_tool_schema_summary() -> None:
    plan = build_prompt_segment_plan(
        packet_id="packet:tool-schema-session",
        invocation_kind="single_agent_turn",
        message_specs=[
            {
                "role": "system",
                "content": "Stable\n"
                + json.dumps(
                    {
                        "available_tools": [
                            {
                                "tool_name": "image_generate",
                                "input_schema_summary": {
                                    "properties": {"task_id": "string", "prompt": "string"},
                                    "required": ["task_id", "prompt"],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                "kind": "turn_stable",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "prefix_tier": "session",
                "compression_role": "preserve",
            }
        ],
    )

    assert plan.segments[0].prefix_tier == "session"


def test_provider_global_prefix_rejects_task_semantic_fields() -> None:
    with pytest.raises(ValueError, match="task semantic fields"):
        build_prompt_segment_plan(
            packet_id="packet:bad-semantic-field",
            invocation_kind="task_execution",
            message_specs=[
                {
                    "role": "system",
                    "content": "Global\n" + json.dumps({"task_id": "task:semantic"}, ensure_ascii=False),
                    "kind": "global_static",
                    "cache_scope": "global",
                    "cache_role": "cacheable_prefix",
                    "prefix_tier": "provider_global",
                    "compression_role": "preserve",
                }
            ],
        )


def test_tool_schema_cache_role_derives_from_matching_stable_tool_index() -> None:
    input_schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    messages = [
        {"role": "system", "content": "stable runtime"},
        {
            "role": "system",
            "content": "Task execution tool index\n"
            + json.dumps(
                {
                    "available_tools": [
                        {
                            "tool_name": "read_file",
                            "input_schema_ref": _short_schema_ref(input_schema),
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        },
        {"role": "user", "content": "current request"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": input_schema,
            },
        }
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:provider-tool-schema-cache",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": messages[0]["content"],
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": messages[1]["content"],
                "kind": "tool_index_stable",
                "source_ref": "task_execution_tool_index",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": messages[2]["content"],
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    model_request = ModelRequestBuilder().build(
        request_id="modelreq:provider-tool-schema-cache",
        messages=messages,
        tools=tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
    )
    provider_tool_segment = next(
        segment
        for segment in model_request.provider_payload_manifest.segments
        if segment.transport_location == "tools"
    )
    assert provider_tool_segment.kind == "tool_schema_catalog"
    assert provider_tool_segment.cache_role == "session_stable"
    assert provider_tool_segment.prefix_tier == "task"

    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:provider-tool-schema-cache",
        messages=messages,
        tools=tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
        model_request=model_request,
    )

    tool_schema = next(segment for segment in segment_map.segments if segment.kind == "tool_schema_catalog")
    assert tool_schema.cache_role == "session_stable"
    assert tool_schema.prefix_tier == "task"
    assert tool_schema.source == "task_execution_tool_index"
    assert tool_schema.metadata["tool_schema_cache_decision"] == "derived_from_stable_tool_index"
    assert tool_schema.metadata["provider_payload_manifest_ref"] == model_request.provider_payload_manifest.manifest_id


def test_prompt_cache_planner_uses_provider_payload_boundary_for_stable_tool_schema() -> None:
    input_schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    changed_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "encoding": {"type": "string"}},
        "required": ["path"],
    }
    messages = [
        {"role": "system", "content": "stable runtime"},
        {
            "role": "system",
            "content": "Task execution tool index\n"
            + json.dumps(
                {
                    "available_tools": [
                        {
                            "tool_name": "read_file",
                            "input_schema_ref": _short_schema_ref(input_schema),
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        },
        {"role": "user", "content": "current request"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": input_schema,
            },
        }
    ]
    changed_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": changed_schema,
            },
        }
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:provider-payload-cache-boundary",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": messages[0]["content"],
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": messages[1]["content"],
                "kind": "tool_index_stable",
                "source_ref": "task_execution_tool_index",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": messages[2]["content"],
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:provider-payload-cache-boundary",
        messages=messages,
        tools=tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:provider-payload-cache-boundary",
        messages=messages,
        tools=tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
        model_request=model_request,
    )
    cache_record = PromptCachePlanner().plan(
        segment_map,
        provider="deepseek",
        model="deepseek-v4-pro",
        model_request=model_request,
    )

    assert cache_record.prefix_hash == model_request.provider_payload_task_prefix_hash
    assert cache_record.prefix_hash != model_request.task_prefix_hash
    assert cache_record.diagnostics["prefix_hash_source"] == "provider_payload_manifest"
    assert cache_record.diagnostics["provider_payload_tool_prefix_segment_count"] == 1
    assert cache_record.diagnostics["tool_catalog_hash"] == model_request.tool_catalog_hash

    changed_request = ModelRequestBuilder().build(
        request_id="modelreq:provider-payload-cache-boundary:changed",
        messages=messages,
        tools=changed_tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
    )
    assert changed_request.task_prefix_hash == model_request.task_prefix_hash
    assert changed_request.tool_catalog_hash != model_request.tool_catalog_hash
    assert changed_request.provider_payload_task_prefix_hash != model_request.provider_payload_task_prefix_hash

    changed_segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:provider-payload-cache-boundary:changed",
        messages=messages,
        tools=changed_tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
        model_request=changed_request,
    )
    tracker = PromptCacheBaselineTracker()
    first_baseline = tracker.build_active_record(
        segment_map=segment_map,
        model_request=model_request,
        previous_records=[],
        created_at=1.0,
    )
    second_baseline = tracker.build_active_record(
        segment_map=changed_segment_map,
        model_request=changed_request,
        previous_records=[first_baseline],
        created_at=2.0,
    )
    assert "tool_catalog" in second_baseline.changed_tiers
    assert "provider_payload" in second_baseline.changed_tiers


def test_tool_schema_stays_never_cache_when_provider_tools_do_not_match_tool_index() -> None:
    input_schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    messages = [
        {"role": "system", "content": "stable runtime"},
        {
            "role": "system",
            "content": "Task execution tool index\n"
            + json.dumps(
                {
                    "available_tools": [
                        {
                            "tool_name": "write_file",
                            "input_schema_ref": _short_schema_ref(input_schema),
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        },
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": input_schema,
            },
        }
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:provider-tool-schema-cache-mismatch",
        invocation_kind="task_execution",
        message_specs=[
            {
                "role": "system",
                "content": messages[0]["content"],
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": messages[1]["content"],
                "kind": "tool_index_stable",
                "source_ref": "task_execution_tool_index",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
            },
        ],
    ).to_dict()

    model_request = ModelRequestBuilder().build(
        request_id="modelreq:provider-tool-schema-cache-mismatch",
        messages=messages,
        tools=tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:provider-tool-schema-cache-mismatch",
        messages=messages,
        tools=tools,
        provider="deepseek",
        model="deepseek-v4-pro",
        segment_plan=segment_plan,
        model_request=model_request,
    )

    tool_schema = next(segment for segment in segment_map.segments if segment.kind == "tool_schema_catalog")
    assert tool_schema.cache_role == "never_cache"
    assert tool_schema.prefix_tier == "none"
    assert tool_schema.metadata["tool_schema_cache_reason"] == "provider_tools_do_not_match_tool_index"


def _short_schema_ref(schema: dict[str, object]) -> str:
    digest = stable_text_hash(json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "sha256:" + digest.removeprefix("sha256:")[:10]
