from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from execution.tool_result_envelope import _looks_like_failed_command_output, tool_result_envelope_from_payload


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
    side_effect_hash: str = ""
    authority: str = "orchestration.tool_observation_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["satisfies"] = list(self.satisfies)
        payload["observed_paths"] = list(self.observed_paths)
        payload["matched_paths"] = list(self.matched_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
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
            "delegation_count": sum(1 for record in self.records if record.side_effect_kind == "delegation"),
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
        return any(_path_matches(target, observed) for observed in self.observed_paths())

    def has_write(self, path: str = "") -> bool:
        write_records = [record for record in self.records if "write_output" in record.satisfies]
        if not str(path or "").strip():
            return bool(write_records)
        target = _normalize_path(path)
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
) -> ToolObservationRecord:
    name = str(tool_name or "").strip()
    args = dict(tool_args or {})
    result_payload = result if isinstance(result, dict) else {}
    envelope = tool_result_envelope_from_payload(result_payload) if isinstance(result_payload, dict) else None
    if envelope is not None:
        args = dict(envelope.tool_args or args)
        result_text = str(envelope.text or "")
        observed_paths = envelope.observed_paths
        matched_paths = envelope.matched_paths
        artifact_refs = envelope.artifact_refs
        command_receipt = dict(envelope.command_receipt or {})
        status = envelope.status
    else:
        result_text = str(result or "")
        observed_paths = tuple(_paths_from_args(name, args))
        matched_paths = tuple(_matched_paths_from_text(name, result_text))
        artifact_refs = tuple(_artifact_refs_from_text(name, args, result_text))
        command_receipt = _command_receipt_from_text(name, args, result_text)
        status = "error" if _looks_failed(result_text) else "ok"
    side_effect_kind = _side_effect_kind(name)
    satisfies = _satisfies_for_tool(name)
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
        side_effect_hash=(
            _side_effect_hash(name=name, args=args, result_text=result_text)
            if side_effect_kind in {"write", "verification"}
            else ""
        ),
    )


def _side_effect_kind(tool_name: str) -> str:
    if tool_name in {"write_file", "edit_file"}:
        return "write"
    if tool_name == "terminal":
        return "verification"
    if tool_name == "delegate_to_agent":
        return "delegation"
    return "read"


def _satisfies_for_tool(tool_name: str) -> tuple[str, ...]:
    if tool_name in {"read_file", "read_structured_file", "search_text", "search_files", "glob_paths"}:
        return ("read_material",)
    if tool_name in {"write_file", "edit_file"}:
        return ("write_output",)
    if tool_name == "terminal":
        return ("verify_command",)
    if tool_name == "delegate_to_agent":
        return ("delegate_review",)
    return ()


def _side_effect_hash(*, name: str, args: dict[str, Any], result_text: str) -> str:
    raw = repr((name, sorted(args.items()), result_text[:5000]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _paths_from_args(tool_name: str, args: dict[str, Any]) -> list[str]:
    if tool_name in {"read_file", "read_structured_file", "write_file", "edit_file", "stat_path", "path_exists"}:
        return _dedupe([str(args.get("path") or "").strip()])
    return []


def _matched_paths_from_text(tool_name: str, text: str) -> list[str]:
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
        if stripped.startswith("[") and "]" in stripped:
            paths.append(stripped.split("]", 1)[1].strip())
            continue
        candidate = stripped.split(":", 1)[0].strip()
        if ("/" in candidate or "\\" in candidate) and "." in candidate:
            paths.append(candidate)
            continue
        paths.extend(match.group("path").strip() for match in path_pattern.finditer(stripped))
    return _dedupe(paths)


def _artifact_refs_from_text(tool_name: str, args: dict[str, Any], text: str) -> list[dict[str, Any]]:
    if tool_name not in {"write_file", "edit_file"}:
        return []
    path = str(args.get("path") or "").strip()
    if not path:
        return []
    return [{"path": path, "kind": "file", "source": tool_name}]


def _command_receipt_from_text(tool_name: str, args: dict[str, Any], text: str) -> dict[str, Any]:
    if tool_name != "terminal":
        return {}
    status = "error" if _looks_failed(text) else "ok"
    return {
        "command": str(args.get("command") or "").strip(),
        "exit_code": 1 if status == "error" else 0,
        "passed": status != "error",
        "output_preview": str(text or "")[:500],
    }


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
