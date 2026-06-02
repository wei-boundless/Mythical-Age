from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.prompt_accounting.serializer import canonical_json
from runtime.prompt_accounting.token_counter import TokenCounterRegistry


WRITING_MARKERS = (
    "graph.writing.modular_novel",
    "env.creation.writing",
    "graph_node_context",
    "世界观",
    "章节",
    "写作",
)

RUNTIME_FIELD_MARKERS = (
    "task_run_id",
    "graph_run_id",
    "work_order_id",
    "runtime_envelope",
    "state_refs",
    "runtime_controls",
    "observations",
)


@dataclass(frozen=True, slots=True)
class PacketCandidate:
    path: Path
    packet: dict[str, Any]
    chars: int
    marker_count: int


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose real writing graph prompt size, ordering, and DeepSeek cache eligibility."
    )
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parents[1]), help="Backend directory.")
    parser.add_argument("--packet", action="append", default=[], help="Specific runtime packet JSON path to inspect.")
    parser.add_argument(
        "--work-order",
        action="append",
        default=[],
        help="Specific graph_node_work_order runtime object JSON path to recompile with current code before inspecting.",
    )
    parser.add_argument("--scan-limit", type=int, default=20, help="Maximum real writing packets to inspect when scanning.")
    parser.add_argument("--provider", default="deepseek", help="Provider used for local token prediction metadata.")
    parser.add_argument("--model", default="deepseek-v4-pro", help="Model used for local token prediction metadata.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    project_root = base_dir.parent if base_dir.name == "backend" else base_dir
    packets = _load_packet_candidates(
        base_dir=base_dir,
        project_root=project_root,
        explicit_paths=[Path(item) for item in list(args.packet or [])],
        work_order_paths=[Path(item) for item in list(args.work_order or [])],
        scan_limit=max(1, int(args.scan_limit or 1)),
    )
    report = build_report(
        packets=packets,
        ledger_dir=project_root / "storage" / "runtime_state" / "prompt_accounting",
        provider=str(args.provider or ""),
        model=str(args.model or ""),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_report(report)
    return 0


def build_report(
    *,
    packets: list[PacketCandidate],
    ledger_dir: Path,
    provider: str,
    model: str,
) -> dict[str, Any]:
    token_counter = TokenCounterRegistry()
    provider_usage_by_task = _provider_usage_by_task(ledger_dir)
    packet_reports = [
        _packet_report(
            candidate=candidate,
            token_counter=token_counter,
            provider=provider,
            model=model,
            provider_usage_by_task=provider_usage_by_task,
        )
        for candidate in packets
    ]
    issue_counts = Counter(
        issue["code"]
        for packet in packet_reports
        for issue in list(packet.get("issues") or [])
        if isinstance(issue, dict)
    )
    aggregate_segments: dict[str, int] = defaultdict(int)
    aggregate_tokens: dict[str, int] = defaultdict(int)
    for packet in packet_reports:
        for segment in list(packet.get("segments") or []):
            if not isinstance(segment, dict):
                continue
            key = f"{segment.get('ordinal')}:{segment.get('kind')}:{segment.get('prefix_tier')}"
            aggregate_segments[key] += 1
            aggregate_tokens[key] += int(segment.get("predicted_tokens") or 0)
    return {
        "authority": "scripts.diagnose_real_writing_prompt_cache",
        "packet_count": len(packet_reports),
        "ledger_dir": str(ledger_dir),
        "issue_counts": dict(sorted(issue_counts.items())),
        "aggregate_segments": [
            {
                "segment": key,
                "packet_count": aggregate_segments[key],
                "avg_predicted_tokens": round(aggregate_tokens[key] / aggregate_segments[key], 2),
            }
            for key in sorted(aggregate_segments)
        ],
        "packets": packet_reports,
    }


def _load_packet_candidates(
    *,
    base_dir: Path,
    project_root: Path,
    explicit_paths: list[Path],
    work_order_paths: list[Path],
    scan_limit: int,
) -> list[PacketCandidate]:
    if work_order_paths:
        return [
            _candidate_from_packet(
                path=_resolve_path(project_root, path),
                packet=_compile_work_order_packet(base_dir=base_dir, path=_resolve_path(project_root, path)),
            )
            for path in work_order_paths
        ]
    if explicit_paths:
        return [_candidate_from_path(_resolve_path(project_root, path)) for path in explicit_paths]
    roots = [
        project_root / "storage" / "runtime_state" / "event_payloads",
        project_root / "output" / "test_runs",
    ]
    candidates: list[PacketCandidate] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            try:
                candidate = _candidate_from_path(path)
            except ValueError:
                continue
            if candidate.marker_count <= 0:
                continue
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: (item.chars, item.path.stat().st_mtime), reverse=True)[:scan_limit]


def _resolve_path(project_root: Path, path: Path) -> Path:
    if path.is_file():
        return path.resolve()
    candidate = project_root / path
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(path)


def _candidate_from_path(path: Path) -> PacketCandidate:
    payload = _read_json(path)
    packet = _find_packet(payload)
    if packet is None:
        raise ValueError(f"not a runtime packet payload: {path}")
    text = _packet_text(packet)
    return PacketCandidate(
        path=path.resolve(),
        packet=packet,
        chars=len(text),
        marker_count=sum(1 for marker in WRITING_MARKERS if marker in text),
    )


def _candidate_from_packet(*, path: Path, packet: dict[str, Any]) -> PacketCandidate:
    text = _packet_text(packet)
    return PacketCandidate(
        path=path.resolve(),
        packet=packet,
        chars=len(text),
        marker_count=sum(1 for marker in WRITING_MARKERS if marker in text),
    )


def _compile_work_order_packet(*, base_dir: Path, path: Path) -> dict[str, Any]:
    from harness.graph.models import GraphNodeWorkOrder
    from harness.runtime.compiler import RuntimeCompiler
    from harness.graph.work_order_contract import _graph_node_contract_from_work_order

    raw = _read_json(path)
    payload = dict(raw.get("payload") or raw)
    work_order = GraphNodeWorkOrder.from_dict(payload)
    contract = _graph_node_contract_from_work_order(work_order).to_dict()
    task_run = {
        "task_run_id": f"gtask:{_safe_id(work_order.work_order_id)}",
        "session_id": "prompt-cache-real-writing-diagnostic",
        "task_id": work_order.task_ref,
        "task_contract_ref": contract.get("contract_id") or "",
        "owner_agent_seat_id": work_order.node_id,
        "agent_id": work_order.agent_id or "agent:writing_modular_creator",
        "agent_profile_id": work_order.agent_profile_id or "main_interactive_agent",
        "execution_runtime_kind": "single_agent_task",
        "status": "running",
        "diagnostics": {
            "contract": contract,
            "graph_node_id": work_order.node_id,
            "origin_kind": "graph_node_assigned",
        },
    }
    runtime_assembly = {
        "assembly_id": "rtasm:prompt-cache-real-writing-diagnostic",
        "backend_dir": str(base_dir),
        "profile": {
            "profile_ref": work_order.agent_profile_id or "main_interactive_agent",
            "interaction_policy": {"style": "task_execution"},
            "context_policy": {"task_run_context": "disabled"},
            "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            "operation_authorization_projection": {"model_visible": "summary_without_denials"},
        },
        "task_environment": {
            "environment_id": "env.creation.writing",
            "task_environment_id": "env.creation.writing",
        },
        "operation_authorization": {"allowed_operations": [], "denied_operations": []},
    }
    return RuntimeCompiler(base_dir=base_dir).compile_task_execution_packet(
        session_id="prompt-cache-real-writing-diagnostic",
        task_run=task_run,
        contract=contract,
        observations=[],
        runtime_assembly=runtime_assembly,
        invocation_index=1,
    ).packet.to_dict()


def _packet_report(
    *,
    candidate: PacketCandidate,
    token_counter: TokenCounterRegistry,
    provider: str,
    model: str,
    provider_usage_by_task: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    packet = candidate.packet
    messages = [dict(item) for item in list(packet.get("model_messages") or []) if isinstance(item, dict)]
    segment_plan = dict(packet.get("segment_plan") or dict(dict(packet.get("diagnostics") or {}).get("segment_plan") or {}))
    plan_by_index = _plan_by_index(segment_plan)
    segments: list[dict[str, Any]] = []
    prefix_tokens = Counter()
    stable_prefix_open = True
    for index, message in enumerate(messages):
        planned = plan_by_index.get(index, {})
        canonical = canonical_json({"role": str(message.get("role") or ""), "content": str(message.get("content") or "")})
        predicted = token_counter.count_text(canonical, provider=provider, model=model)
        prefix_tier = str(planned.get("prefix_tier") or _fallback_prefix_tier(planned))
        cache_role = str(planned.get("cache_role") or "")
        kind = str(planned.get("kind") or f"message_{index}")
        if stable_prefix_open and cache_role in {"cacheable_prefix", "session_stable"}:
            prefix_tokens["stable_prefix"] += predicted.tokens
        else:
            stable_prefix_open = False
        if prefix_tier in {"provider_global", "session", "task"}:
            prefix_tokens[prefix_tier] += predicted.tokens
        elif prefix_tier in {"volatile", "none"}:
            prefix_tokens[prefix_tier] += predicted.tokens
        segments.append(
            {
                "ordinal": index + 1,
                "role": str(message.get("role") or ""),
                "kind": kind,
                "cache_role": cache_role,
                "prefix_tier": prefix_tier,
                "chars": len(str(message.get("content") or "")),
                "predicted_tokens": predicted.tokens,
                "content_hash": _hash_text(str(message.get("content") or "")),
                "runtime_field_markers": [
                    marker for marker in RUNTIME_FIELD_MARKERS if marker in str(message.get("content") or "")
                ],
                "top_json_fields": _top_json_fields(str(message.get("content") or "")),
            }
        )
    task_run_id = str(packet.get("task_run_id") or "")
    provider_rows = provider_usage_by_task.get(task_run_id, [])
    issues = _packet_issues(segments=segments, provider_rows=provider_rows)
    cache_layer_summary = _cache_layer_summary(segments)
    return {
        "packet_id": str(packet.get("packet_id") or ""),
        "task_run_id": task_run_id,
        "path": str(candidate.path),
        "message_count": len(messages),
        "model_chars": candidate.chars,
        "predicted_prompt_tokens": sum(int(item.get("predicted_tokens") or 0) for item in segments),
        "diagnostics": _packet_diagnostics(segments),
        "cache_layer_summary": cache_layer_summary,
        "prefix_token_summary": dict(sorted(prefix_tokens.items())),
        "segments": segments,
        "provider_usage": provider_rows[-8:],
        "issues": issues,
        "recommendations": _packet_recommendations(segments=segments, cache_layer_summary=cache_layer_summary),
    }


def _packet_diagnostics(segments: list[dict[str, Any]]) -> dict[str, Any]:
    stable_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}
    )
    provider_global_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("prefix_tier") or "") == "provider_global"
    )
    return {
        "provider_global_prefix_under_reports_real_stable_prefix": bool(
            provider_global_tokens and stable_tokens > provider_global_tokens * 4
        ),
        "provider_global_tokens": provider_global_tokens,
        "stable_tokens": stable_tokens,
    }


