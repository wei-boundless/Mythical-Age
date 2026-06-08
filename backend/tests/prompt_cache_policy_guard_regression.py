from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_cache_policy import cache_policy_findings
from prompt_library import PromptGovernanceManager, PromptLibraryRegistry
from runtime.model_gateway.model_request import ModelRequestBuilder
from runtime.prompt_accounting import CanonicalPromptSerializer, PromptCachePlanner


def test_segment_plan_rejects_unknown_cache_role_with_stable_tier() -> None:
    with pytest.raises(ValueError, match="invalid_cache_role"):
        build_prompt_segment_plan(
            packet_id="packet:invalid-cache-role",
            invocation_kind="single_agent_turn",
            message_specs=[
                {
                    "role": "system",
                    "content": "legacy tool guidance",
                    "kind": "tool_guidance_stable",
                    "cache_scope": "global",
                    "cache_role": "operation_package_static",
                    "prefix_tier": "provider_global",
                    "compression_role": "preserve",
                }
            ],
        )


def test_segment_plan_rejects_volatile_segment_with_stable_tier() -> None:
    with pytest.raises(ValueError, match="volatile_tier_must_be_volatile"):
        build_prompt_segment_plan(
            packet_id="packet:volatile-stable-tier",
            invocation_kind="single_agent_turn",
            message_specs=[
                {
                    "role": "system",
                    "content": "volatile content",
                    "kind": "tool_guidance_stable",
                    "cache_scope": "none",
                    "cache_role": "volatile",
                    "prefix_tier": "provider_global",
                    "compression_role": "summarize",
                }
            ],
        )


def test_legacy_noneligible_prefix_tier_does_not_become_cache_key() -> None:
    messages = [
        {"role": "system", "content": "legacy tool guidance"},
        {"role": "user", "content": "current request"},
    ]
    legacy_plan = {
        "segments": [
            {
                "model_message_index": 0,
                "kind": "tool_guidance_stable",
                "source_ref": "legacy.tool",
                "cache_scope": "global",
                "cache_role": "operation_package_static",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "model_message_index": 1,
                "kind": "volatile_user",
                "source_ref": "turn.current",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ]
    }

    model_request = ModelRequestBuilder().build(
        request_id="modelreq:legacy-cache-policy",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4",
        segment_plan=legacy_plan,
    )
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:legacy-cache-policy",
        messages=messages,
        provider="deepseek",
        model="deepseek-v4",
        segment_plan=legacy_plan,
        model_request=model_request,
    )
    cache_record = PromptCachePlanner().plan(segment_map, provider="deepseek", model="deepseek-v4")
    adapter = model_request.diagnostics["provider_prompt_adapter"]

    assert model_request.stable_prefix_hash == ""
    assert model_request.provider_global_prefix_hash == ""
    assert model_request.session_prefix_hash == ""
    assert model_request.task_prefix_hash == ""
    assert adapter["declared_provider_global_block_count"] == 1
    assert adapter["provider_global_block_count"] == 0
    assert adapter["provider_global_prefix_hash"] == ""
    assert cache_record.status == "bypassed"
    assert "no_stable_prefix_boundary" in cache_record.cache_safety_reasons


def test_builtin_tool_prompt_cache_hints_use_unified_policy() -> None:
    tool_resources = [
        resource
        for resource in PromptLibraryRegistry(BACKEND_DIR).list_resources()
        if resource.resource_type == "tool_guidance"
    ]

    assert tool_resources
    for resource in tool_resources:
        findings = cache_policy_findings(
            cache_scope=resource.cache_hint.get("cache_scope"),
            cache_role=resource.cache_hint.get("cache_role"),
            prefix_tier=resource.cache_hint.get("prefix_tier"),
            kind=",".join(resource.segment_bindings.get("allowed_prompt_segment_kinds") or []),
            source_ref=resource.source_ref,
        )
        assert findings == ()


def test_prompt_governance_rejects_invalid_stable_cache_hint(tmp_path: Path) -> None:
    resource_dir = tmp_path / "prompt_library" / "resources" / "general" / "cycles" / "execution_step_selection"
    resource_dir.mkdir(parents=True)
    (resource_dir / "catalog.yaml").write_text(
        textwrap.dedent(
            """
            resources:
              - resource_id: general.cycles.execution_step_selection.cache.bad.test
                environment_scope: general
                category: general
                subtype: cycles.execution_step_selection
                resource_type: general.cycle
                status: staged
                semantic_role: route_method
                function_cells: [way.route]
                agent_running_cycles: [execution_step_selection]
                manager_owner: RouteMethodManager
                authority_refs: [prompt_governance]
                harness_bindings:
                  allowed_invocation_kinds: [single_agent_turn]
                segment_bindings:
                  allowed_prompt_segment_kinds: [global_static]
                cache_hint:
                  cache_scope: global
                  cache_role: operation_package_static
                  prefix_tier: provider_global
                content: 你需要选择最小可验证路径。
            """
        ).strip(),
        encoding="utf-8",
    )

    report = PromptGovernanceManager(tmp_path).report(mode="source_catalog")
    issues = {finding.get("issue") for finding in report.findings}

    assert report.status == "needs_review"
    assert "invalid_cache_role" in issues
