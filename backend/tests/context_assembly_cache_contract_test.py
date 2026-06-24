from __future__ import annotations

import json

import pytest

from harness.runtime.compiler import _fixed_context_package_message_specs
from harness.loop.single_agent_turn import (
    _append_tool_followup_context_boundary,
    _ordered_tool_followup_prompt_messages,
    _single_agent_turn_followup_message_spec,
    _single_agent_turn_followup_segment_plan,
    _annotate_single_agent_followup_segment_plan,
    _validate_single_agent_followup_tail_order,
)
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_composition import build_model_message_spec
from runtime.context_management import (
    PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS,
    assemble_provider_visible_context_specs,
    confirm_provider_visible_context_entries,
    load_provider_visible_context_ledger,
)
from runtime.context_management.context_assembly import classify_context_spec, is_sealable_context_spec
from runtime.model_gateway.provider_cache_policy import ProviderCachePolicyResolver
from runtime.model_gateway.model_request import ModelRequestBuilder
from runtime.model_gateway.provider_payload import _short_schema_ref
from runtime.prompt_accounting.cache_planner import PromptCachePlanner
from runtime.prompt_accounting.models import ModelTokenUsageRecord
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


def _confirm_pending_specs(specs: list[dict], *, backend_dir, request_id: str = "modelreq:test-confirm") -> None:
    refs = [
        dict(dict(item.get("metadata") or {}))
        for item in list(specs or [])
        if str(dict(item.get("metadata") or {}).get("provider_visible_context_ledger_commit_stage") or "") == "provider_success_required"
    ]
    if refs:
        confirm_provider_visible_context_entries(refs, default_storage_root=backend_dir, request_id=request_id)


def test_context_classifier_separates_memory_context_from_dynamic_tail() -> None:
    runtime_memory = classify_context_spec({"kind": "runtime_memory_context", "cache_role": "volatile"})
    user_request = classify_context_spec({"kind": "current_turn_user_context", "cache_role": "volatile"})
    action_contract = classify_context_spec({"kind": "single_agent_turn_followup_action_contract", "cache_role": "session_stable"})
    lifecycle = classify_context_spec({"kind": "lifecycle_runtime_guidance", "cache_role": "volatile"})

    assert runtime_memory.context_cache_section == "context_append"
    assert runtime_memory.cache_role == "session_stable"
    assert user_request.context_cache_section == "context_append"
    assert user_request.cache_role == "session_stable"
    assert user_request.prefix_tier == "task"
    assert is_sealable_context_spec({"kind": "current_turn_user_context", "cache_role": "volatile"}) is True
    assert action_contract.context_cache_section == "dynamic_tail"
    assert action_contract.memory_commit_policy == "never_commit"
    assert is_sealable_context_spec({"kind": "single_agent_turn_followup_action_contract", "cache_role": "session_stable"}) is False
    assert lifecycle.context_cache_section == "dynamic_tail"
    assert lifecycle.cache_role == "volatile"


