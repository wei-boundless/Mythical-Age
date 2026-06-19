from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .assembly_plan import PromptAssemblyPlan


@dataclass(frozen=True, slots=True)
class PromptMaterializedPacket:
    packet_id: str
    invocation_kind: str
    assembly_plan_id: str
    message_specs: tuple[dict[str, Any], ...] = ()
    model_messages: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "prompt_composition.materialized_packet"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["message_specs"] = [dict(item) for item in self.message_specs]
        payload["model_messages"] = [dict(item) for item in self.model_messages]
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


def materialize_prompt_packet(
    *,
    assembly_plan: PromptAssemblyPlan,
) -> PromptMaterializedPacket:
    specs: list[dict[str, Any]] = []
    model_messages: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for slot in tuple(assembly_plan.slots or ()):
        spec = dict(slot.message_spec or {})
        metadata = dict(spec.get("metadata") or {})
        metadata.update(
            {
                "prompt_assembly_plan_id": assembly_plan.plan_id,
                "prompt_assembly_slot_id": slot.slot_id,
                "prompt_assembly_source_id": slot.source_id,
                "prompt_assembly_authority": assembly_plan.authority,
            }
        )
        spec["metadata"] = metadata
        spec["role"] = str(spec.get("role") or slot.target_role or "user")
        spec["kind"] = str(spec.get("kind") or slot.slot_kind or "unknown_unplanned")
        spec["source_ref"] = str(spec.get("source_ref") or slot.source_ref or "")
        spec["cache_scope"] = slot.cache_scope
        spec["cache_role"] = slot.cache_role
        spec["prefix_tier"] = slot.prefix_tier
        spec["compression_role"] = slot.compression_role
        model_message = _model_message_from_spec(spec)
        spec["content"] = str(model_message.get("content") or spec.get("content") or "")
        spec["model_message"] = model_message
        actual_model_hash = _stable_text_hash(_stable_json(model_message))
        if slot.model_message_hash and actual_model_hash != slot.model_message_hash:
            mismatches.append(
                {
                    "slot_id": slot.slot_id,
                    "kind": slot.slot_kind,
                    "planned_model_message_hash": slot.model_message_hash,
                    "materialized_model_message_hash": actual_model_hash,
                }
            )
        specs.append(spec)
        model_messages.append(model_message)
    seed = {
        "assembly_plan_id": assembly_plan.plan_id,
        "messages": [_stable_json(message) for message in model_messages],
    }
    return PromptMaterializedPacket(
        packet_id=assembly_plan.packet_id,
        invocation_kind=assembly_plan.invocation_kind,
        assembly_plan_id=assembly_plan.plan_id,
        message_specs=tuple(specs),
        model_messages=tuple(model_messages),
        diagnostics={
            "message_count": len(model_messages),
            "segment_count": len(specs),
            "materialized_hash": "sha256:" + _stable_hash(seed),
            "model_message_hash_mismatches": mismatches,
            "authority": "prompt_composition.materializer",
        },
    )


def _model_message_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    raw_message = spec.get("model_message") if isinstance(spec.get("model_message"), dict) else spec
    role = str(raw_message.get("role") or spec.get("role") or "user").strip() or "user"
    message: dict[str, Any] = {
        "role": role,
        "content": str(raw_message.get("content") if raw_message.get("content") is not None else spec.get("content") or ""),
    }
    for key in ("name", "tool_call_id"):
        value = str(raw_message.get(key) or spec.get(key) or "").strip()
        if value:
            message[key] = value
    tool_calls = raw_message.get("tool_calls") if raw_message.get("tool_calls") is not None else spec.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        message["tool_calls"] = [dict(item) for item in tool_calls if isinstance(item, dict)]
    reasoning_content = str(
        raw_message.get("reasoning_content")
        if raw_message.get("reasoning_content") is not None
        else spec.get("reasoning_content")
        or ""
    ).strip()
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    prefix = raw_message.get("prefix") if raw_message.get("prefix") is not None else spec.get("prefix")
    if prefix is True or str(prefix or "").strip().lower() == "true":
        message["prefix"] = True
    return message


def _stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8", errors="ignore")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