def _cache_layer_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier: dict[str, int] = defaultdict(int)
    by_kind: dict[str, int] = defaultdict(int)
    stable_prefix_kinds: list[str] = []
    first_nonstable: dict[str, Any] | None = None
    stable_prefix_open = True
    for item in segments:
        tokens = int(item.get("predicted_tokens") or 0)
        tier = str(item.get("prefix_tier") or "none")
        kind = str(item.get("kind") or "")
        by_tier[tier] += tokens
        by_kind[kind] += tokens
        if stable_prefix_open and str(item.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}:
            stable_prefix_kinds.append(kind)
            continue
        if stable_prefix_open:
            first_nonstable = {"kind": kind, "prefix_tier": tier, "predicted_tokens": tokens}
        stable_prefix_open = False
    return {
        "by_prefix_tier_tokens": dict(sorted(by_tier.items())),
        "by_kind_tokens": dict(sorted(by_kind.items(), key=lambda pair: pair[1], reverse=True)),
        "stable_prefix_kinds": stable_prefix_kinds,
        "first_nonstable_segment": first_nonstable or {},
    }


def _packet_recommendations(
    *,
    segments: list[dict[str, Any]],
    cache_layer_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    stable_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}
    )
    kind_tokens = dict(cache_layer_summary.get("by_kind_tokens") or {})
    node_local_tokens = int(kind_tokens.get("task_contract_stable") or 0)
    graph_shared_tokens = int(kind_tokens.get("graph_task_shared_stable") or 0)
    volatile_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("prefix_tier") or "") == "volatile"
    )
    if node_local_tokens and stable_tokens and node_local_tokens / stable_tokens >= 0.5:
        recommendations.append(
            {
                "code": "split_or_summarize_node_local_contract",
                "detail": "节点本地契约占稳定前缀过半。优先压缩 authorized_inputs、memory、loop、output 中只供当前节点使用的大段文本；共享规则应放在 graph_task_shared_stable。",
                "task_contract_tokens": node_local_tokens,
                "stable_tokens": stable_tokens,
            }
        )
    if not graph_shared_tokens:
        recommendations.append(
            {
                "code": "missing_graph_shared_stable_layer",
                "detail": "未发现 graph_task_shared_stable。图任务应把跨节点不变的图级说明放在节点本地契约之前，以便同一图内复用前缀缓存。",
            }
        )
    if volatile_tokens > stable_tokens:
        recommendations.append(
            {
                "code": "reduce_volatile_tail",
                "detail": "动态尾部大于稳定前缀。检查 runtime projection、current state、观察记录是否携带了可摘要或可引用的大段内容。",
                "volatile_tokens": volatile_tokens,
                "stable_tokens": stable_tokens,
            }
        )
    top_kinds = list(dict(cache_layer_summary.get("by_kind_tokens") or {}).items())[:3]
    if top_kinds:
        recommendations.append(
            {
                "code": "largest_cache_layers",
                "detail": "优先优化 token 最大的 prompt 层；不要先动很小的静态层。",
                "top_kinds": [{"kind": str(kind), "predicted_tokens": int(tokens)} for kind, tokens in top_kinds],
            }
        )
    return recommendations