def test_fixed_context_order_seals_previous_context_and_keeps_dynamic_tail_last(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    specs = [
        _spec(kind="global_static", content="Global protocol", cache_role="cacheable_prefix", cache_scope="global"),
        _spec(kind="lifecycle_runtime_guidance", content="Lifecycle now"),
        _spec(kind="runtime_memory_context", content="Memory\n{\"fact\":\"remember\"}"),
        _spec(kind="current_turn_user_context", content="Current request\n{\"text\":\"fix cache\"}", cache_role="volatile"),
        _spec(kind="read_evidence_context", content="Evidence ref\n{\"ref\":\"obs:1\"}", cache_role="session_stable", cache_scope="task"),
    ]

    first = _fixed_context_package_message_specs(
        specs,
        invocation_kind="single_agent_turn",
        provider_visible_context_scope="session:test",
        storage_root=backend_dir,
    )
    first_kinds = [item["kind"] for item in first]
    assert first_kinds[-1] == "lifecycle_runtime_guidance"
    assert first_kinds[:4] == ["global_static", "runtime_memory_context", "current_turn_user_context", "read_evidence_context"]
    assert [dict(item["metadata"]).get("context_cache_section") for item in first[1:4]] == [
        "context_append",
        "context_append",
        "context_append",
    ]
    _confirm_pending_specs(first, backend_dir=backend_dir)

    second = _fixed_context_package_message_specs(
        specs,
        invocation_kind="single_agent_turn",
        provider_visible_context_scope="session:test",
        storage_root=backend_dir,
    )
    assert [dict(item["metadata"]).get("context_cache_section") for item in second[1:4]] == [
        "context_memory_prefix",
        "context_memory_prefix",
        "context_memory_prefix",
    ]
    assert all(dict(item["metadata"]).get("provider_visible_context_ledger_entry_index", 0) > 0 for item in second[1:4])


def test_provider_policy_can_disable_dynamic_tail_physical_segment(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    unsupported_policy = ProviderCachePolicyResolver().resolve(
        provider="openai",
        model="custom-compatible",
        base_url="http://compatible.example/v1",
    )
    specs = [
        _spec(kind="global_static", content="Global protocol", cache_role="cacheable_prefix", cache_scope="global"),
        _spec(kind="runtime_memory_context", content="Memory fact"),
        _spec(kind="lifecycle_runtime_guidance", content="Lifecycle now"),
    ]

    ordered = _fixed_context_package_message_specs(
        specs,
        invocation_kind="single_agent_turn",
        provider_visible_context_scope="session:no-tail",
        storage_root=backend_dir,
        provider_cache_policy=unsupported_policy,
    )

    assert [item["kind"] for item in ordered] == ["global_static", "runtime_memory_context"]
    assert all(dict(item["metadata"]).get("context_dynamic_tail_enabled") is False for item in ordered)


def test_context_memory_prefix_materializes_previous_memory_when_current_context_changes(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    first = _fixed_context_package_message_specs(
        [
            _spec(kind="global_static", content="Global protocol", cache_role="cacheable_prefix", cache_scope="global"),
            _spec(kind="runtime_memory_context", content="Memory\n{\"fact\":\"first\"}"),
            _spec(kind="lifecycle_runtime_guidance", content="Lifecycle now"),
        ],
        invocation_kind="task_execution",
        provider_visible_context_scope="taskrun:sealed-order",
        storage_root=backend_dir,
    )
    assert [item["kind"] for item in first] == ["global_static", "runtime_memory_context", "lifecycle_runtime_guidance"]
    _confirm_pending_specs(first, backend_dir=backend_dir, request_id="modelreq:sealed-order:1")

    second = _fixed_context_package_message_specs(
        [
            _spec(kind="global_static", content="Global protocol", cache_role="cacheable_prefix", cache_scope="global"),
            _spec(kind="runtime_memory_context", content="Memory\n{\"fact\":\"second\"}"),
            _spec(kind="task_state_replay_entry", content="Replay\n{\"ref\":\"obs:1\"}", cache_role="session_stable", cache_scope="task"),
            _spec(kind="lifecycle_runtime_guidance", content="Lifecycle now"),
        ],
        invocation_kind="task_execution",
        provider_visible_context_scope="taskrun:sealed-order",
        storage_root=backend_dir,
    )
    second_context = second[1:-1]

    assert [item["content"] for item in second_context] == [
        "Memory\n{\"fact\":\"first\"}",
        "Memory\n{\"fact\":\"second\"}",
        "Replay\n{\"ref\":\"obs:1\"}",
    ]
    assert [dict(item["metadata"]).get("context_cache_section") for item in second_context] == [
        "context_memory_prefix",
        "context_append",
        "context_append",
    ]
    _confirm_pending_specs(second, backend_dir=backend_dir, request_id="modelreq:sealed-order:2")

    third = _fixed_context_package_message_specs(
        [
            _spec(kind="global_static", content="Global protocol", cache_role="cacheable_prefix", cache_scope="global"),
            _spec(kind="runtime_memory_context", content="Memory\n{\"fact\":\"second\"}"),
            _spec(kind="task_state_replay_entry", content="Replay\n{\"ref\":\"obs:1\"}", cache_role="session_stable", cache_scope="task"),
            _spec(kind="task_state_replay_entry", content="Replay\n{\"ref\":\"obs:2\"}", cache_role="session_stable", cache_scope="task"),
            _spec(kind="lifecycle_runtime_guidance", content="Lifecycle now"),
        ],
        invocation_kind="task_execution",
        provider_visible_context_scope="taskrun:sealed-order",
        storage_root=backend_dir,
    )
    third_context = third[1:-1]

    assert [item["content"] for item in third_context] == [
        "Memory\n{\"fact\":\"first\"}",
        "Memory\n{\"fact\":\"second\"}",
        "Replay\n{\"ref\":\"obs:1\"}",
        "Replay\n{\"ref\":\"obs:2\"}",
    ]
    assert [dict(item["metadata"]).get("context_cache_section") for item in third_context] == [
        "context_memory_prefix",
        "context_memory_prefix",
        "context_memory_prefix",
        "context_append",
    ]


def test_tool_followup_action_contract_is_dynamic_tail_not_context_memory() -> None:
    spec = _single_agent_turn_followup_message_spec(
        {
            "role": "user",
            "content": "你是正在根据刚才工具观察决定下一步的 coding agent。\n只决定本轮下一步。",
        },
        tool_iteration=3,
    )

    classification = classify_context_spec(spec)
    assert spec["kind"] == "single_agent_turn_followup_action_contract"
    assert spec["cache_role"] == "volatile"
    assert spec["prefix_tier"] == "volatile"
    assert classification.context_cache_section == "dynamic_tail"
    assert classification.memory_commit_policy == "never_commit"
    assert is_sealable_context_spec(spec) is False


def test_followup_segment_plan_rejects_context_append_after_dynamic_tail() -> None:
    with pytest.raises(RuntimeError, match="single_agent_followup_context_after_dynamic_tail"):
        _validate_single_agent_followup_tail_order(
            {
                "segments": [
                    {
                        "ordinal": 1,
                        "kind": "global_static",
                        "cache_role": "cacheable_prefix",
                        "cache_scope": "global",
                        "prefix_tier": "provider_global",
                    },
                    {
                        "ordinal": 2,
                        "kind": "single_agent_turn_followup_action_contract",
                        "cache_role": "volatile",
                        "cache_scope": "none",
                        "prefix_tier": "volatile",
                    },
                    {
                        "ordinal": 3,
                        "kind": "single_agent_turn_followup_message",
                        "cache_role": "session_stable",
                        "cache_scope": "task",
                        "prefix_tier": "task",
                    },
                ]
            }
        )


def test_followup_segment_plan_repairs_tool_observation_after_dynamic_tail() -> None:
    base_segment_plan = build_prompt_segment_plan(
        packet_id="rtpacket:turn:session-followup-order:1",
        invocation_kind="single_agent_turn",
        message_specs=[
            build_model_message_spec(
                role="system",
                content="Global protocol",
                kind="global_static",
                source_ref="global_static",
                cache_scope="global",
                cache_role="cacheable_prefix",
                compression_role="preserve",
                metadata={"context_cache_section": "static_prefix"},
            ),
            build_model_message_spec(
                role="user",
                content="Read the files",
                kind="current_turn_user_context",
                source_ref="current_turn_user_context",
                cache_scope="task",
                cache_role="session_stable",
                compression_role="preserve",
                metadata={"context_cache_section": "context_append"},
            ),
            build_model_message_spec(
                role="system",
                content="Dynamic projection",
                kind="dynamic_projection",
                source_ref="dynamic_projection",
                cache_scope="none",
                cache_role="volatile",
                compression_role="preserve",
                metadata={"context_cache_section": "dynamic_tail"},
            ),
            build_model_message_spec(
                role="system",
                content="Skill candidates",
                kind="skill_candidates",
                source_ref="skill_candidates",
                cache_scope="none",
                cache_role="volatile",
                compression_role="preserve",
                metadata={"context_cache_section": "dynamic_tail"},
            ),
            build_model_message_spec(
                role="system",
                content="Lifecycle guidance",
                kind="lifecycle_runtime_guidance",
                source_ref="lifecycle_runtime_guidance",
                cache_scope="none",
                cache_role="volatile",
                compression_role="preserve",
                metadata={"context_cache_section": "dynamic_tail"},
            ),
        ],
    ).to_dict()
    model_messages = [
        {"role": "system", "content": "Global protocol"},
        {"role": "user", "content": "Read the files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "read_file", "args": {"path": "a.py"}},
                {"id": "call_2", "name": "read_file", "args": {"path": "b.py"}},
            ],
        },
        {"role": "system", "content": "Dynamic projection"},
        {"role": "system", "content": "Skill candidates"},
        {"role": "system", "content": "Lifecycle guidance"},
        {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "a"},
        {"role": "tool", "tool_call_id": "call_2", "name": "read_file", "content": "b"},
    ]

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=model_messages,
        packet_id="rtpacket:turn:session-followup-order:1",
        tool_iteration=1,
    )
    segments = [dict(item) for item in list(segment_plan.get("segments") or [])]
    sections = [classify_context_spec(segment).context_cache_section for segment in segments]
    first_dynamic_tail_index = sections.index("dynamic_tail")
    tool_observation_indexes = [
        index
        for index, segment in enumerate(segments)
        if str(segment.get("kind") or "") == "single_agent_turn_tool_observation"
    ]

    assert len(tool_observation_indexes) == 2
    assert all(index < first_dynamic_tail_index for index in tool_observation_indexes)
    assert [segments[index]["model_message_role"] for index in tool_observation_indexes] == ["tool", "tool"]


def test_sealed_followup_prefix_lock_mismatch_is_structured_violation() -> None:
    old_tool_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_old", "name": "read_file", "args": {"path": "a.py"}}],
    }
    new_tool_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_new", "name": "read_file", "args": {"path": "a.py"}}],
    }
    base_segment_plan = build_prompt_segment_plan(
        packet_id="rtpacket:turn:session-receipt-prefix-lock:1",
        invocation_kind="single_agent_turn_tool_followup",
        message_specs=[
            {
                "role": "system",
                "content": "Global protocol",
                "kind": "global_static",
                "source_ref": "global_static",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "static_prefix"},
            },
            {
                "role": "assistant",
                "content": "",
                "kind": "single_agent_turn_tool_call",
                "source_ref": "single_agent_turn.tool_call:read_file:call_old",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "context_memory_prefix"},
                "model_message": old_tool_call,
            },
            {
                "role": "system",
                "content": "Current lifecycle",
                "kind": "lifecycle_runtime_guidance",
                "source_ref": "lifecycle_runtime_guidance",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "dynamic_tail"},
            },
        ],
    ).to_dict()

    segment_plan = _single_agent_turn_followup_segment_plan(
        base_segment_plan=base_segment_plan,
        model_messages=[
            {"role": "system", "content": "Global protocol"},
            new_tool_call,
            {"role": "system", "content": "Current lifecycle"},
        ],
        packet_id="rtpacket:turn:session-receipt-prefix-lock:1",
        tool_iteration=2,
    )
    segments = [dict(item) for item in list(segment_plan.get("segments") or [])]
    tool_call_segment = next(item for item in segments if str(item.get("kind") or "") == "single_agent_turn_tool_call")
    prefix_lock = dict(segment_plan.get("prefix_lock") or {})

    assert tool_call_segment["cache_role"] == "session_stable"
    assert tool_call_segment["prefix_tier"] == "task"
    assert classify_context_spec(tool_call_segment).context_cache_section == "context_memory_prefix"
    assert prefix_lock["status"] == "violated"
    assert prefix_lock["violation_count"] == 1
    assert prefix_lock["violations"][0]["reason"] == "model_message_hash_changed"


