from __future__ import annotations

from harness.runtime.compiler import _fixed_context_package_message_specs
from prompt_composition import build_model_message_spec
from runtime.context_management import confirm_provider_visible_context_entries
from runtime.model_gateway.provider_cache_policy import ProviderCachePolicyResolver


def _spec(*, kind: str, content: str, cache_role: str = "volatile", cache_scope: str = "none") -> dict:
    return build_model_message_spec(
        role="system",
        content=content,
        kind=kind,
        source_ref=kind,
        cache_scope=cache_scope,
        cache_role=cache_role,
        compression_role="preserve",
    )


def _confirm_pending_specs(specs: list[dict], *, backend_dir, request_id: str = "modelreq:test-confirm") -> None:
    refs = [
        dict(dict(item.get("metadata") or {}))
        for item in list(specs or [])
        if str(dict(item.get("metadata") or {}).get("provider_visible_context_ledger_commit_stage") or "") == "provider_success_required"
    ]
    if refs:
        confirm_provider_visible_context_entries(refs, default_storage_root=backend_dir, request_id=request_id)


def test_context_segments_carry_physical_prefix_metadata(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    specs = [
        _spec(kind="global_static", content="Static protocol", cache_role="cacheable_prefix", cache_scope="global"),
        _spec(kind="runtime_memory_context", content="Memory fact with old volatile label"),
        _spec(kind="lifecycle_runtime_guidance", content="Current lifecycle only"),
    ]

    ordered = _fixed_context_package_message_specs(
        specs,
        invocation_kind="single_agent_turn",
        provider_visible_context_scope="session:physical-metadata",
        storage_root=backend_dir,
    )
    metadata_by_kind = {item["kind"]: dict(item["metadata"]) for item in ordered}

    assert [item["kind"] for item in ordered] == [
        "global_static",
        "runtime_memory_context",
        "lifecycle_runtime_guidance",
    ]
    assert metadata_by_kind["global_static"]["context_physical_segment"] == "static_prefix"
    assert metadata_by_kind["runtime_memory_context"]["context_physical_segment"] == "context_memory"
    assert metadata_by_kind["runtime_memory_context"]["context_prefix_cache_role"] == "session_stable"
    assert metadata_by_kind["runtime_memory_context"]["context_prefix_boundary"] == "materialize_then_cache_on_next_request"
    assert metadata_by_kind["lifecycle_runtime_guidance"]["context_physical_segment"] == "dynamic_tail"
    assert metadata_by_kind["lifecycle_runtime_guidance"]["context_prefix_boundary"] == "never_cache"


def test_provider_without_dynamic_tail_drops_tail_and_keeps_context_memory(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    unsupported_policy = ProviderCachePolicyResolver().resolve(
        provider="openai",
        model="compatible",
        base_url="http://compatible.example/v1",
    )

    ordered = _fixed_context_package_message_specs(
        [
            _spec(kind="global_static", content="Static protocol", cache_role="cacheable_prefix", cache_scope="global"),
            _spec(kind="current_turn_user_context", content="Remember this user fact"),
            _spec(kind="lifecycle_runtime_guidance", content="Current lifecycle only"),
        ],
        invocation_kind="single_agent_turn",
        provider_visible_context_scope="session:no-tail",
        storage_root=backend_dir,
        provider_cache_policy=unsupported_policy,
    )

    assert [item["kind"] for item in ordered] == ["global_static", "current_turn_user_context"]
    assert all(dict(item["metadata"])["context_dynamic_tail_enabled"] is False for item in ordered)
    assert ordered[1]["metadata"]["context_physical_segment_order"] == ["static_prefix", "context_memory"]


def test_provider_visible_context_replays_previous_payload_before_new_append(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    scope = "session:append-only"

    first = _fixed_context_package_message_specs(
        [_spec(kind="current_turn_user_context", content="User fact A")],
        invocation_kind="single_agent_turn",
        provider_visible_context_scope=scope,
        storage_root=backend_dir,
    )
    _confirm_pending_specs(first, backend_dir=backend_dir)
    second = _fixed_context_package_message_specs(
        [_spec(kind="current_turn_user_context", content="User fact B")],
        invocation_kind="single_agent_turn",
        provider_visible_context_scope=scope,
        storage_root=backend_dir,
    )

    assert [item["content"] for item in first] == ["User fact A"]
    assert [item["content"] for item in second] == ["User fact A", "User fact B"]
    assert second[0]["metadata"]["context_cache_section"] == "context_memory_prefix"
    assert second[0]["metadata"]["context_prefix_boundary"] == "cacheable_prefix"
    assert second[1]["metadata"]["context_cache_section"] == "context_append"