def _packet_issues(*, segments: list[dict[str, Any]], provider_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    stable_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("cache_role") or "") in {"cacheable_prefix", "session_stable"}
    )
    provider_global_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("prefix_tier") or "") == "provider_global"
    )
    volatile_tokens = sum(
        int(item.get("predicted_tokens") or 0)
        for item in segments
        if str(item.get("prefix_tier") or "") == "volatile"
    )
    if volatile_tokens > stable_tokens:
        issues.append(
            {
                "code": "volatile_tail_dominates_prompt",
                "detail": "动态尾部 token 多于稳定前缀，重复请求也难以达到别人那种 cached 远大于 uncached。",
                "volatile_tokens": volatile_tokens,
                "stable_tokens": stable_tokens,
            }
        )
    for item in segments:
        markers = list(item.get("runtime_field_markers") or [])
        if str(item.get("prefix_tier") or "") in {"provider_global", "session", "task"} and markers:
            issues.append(
                {
                    "code": "runtime_fields_in_stable_segment",
                    "segment": item.get("kind"),
                    "prefix_tier": item.get("prefix_tier"),
                    "markers": markers,
                }
            )
    if provider_rows:
        latest = provider_rows[-1]
        prompt_tokens = int(latest.get("prompt_tokens") or 0)
        cached_tokens = max(int(latest.get("cached_tokens") or 0), int(latest.get("cache_read_tokens") or 0))
        if prompt_tokens > 0 and cached_tokens / prompt_tokens < 0.5:
            issues.append(
                {
                    "code": "latest_provider_hit_rate_below_50_percent",
                    "prompt_tokens": prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "hit_rate": round(cached_tokens / prompt_tokens, 4),
                }
            )
    return issues