def test_provider_visible_ledger_reports_hash_change_as_structured_recovery(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    first = assemble_provider_visible_context_specs(
        [
            (
                1,
                _spec(
                    kind="runtime_memory_context",
                    content="Memory\nfirst",
                    metadata={"provider_visible_context_ledger_item_key": "item:1"},
                ),
            )
        ],
        storage_root=backend_dir,
        scope="single_agent_turn:session-hash",
    )
    confirm_provider_visible_context_entries(
        [dict(first[0][1]["metadata"])],
        default_storage_root=backend_dir,
        request_id="modelreq:hash:first",
    )
    second = assemble_provider_visible_context_specs(
        [
            (
                1,
                _spec(
                    kind="runtime_memory_context",
                    content="Memory\nchanged",
                    metadata={"provider_visible_context_ledger_item_key": "item:1"},
                ),
            )
        ],
        storage_root=backend_dir,
        scope="single_agent_turn:session-hash",
    )
    ledger = load_provider_visible_context_ledger(storage_root=backend_dir, scope="single_agent_turn:session-hash")
    recovery_events = [dict(item) for item in list(ledger.get("recovery_events") or []) if isinstance(item, dict)]

    assert [item[1]["content"] for item in first] == ["Memory\nfirst"]
    assert second[0][1]["content"].startswith("Memory\nfirst")
    assert ledger["status"] == "recovery_required"
    assert recovery_events[-1]["code"] == "provider_visible_hash_changed_for_entry"


def test_provider_visible_ledger_appends_confirmed_log_only_after_provider_success(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    scope = "single_agent_turn:session-confirmation"
    first = assemble_provider_visible_context_specs(
        [(1, _spec(kind="runtime_memory_context", content="Memory\nfirst"))],
        storage_root=backend_dir,
        scope=scope,
    )
    second = assemble_provider_visible_context_specs(
        [(1, _spec(kind="runtime_memory_context", content="Memory\nfirst"))],
        storage_root=backend_dir,
        scope=scope,
    )
    ledger_before_confirm = load_provider_visible_context_ledger(storage_root=backend_dir, scope=scope)

    assert first[0][1]["metadata"]["context_cache_section"] == "context_append"
    assert second[0][1]["metadata"]["context_cache_section"] == "context_append"
    assert ledger_before_confirm == {}

    confirmation = confirm_provider_visible_context_entries(
        [dict(first[0][1]["metadata"])],
        default_storage_root=backend_dir,
        request_id="modelreq:confirmation:first",
    )
    third = assemble_provider_visible_context_specs(
        [(1, _spec(kind="runtime_memory_context", content="Memory\nfirst"))],
        storage_root=backend_dir,
        scope=scope,
    )
    ledger_after_confirm = load_provider_visible_context_ledger(storage_root=backend_dir, scope=scope)

    assert confirmation["confirmed_count"] == 1
    assert third[0][1]["metadata"]["context_cache_section"] == "context_memory_prefix"
    assert ledger_after_confirm["entries"][0]["commit_status"] == PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS


def test_followup_ledger_append_preserves_provider_visible_message(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_assemble(items, **kwargs):
        captured.update(kwargs)
        captured["items"] = list(items)
        return []

    monkeypatch.setattr(
        "harness.loop.single_agent_turn.assemble_provider_visible_context_specs",
        fake_assemble,
    )
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": "Need exact evidence before the next tool.",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}}
        ],
    }
    segment_plan = {
        "segments": [
            {
                "segment_id": "seg:tool-call",
                "kind": "single_agent_turn_tool_call",
                "ordinal": 1,
                "model_message_index": 0,
                "model_message_role": "assistant",
                "source_ref": "single_agent_turn.tool_call:call_1",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
                "content_hash": "sha256:content",
                "model_message_hash": "sha256:model",
                "metadata": {"context_cache_section": "context_append"},
            }
        ]
    }

    annotated = _annotate_single_agent_followup_segment_plan(
        segment_plan,
        packet_id="rtpacket:turn:session-followup-provider-message:1",
        message_specs=[
            {
                "role": "assistant",
                "content": "",
                "kind": "single_agent_turn_tool_call",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "model_message": message,
            }
        ],
    )

    items = captured["items"]
    provider_visible_message = items[0][1]["model_message"]
    assert provider_visible_message["role"] == "assistant"
    assert provider_visible_message["reasoning_content"] == "Need exact evidence before the next tool."
    assert provider_visible_message["tool_calls"][0]["id"] == "call_1"
    assert captured["scope"] == "single_agent_turn:session-followup-provider-message"
    assert annotated["segments"][0]["metadata"]["provider_visible_hash"] != "sha256:model"
    assert annotated["segments"][0]["metadata"]["provider_visible_context_authority"] == (
        "runtime.context_management.provider_visible_context_ledger"
    )


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
                "kind": "current_turn_user_context",
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
    assert diagnostics["target_warm_cache_read_rate_goal"] == 0.95
    assert diagnostics["context_append_promoted_to_next_context_memory_prefix"] is True


def test_provider_cache_anchor_uses_expected_prefix_not_current_context_append() -> None:
    messages = [
        {"role": "system", "content": "Global protocol"},
        {"role": "system", "content": "Sealed previous context\nMemory fact: stable."},
        {"role": "user", "content": "New feedback\n" + ("This belongs to the next sealed context. " * 1200)},
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
                "segment_id": "seg:sealed",
                "kind": "runtime_memory_context",
                "ordinal": 2,
                "model_message_index": 1,
                "model_message_role": "system",
                "cache_scope": "task",
                "cache_role": "session_stable",
                "prefix_tier": "task",
                "compression_role": "preserve",
                "metadata": {"context_cache_section": "context_memory_prefix"},
            },
            {
                "segment_id": "seg:append",
                "kind": "current_turn_user_context",
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
        request_id="modelreq:context-cache-anchor",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        segment_plan=segment_plan,
        metadata={"cache_relevant_params": {"thinking_mode": "enabled"}},
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:context-cache-anchor",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4-flash",
        segment_plan=segment_plan,
        model_request=model_request,
    )
    planner = PromptCachePlanner()
    cache_record = planner.plan(
        segment_map,
        provider="deepseek",
        model="deepseek-v4-flash",
        model_request=model_request,
    )
    planned = dict(cache_record.diagnostics)
    expected_prefix = int(planned["expected_cache_read_prefix_predicted_tokens"])
    provider_prompt_tokens = int(planned["target_warm_cache_read_rate_total_tokens"])

    assert expected_prefix > 0
    assert planned["context_append_prefix_predicted_tokens"] > expected_prefix

    observed = planner.with_provider_usage(
        cache_record,
        ModelTokenUsageRecord(
            usage_id="usage:context-cache-anchor",
            request_id="modelreq:context-cache-anchor",
            provider="deepseek",
            model="deepseek-v4-flash",
            source="provider_usage",
            prompt_tokens=provider_prompt_tokens,
            cached_tokens=expected_prefix + 1,
            cache_read_tokens=expected_prefix + 1,
        ),
    )
    diagnostics = dict(observed.diagnostics)

    assert diagnostics["target_warm_cache_read_rate_actual"] < 0.95
    assert diagnostics["target_warm_cache_read_rate_status"] == "provider_below_target"
    assert diagnostics["provider_cache_anchor_status"] == "dynamic_tail_or_current_append_over_budget"
    assert diagnostics["provider_cache_read_stable_prefix_estimated_source"] == "expected_cache_read_prefix_excluding_current_context_append"
    assert diagnostics["provider_cache_read_stable_prefix_estimated_tokens"] == expected_prefix
    assert diagnostics["provider_cache_read_stable_prefix_estimated_covered"] is True
    assert diagnostics["provider_cache_read_first_uncovered_stable_segment"] == {}
    assert diagnostics["provider_cache_read_first_current_context_append_segment"]["kind"] == "current_turn_user_context"


def test_tool_followup_does_not_insert_dynamic_boundary_into_provider_prefix() -> None:
    previous_context = [
        {"role": "system", "content": "Static protocol"},
        {"role": "user", "content": "Sealed context fact"},
    ]
    next_round = [
        *previous_context,
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": "new observation"},
        {"role": "system", "content": "你是正在根据刚才工具观察决定下一步的 coding agent。"},
    ]

    unchanged = _append_tool_followup_context_boundary(
        next_round[:-1],
        tool_iteration=2,
        turn_id="turn:cache-prefix",
    )
    ordered = _ordered_tool_followup_prompt_messages([*unchanged, next_round[-1]], segment_plan={})

    assert unchanged == next_round[:-1]
    assert all("accumulated_context_boundary" not in str(message.get("content") or "") for message in ordered)
    assert ordered[: len(previous_context)] == previous_context
    assert ordered[-1]["content"].startswith("你是正在根据刚才工具观察决定下一步的 coding agent。")


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
