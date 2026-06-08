from __future__ import annotations

import json
from pathlib import Path

from scripts.diagnose_deepseek_prompt_cache import diagnose


def test_deepseek_cache_diagnosis_flags_repeated_prefix_miss(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_cache.jsonl",
        [
            _cache_record("req:1", "key:a", "miss"),
            _cache_record("req:2", "key:a", "miss"),
        ],
    )
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [
            _provider_usage("req:1", prompt_tokens=1200, cached_tokens=0),
            _provider_usage("req:2", prompt_tokens=1200, cached_tokens=0),
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.summary["deepseek_cache_hit_rate"] == 0.0
    assert result.prefix_groups[0]["provider_misses"] == 2
    assert any(issue["code"] == "repeated_prefix_provider_miss" for issue in result.issues)


def test_deepseek_cache_diagnosis_does_not_flag_first_cold_miss(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_cache.jsonl",
        [
            {**_cache_record("req:1", "key:a", "miss"), "created_at": 1},
            {**_cache_record("req:2", "key:a", "hit"), "created_at": 2},
            {**_cache_record("req:3", "key:a", "hit"), "created_at": 3},
        ],
    )
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [
            {**_provider_usage("req:1", prompt_tokens=1200, cached_tokens=0), "created_at": 1},
            {**_provider_usage("req:2", prompt_tokens=1200, cached_tokens=1100), "created_at": 2},
            {**_provider_usage("req:3", prompt_tokens=1200, cached_tokens=1100), "created_at": 3},
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.prefix_groups[0]["warmup_provider_misses"] == 1
    assert result.prefix_groups[0]["post_warm_provider_misses"] == 0
    assert result.prefix_groups[0]["post_warm_hit_rate"] == 0.9167
    assert not any(issue["code"] == "repeated_prefix_provider_miss" for issue in result.issues)


def test_deepseek_cache_diagnosis_reads_recent_tail_window_for_large_ledgers(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_cache.jsonl",
        [
            {**_cache_record("req:old-small", "key:old", "miss"), "created_at": 1},
            {**_cache_record("req:tail", "key:tail", "hit"), "created_at": 2},
        ],
    )
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [
            {
                **_provider_usage("req:old-small", prompt_tokens=100, cached_tokens=0),
                "diagnostics": {"padding": "x" * (1024 * 1024 + 512)},
                "created_at": 1,
            },
            {**_provider_usage("req:tail", prompt_tokens=100, cached_tokens=80), "created_at": 2},
        ],
    )

    result = diagnose(ledger_dir=ledger_dir, ledger_tail_mb=1)

    read_window = result.summary["ledger_read_window"]
    assert read_window["files"]["token_usage.jsonl"]["read_mode"] == "tail"
    assert read_window["files"]["prompt_cache.jsonl"]["read_mode"] == "full"
    assert read_window["created_at_floor"] == 2
    assert result.summary["cache_records"] == 1
    assert result.summary["provider_usage_records"] == 1
    assert result.recent_requests[0]["request_id"] == "req:tail"


def test_deepseek_cache_diagnosis_flags_volatile_stable_segment(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "segment_maps.jsonl",
        [
            {
                "request_id": "req:1",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "created_at": 1,
                "metadata": {"packet_ref": "rtpacket:demo:task_execution:1"},
                "segments": [
                    _segment("global_static", "cacheable_prefix", "hash:static", 100),
                    _segment(
                        "runtime_boundary",
                        "session_stable",
                        "hash:runtime",
                        800,
                        metadata={
                            "cache_impact": "volatile",
                            "volatility_reason": "runtime assembly can vary",
                        },
                    ),
                    _segment("volatile_task_state", "volatile", "hash:tail", 50),
                ],
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.volatile_stable_segments[0]["kind"] == "runtime_boundary"
    assert any(issue["code"] == "volatile_metadata_inside_stable_prefix" for issue in result.issues)


def test_deepseek_cache_diagnosis_includes_prompt_stability_report(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_cache.jsonl",
        [_cache_record("req:stable", "key:stable", "hit")],
    )
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [_provider_usage("req:stable", prompt_tokens=100, cached_tokens=80)],
    )
    _write_jsonl(
        ledger_dir / "prompt_stability.jsonl",
        [
            {
                "report_id": "pstability:req:stable",
                "request_id": "req:stable",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "session_id": "session:stable",
                "session_cache_key": "session:stable",
                "stable_prefix_hash": "sha256:stable",
                "stable_prefix_tokens": 70,
                "stable_section_count": 2,
                "volatile_token_count": 30,
                "dynamic_param_hash": "sha256:params",
                "first_changed_section": {
                    "ordinal": 2,
                    "current_kind": "task_stable",
                    "change_type": "section_changed",
                },
                "provider_usage": {
                    "prompt_tokens": 100,
                    "cached_tokens": 80,
                    "cache_read_tokens": 80,
                    "cache_hit_rate": 0.8,
                },
                "diagnostics": {"likely_break_reason": "provider_cache_hit"},
                "created_at": 3,
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir, session_id="session:stable")

    assert result.summary["stability_reports"] == 1
    assert result.stability_reports[0]["first_changed_section"] == "2:task_stable:section_changed"
    assert result.recent_requests[0]["likely_break_reason"] == "provider_cache_hit"


def test_deepseek_cache_diagnosis_summarizes_dynamic_param_diff(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_stability.jsonl",
        [
            {
                "report_id": "pstability:req:param",
                "request_id": "req:param",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "session_id": "session:param",
                "session_cache_key": "session:param",
                "stable_prefix_hash": "sha256:stable",
                "stable_prefix_tokens": 70,
                "stable_section_count": 1,
                "volatile_token_count": 30,
                "dynamic_param_hash": "sha256:params",
                "diagnostics": {
                    "likely_break_reason": "dynamic_request_params_changed",
                    "dynamic_param_diff": {
                        "request_params": {
                            "previous": {"temperature": 0.0},
                            "current": {"temperature": 0.7},
                        }
                    },
                },
                "created_at": 3,
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir, session_id="session:param")

    assert result.stability_reports[0]["dynamic_param_diff"] == "request_params"


def test_deepseek_cache_diagnosis_summarizes_provider_payload_break_reason(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_cache.jsonl",
        [
            {
                **_cache_record("req:tool-break", "key:tool:new", "miss"),
                "prefix_hash": "sha256:provider-payload-new",
                "diagnostics": {
                    "provider_cache_policy": {
                        "mode": "automatic_prefix",
                        "provider": "deepseek",
                    },
                    "provider_payload_prefix_hash": "sha256:provider-payload-new",
                    "tool_catalog_hash": "sha256:tool-catalog-new",
                    "cache_sensitive_params_hash": "sha256:params",
                },
            }
        ],
    )
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [_provider_usage("req:tool-break", prompt_tokens=1000, cached_tokens=0)],
    )
    _write_jsonl(
        ledger_dir / "prompt_cache_breaks.jsonl",
        [
            {
                "break_id": "pcachebreak:req:tool-break",
                "request_id": "req:tool-break",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "reason": "tool_schema_hash_changed",
                "diagnostics": {
                    "provider_payload": {
                        "tool_catalog_hash": {
                            "previous": "sha256:tool-catalog-old",
                            "current": "sha256:tool-catalog-new",
                        }
                    }
                },
                "created_at": 3,
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.summary["cache_break_reason_counts"]["tool_schema_hash_changed"] == 1
    assert result.recent_requests[0]["cache_break_reason"] == "tool_schema_hash_changed"
    assert result.recent_requests[0]["provider_payload_prefix_hash"] == "sha256:provider-pay"
    assert result.recent_requests[0]["tool_catalog_hash"] == "sha256:tool-catalog"


def test_deepseek_cache_diagnosis_summarizes_prompt_assembly_break_detail(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_cache.jsonl",
        [
            {
                **_cache_record("req:assembly-break", "key:assembly:new", "miss"),
                "prefix_hash": "sha256:section-new",
                "diagnostics": {
                    "provider_cache_policy": {
                        "mode": "automatic_prefix",
                        "provider": "deepseek",
                    },
                    "assembly_request_fingerprint": "sha256:req-new",
                    "section_fingerprint": "sha256:sec-new",
                    "prompt_composition_cache_boundary_status": "warning",
                    "prompt_composition_layer_violation_count": 1,
                    "prompt_composition_segment_violation_count": 2,
                },
            }
        ],
    )
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [_provider_usage("req:assembly-break", prompt_tokens=1000, cached_tokens=0)],
    )
    _write_jsonl(
        ledger_dir / "prompt_cache_breaks.jsonl",
        [
            {
                "break_id": "pcachebreak:req:assembly-break",
                "request_id": "req:assembly-break",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "reason": "prompt_section_fingerprint_changed",
                "diagnostics": {
                    "prompt_assembly": {
                        "assembly_request_fingerprint": {
                            "previous": "sha256:req-same",
                            "current": "sha256:req-same",
                        },
                        "section_fingerprint": {
                            "previous": "sha256:sec-old",
                            "current": "sha256:sec-new",
                        },
                    }
                },
                "created_at": 3,
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.summary["cache_break_reason_counts"]["prompt_section_fingerprint_changed"] == 1
    recent = result.recent_requests[0]
    assert recent["cache_break_reason"] == "prompt_section_fingerprint_changed"
    assert recent["cache_break_detail"] == "prompt_assembly.section_fingerprint"
    assert recent["assembly_request_fingerprint"] == "sha256:req-new"
    assert recent["section_fingerprint"] == "sha256:sec-new"
    assert recent["prompt_composition_status"] == "warning"
    assert recent["prompt_composition_violations"] == "layer=1,segment=2"


def test_deepseek_cache_diagnosis_summarizes_context_window_facts(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "prompt_stability.jsonl",
        [
            {
                "report_id": "pstability:req:window",
                "request_id": "req:window",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "session_id": "session:window",
                "session_cache_key": "session:window",
                "context_window_generation": 1,
                "compaction_generation": 1,
                "stable_prefix_hash": "sha256:stable",
                "stable_prefix_tokens": 70,
                "stable_section_count": 1,
                "volatile_token_count": 30,
                "dynamic_param_hash": "sha256:params",
                "diagnostics": {
                    "likely_break_reason": "provider_cache_cold_or_expired",
                    "context_window": {
                        "context_recovery_package_present": True,
                        "context_recovery_package_hash": "sha256:compressed",
                        "raw_history_message_count": 12,
                        "active_history_message_count": 12,
                    },
                },
                "created_at": 3,
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir, session_id="session:window")
    report = result.stability_reports[0]

    assert report["context_window_generation"] == 1
    assert report["compaction_generation"] == 1
    assert report["context_recovery_package"] == "yes"
    assert report["active_history_messages"] == 12


def test_deepseek_cache_diagnosis_does_not_mix_stable_hashes_across_tasks(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "segment_maps.jsonl",
        [
            {
                "request_id": "req:task:a",
                "run_id": "taskrun:a",
                "task_run_id": "taskrun:a",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "metadata": {"packet_ref": "rtpacket:taskrun:a:task_execution:1"},
                "segments": [_segment("task_stable", "session_stable", "hash:a", 100)],
                "created_at": 1,
            },
            {
                "request_id": "req:task:b",
                "run_id": "taskrun:b",
                "task_run_id": "taskrun:b",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "metadata": {"packet_ref": "rtpacket:taskrun:b:task_execution:1"},
                "segments": [_segment("task_stable", "session_stable", "hash:b", 100)],
                "created_at": 2,
            },
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.unstable_stable_segments == ()


def test_deepseek_cache_diagnosis_flags_stable_hash_changes_inside_same_task(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "segment_maps.jsonl",
        [
            {
                "request_id": "req:task:1",
                "run_id": "taskrun:same",
                "task_run_id": "taskrun:same",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "metadata": {"packet_ref": "rtpacket:taskrun:same:task_execution:1"},
                "segments": [_segment("task_stable", "session_stable", "hash:1", 100)],
                "created_at": 1,
            },
            {
                "request_id": "req:task:2",
                "run_id": "taskrun:same",
                "task_run_id": "taskrun:same",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "metadata": {"packet_ref": "rtpacket:taskrun:same:task_execution:2"},
                "segments": [_segment("task_stable", "session_stable", "hash:2", 100)],
                "created_at": 2,
            },
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.unstable_stable_segments[0]["stability_scope"] == "task:taskrun:same"
    assert result.unstable_stable_segments[0]["distinct_content_hashes"] == 2


def test_deepseek_cache_diagnosis_splits_utility_scope_from_agent_runtime(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [
            {
                **_provider_usage("req:agent", prompt_tokens=100, cached_tokens=50),
                "created_at": 2,
            },
            {
                **_provider_usage("req:utility", prompt_tokens=100, cached_tokens=0),
                "created_at": 2,
            },
            {
                "usage_id": "tokuse:req:agent:local_prediction",
                "request_id": "req:agent",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "source": "local_prediction",
                "prompt_tokens": 100,
                "diagnostics": {"cache_metric_scope": "agent_runtime"},
                "created_at": 1,
            },
            {
                "usage_id": "tokuse:req:utility:local_prediction",
                "request_id": "req:utility",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "source": "local_prediction",
                "prompt_tokens": 100,
                "diagnostics": {
                    "cache_metric_scope": "utility_minimal_plan",
                    "call_purpose": "utility.generate_title",
                },
                "created_at": 1,
            },
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.summary["deepseek_cache_hit_rate"] == 0.25
    assert result.summary["agent_runtime_deepseek_cache_hit_rate"] == 0.5
    assert result.summary["cache_metric_scope_counts"] == {
        "agent_runtime": 1,
        "utility_minimal_plan": 1,
    }


def test_deepseek_cache_diagnosis_flags_unplanned_model_call(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "prompt_accounting"
    ledger_dir.mkdir()
    _write_jsonl(
        ledger_dir / "token_usage.jsonl",
        [
            _provider_usage("req:unplanned", prompt_tokens=100, cached_tokens=0),
            {
                "usage_id": "tokuse:req:unplanned:local_prediction",
                "request_id": "req:unplanned",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "source": "local_prediction",
                "prompt_tokens": 100,
                "diagnostics": {
                    "cache_metric_scope": "unplanned_model_call",
                    "prompt_manifest": {"unplanned_model_call": True},
                },
                "created_at": 1,
            },
        ],
    )
    _write_jsonl(
        ledger_dir / "prompt_cache_breaks.jsonl",
        [
            {
                "break_id": "pcbreak:req:unplanned",
                "request_id": "req:unplanned",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "reason": "unplanned_model_call",
                "diagnostics": {"severity": "high"},
                "created_at": 2,
            }
        ],
    )

    result = diagnose(ledger_dir=ledger_dir)

    assert result.summary["unplanned_model_call_breaks"] == 1
    assert result.summary["cache_metric_scope_counts"]["unplanned_model_call"] == 1
    assert result.summary["cache_metric_scope_usage"]["unplanned_model_call"]["prompt_tokens"] == 100
    assert any(issue["code"] == "unplanned_model_call" for issue in result.issues)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _cache_record(request_id: str, cache_key: str, status: str) -> dict:
    return {
        "cache_record_id": f"pcache:{request_id}",
        "request_id": request_id,
        "session_id": "session:stable" if request_id == "req:stable" else "",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "cache_key": cache_key,
        "prefix_hash": "hash:a",
        "status": status,
        "created_at": 1,
        "diagnostics": {
            "provider_cache_policy": {
                "mode": "automatic_prefix",
                "provider": "deepseek",
            }
        },
    }


def _provider_usage(request_id: str, *, prompt_tokens: int, cached_tokens: int) -> dict:
    return {
        "usage_id": f"tokuse:{request_id}:provider_usage",
        "request_id": request_id,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "source": "provider_usage",
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "cache_read_tokens": cached_tokens,
        "total_tokens": prompt_tokens,
        "created_at": 2,
    }


def _segment(
    kind: str,
    cache_role: str,
    content_hash: str,
    predicted_tokens: int,
    *,
    metadata: dict | None = None,
) -> dict:
    return {
        "kind": kind,
        "cache_role": cache_role,
        "content_hash": content_hash,
        "predicted_tokens": predicted_tokens,
        "ordinal": 1,
        "metadata": dict(metadata or {}),
    }
