from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    envelope_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    text: str = ""
    structured_payload: dict[str, Any] = field(default_factory=dict)
    observed_paths: tuple[str, ...] = ()
    matched_paths: tuple[str, ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    command_receipt: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    result_ref: str = ""
    error: str = ""
    authority: str = "execution.tool_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_paths"] = list(self.observed_paths)
        payload["matched_paths"] = list(self.matched_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        return payload


def build_tool_result_envelope(
    *,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    result: Any = None,
    execution_receipt: dict[str, Any] | None = None,
    result_ref: str = "",
    truncated: bool = False,
    sandbox: dict[str, Any] | None = None,
) -> ToolResultEnvelope:
    name = str(tool_name or "").strip()
    args = dict(tool_args or {})
    result_payload = _structured_result_payload(result)
    text = str(result_payload.get("text") if result_payload else result or "")
    status = "error" if _looks_failed(text) else "ok"
    observed_paths = tuple(_observed_paths(name, args, text))
    matched_paths = tuple(_matched_paths(name, text))
    artifact_refs = tuple(_artifact_refs(name, args, text, sandbox=sandbox))
    command_receipt = _command_receipt(name, args, text, status=status)
    structured_payload = {
        "truncated": bool(truncated),
        "sandbox": dict(sandbox or {}),
    }
    if result_payload:
        structured_payload.update(dict(result_payload.get("structured_payload") or {}))
    if matched_paths:
        structured_payload["matched_paths"] = list(matched_paths)
    if observed_paths:
        structured_payload["observed_paths"] = list(observed_paths)
    if artifact_refs:
        structured_payload["artifact_refs"] = [dict(item) for item in artifact_refs]
    if command_receipt:
        structured_payload["command_receipt"] = command_receipt
    return ToolResultEnvelope(
        envelope_id=f"tool-result:{uuid.uuid4().hex[:12]}",
        tool_name=name,
        tool_args=args,
        status=status,
        text=text,
        structured_payload=structured_payload,
        observed_paths=observed_paths,
        matched_paths=matched_paths,
        artifact_refs=artifact_refs,
        command_receipt=command_receipt,
        execution_receipt=dict(execution_receipt or {}),
        result_ref=str(result_ref or ""),
        error=text if status == "error" else "",
    )


def _structured_result_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = dict(result)
    if "structured_payload" not in payload:
        return {}
    return {
        "text": str(payload.get("text") or payload.get("summary") or ""),
        "structured_payload": dict(payload.get("structured_payload") or {}),
    }


def tool_result_envelope_from_payload(payload: dict[str, Any] | None) -> ToolResultEnvelope | None:
    item = dict(payload or {})
    envelope = item.get("result_envelope")
    if isinstance(envelope, dict):
        try:
            return ToolResultEnvelope(
                envelope_id=str(envelope.get("envelope_id") or ""),
                tool_name=str(envelope.get("tool_name") or item.get("tool_name") or ""),
                tool_args=dict(envelope.get("tool_args") or item.get("tool_args") or {}),
                status=str(envelope.get("status") or "ok"),
                text=str(envelope.get("text") or item.get("result") or ""),
                structured_payload=dict(envelope.get("structured_payload") or {}),
                observed_paths=tuple(str(value) for value in list(envelope.get("observed_paths") or []) if str(value).strip()),
                matched_paths=tuple(str(value) for value in list(envelope.get("matched_paths") or []) if str(value).strip()),
                artifact_refs=tuple(dict(value) for value in list(envelope.get("artifact_refs") or []) if isinstance(value, dict)),
                command_receipt=dict(envelope.get("command_receipt") or {}),
                execution_receipt=dict(envelope.get("execution_receipt") or item.get("execution_receipt") or {}),
                result_ref=str(envelope.get("result_ref") or item.get("result_ref") or ""),
                error=str(envelope.get("error") or ""),
            )
        except Exception:
            return None
    return None


def _observed_paths(tool_name: str, args: dict[str, Any], text: str) -> list[str]:
    if tool_name in {"read_file", "read_structured_file", "write_file", "edit_file", "stat_path", "path_exists"}:
        return _dedupe([str(args.get("path") or "").strip()])
    if tool_name == "glob_paths":
        return _dedupe(_extract_plain_paths(text))
    return []


def _matched_paths(tool_name: str, text: str) -> list[str]:
    if tool_name not in {"search_files", "search_text", "glob_paths"}:
        return []
    paths: list[str] = []
    path_pattern = re.compile(
        r"(?P<path>(?:[A-Za-z]:)?(?:[\w.\-\u4e00-\u9fff]+[\\/])+[\w.\-\u4e00-\u9fff ()（）]+?\.[A-Za-z0-9]+)",
        flags=re.IGNORECASE,
    )
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        bracket = re.match(r"^\[\d+\]\s+(?P<path>.+)$", stripped)
        if bracket:
            paths.append(bracket.group("path").strip())
            continue
        search = re.match(r"^(?P<path>[^:\n]+?\.[A-Za-z0-9]+)(?::\d+:\d+:|:\d+:)", stripped)
        if search:
            paths.append(search.group("path").strip())
            continue
        matches = [match.group("path").strip() for match in path_pattern.finditer(stripped)]
        if matches:
            paths.extend(matches)
            continue
        if "/" in stripped or "\\" in stripped:
            candidate = stripped.split(":", 1)[0].strip()
            if "." in candidate:
                paths.append(candidate)
    return _dedupe(paths)


def _artifact_refs(tool_name: str, args: dict[str, Any], text: str, *, sandbox: dict[str, Any] | None) -> list[dict[str, Any]]:
    if tool_name not in {"write_file", "edit_file"}:
        return []
    path = str(args.get("path") or "").strip()
    match = re.search(r"(?:Write|Edit) succeeded:\s*(?P<path>.+)$", str(text or ""), flags=re.IGNORECASE)
    if match:
        path = match.group("path").strip()
    if not path:
        return []
    return [
        {
            "path": path,
            "kind": "file",
            "sandbox": dict(sandbox or {}),
            "source": tool_name,
        }
    ]


def _command_receipt(tool_name: str, args: dict[str, Any], text: str, *, status: str) -> dict[str, Any]:
    if tool_name != "terminal":
        return {}
    command = str(args.get("command") or "").strip()
    exit_code = 1 if status == "error" else 0
    if "timed out" in str(text or "").lower() or "blocked:" in str(text or "").lower():
        exit_code = 1
    return {
        "command": command,
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "output_preview": str(text or "")[:500],
    }


def _extract_plain_paths(text: str) -> list[str]:
    return [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip() and not line.strip().lower().startswith(("no ", "glob failed", "search failed"))
    ]


def _looks_failed(text: str) -> bool:
    lowered = str(text or "").lower()
    if lowered.startswith(("read failed", "structured read failed", "search failed", "write failed", "edit failed", "blocked:", "timed out")):
        return True
    return _looks_like_failed_command_output(lowered)


def _looks_like_failed_command_output(lowered: str) -> bool:
    text = str(lowered or "")
    if not text:
        return False
    failure_needles = (
        "parsererror",
        "parentcontainserrorrecordexception",
        "fullyqualifiederrorid",
        "traceback (most recent call last)",
        "syntaxerror:",
        "exception:",
        "the token '&&' is not a valid statement separator",
        "is not a valid statement separator",
        "commandnotfoundexception",
        "nativecommanderror",
        "exit code 1",
        "exit code: 1",
        "returned non-zero exit status",
        "subprocess.calledprocesserror",
        "= failures =",
        "=== failures ===",
        " failed in ",
        " error in ",
    )
    if any(needle in text for needle in failure_needles):
        return True
    failure_patterns = (
        r"(^|\s)[1-9]\d*\s+failed\b",
        r"(^|\s)[1-9]\d*\s+errors?\b",
        r"\bfailed,\s*[1-9]\d*\s+passed\b",
        r"\b[1-9]\d*\s+passed,\s*[1-9]\d*\s+failed\b",
        r"\berror:\s+",
    )
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in failure_patterns):
        return True
    success_patterns = (
        r"(^|\s)[1-9]\d*\s+passed\b",
        r"\bpassed in \d",
        r"\bno tests ran\b",
    )
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in success_patterns):
        return False
    return False


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip().replace("\\", "/")
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
