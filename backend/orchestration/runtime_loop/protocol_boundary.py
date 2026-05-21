from __future__ import annotations

import re
from dataclasses import asdict, dataclass


_PROTOCOL_MARKERS = (
    "<｜｜DSML｜｜tool_calls>",
    "<｜｜DSML｜｜invoke",
    "<tool_call",
    "</tool_call",
    '"tool_calls"',
    "'tool_calls'",
    "tool_calls",
    "invoke name=",
    "name=\"query\"",
    "name=\"path\"",
    "name=\"command\"",
    "name=\"old_text\"",
    "name=\"new_text\"",
    "name=\"content\"",
    "name=\"read_file\"",
    "name=\"read_structured_file\"",
    "name=\"search_text\"",
    "name=\"search_files\"",
    "name=\"glob_paths\"",
    "name=\"write_file\"",
    "name=\"edit_file\"",
    "name=\"terminal\"",
    "name=\"delegate_to_agent\"",
    "｜｜parameter",
    "｜｜invoke",
)

_TAG_RE = re.compile(
    r"<\s*(?:tool_call|invoke|read_file|read_structured_file|search_text|search_files|glob_paths|"
    r"write_file|edit_file|terminal|delegate_to_agent|｜｜DSML)"
    r"|</\s*(?:tool_call|invoke|read_file|read_structured_file|search_text|search_files|glob_paths|"
    r"write_file|edit_file|terminal|delegate_to_agent)\s*>"
    r"|name=\"(?:query|path|command|old_text|new_text|content|read_file|read_structured_file|search_text|search_files|glob_paths|"
    r"write_file|edit_file|terminal|delegate_to_agent)\"",
    flags=re.IGNORECASE,
)


INTERNAL_PROTOCOL_INPUT_KEYS = frozenset(
    {
        "a2a_payload",
        "graph_unit_runtime_handle",
        "graph_unit_runtime_handle_id",
        "parent_coordination_run_id",
        "parent_dispatch_event_id",
        "parent_graph_id",
        "parent_graph_unit_runtime_handle",
        "parent_node_id",
        "parent_root_task_run_id",
        "parent_source",
        "parent_stage_execution_request",
        "parent_stage_id",
        "parent_stage_idempotency_key",
        "parent_stage_request_id",
        "parent_standard_input_package",
        "parent_task_ref",
        "runtime_assembly",
        "stage_execution_request",
        "standard_input_package",
    }
)

INTERNAL_PROTOCOL_INPUT_PREFIXES = (
    "graph_unit_runtime.",
    "orchestration_protocol.",
    "parent_",
    "runtime_protocol.",
)


@dataclass(frozen=True, slots=True)
class ProtocolLeakResult:
    detected: bool
    markers: tuple[str, ...] = ()
    authority: str = "orchestration.protocol_boundary"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["markers"] = list(self.markers)
        return payload


def protocol_leak_markers() -> tuple[str, ...]:
    return _PROTOCOL_MARKERS


def is_internal_protocol_input_key(key: str) -> bool:
    normalized = str(key or "").strip()
    if normalized in INTERNAL_PROTOCOL_INPUT_KEYS:
        return True
    return normalized.startswith(INTERNAL_PROTOCOL_INPUT_PREFIXES)


def detect_protocol_leak(content: str) -> ProtocolLeakResult:
    text = str(content or "")
    lowered = text.lower()
    markers = [
        marker
        for marker in _PROTOCOL_MARKERS
        if marker in text or marker.lower() in lowered
    ]
    if _TAG_RE.search(text):
        markers.append("tool_protocol_tag")
    return ProtocolLeakResult(
        detected=bool(markers),
        markers=tuple(dict.fromkeys(markers)),
    )


def has_protocol_leak(content: str) -> bool:
    return detect_protocol_leak(content).detected


def strip_protocol_leak(content: str) -> str:
    text = str(content or "").replace("\r\n", "\n")
    for marker in ("<｜｜DSML｜｜tool_calls>", "<｜｜DSML｜｜invoke", "<tool_call"):
        index = text.find(marker)
        if index >= 0:
            text = text[:index]
    lines: list[str] = []
    for line in text.splitlines():
        if detect_protocol_leak(line).detected:
            continue
        lines.append(line)
    return "\n".join(lines).strip()
