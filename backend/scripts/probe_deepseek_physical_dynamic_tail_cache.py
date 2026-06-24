from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.config import get_settings
from runtime.model_gateway.lightweight_chat_model import LightweightChatModel
from runtime.prompt_accounting.serializer import canonical_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe whether replaceable dynamic tail breaks DeepSeek prompt cache reuse "
            "at the physical provider-payload shape."
        )
    )
    parser.add_argument("--live", action="store_true", help="Send the tail scenario to DeepSeek.")
    parser.add_argument("--stable-lines", type=int, default=900, help="Size of deterministic stable prefix.")
    parser.add_argument("--context-chars", type=int, default=1400, help="Chars per appended context chunk.")
    parser.add_argument("--tail-chars", type=int, default=700, help="Chars per volatile dynamic tail.")
    parser.add_argument("--max-output-tokens", type=int, default=32)
    parser.add_argument("--thinking-mode", default="", help="enabled/disabled; empty means project setting.")
    parser.add_argument("--without-tools", action="store_true", help="Do not include native tool sidecar.")
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report path. Defaults to storage/runtime_state/prompt_cache_live_tests.",
    )
    args = parser.parse_args()
    report = build_local_report(args)
    if args.live:
        report["live"] = asyncio.run(run_live_tail_probe(args))
    output_path = _output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(_summary(report, output_path), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_local_report(args: argparse.Namespace) -> dict[str, Any]:
    tools = [] if args.without_tools else _probe_tools()
    scenarios = {
        "append_only_without_dynamic_tail": _append_only_requests(args, include_tail=False),
        "append_only_with_replaceable_dynamic_tail": _append_only_requests(args, include_tail=True),
    }
    scenario_reports = {}
    for name, messages_by_request in scenarios.items():
        bodies = [_provider_body(messages, tools=tools, stream=False, max_output_tokens=args.max_output_tokens) for messages in messages_by_request]
        scenario_reports[name] = {
            "request_shapes": [_request_shape(body) for body in bodies],
            "pairwise_message_prefix": [
                _compare_bodies(bodies[index - 1], bodies[index], messages_only=True)
                for index in range(1, len(bodies))
            ],
            "pairwise_full_physical_prefix": [
                _compare_bodies(bodies[index - 1], bodies[index], messages_only=False)
                for index in range(1, len(bodies))
            ],
        }
    return {
        "authority": "backend.scripts.probe_deepseek_physical_dynamic_tail_cache",
        "live_enabled": bool(args.live),
        "with_native_tools": bool(tools),
        "stable_lines": int(args.stable_lines or 0),
        "context_chars": int(args.context_chars or 0),
        "tail_chars": int(args.tail_chars or 0),
        "physical_model": (
            "message prefix is messages in order. Full physical sequence is messages in order, "
            "then native tools sidecar, then cache-sensitive request params. Dynamic tail is intentionally the last message."
        ),
        "scenarios": scenario_reports,
        "interpretation": {
            "rule": (
                "If previous_messages_are_prefix_of_current is false in the tail scenario, the model-visible message prefix moved. "
                "If previous_full_input_is_prefix_of_current is false only after tools, the sidecar sits after messages and prevents "
                "the whole provider request from being a strict append-only physical sequence. "
                "It may still persist the common prefix after comparing requests, so the benefit lags by a later request."
            ),
            "expected_tail_effect": (
                "S+C1+T1 -> S+C1+C2+T2 shares S+C1, but the previous full payload is not the current prefix "
                "because T1 occupied the append point before C2 existed."
            ),
        },
    }


async def run_live_tail_probe(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    if str(settings.llm_provider or "").strip().lower() != "deepseek":
        raise RuntimeError(f"live probe requires deepseek provider, got {settings.llm_provider!r}")
    if not settings.llm_api_key:
        raise RuntimeError("DeepSeek API key is not configured.")
    thinking_mode = str(args.thinking_mode or settings.llm_thinking_mode or "disabled").strip().lower()
    tools = [] if args.without_tools else _probe_tools()
    model = LightweightChatModel(
        provider="deepseek",
        model=str(settings.llm_model or "deepseek-v4-flash"),
        api_key=settings.llm_api_key,
        base_url=str(settings.llm_base_url or "https://api.deepseek.com"),
        timeout_seconds=min(60.0, float(settings.llm_timeout_seconds or 45.0)),
        max_output_tokens=max(1, int(args.max_output_tokens or 32)),
        output_token_parameter="max_tokens",
        temperature=0,
        extra_body={"thinking": {"type": "enabled" if thinking_mode == "enabled" else "disabled"}},
        tools=tools,
        tool_bind_kwargs={"tool_choice": "none"} if tools else {},
    )
    messages_by_request = _append_only_requests(args, include_tail=True)
    calls: list[dict[str, Any]] = []
    try:
        for index, messages in enumerate(messages_by_request, start=1):
            started = time.time()
            response = await model.ainvoke(messages)
            raw = dict(getattr(response, "raw_response", {}) or {})
            usage = dict(raw.get("usage") or {})
            calls.append(
                {
                    "index": index,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "message_count": len(messages),
                    "usage": _usage_projection(usage),
                    "finish_reason": _finish_reason(raw),
                }
            )
            await asyncio.sleep(1.0)
    finally:
        await model.close()
    return {
        "provider": "deepseek",
        "model": str(settings.llm_model or ""),
        "thinking_mode": thinking_mode,
        "with_native_tools": bool(tools),
        "scenario": "append_only_with_replaceable_dynamic_tail",
        "calls": calls,
        "cache_read_pattern": _cache_read_pattern(calls),
    }


def _append_only_requests(args: argparse.Namespace, *, include_tail: bool) -> list[list[dict[str, Any]]]:
    stable = _stable_prefix(int(args.stable_lines or 900))
    chunks = [_context_chunk(index, int(args.context_chars or 1400)) for index in range(1, 4)]
    requests: list[list[dict[str, Any]]] = []
    for request_index in range(1, 4):
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": stable},
            *({"role": "user", "content": chunk} for chunk in chunks[:request_index]),
        ]
        if include_tail:
            messages.append({"role": "user", "content": _dynamic_tail(request_index, int(args.tail_chars or 700))})
        requests.append(messages)
    return requests


def _provider_body(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    stream: bool,
    max_output_tokens: int,
) -> dict[str, Any]:
    model = LightweightChatModel(
        provider="deepseek",
        model="deepseek-physical-probe",
        api_key="",
        base_url="https://api.deepseek.com",
        timeout_seconds=30,
        max_output_tokens=max(1, int(max_output_tokens or 32)),
        output_token_parameter="max_tokens",
        temperature=0,
        extra_body={"thinking": {"type": "disabled"}},
        tools=tools,
        tool_bind_kwargs={"tool_choice": "none"} if tools else {},
    )
    return model._request_body(messages, stream=stream)


def _request_shape(body: dict[str, Any]) -> dict[str, Any]:
    sequence = _provider_ordered_sequence(body)
    return {
        "message_count": len(list(body.get("messages") or [])),
        "has_tools_sidecar": bool(body.get("tools")),
        "sequence_segment_count": len(sequence),
        "sequence": [
            {
                "ordinal": index + 1,
                "location": item["location"],
                "label": item["label"],
                "chars": len(item["payload"]),
                "hash": _short_hash(item["payload"]),
            }
            for index, item in enumerate(sequence)
        ],
    }


def _compare_bodies(previous: dict[str, Any], current: dict[str, Any], *, messages_only: bool) -> dict[str, Any]:
    previous_sequence = _provider_ordered_sequence(previous, messages_only=messages_only)
    current_sequence = _provider_ordered_sequence(current, messages_only=messages_only)
    common = 0
    for left, right in zip(previous_sequence, current_sequence):
        if left["payload"] != right["payload"] or left["location"] != right["location"]:
            break
        common += 1
    previous_full_is_prefix = len(previous_sequence) <= len(current_sequence) and all(
        previous_sequence[index]["payload"] == current_sequence[index]["payload"]
        and previous_sequence[index]["location"] == current_sequence[index]["location"]
        for index in range(len(previous_sequence))
    )
    first_diff = {}
    if common < max(len(previous_sequence), len(current_sequence)):
        first_diff = {
            "ordinal": common + 1,
            "previous": _segment_summary(previous_sequence[common]) if common < len(previous_sequence) else {},
            "current": _segment_summary(current_sequence[common]) if common < len(current_sequence) else {},
        }
    return {
        "previous_segment_count": len(previous_sequence),
        "current_segment_count": len(current_sequence),
        "common_leading_segments": common,
        (
            "previous_messages_are_prefix_of_current"
            if messages_only
            else "previous_full_input_is_prefix_of_current"
        ): previous_full_is_prefix,
        "first_diff": first_diff,
    }


def _provider_ordered_sequence(body: dict[str, Any], *, messages_only: bool = False) -> list[dict[str, str]]:
    sequence: list[dict[str, str]] = []
    for index, message in enumerate(list(body.get("messages") or []), start=1):
        payload = canonical_json(message)
        sequence.append(
            {
                "location": "messages",
                "label": f"message:{index}:{str(dict(message).get('role') or '')}",
                "payload": payload,
            }
        )
    if messages_only:
        return sequence
    if body.get("tools"):
        sequence.append(
            {
                "location": "tools",
                "label": "native_tool_binding_schema",
                "payload": canonical_json({"tools": body.get("tools")}),
            }
        )
    for key in ("tool_choice", "parallel_tool_calls", "response_format", "thinking"):
        if key in body:
            sequence.append(
                {
                    "location": "request_params",
                    "label": key,
                    "payload": canonical_json({key: body.get(key)}),
                }
            )
    return sequence


def _segment_summary(segment: dict[str, str]) -> dict[str, Any]:
    return {
        "location": segment.get("location", ""),
        "label": segment.get("label", ""),
        "chars": len(segment.get("payload", "")),
        "hash": _short_hash(segment.get("payload", "")),
    }


def _stable_prefix(lines: int) -> str:
    count = max(1, int(lines or 1))
    rows = [
        "你是一名严格执行上下文缓存探针的 agent。稳定前缀里的每个字节都必须保持不变。每次只回复 OK，不要解释，不要调用工具。",
        "下面是稳定事实表，用于制造可复用的 provider prompt prefix。",
    ]
    for index in range(1, count + 1):
        rows.append(
            f"STABLE_FACT_{index:04d}: cache probe invariant text; provider-visible prefix byte order must remain fixed."
        )
    return "\n".join(rows)


def _context_chunk(index: int, chars: int) -> str:
    unit = (
        f"APPEND_ONLY_CONTEXT_CHUNK_{index}: "
        "这是已经发生并会在后续轮次锁死的上下文增量。"
        "它应该追加在旧上下文之后，下一轮不得移动、不得改写。"
    )
    return _repeat_to_length(unit, max(1, int(chars or 1)))


def _dynamic_tail(index: int, chars: int) -> str:
    unit = (
        f"VOLATILE_DYNAMIC_TAIL_{index}: "
        "这是本轮执行游标和控制契约，只能位于请求末尾；它允许变化，不应插入旧上下文之前。只回复 OK。"
    )
    return _repeat_to_length(unit, max(1, int(chars or 1)))


def _repeat_to_length(unit: str, target_chars: int) -> str:
    parts: list[str] = []
    while len("\n".join(parts)) < target_chars:
        parts.append(unit)
    return "\n".join(parts)[:target_chars]


def _probe_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "cache_probe_noop",
            "description": "No-op probe tool. The model must not call this tool during cache probing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string"},
                },
                "required": ["note"],
                "additionalProperties": False,
            },
        }
    ]


