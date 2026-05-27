from __future__ import annotations

from typing import Any, Callable

from response_system.boundary.boundary import sanitize_visible_assistant_content
from response_system.models.output_models import ToolResultEnvelope
from runtime.model_gateway.model_runtime import stringify_content
from capability_system.tool_definitions import get_tool_definition_map


VISIBLE_TEXT_KEYS = ("answer", "summary", "result", "output", "text", "content")


def build_tool_result_envelope(
    output: Any,
    *,
    tool_name: str,
    stringify_output: Callable[[Any], str] | None = None,
) -> ToolResultEnvelope:
    definition = get_tool_definition_map().get(str(tool_name or "").strip())
    output_contract = getattr(definition, "output_contract", None)
    display_mode = str(getattr(output_contract, "display_mode", "") or "summary_text").strip()
    finalization_policy = str(getattr(output_contract, "finalization_policy", "") or "none").strip()
    persistence_policy = str(getattr(output_contract, "persistence_policy", "") or "persist_canonical").strip()

    raw_text = (
        stringify_output(output)
        if stringify_output is not None
        else _default_stringify_output(output)
    ).strip()
    display_text, structured_visible = _extract_display_text(output, raw_text=raw_text)
    allow_unlabeled = structured_visible or display_mode in {"verbatim_text", "summary_text"}
    if display_mode in {"artifact_only", "raw_debug_only"}:
        allow_unlabeled = False
    return ToolResultEnvelope(
        tool_name=str(tool_name or "").strip(),
        raw_text=raw_text,
        display_text=display_text,
        display_mode=display_mode,
        finalization_policy=finalization_policy,
        persistence_policy=persistence_policy,
        allow_unlabeled_answer=allow_unlabeled,
        metadata={
            "output_contract_display_mode": display_mode,
            "output_contract_finalization_policy": finalization_policy,
            "output_contract_persistence_policy": persistence_policy,
        },
    )


def _extract_display_text(output: Any, *, raw_text: str) -> tuple[str, bool]:
    if isinstance(output, dict):
        for key in VISIBLE_TEXT_KEYS:
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return sanitize_visible_assistant_content(value).strip(), True
    return raw_text, False


def _default_stringify_output(output: Any) -> str:
    normalized = stringify_content(output)
    if isinstance(normalized, str):
        return sanitize_visible_assistant_content(normalized).strip()
    return sanitize_visible_assistant_content(str(normalized)).strip()


