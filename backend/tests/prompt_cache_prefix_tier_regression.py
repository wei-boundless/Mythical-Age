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
from runtime.prompt_accounting import CanonicalPromptSerializer, CompressionBudgetPlanner, PromptCachePlanner, PromptSegment


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


def test_prompt_cache_planner_uses_provider_global_prefix_key() -> None:
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

    assert cache_record.prefix_hash == model_request.provider_global_prefix_hash
    assert cache_record.prefix_hash != model_request.stable_prefix_hash
    assert cache_record.diagnostics["prefix_key_tier"] == "provider_global"
    assert cache_record.diagnostics["provider_global_prefix_segment_count"] == 1
    assert cache_record.diagnostics["task_prefix_segment_count"] == 2


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

    assert decision.cache_impact == "preserved"
    assert decision.cache_impact_tiers["provider_global"] == "preserved"
    assert decision.cache_impact_tiers["task"] == "preserved"
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
