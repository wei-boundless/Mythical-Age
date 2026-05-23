from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any

from .model_runtime import stringify_content


@dataclass(frozen=True, slots=True)
class StructuredSidecarResult:
    payload: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return bool(self.payload)


def model_runtime_supports_structured_sidecars(model_runtime: Any) -> bool:
    return bool(getattr(model_runtime, "supports_structured_sidecars", False) is True)


async def invoke_structured_json_sidecar(
    *,
    invoker: Any,
    request_payload: dict[str, Any],
    sidecar_name: str,
    model_spec: Any | None = None,
) -> StructuredSidecarResult:
    if not callable(invoker):
        return StructuredSidecarResult(
            diagnostics={
                "sidecar_name": sidecar_name,
                "sidecar_status": "not_invoked_no_model_invoker",
                "model_call_performed": False,
            }
        )
    request = dict(request_payload or {})
    role_prompt = str(request.get("role_prompt") or "").strip()
    messages = [
        {
            "role": "system",
            "content": (
                f"{role_prompt}\n"
                "你只能返回一个 JSON object；不要输出 Markdown、解释文字、代码块或工具调用。"
            ).strip(),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "request": request,
                    "output_contract": "Return exactly one JSON object matching the requested schema.",
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        response = await _call_invoker(invoker, messages, model_spec=model_spec)
    except Exception as exc:
        return StructuredSidecarResult(
            diagnostics={
                "sidecar_name": sidecar_name,
                "sidecar_status": "model_call_failed",
                "model_call_performed": True,
                "error_type": exc.__class__.__name__,
                "error": _preview(str(exc) or exc.__class__.__name__),
            }
        )

    raw_text = stringify_content(getattr(response, "content", response)).strip()
    parsed, parse_diagnostics = extract_json_object(raw_text)
    if parsed is None:
        return StructuredSidecarResult(
            diagnostics={
                "sidecar_name": sidecar_name,
                "sidecar_status": "rejected_invalid_json",
                "model_call_performed": True,
                "raw_preview": _preview(raw_text),
                **parse_diagnostics,
            }
        )
    return StructuredSidecarResult(
        payload=parsed,
        diagnostics={
            "sidecar_name": sidecar_name,
            "sidecar_status": "json_parsed",
            "model_call_performed": True,
            "raw_chars": len(raw_text),
            **parse_diagnostics,
        },
    )


def extract_json_object(text: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None, {"json_parse_error": "empty_model_response"}
    candidates = _json_candidates(raw)
    decoder = json.JSONDecoder()
    errors: list[str] = []
    for candidate in candidates:
        value = candidate.strip()
        if not value:
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            errors.append(f"{exc.msg}@{exc.pos}")
            try:
                parsed, end = decoder.raw_decode(value)
            except json.JSONDecodeError:
                continue
            trailing = value[end:].strip()
            if trailing:
                errors.append("trailing_text_after_json_object")
                continue
        if not isinstance(parsed, dict):
            errors.append("json_root_must_be_object")
            continue
        return parsed, {"json_extraction": "object", "json_candidate_count": len(candidates)}
    return None, {
        "json_parse_error": "no_valid_json_object",
        "json_candidate_count": len(candidates),
        "json_errors": errors[:5],
    }


def _json_candidates(text: str) -> list[str]:
    stripped = text.strip()
    candidates = [stripped]
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            candidates.append("\n".join(lines[1:-1]).strip())
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        candidates.append(stripped[first : last + 1])
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


async def _call_invoker(invoker: Any, messages: list[dict[str, str]], *, model_spec: Any | None) -> Any:
    try:
        result = invoker(messages, model_spec=model_spec)
    except TypeError as exc:
        if "model_spec" not in str(exc):
            raise
        result = invoker(messages)
    if inspect.isawaitable(result):
        return await result
    return result


def _preview(text: str, *, limit: int = 500) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."
