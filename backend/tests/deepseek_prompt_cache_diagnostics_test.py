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


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _cache_record(request_id: str, cache_key: str, status: str) -> dict:
    return {
        "cache_record_id": f"pcache:{request_id}",
        "request_id": request_id,
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