def _provider_usage_by_task(ledger_dir: Path) -> dict[str, list[dict[str, Any]]]:
    rows = [
        row
        for row in _read_jsonl(ledger_dir / "token_usage.jsonl")
        if str(row.get("source") or "") == "provider_usage"
    ]
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: float(item.get("created_at") or 0.0)):
        task_run_id = str(row.get("task_run_id") or "")
        if not task_run_id:
            continue
        result[task_run_id].append(
            {
                "request_id": str(row.get("request_id") or ""),
                "created_at": float(row.get("created_at") or 0.0),
                "provider": str(row.get("provider") or ""),
                "model": str(row.get("model") or ""),
                "prompt_tokens": int(row.get("prompt_tokens") or 0),
                "cached_tokens": max(int(row.get("cached_tokens") or 0), int(row.get("cache_read_tokens") or 0)),
                "completion_tokens": int(row.get("completion_tokens") or 0),
            }
        )
    return result


def _plan_by_index(segment_plan: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for raw in list(segment_plan.get("segments") or []):
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("model_message_index"))
        except (TypeError, ValueError):
            continue
        result[index] = raw
    return result


def _fallback_prefix_tier(planned: dict[str, Any]) -> str:
    cache_role = str(planned.get("cache_role") or "")
    cache_scope = str(planned.get("cache_scope") or "")
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        if cache_scope == "task":
            return "task"
        if cache_scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "volatile":
        return "volatile"
    return "none"


