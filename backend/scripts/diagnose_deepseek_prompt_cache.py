from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any


STABLE_CACHE_ROLES = {"cacheable_prefix", "session_stable"}


@dataclass(frozen=True, slots=True)
class Diagnosis:
    summary: dict[str, Any]
    issues: tuple[dict[str, Any], ...] = ()
    prefix_groups: tuple[dict[str, Any], ...] = ()
    unstable_stable_segments: tuple[dict[str, Any], ...] = ()
    volatile_stable_segments: tuple[dict[str, Any], ...] = ()
    recent_requests: tuple[dict[str, Any], ...] = ()
    stability_reports: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "issues": list(self.issues),
            "prefix_groups": list(self.prefix_groups),
            "unstable_stable_segments": list(self.unstable_stable_segments),
            "volatile_stable_segments": list(self.volatile_stable_segments),
            "recent_requests": list(self.recent_requests),
            "stability_reports": list(self.stability_reports),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose DeepSeek prompt cache hit rate from the prompt accounting ledger."
    )
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parents[1]), help="Backend directory.")
    parser.add_argument("--ledger-dir", default="", help="Prompt accounting ledger directory.")
    parser.add_argument("--session-id", default="", help="Filter by session_id.")
    parser.add_argument("--run-id", default="", help="Filter by run_id.")
    parser.add_argument("--task-run-id", default="", help="Filter by task_run_id.")
    parser.add_argument("--provider", default="deepseek", help="Provider filter. Use empty string for all providers.")
    parser.add_argument("--min-prefix-repeats", type=int, default=2, help="Minimum repeated prefix group size to report.")
    parser.add_argument("--limit", type=int, default=12, help="Maximum rows per detailed section.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    ledger_dir = Path(args.ledger_dir).resolve() if args.ledger_dir else _default_ledger_dir(base_dir)
    diagnosis = diagnose(
        ledger_dir=ledger_dir,
        session_id=args.session_id,
        run_id=args.run_id,
        task_run_id=args.task_run_id,
        provider=args.provider,
        min_prefix_repeats=max(1, int(args.min_prefix_repeats or 1)),
        limit=max(1, int(args.limit or 1)),
    )
    if args.json:
        print(json.dumps(diagnosis.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_report(diagnosis, ledger_dir=ledger_dir)
    return 0


def diagnose(
    *,
    ledger_dir: Path,
    session_id: str = "",
    run_id: str = "",
    task_run_id: str = "",
    provider: str = "deepseek",
    min_prefix_repeats: int = 2,
    limit: int = 12,
) -> Diagnosis:
    token_usage = _filter_rows(
        _dedupe_latest(_read_jsonl(ledger_dir / "token_usage.jsonl"), key_fields=("usage_id",)),
        session_id=session_id,
        run_id=run_id,
        task_run_id=task_run_id,
        provider=provider,
    )
    cache_records = _filter_rows(
        _dedupe_latest(_read_jsonl(ledger_dir / "prompt_cache.jsonl"), key_fields=("cache_record_id",)),
        session_id=session_id,
        run_id=run_id,
        task_run_id=task_run_id,
        provider=provider,
    )
    segment_maps = _filter_rows(
        _read_jsonl(ledger_dir / "segment_maps.jsonl"),
        session_id=session_id,
        run_id=run_id,
        task_run_id=task_run_id,
        provider=provider,
    )
    stability_records = _filter_rows(
        _dedupe_latest(_read_jsonl(ledger_dir / "prompt_stability.jsonl"), key_fields=("report_id",)),
        session_id=session_id,
        run_id=run_id,
        task_run_id=task_run_id,
        provider=provider,
    )
    cache_breaks = _filter_rows(
        _dedupe_latest(_read_jsonl(ledger_dir / "prompt_cache_breaks.jsonl"), key_fields=("break_id",)),
        session_id=session_id,
        run_id=run_id,
        task_run_id=task_run_id,
        provider=provider,
    )

    provider_usage = [row for row in token_usage if str(row.get("source") or "") == "provider_usage"]
    local_predictions = [row for row in token_usage if str(row.get("source") or "") == "local_prediction"]
    usage_by_request = {str(row.get("request_id") or ""): row for row in provider_usage}
    cache_by_request = {str(row.get("request_id") or ""): row for row in cache_records}

    cache_metric_scope_counts = Counter(_cache_metric_scope(row) for row in local_predictions)
    scope_by_request = {str(row.get("request_id") or ""): _cache_metric_scope(row) for row in local_predictions}
    non_agent_request_ids = {
        request_id
        for request_id, scope in scope_by_request.items()
        if scope != "agent_runtime"
    }
    agent_provider_usage = [row for row in provider_usage if str(row.get("request_id") or "") not in non_agent_request_ids]
    scoped_usage = _scope_usage_summary(provider_usage=provider_usage, scope_by_request=scope_by_request)
    unplanned_breaks = [row for row in cache_breaks if str(row.get("reason") or "") == "unplanned_model_call"]
    prompt_tokens = sum(_int(row.get("prompt_tokens")) for row in provider_usage)
    cached_tokens = sum(max(_int(row.get("cached_tokens")), _int(row.get("cache_read_tokens"))) for row in provider_usage)
    cache_miss_tokens = max(0, prompt_tokens - cached_tokens)
    hit_rate = round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0
    agent_prompt_tokens = sum(_int(row.get("prompt_tokens")) for row in agent_provider_usage)
    agent_cached_tokens = sum(max(_int(row.get("cached_tokens")), _int(row.get("cache_read_tokens"))) for row in agent_provider_usage)
    status_counts = Counter(str(row.get("status") or "unknown") for row in cache_records)
    policy_counts = Counter(_provider_cache_policy_mode(row) for row in cache_records)

    prefix_groups = _build_prefix_groups(
        cache_records=cache_records,
        usage_by_request=usage_by_request,
        min_repeats=min_prefix_repeats,
        limit=limit,
    )
    volatile_stable_segments = _find_volatile_stable_segments(segment_maps, limit=limit)
    unstable_stable_segments = _find_unstable_stable_segments(segment_maps, limit=limit)
    stability_by_request = {str(row.get("request_id") or ""): row for row in stability_records}
    recent_requests = _recent_requests(
        cache_records=cache_records,
        usage_by_request=usage_by_request,
        local_predictions=local_predictions,
        stability_by_request=stability_by_request,
        limit=limit,
    )
    stability_reports = _recent_stability_reports(stability_records, limit=limit)
    issues = _build_issues(
        provider_usage=provider_usage,
        cache_records=cache_records,
        prefix_groups=prefix_groups,
        volatile_stable_segments=volatile_stable_segments,
        unstable_stable_segments=unstable_stable_segments,
        hit_rate=hit_rate,
        policy_counts=policy_counts,
        unplanned_breaks=unplanned_breaks,
    )
    summary = {
        "provider": provider or "all",
        "ledger_dir": str(ledger_dir),
        "filters": {
            "session_id": session_id,
            "run_id": run_id,
            "task_run_id": task_run_id,
        },
        "provider_usage_records": len(provider_usage),
        "local_prediction_records": len(local_predictions),
        "cache_records": len(cache_records),
        "segment_maps": len(segment_maps),
        "stability_reports": len(stability_records),
        "cache_break_records": len(cache_breaks),
        "unplanned_model_call_breaks": len(unplanned_breaks),
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "deepseek_cache_hit_rate": hit_rate,
        "agent_runtime_prompt_tokens": agent_prompt_tokens,
        "agent_runtime_cached_tokens": agent_cached_tokens,
        "agent_runtime_cache_miss_tokens": max(0, agent_prompt_tokens - agent_cached_tokens),
        "agent_runtime_deepseek_cache_hit_rate": round(agent_cached_tokens / agent_prompt_tokens, 4) if agent_prompt_tokens > 0 else 0.0,
        "cache_metric_scope_counts": dict(sorted(cache_metric_scope_counts.items())),
        "cache_metric_scope_usage": scoped_usage,
        "cache_status_counts": dict(sorted(status_counts.items())),
        "provider_cache_policy_modes": dict(sorted(policy_counts.items())),
    }
    return Diagnosis(
        summary=summary,
        issues=tuple(issues),
        prefix_groups=tuple(prefix_groups),
        unstable_stable_segments=tuple(unstable_stable_segments),
        volatile_stable_segments=tuple(volatile_stable_segments),
        recent_requests=tuple(recent_requests),
        stability_reports=tuple(stability_reports),
    )


def _default_ledger_dir(base_dir: Path) -> Path:
    project_root = base_dir.parent if base_dir.name == "backend" else base_dir
    return project_root / "storage" / "runtime_state" / "prompt_accounting"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _dedupe_latest(rows: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = "|".join(str(row.get(field) or "") for field in key_fields)
        if not key.strip("|"):
            key = f"{row.get('request_id', '')}|{row.get('created_at', '')}|{len(by_key)}"
        previous = by_key.get(key)
        if previous is None or _float(row.get("created_at")) >= _float(previous.get("created_at")):
            by_key[key] = row
    return sorted(by_key.values(), key=lambda item: _float(item.get("created_at")))


def _filter_rows(
    rows: list[dict[str, Any]],
    *,
    session_id: str,
    run_id: str,
    task_run_id: str,
    provider: str,
) -> list[dict[str, Any]]:
    provider_filter = str(provider or "").strip().lower()
    result: list[dict[str, Any]] = []
    for row in rows:
        if session_id and str(row.get("session_id") or "") != session_id:
            continue
        if run_id and str(row.get("run_id") or row.get("task_run_id") or "") != run_id:
            continue
        if task_run_id and str(row.get("task_run_id") or "") != task_run_id:
            continue
        if provider_filter and str(row.get("provider") or "").strip().lower() != provider_filter:
            continue
        result.append(row)
    return result


def _build_prefix_groups(
    *,
    cache_records: list[dict[str, Any]],
    usage_by_request: dict[str, dict[str, Any]],
    min_repeats: int,
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cache_records:
        key = str(row.get("cache_key") or row.get("prefix_hash") or "")
        if key:
            grouped[key].append(row)

    result: list[dict[str, Any]] = []
    for cache_key, unsorted_records in grouped.items():
        records = sorted(unsorted_records, key=lambda item: _float(item.get("created_at")))
        if len(records) < min_repeats:
            continue
        provider_hits = 0
        provider_misses = 0
        provider_missing = 0
        warmup_provider_misses = 0
        post_warm_provider_hits = 0
        post_warm_provider_misses = 0
        cached_tokens = 0
        prompt_tokens = 0
        post_warm_cached_tokens = 0
        post_warm_prompt_tokens = 0
        statuses = Counter(str(row.get("status") or "unknown") for row in records)
        observed_provider_index = 0
        for row in records:
            usage = usage_by_request.get(str(row.get("request_id") or ""))
            if usage is None:
                provider_missing += 1
                continue
            current_cached = max(_int(usage.get("cached_tokens")), _int(usage.get("cache_read_tokens")))
            current_prompt = _int(usage.get("prompt_tokens"))
            is_warmup_observation = observed_provider_index == 0
            observed_provider_index += 1
            cached_tokens += current_cached
            prompt_tokens += current_prompt
            if current_cached > 0:
                provider_hits += 1
                if not is_warmup_observation:
                    post_warm_provider_hits += 1
                    post_warm_cached_tokens += current_cached
                    post_warm_prompt_tokens += current_prompt
            else:
                provider_misses += 1
                if is_warmup_observation:
                    warmup_provider_misses += 1
                else:
                    post_warm_provider_misses += 1
                    post_warm_prompt_tokens += current_prompt
        result.append(
            {
                "cache_key": cache_key,
                "prefix_hash": str(records[-1].get("prefix_hash") or ""),
                "count": len(records),
                "provider_hits": provider_hits,
                "provider_misses": provider_misses,
                "provider_usage_missing": provider_missing,
                "warmup_provider_misses": warmup_provider_misses,
                "post_warm_provider_hits": post_warm_provider_hits,
                "post_warm_provider_misses": post_warm_provider_misses,
                "cached_tokens": cached_tokens,
                "prompt_tokens": prompt_tokens,
                "hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0,
                "post_warm_cached_tokens": post_warm_cached_tokens,
                "post_warm_prompt_tokens": post_warm_prompt_tokens,
                "post_warm_hit_rate": round(post_warm_cached_tokens / post_warm_prompt_tokens, 4)
                if post_warm_prompt_tokens > 0
                else 0.0,
                "statuses": dict(sorted(statuses.items())),
                "request_ids": [str(row.get("request_id") or "") for row in records[-5:]],
                "latest_created_at": _float(records[-1].get("created_at")),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            int(item["post_warm_provider_misses"]),
            int(item["provider_misses"]),
            int(item["count"]),
            _float(item["latest_created_at"]),
        ),
        reverse=True,
    )[:limit]


def _find_volatile_stable_segments(segment_maps: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for segment_map in segment_maps:
        for segment in _stable_prefix_segments(segment_map):
            metadata = dict(segment.get("metadata") or {})
            if str(metadata.get("cache_impact") or "") == "volatile" or str(metadata.get("volatility_reason") or ""):
                findings.append(
                    {
                        "request_id": str(segment_map.get("request_id") or ""),
                        "packet_ref": str(dict(segment_map.get("metadata") or {}).get("packet_ref") or ""),
                        "kind": str(segment.get("kind") or ""),
                        "ordinal": _int(segment.get("ordinal")),
                        "cache_role": str(segment.get("cache_role") or ""),
                        "predicted_tokens": _int(segment.get("predicted_tokens")),
                        "content_hash": str(segment.get("content_hash") or ""),
                        "volatility_reason": str(metadata.get("volatility_reason") or ""),
                        "dynamic_context_report_ref": str(metadata.get("dynamic_context_report_ref") or ""),
                    }
                )
    return sorted(findings, key=lambda item: int(item["predicted_tokens"]), reverse=True)[:limit]


def _find_unstable_stable_segments(segment_maps: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for segment_map in segment_maps:
        invocation_kind = _packet_invocation_kind(segment_map)
        stability_scope = _stability_scope(segment_map)
        for segment in _stable_prefix_segments(segment_map):
            key = (
                stability_scope,
                invocation_kind,
                str(segment.get("kind") or ""),
                str(segment.get("source") or ""),
            )
            bucket = grouped.setdefault(
                key,
                {
                    "stability_scope": stability_scope,
                    "invocation_kind": invocation_kind,
                    "kind": key[2],
                    "source": key[3],
                    "request_count": 0,
                    "hashes": Counter(),
                    "predicted_tokens": [],
                    "request_ids": [],
                },
            )
            bucket["request_count"] += 1
            bucket["hashes"][str(segment.get("content_hash") or "")] += 1
            bucket["predicted_tokens"].append(_int(segment.get("predicted_tokens")))
            if len(bucket["request_ids"]) < 5:
                bucket["request_ids"].append(str(segment_map.get("request_id") or ""))

    findings: list[dict[str, Any]] = []
    for bucket in grouped.values():
        distinct_hashes = len(bucket["hashes"])
        if distinct_hashes <= 1 or bucket["request_count"] <= 1:
            continue
        token_values = list(bucket["predicted_tokens"])
        findings.append(
            {
                "invocation_kind": bucket["invocation_kind"],
                "stability_scope": bucket["stability_scope"],
                "kind": bucket["kind"],
                "source": bucket["source"],
                "request_count": bucket["request_count"],
                "distinct_content_hashes": distinct_hashes,
                "avg_predicted_tokens": round(sum(token_values) / max(1, len(token_values)), 1),
                "top_hashes": [
                    {"content_hash": content_hash, "count": count}
                    for content_hash, count in bucket["hashes"].most_common(3)
                ],
                "sample_request_ids": list(bucket["request_ids"]),
            }
        )
    return sorted(
        findings,
        key=lambda item: (int(item["distinct_content_hashes"]), float(item["avg_predicted_tokens"])),
        reverse=True,
    )[:limit]


def _recent_requests(
    *,
    cache_records: list[dict[str, Any]],
    usage_by_request: dict[str, dict[str, Any]],
    local_predictions: list[dict[str, Any]],
    stability_by_request: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    local_by_request = {str(row.get("request_id") or ""): row for row in local_predictions}
    rows = sorted(cache_records, key=lambda item: _float(item.get("created_at")), reverse=True)[:limit]
    result: list[dict[str, Any]] = []
    for row in rows:
        request_id = str(row.get("request_id") or "")
        usage = usage_by_request.get(request_id)
        local = local_by_request.get(request_id)
        stability = stability_by_request.get(request_id) or {}
        cached_tokens = max(_int((usage or {}).get("cached_tokens")), _int((usage or {}).get("cache_read_tokens")))
        prompt_tokens = _int((usage or local or {}).get("prompt_tokens"))
        first_changed = dict(stability.get("first_changed_section") or {})
        result.append(
            {
                "request_id": request_id,
                "status": str(row.get("status") or ""),
                "provider_usage": usage is not None,
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0,
                "cache_metric_scope": _cache_metric_scope(local or usage or {}),
                "call_purpose": str(dict((local or usage or {}).get("diagnostics") or {}).get("call_purpose") or ""),
                "provider_global_prefix_tokens": _int(dict(row.get("diagnostics") or {}).get("provider_global_prefix_predicted_tokens")),
                "session_prefix_tokens": _int(dict(row.get("diagnostics") or {}).get("session_prefix_predicted_tokens")),
                "task_prefix_tokens": _int(dict(row.get("diagnostics") or {}).get("task_prefix_predicted_tokens")),
                "stable_prefix_tokens": _int(dict(row.get("diagnostics") or {}).get("stable_prefix_predicted_tokens")),
                "stable_prefix_segments": _int(dict(row.get("diagnostics") or {}).get("stable_prefix_segment_count")),
                "prefix_hash": str(row.get("prefix_hash") or ""),
                "packet_ref": str(dict((usage or local or {}).get("diagnostics") or {}).get("packet_ref") or ""),
                "first_changed_section": _changed_section_label(first_changed),
                "likely_break_reason": str(dict(stability.get("diagnostics") or {}).get("likely_break_reason") or ""),
                "dynamic_param_hash": str(stability.get("dynamic_param_hash") or "")[:19],
                "dynamic_param_diff": _dynamic_param_diff_label(dict(dict(stability.get("diagnostics") or {}).get("dynamic_param_diff") or {})),
            }
        )
    return result


def _recent_stability_reports(records: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = sorted(records, key=lambda item: _float(item.get("created_at")), reverse=True)[:limit]
    result: list[dict[str, Any]] = []
    for row in rows:
        provider_usage = dict(row.get("provider_usage") or {})
        first_changed = dict(row.get("first_changed_section") or {})
        context_window = dict(dict(row.get("diagnostics") or {}).get("context_window") or {})
        result.append(
            {
                "request_id": str(row.get("request_id") or ""),
                "session_cache_key": str(row.get("session_cache_key") or ""),
                "context_window_generation": _int(row.get("context_window_generation")),
                "compaction_generation": _int(row.get("compaction_generation")),
                "stable_prefix_tokens": _int(row.get("stable_prefix_tokens")),
                "provider_global_prefix_tokens": _int(row.get("provider_global_prefix_tokens")),
                "session_prefix_tokens": _int(row.get("session_prefix_tokens")),
                "task_prefix_tokens": _int(row.get("task_prefix_tokens")),
                "stable_section_count": _int(row.get("stable_section_count")),
                "volatile_token_count": _int(row.get("volatile_token_count")),
                "stable_prefix_hash": str(row.get("stable_prefix_hash") or "")[:19],
                "dynamic_param_hash": str(row.get("dynamic_param_hash") or "")[:19],
                "context_recovery_package": "yes" if context_window.get("context_recovery_package_present") else "",
                "active_history_messages": _int(context_window.get("active_history_message_count")),
                "first_changed_section": _changed_section_label(first_changed),
                "likely_break_reason": str(dict(row.get("diagnostics") or {}).get("likely_break_reason") or ""),
                "dynamic_param_diff": _dynamic_param_diff_label(dict(dict(row.get("diagnostics") or {}).get("dynamic_param_diff") or {})),
                "cached_tokens": _int(provider_usage.get("cached_tokens")),
                "hit_rate": _float(provider_usage.get("cache_hit_rate")),
            }
        )
    return result


def _build_issues(
    *,
    provider_usage: list[dict[str, Any]],
    cache_records: list[dict[str, Any]],
    prefix_groups: list[dict[str, Any]],
    volatile_stable_segments: list[dict[str, Any]],
    unstable_stable_segments: list[dict[str, Any]],
    hit_rate: float,
    policy_counts: Counter,
    unplanned_breaks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not provider_usage:
        issues.append(
            {
                "severity": "high",
                "code": "no_provider_usage",
                "message": "没有 provider_usage 记录，无法判断 DeepSeek 真实缓存命中。先确认模型响应 usage 是否被 LangChain 返回并写入账本。",
            }
        )
    if cache_records and policy_counts.get("disabled", 0):
        issues.append(
            {
                "severity": "high",
                "code": "provider_cache_policy_disabled",
                "message": "部分请求的 provider cache policy 为 disabled。DeepSeek 应该是 automatic_prefix；请检查 provider/base_url 是否走官方 DeepSeek 适配。",
                "count": policy_counts.get("disabled", 0),
            }
        )
    if unplanned_breaks:
        high_count = sum(1 for row in unplanned_breaks if str(dict(row.get("diagnostics") or {}).get("severity") or "") == "high")
        issues.append(
            {
                "severity": "high" if high_count else "medium",
                "code": "unplanned_model_call",
                "message": "存在没有 segment_plan 的模型调用。agent 主链路必须通过 RuntimeCompiler 装配；utility 调用也必须显式标注 scope。",
                "count": len(unplanned_breaks),
                "high_count": high_count,
            }
        )
    repeated_miss_groups = [
        group
        for group in prefix_groups
        if int(group.get("post_warm_provider_misses") or 0) > 0 and int(group.get("count") or 0) > 1
    ]
    if repeated_miss_groups:
        issues.append(
            {
                "severity": "high",
                "code": "repeated_prefix_provider_miss",
                "message": "重复 stable prefix 在首个冷启动请求之后仍有 DeepSeek 未命中。优先检查请求间隔、重试路径、真实 base_url、以及 provider usage 是否缺失。",
                "groups": len(repeated_miss_groups),
            }
        )
    if volatile_stable_segments:
        issues.append(
            {
                "severity": "medium",
                "code": "volatile_metadata_inside_stable_prefix",
                "message": "stable prefix 里有标注为 volatile 的动态上下文段。这类段会降低跨轮/跨节点复用概率，应考虑移到 volatile tail 或拆成稳定 baseline + volatile delta。",
                "segments": len(volatile_stable_segments),
            }
        )
    if unstable_stable_segments:
        issues.append(
            {
                "severity": "medium",
                "code": "stable_segment_content_changes",
                "message": "同类 stable segment 在多次请求中 content_hash 变化。若不是任务合同真实变化，就说明 stable 装载里混入了动态字段。",
                "segments": len(unstable_stable_segments),
            }
        )
    if provider_usage and hit_rate < 0.2:
        issues.append(
            {
                "severity": "medium",
                "code": "low_deepseek_cache_hit_rate",
                "message": "DeepSeek provider usage 存在，但总体缓存命中率低于 20%。优先看 stable prefix 是否重复、是否过短、以及 volatile 是否提前进入消息序列。",
                "hit_rate": hit_rate,
            }
        )
    return issues


def _stable_prefix_segments(segment_map: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for segment in list(segment_map.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        if str(segment.get("cache_role") or "") in STABLE_CACHE_ROLES:
            result.append(segment)
            continue
        break
    return result


def _packet_invocation_kind(segment_map: dict[str, Any]) -> str:
    packet_ref = str(dict(segment_map.get("metadata") or {}).get("packet_ref") or "")
    if ":task_execution:" in packet_ref:
        return "task_execution"
    if ":turn_action:" in packet_ref:
        return "turn_action"
    if ":plain_conversation:" in packet_ref:
        return "plain_conversation"
    if ":observation_followup:" in packet_ref:
        return "observation_followup"
    return "unknown"


def _stability_scope(segment_map: dict[str, Any]) -> str:
    task_run_id = str(segment_map.get("task_run_id") or segment_map.get("run_id") or "").strip()
    if task_run_id:
        return f"task:{task_run_id}"
    metadata = dict(segment_map.get("metadata") or {})
    packet_ref = str(metadata.get("packet_ref") or "").strip()
    if packet_ref:
        return f"packet_family:{_packet_family_ref(packet_ref)}"
    session_id = str(segment_map.get("session_id") or "").strip()
    if session_id:
        return f"session:{session_id}"
    return "global"


def _packet_family_ref(packet_ref: str) -> str:
    value = str(packet_ref or "")
    if ":attempt:" in value:
        value = value.split(":attempt:", 1)[0]
    parts = value.split(":")
    if len(parts) > 5:
        return ":".join(parts[:5])
    return value


def _provider_cache_policy_mode(row: dict[str, Any]) -> str:
    policy = dict(dict(row.get("diagnostics") or {}).get("provider_cache_policy") or {})
    return str(policy.get("mode") or "unknown")


def _cache_metric_scope(row: dict[str, Any]) -> str:
    diagnostics = dict(row.get("diagnostics") or {})
    return str(diagnostics.get("cache_metric_scope") or "agent_runtime")


def _scope_usage_summary(
    *,
    provider_usage: list[dict[str, Any]],
    scope_by_request: dict[str, str],
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in provider_usage:
        request_id = str(row.get("request_id") or "")
        scope = scope_by_request.get(request_id) or "agent_runtime"
        bucket = buckets.setdefault(
            scope,
            {
                "provider_usage_records": 0,
                "prompt_tokens": 0,
                "cached_tokens": 0,
                "cache_miss_tokens": 0,
                "deepseek_cache_hit_rate": 0.0,
            },
        )
        prompt_tokens = _int(row.get("prompt_tokens"))
        cached_tokens = max(_int(row.get("cached_tokens")), _int(row.get("cache_read_tokens")))
        bucket["provider_usage_records"] += 1
        bucket["prompt_tokens"] += prompt_tokens
        bucket["cached_tokens"] += cached_tokens
    for bucket in buckets.values():
        prompt_tokens = int(bucket["prompt_tokens"] or 0)
        cached_tokens = int(bucket["cached_tokens"] or 0)
        bucket["cache_miss_tokens"] = max(0, prompt_tokens - cached_tokens)
        bucket["deepseek_cache_hit_rate"] = round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0
    return dict(sorted(buckets.items()))


def _print_report(diagnosis: Diagnosis, *, ledger_dir: Path) -> None:
    payload = diagnosis.to_dict()
    summary = payload["summary"]
    print(f"ledger_dir: {ledger_dir}")
    print(f"provider: {summary['provider']}")
    print(
        "records: "
        f"provider_usage={summary['provider_usage_records']} "
        f"local_prediction={summary['local_prediction_records']} "
        f"cache={summary['cache_records']} "
        f"cache_breaks={summary['cache_break_records']} "
        f"segment_maps={summary['segment_maps']} "
        f"stability={summary['stability_reports']}"
    )
    print(
        "tokens: "
        f"prompt={summary['prompt_tokens']} "
        f"cached={summary['cached_tokens']} "
        f"miss={summary['cache_miss_tokens']} "
        f"deepseek_hit_rate={summary['deepseek_cache_hit_rate']:.2%}"
    )
    print(
        "agent_runtime_tokens: "
        f"prompt={summary['agent_runtime_prompt_tokens']} "
        f"cached={summary['agent_runtime_cached_tokens']} "
        f"miss={summary['agent_runtime_cache_miss_tokens']} "
        f"deepseek_hit_rate={summary['agent_runtime_deepseek_cache_hit_rate']:.2%}"
    )
    print(f"cache_metric_scope_counts: {json.dumps(summary['cache_metric_scope_counts'], ensure_ascii=False, sort_keys=True)}")
    print(f"cache_metric_scope_usage: {json.dumps(summary['cache_metric_scope_usage'], ensure_ascii=False, sort_keys=True)}")
    print(f"unplanned_model_call_breaks: {summary['unplanned_model_call_breaks']}")
    print(f"cache_status_counts: {json.dumps(summary['cache_status_counts'], ensure_ascii=False, sort_keys=True)}")
    print(f"provider_cache_policy_modes: {json.dumps(summary['provider_cache_policy_modes'], ensure_ascii=False, sort_keys=True)}")

    _print_section("issues", payload["issues"], fields=("severity", "code", "message"))
    _print_section(
        "repeated_prefix_groups",
        payload["prefix_groups"],
        fields=("count", "provider_hits", "provider_misses", "provider_usage_missing", "hit_rate", "prompt_tokens", "cached_tokens", "prefix_hash"),
    )
    _print_section(
        "volatile_segments_inside_stable_prefix",
        payload["volatile_stable_segments"],
        fields=("kind", "ordinal", "cache_role", "predicted_tokens", "volatility_reason", "request_id"),
    )
    _print_section(
        "stable_segments_with_changing_hash",
        payload["unstable_stable_segments"],
        fields=("stability_scope", "invocation_kind", "kind", "request_count", "distinct_content_hashes", "avg_predicted_tokens", "source"),
    )
    _print_section(
        "recent_requests",
        payload["recent_requests"],
        fields=("status", "provider_usage", "cache_metric_scope", "call_purpose", "prompt_tokens", "cached_tokens", "hit_rate", "provider_global_prefix_tokens", "session_prefix_tokens", "task_prefix_tokens", "first_changed_section", "dynamic_param_diff", "likely_break_reason", "packet_ref"),
    )
    _print_section(
        "prompt_stability_reports",
        payload["stability_reports"],
        fields=("request_id", "stable_section_count", "provider_global_prefix_tokens", "session_prefix_tokens", "task_prefix_tokens", "stable_prefix_tokens", "volatile_token_count", "hit_rate", "context_window_generation", "compaction_generation", "context_recovery_package", "active_history_messages", "first_changed_section", "dynamic_param_diff", "likely_break_reason"),
    )


def _print_section(title: str, rows: list[dict[str, Any]], *, fields: tuple[str, ...]) -> None:
    print("")
    print(f"{title}:")
    if not rows:
        print("- none")
        return
    for index, row in enumerate(rows, start=1):
        parts = [f"{field}={row.get(field, '')}" for field in fields]
        print(f"- {index}. " + " ".join(parts))


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _changed_section_label(value: dict[str, Any]) -> str:
    if not value:
        return ""
    ordinal = str(value.get("ordinal") or "")
    kind = str(value.get("current_kind") or value.get("previous_kind") or "")
    change_type = str(value.get("change_type") or "")
    if ordinal or kind:
        return f"{ordinal}:{kind}:{change_type}"
    return change_type


def _dynamic_param_diff_label(value: dict[str, Any]) -> str:
    if not value:
        return ""
    return ",".join(sorted(str(key) for key in value)[:8])


if __name__ == "__main__":
    raise SystemExit(main())
