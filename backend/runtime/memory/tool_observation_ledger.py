from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.tool_runtime.tool_result_envelope import _looks_like_failed_command_output, tool_result_envelope_from_payload


@dataclass(frozen=True, slots=True)
class ToolObservationRecord:
    observation_ref: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    result_preview: str = ""
    side_effect_kind: str = "read"
    satisfies: tuple[str, ...] = ()
    status: str = "ok"
    observed_paths: tuple[str, ...] = ()
    matched_paths: tuple[str, ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    command_receipt: dict[str, Any] = field(default_factory=dict)
    result_metadata: dict[str, Any] = field(default_factory=dict)
    side_effect_hash: str = ""
    evidence_source: str = "structured_envelope"
    debug_hints: dict[str, Any] = field(default_factory=dict)
    runtime_freshness: dict[str, Any] = field(default_factory=dict)
    structured_error: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.tool_observation_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["satisfies"] = list(self.satisfies)
        payload["observed_paths"] = list(self.observed_paths)
        payload["matched_paths"] = list(self.matched_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["debug_hints"] = dict(self.debug_hints)
        payload["runtime_freshness"] = dict(self.runtime_freshness)
        payload["structured_error"] = dict(self.structured_error)
        payload["result_metadata"] = dict(self.result_metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ToolObservationLedger:
    ledger_id: str
    task_run_id: str
    records: tuple[ToolObservationRecord, ...] = ()
    authority: str = "orchestration.tool_observation_ledger"

    def append(self, record: ToolObservationRecord) -> "ToolObservationLedger":
        return ToolObservationLedger(
            ledger_id=self.ledger_id,
            task_run_id=self.task_run_id,
            records=(*self.records, record),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [record.to_dict() for record in self.records]
        return payload

    def summary(self) -> dict[str, Any]:
        return {
            "record_count": len(self.records),
            "read_count": sum(1 for record in self.records if record.side_effect_kind == "read"),
            "write_count": sum(1 for record in self.records if record.side_effect_kind == "write"),
            "verification_count": sum(1 for record in self.records if record.side_effect_kind == "verification"),
            "subagent_lifecycle_count": sum(1 for record in self.records if record.side_effect_kind == "subagent_lifecycle"),
            "observed_paths": self.observed_paths(),
            "matched_paths": self.matched_paths(),
            "artifact_refs": self.artifact_refs(),
            "verification_passed": self.verification_passed(),
            "satisfied_obligations": sorted({item for record in self.records for item in record.satisfies}),
        }

    def observed_paths(self) -> list[str]:
        return _dedupe(
            [
                path
                for record in self.records
                for path in (*record.observed_paths, *record.matched_paths)
            ]
        )

    def matched_paths(self) -> list[str]:
        return _dedupe([path for record in self.records for path in record.matched_paths])

    def artifact_refs(self) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in self.records:
            for ref in record.artifact_refs:
                path = str(dict(ref).get("path") or "").strip()
                key = path or repr(sorted(dict(ref).items()))
                if not key or key in seen:
                    continue
                seen.add(key)
                refs.append(dict(ref))
        return refs

    def has_read(self, path: str = "") -> bool:
        if not str(path or "").strip():
            return any("read_material" in record.satisfies for record in self.records)
        target = _normalize_path(path)
        if _path_is_directory(target):
            return any(_directory_satisfied_by_path(target, observed) for observed in self.observed_paths())
        return any(_path_matches(target, observed) for observed in self.observed_paths())

    def has_write(self, path: str = "") -> bool:
        write_records = [record for record in self.records if "write_output" in record.satisfies]
        if not str(path or "").strip():
            return bool(write_records)
        target = _normalize_path(path)
        if _path_is_directory(target):
            for record in write_records:
                paths = [
                    *record.observed_paths,
                    *(str(ref.get("path") or "") for ref in record.artifact_refs),
                ]
                if any(_directory_satisfied_by_path(target, candidate) for candidate in paths):
                    return True
            return False
        for record in write_records:
            paths = [
                *record.observed_paths,
                *(str(ref.get("path") or "") for ref in record.artifact_refs),
            ]
            if any(_path_matches(target, candidate) for candidate in paths):
                return True
        return False

    def has_verification(self, command_hint: str = "") -> bool:
        hint = str(command_hint or "").strip().lower()
        for record in self.records:
            if "verify_command" not in record.satisfies:
                continue
            if not hint:
                return True
            command = str(record.command_receipt.get("command") or record.tool_args.get("command") or "").lower()
            if hint in command:
                return True
        return False

    def verification_passed(self) -> bool:
        verification_records = [record for record in self.records if "verify_command" in record.satisfies]
        if not verification_records:
            return False
        return any(dict(record.command_receipt or {}).get("passed") is True for record in verification_records)


def build_tool_observation_record(
    *,
    observation_ref: str,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    result: Any = None,
    runtime_fingerprint: dict[str, Any] | None = None,
    structured_error: dict[str, Any] | None = None,
    freshness: dict[str, Any] | None = None,
) -> ToolObservationRecord:
    name = str(tool_name or "").strip()
    args = dict(tool_args or {})
    result_payload = result if isinstance(result, dict) else {}
    envelope = tool_result_envelope_from_payload(result_payload) if isinstance(result_payload, dict) else None
    if envelope is not None:
        args = dict(envelope.tool_args or args)
        result_text = str(envelope.text or "")
        structured_payload = dict(envelope.structured_payload or {})
        observed_paths = envelope.observed_paths
        matched_paths = envelope.matched_paths
        artifact_refs = envelope.artifact_refs
        command_receipt = dict(envelope.command_receipt or {})
        status = envelope.status
    else:
        result_text = str(result or "")
        structured_payload = {}
        observed_paths = tuple(_legacy_observed_paths_from_args(name, args))
        matched_paths = ()
        artifact_refs = ()
        command_receipt = {}
        status = "error" if _looks_failed(result_text) else "ok"
    evidence_source = "structured_envelope" if envelope is not None else "legacy_text"
    debug_hints = (
        {}
        if envelope is not None
        else {
            "legacy_text_preview": result_text[:500],
            "args_paths": _legacy_observed_paths_from_args(name, args),
            "text_path_candidates": _debug_path_candidates_from_text(result_text),
            "hard_evidence_accepted": False,
        }
    )
    recoverable_repair = bool(result_payload.get("recoverable") is True or result_payload.get("repair_kind"))
    result_metadata = _result_metadata_for_tool(
        name=name,
        args=args,
        result_text=result_text,
        status=status,
        structured_payload=structured_payload,
        observed_paths=observed_paths,
    )
    if recoverable_repair:
        side_effect_kind = "repair"
        satisfies = ()
        status = "error"
        observed_paths = ()
        matched_paths = ()
        artifact_refs = ()
    else:
        side_effect_kind = _side_effect_kind(name)
        satisfies = _satisfies_for_tool(
            name,
            args=args,
            result_text=result_text,
            status=status,
            has_structured_envelope=envelope is not None,
            observed_paths=observed_paths,
            artifact_refs=artifact_refs,
            command_receipt=command_receipt,
            structured_payload=structured_payload,
        )
    if name == "browser_control" and "verify_command" in satisfies and not command_receipt:
        command_receipt = {
            "command": str(args.get("action") or "browser_control").strip(),
            "exit_code": 0 if status == "ok" else 1,
            "passed": status == "ok",
            "output_preview": result_text[:500],
        }
    return ToolObservationRecord(
        observation_ref=str(observation_ref or "").strip(),
        tool_name=name,
        tool_args=args,
        result_preview=result_text[:500],
        side_effect_kind=side_effect_kind,
        satisfies=satisfies,
        status=status,
        observed_paths=tuple(observed_paths),
        matched_paths=tuple(matched_paths),
        artifact_refs=tuple(artifact_refs),
        command_receipt=command_receipt,
        result_metadata=result_metadata,
        side_effect_hash=(
            _side_effect_hash(name=name, args=args, result_text=result_text)
            if side_effect_kind in {"write", "verification"}
            else ""
        ),
        evidence_source=evidence_source,
        debug_hints=debug_hints,
        runtime_freshness={
            **({"fingerprint": dict(runtime_fingerprint or {})} if runtime_fingerprint else {}),
            **dict(freshness or {}),
        },
        structured_error=dict(structured_error or {}),
    )


def _result_metadata_for_tool(
    *,
    name: str,
    args: dict[str, Any],
    result_text: str,
    status: str,
    structured_payload: dict[str, Any],
    observed_paths: tuple[str, ...],
) -> dict[str, Any]:
    if name != "read_file" or status != "ok":
        return {}
    tool_result = dict(structured_payload.get("tool_result") or {})
    path = str(tool_result.get("path") or (observed_paths[0] if observed_paths else "") or args.get("path") or "").strip()
    start_line = _int_or_none(tool_result.get("start_line"))
    end_line = _int_or_none(tool_result.get("end_line"))
    returned_lines = _int_or_none(tool_result.get("returned_lines"))
    total_lines = _int_or_none(tool_result.get("total_lines"))
    line_count = _int_or_none(tool_result.get("line_count"))
    next_start_line = _int_or_none(tool_result.get("next_start_line"))
    if start_line is None and end_line is None and returned_lines is None and total_lines is None:
        return {}
    has_more = bool(tool_result.get("has_more") or tool_result.get("truncated"))
    content_range = _drop_empty_dict(
        {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "returned_lines": returned_lines,
            "total_lines": total_lines,
            "line_count": line_count,
            "next_start_line": next_start_line,
            "has_more": has_more,
            "truncated": bool(tool_result.get("truncated") or has_more),
            "content_sha256": str(tool_result.get("content_sha256") or "").strip(),
        }
    )
    if not content_range:
        return {}
    if has_more and next_start_line is not None:
        guidance = (
            f"read_file 已返回 {path} 的第 {start_line} 行到第 {end_line} 行。"
            f"如仍需要后续内容，下一次应使用 start_line={next_start_line} 和 line_count={line_count or ''}；不要重复读取相同行窗口。"
        )
    else:
        guidance = f"read_file 已读到 {path} 的当前可用结尾；不要重复读取相同行窗口。"
    return {
        "content_range": content_range,
        "tool_guidance": guidance,
    }


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _drop_empty_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _side_effect_kind(tool_name: str) -> str:
    if tool_name in {"write_file", "edit_file"}:
        return "write"
    if tool_name in {"terminal", "browser_control"}:
        return "verification"
    if tool_name in {"spawn_subagent", "send_subagent_message", "wait_subagent", "list_subagents", "close_subagent"}:
        return "subagent_lifecycle"
    return "read"


def _satisfies_for_tool(
    tool_name: str,
    *,
    args: dict[str, Any] | None = None,
    result_text: str = "",
    status: str = "ok",
    has_structured_envelope: bool = False,
    observed_paths: tuple[str, ...] = (),
    artifact_refs: tuple[dict[str, Any], ...] = (),
    command_receipt: dict[str, Any] | None = None,
    structured_payload: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    if tool_name in {"read_file", "read_structured_file", "search_text", "search_files", "glob_paths"}:
        if has_structured_envelope and status == "ok" and (observed_paths or tool_name in {"search_text", "search_files", "glob_paths"}):
            return ("read_material",)
        return ()
    if tool_name in {"write_file", "edit_file"}:
        if has_structured_envelope and (artifact_refs or observed_paths) and status == "ok":
            return ("write_output",)
        return ()
    if tool_name == "terminal":
        receipt = dict(command_receipt or {})
        if (
            has_structured_envelope
            and receipt
            and receipt.get("passed") is True
            and _structured_verification_intent(structured_payload)
        ):
            return ("verify_command",)
        return ()
    if tool_name == "browser_control":
        if has_structured_envelope and status == "ok" and _structured_verification_intent(structured_payload):
            return ("verify_command",)
        return ()
    if tool_name in {"spawn_subagent", "send_subagent_message", "wait_subagent", "list_subagents", "close_subagent"}:
        return ("subagent_lifecycle",)
    return ()


def _structured_verification_intent(structured_payload: dict[str, Any] | None) -> bool:
    payload = dict(structured_payload or {})
    intent = dict(payload.get("verification_intent") or {})
    if not intent:
        return False
    return bool(
        str(intent.get("obligation") or "").strip() == "verify_command"
        or str(intent.get("stage") or "").strip() == "verify_output"
        or str(intent.get("required_action") or "").strip() == "verify_command"
    )


def _side_effect_hash(*, name: str, args: dict[str, Any], result_text: str) -> str:
    raw = repr((name, sorted(args.items()), result_text[:5000]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_observed_paths_from_args(tool_name: str, args: dict[str, Any]) -> list[str]:
    if tool_name in {"read_file", "read_structured_file", "stat_path", "path_exists"}:
        return _dedupe([str(args.get("path") or "").strip()])
    return []


def _debug_path_candidates_from_text(text: str) -> list[str]:
    paths: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and "]" in stripped:
            paths.append(stripped.split("]", 1)[1].strip())
            continue
        candidate = stripped.split(":", 1)[0].strip()
        if ("/" in candidate or "\\" in candidate) and "." in candidate:
            paths.append(candidate)
            continue
    return _dedupe(paths)


def _looks_failed(text: str) -> bool:
    lowered = str(text or "").lower()
    if lowered.startswith(("read failed", "structured read failed", "search failed", "write failed", "edit failed", "blocked:", "timed out")):
        return True
    return _looks_like_failed_command_output(lowered)


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


def _normalize_path(path: str) -> str:
    return str(path or "").strip().strip("`'\"“”‘’").replace("\\", "/").lower()


def _path_matches(target: str, candidate: str) -> bool:
    normalized = _normalize_path(candidate)
    if not target or not normalized:
        return False
    target_base = target.rsplit("/", 1)[-1]
    candidate_base = normalized.rsplit("/", 1)[-1]
    return (
        normalized == target
        or normalized.endswith("/" + target)
        or target.endswith("/" + normalized)
        or bool(target_base and target_base == candidate_base)
    )


def _path_is_directory(path: str) -> bool:
    name = str(path or "").strip("/").rsplit("/", 1)[-1]
    return bool(path) and "." not in name


def _directory_satisfied_by_path(directory: str, candidate: str) -> bool:
    target = _normalize_path(directory).strip("/")
    observed = _normalize_path(candidate).strip("/")
    if not target or not observed:
        return False
    return observed == target or observed.startswith(target + "/") or observed.endswith("/" + target) or ("/" + target + "/") in ("/" + observed + "/")