def _top_json_fields(content: str) -> list[dict[str, Any]]:
    payload = _json_payload_after_title(content)
    if not isinstance(payload, dict):
        return []
    sizes = [
        {
            "field": str(key),
            "chars": len(json.dumps(value, ensure_ascii=False, sort_keys=True)),
        }
        for key, value in payload.items()
    ]
    return sorted(sizes, key=lambda item: int(item["chars"]), reverse=True)[:8]


def _json_payload_after_title(content: str) -> Any | None:
    text = str(content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "\n" in text:
        candidates.append(text.split("\n", 1)[1].strip())
    for candidate in candidates:
        if not candidate or candidate[0] not in "{[":
            continue
        try:
            return json.loads(candidate)
        except JSONDecodeError:
            continue
    return None


def _find_packet(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("model_messages"), list):
            return payload
        if isinstance(payload.get("packet"), dict):
            found = _find_packet(payload.get("packet"))
            if found is not None:
                return found
        if isinstance(payload.get("payload"), dict):
            found = _find_packet(payload.get("payload"))
            if found is not None:
                return found
        for value in payload.values():
            found = _find_packet(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_packet(value)
            if found is not None:
                return found
    return None


def _packet_text(packet: dict[str, Any]) -> str:
    return "".join(
        str(dict(item).get("content") or "")
        for item in list(packet.get("model_messages") or [])
        if isinstance(item, dict)
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))[:160]


def _print_report(report: dict[str, Any]) -> None:
    print(f"packet_count: {report.get('packet_count')}")
    print(f"ledger_dir: {report.get('ledger_dir')}")
    print(f"issue_counts: {json.dumps(report.get('issue_counts') or {}, ensure_ascii=False, sort_keys=True)}")
    print("")
    for packet in list(report.get("packets") or []):
        print(f"packet: {packet.get('packet_id')}")
        print(f"  task_run_id: {packet.get('task_run_id')}")
        print(f"  path: {packet.get('path')}")
        print(f"  chars: {packet.get('model_chars')} predicted_tokens: {packet.get('predicted_prompt_tokens')}")
        print(f"  prefix_tokens: {json.dumps(packet.get('prefix_token_summary') or {}, ensure_ascii=False, sort_keys=True)}")
        print(f"  diagnostics: {json.dumps(packet.get('diagnostics') or {}, ensure_ascii=False, sort_keys=True)}")
        for segment in list(packet.get("segments") or []):
            fields = ", ".join(
                f"{item.get('field')}={item.get('chars')}"
                for item in list(segment.get("top_json_fields") or [])[:4]
            )
            markers = ",".join(list(segment.get("runtime_field_markers") or []))
            print(
                "  - "
                f"{segment.get('ordinal')} {segment.get('kind')} role={segment.get('role')} "
                f"tier={segment.get('prefix_tier')} cache={segment.get('cache_role')} "
                f"tokens={segment.get('predicted_tokens')} chars={segment.get('chars')} "
                f"markers={markers or '-'} fields={fields or '-'}"
            )
        if packet.get("provider_usage"):
            latest = list(packet.get("provider_usage") or [])[-1]
            prompt_tokens = int(latest.get("prompt_tokens") or 0)
            cached_tokens = int(latest.get("cached_tokens") or 0)
            hit = round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0
            print(f"  latest_provider_usage: prompt={prompt_tokens} cached={cached_tokens} hit={hit}")
        if packet.get("issues"):
            print("  issues:")
            for issue in list(packet.get("issues") or []):
                print(f"    - {json.dumps(issue, ensure_ascii=False, sort_keys=True)}")
        print("")


if __name__ == "__main__":
    raise SystemExit(main())