def _usage_projection(usage: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = _int(usage.get("prompt_tokens"))
    cached_tokens = max(
        _int(usage.get("prompt_cache_hit_tokens")),
        _int(usage.get("cache_read_tokens")),
        _int(dict(usage.get("prompt_tokens_details") or {}).get("cached_tokens")),
    )
    miss_tokens = max(_int(usage.get("prompt_cache_miss_tokens")), max(0, prompt_tokens - cached_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "cache_miss_tokens": miss_tokens,
        "hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "raw_keys": sorted(str(key) for key in usage.keys()),
    }


def _cache_read_pattern(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "hit_rates": [dict(call.get("usage") or {}).get("hit_rate", 0.0) for call in calls],
        "cached_tokens": [dict(call.get("usage") or {}).get("cached_tokens", 0) for call in calls],
        "prompt_tokens": [dict(call.get("usage") or {}).get("prompt_tokens", 0) for call in calls],
    }


def _finish_reason(raw: dict[str, Any]) -> str:
    choices = list(raw.get("choices") or [])
    if not choices:
        return ""
    return str(dict(choices[0]).get("finish_reason") or "")


def _output_path(raw: str) -> Path:
    if raw:
        return Path(raw).resolve()
    filename = f"deepseek_dynamic_tail_physical_probe_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.json"
    return (BACKEND_DIR.parent / "storage" / "runtime_state" / "prompt_cache_live_tests" / filename).resolve()


def _summary(report: dict[str, Any], output_path: Path) -> dict[str, Any]:
    tail = dict(dict(report.get("scenarios") or {}).get("append_only_with_replaceable_dynamic_tail") or {})
    no_tail = dict(dict(report.get("scenarios") or {}).get("append_only_without_dynamic_tail") or {})
    live = dict(report.get("live") or {})
    return {
        "report_path": str(output_path),
        "with_native_tools": bool(report.get("with_native_tools")),
        "no_tail_messages_prefix": [
            bool(item.get("previous_messages_are_prefix_of_current"))
            for item in list(no_tail.get("pairwise_message_prefix") or [])
        ],
        "no_tail_full_physical_prefix": [
            bool(item.get("previous_full_input_is_prefix_of_current"))
            for item in list(no_tail.get("pairwise_full_physical_prefix") or [])
        ],
        "tail_messages_prefix": [
            bool(item.get("previous_messages_are_prefix_of_current"))
            for item in list(tail.get("pairwise_message_prefix") or [])
        ],
        "tail_full_physical_prefix": [
            bool(item.get("previous_full_input_is_prefix_of_current"))
            for item in list(tail.get("pairwise_full_physical_prefix") or [])
        ],
        "tail_common_leading_segments": [
            int(item.get("common_leading_segments") or 0)
            for item in list(tail.get("pairwise_message_prefix") or [])
        ],
        "live_cache_read_pattern": dict(live.get("cache_read_pattern") or {}),
    }


def _short_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

