from __future__ import annotations

import json

from harness.runtime.compiler import _fixed_context_package_message_specs
from prompt_composition import build_model_message_spec
from runtime.context_management import assign_sealed_append_order
from runtime.context_management.context_assembly import classify_context_spec
from runtime.model_gateway.model_request import ModelRequestBuilder
from runtime.model_gateway.provider_payload import _short_schema_ref
from runtime.prompt_accounting.cache_planner import PromptCachePlanner
from runtime.prompt_accounting.serializer import CanonicalPromptSerializer


def _spec(*, kind: str, content: str, cache_role: str = "volatile", cache_scope: str = "none", metadata: dict | None = None) -> dict:
    return build_model_message_spec(
        role="system",
        content=content,
        kind=kind,
        source_ref=kind,
        cache_scope=cache_scope,
        cache_role=cache_role,
        compression_role="preserve",
        metadata=dict(metadata or {}),
    )


def test_context_classifier_separates_memory_context_from_dynamic_tail() -> None:
    runtime_memory = classify_context_spec({"kind": "runtime_memory_context", "cache_role": "volatile"})
    user_request = classify_context_spec({"kind": "volatile_user", "cache_role": "volatile"})
    lifecycle = classify_context_spec({"kind": "lifecycle_runtime_guidance", "cache_role": "volatile"})

    assert runtime_memory.context_cache_section == "context_append"
    assert runtime_memory.cache_role == "session_stable"
    assert user_request.context_cache_section == "context_append"
    assert lifecycle.context_cache_section == "dynamic_tail"
    assert lifecycle.cache_role == "volatile"


def test_fixed_context_order_seals_previous_context_and_keeps_dynamic_tail_last(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    specs = [
        _spec(kind="global_static", content="Global protocol", cache_role="cacheable_prefix", cache_scope="global"),
        _spec(kind="lifecycle_runtime_guidance", content="Lifecycle now"),
        _spec(kind="runtime_memory_context", content="Memory\n{\"fact\":\"remember\"}"),
        _spec(kind="volatile_user", content="Current request\n{\"text\":\"fix cache\"}", cache_role="volatile"),
        _spec(kind="read_evidence_context", content="Evidence ref\n{\"ref\":\"obs:1\"}", cache_role="session_stable", cache_scope="task"),
    ]

    first = _fixed_context_package_message_specs(
        specs,
        invocation_kind="single_agent_turn",
        sealed_context_scope="session:test",
        storage_root=backend_dir,
    )
    first_kinds = [item["kind"] for item in first]
    assert first_kinds[-1] == "lifecycle_runtime_guidance"
    assert first_kinds[:4] == ["global_static", "runtime_memory_context", "volatile_user", "read_evidence_context"]
    assert [dict(item["metadata"]).get("context_cache_section") for item in first[1:4]] == [
        "context_append",
        "context_append",
        "context_append",
    ]

    second = _fixed_context_package_message_specs(
        specs,
        invocation_kind="single_agent_turn",
        sealed_context_scope="session:test",
        storage_root=backend_dir,
    )
    assert [dict(item["metadata"]).get("context_cache_section") for item in second[1:4]] == [
        "sealed_context_prefix",
        "sealed_context_prefix",
        "sealed_context_prefix",
    ]
    assert all(dict(item["metadata"]).get("sealed_accumulated_context_order", 0) > 0 for item in second[1:4])


def test_sealed_receipt_reports_hash_change_as_structured_recovery(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    first = assign_sealed_append_order(
        storage_root=backend_dir,
        scope="single_agent_turn:session-hash",
        item_key="item:1",
        provider_visible_hash="sha256:first",
        kind="runtime_memory_context",
        source_ref="memory:test",
        receipt_authority="test",
    )
    second = assign_sealed_append_order(
        storage_root=backend_dir,
        scope="single_agent_turn:session-hash",
        item_key="item:1",
        provider_visible_hash="sha256:changed",
        kind="runtime_memory_context",
        source_ref="memory:test",
        receipt_authority="test",
    )

    assert first["order"] == 1
    assert second["order"] == 1
    assert second["integrity_status"] == "failed"
    assert second["recovery_required"] is True
    assert second["structured_failure"]["code"] == "provider_visible_hash_changed_for_append_index"


def test_provider_accounting_excludes_sidecar_and_current_context_append_from_hit_target() -> None:
    schema = {"type": "object", "properties": {"path": {"type": "string"}}}
    tool = {"name": "read_file", "description": "Read file", "schema": schema}
    tool_index_payload = {
        "available_tools": [
            {"tool_name": "read_file", "input_schema_ref": _short_schema_ref(schema)}
        ]
    }
    messages = [
        {"role": "system", "content": "Global protocol"},
        {"role": "system", "content": "Tool index\n" + json.dumps(tool_index_payload, sort_keys=True)},
        {"role": "user", "content": "Remember this new requirement"},
        {"role": "system", "content": "Lifecycle now"},
    ]
    segment_plan = {
        "segments": [
            {
                "segment_id": "seg:global",
                "kind": "global_static",
                "ordinal": 1,
                "model_message_index": 0,
                "model_message_role": "system",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "static_prefix"},
            },
            {
                "segment_id": "seg:tool-index",
                "kind": "tool_index_stable",
                "ordinal": 2,
                "model_message_index": 1,
                "model_message_role": "system",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "prefix_tier": "session",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "static_prefix"},
            },
            {
                "segment_id": "seg:user-append",
                "kind": "volatile_user",
                "ordinal": 3,
                "model_message_index": 2,
                "model_message_role": "user",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "context_append"},
            },
            {
                "segment_id": "seg:tail",
                "kind": "lifecycle_runtime_guidance",
                "ordinal": 4,
                "model_message_index": 3,
                "model_message_role": "system",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "dynamic_tail"},
            },
        ]
    }
    model_request = ModelRequestBuilder().build(
        request_id="modelreq:context-cache",
        messages=messages,
        tools=[tool],
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        segment_plan=segment_plan,
        metadata={"cache_relevant_params": {"thinking_mode": "enabled"}},
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:context-cache",
        messages=messages,
        tools=[tool],
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=segment_plan,
        model_request=model_request,
    )
    cache_record = PromptCachePlanner().plan(
        segment_map,
        provider="deepseek",
        model="deepseek-v4-flash",
        model_request=model_request,
    )
    diagnostics = dict(cache_record.diagnostics)

    assert diagnostics["provider_sidecar_tool_schema_predicted_tokens"] > 0
    assert diagnostics["stable_transport_contract_predicted_tokens"] > 0
    assert diagnostics["provider_payload_prefix_predicted_tokens"] == diagnostics["provider_payload_message_prefix_predicted_tokens"]
    assert diagnostics["context_append_prefix_predicted_tokens"] > 0
    assert diagnostics["expected_cache_read_prefix_predicted_tokens"] < diagnostics["provider_payload_prefix_predicted_tokens"]
    assert diagnostics["context_append_promoted_to_next_sealed_context"] is True


def test_deepseek_v4_reasoning_content_contract_is_provider_visible() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I need to read the file before answering.",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "content"},
    ]
    request = ModelRequestBuilder().build(
        request_id="modelreq:reasoning",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        metadata={"cache_relevant_params": {"thinking_mode": "enabled"}},
    )

    contract = request.diagnostics["provider_reasoning_contract"]
    transport_messages = request.diagnostics["provider_transport_payload"]
    assert transport_messages["messages_include_provider_reasoning_content"] is True
    assert contract["deepseek_v4_thinking_contract"] is True
    assert contract["status"] == "ok"
    assert contract["assistant_tool_call_reasoning_content_indexes"] == [0]
