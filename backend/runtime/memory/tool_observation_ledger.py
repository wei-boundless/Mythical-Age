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
    side_effect_hash: str = ""
    evidence_source: str = "structured_envelope"
    debug_hints: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.tool_observation_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["satisfies"] = list(self.satisfies)
        payload["observed_paths"] = list(self.observed_paths)
        payload["matched_paths"] = list(self.matched_paths)
        payload["artifact_refs"] = [dict(item) for item in self.artifact_refs]
        payload["debug_hints"] = dict(self.debug_hints)
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
        side_effect_hash=(
            _side_effect_hash(name=name, args=args, result_text=result_text)
            if side_effect_kind in {"write", "verification"}
            else ""
        ),
        evidence_source=evidence_source,
        debug_hints=debug_hints,
    )


def _side_effect_kind(tool_name: str) -> str:
    if tool_name in {"write_file", "edit_file"}:
        return "write"
    if tool_name in {"terminal", "browser_control"}:
        return "verification"
    if tool_name == "delegate_to_agent":
        return "delegation"
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
        if has_structured_envelope and receipt and _terminal_observation_is_verification(args or {}, result_text, status=status):
            return ("verify_command",)
        return ()
    if tool_name == "browser_control":
        return ("verify_command",)
    if tool_name == "delegate_to_agent":
        return ("delegate_review",)
    return ()


def _terminal_observation_is_verification(args: dict[str, Any], result_text: str, *, status: str) -> bool:
    command = str(args.get("command") or "").lower()
    text = str(result_text or "").lower()
    combined = f"{command}\n{text}"
    verification_markers = (
        "pytest",
        "npm test",
        "pnpm test",
        "yarn test",
        "npm run build",
        "pnpm build",
        "yarn build",
        "tsc",
        "playwright",
        "verification",
        "verify",
        "验证",
        "test-path",
        "testpath",
        "assert",
        "检查",
    )
    output_reference_markers = (
        "index.html",
        "styles.css",
        "game.js",
        "readme.md",
        "assets/",
        "file exists",
        "exists",
        "引用",
        "存在",
    )
    if any(marker in combined for marker in verification_markers):
        return True
    if status == "ok" and any(marker in combined for marker in output_reference_markers) and any(
        marker in command for marker in ("test-path", "get-content", "select-string", "dir ", "ls ", "python", "node", "powershell")
    ):
        return True
    return False


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
