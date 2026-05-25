from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..memory.tool_observation_ledger import ToolObservationLedger
from .goal_contract import ProfessionalTaskGoalContract, _dedupe_strings, _normalize_path_for_match


@dataclass(frozen=True, slots=True)
class DeliverableObligation:
    obligation_id: str
    kind: str
    suggested_tool_names: tuple[str, ...]
    path: str = ""
    satisfied: bool = False
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["suggested_tool_names"] = list(self.suggested_tool_names)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class DeliverableProgress:
    obligations: tuple[DeliverableObligation, ...]
    next_missing_deliverable: DeliverableObligation | None = None
    authority: str = "orchestration.professional_deliverable_progress"

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligations": [obligation.to_dict() for obligation in self.obligations],
            "next_missing_deliverable": (
                self.next_missing_deliverable.to_dict() if self.next_missing_deliverable is not None else None
            ),
            "missing_obligations": list(self.missing_obligations()),
            "suggested_tool_names": list(self.suggested_tool_names()),
            "authority": self.authority,
        }

    def missing_obligations(self) -> tuple[str, ...]:
        return tuple(_obligation_label(obligation) for obligation in self.obligations if not obligation.satisfied)

    def suggested_tool_names(self) -> tuple[str, ...]:
        if self.next_missing_deliverable is None:
            return ()
        return self.next_missing_deliverable.suggested_tool_names

    def current_path(self) -> str:
        return self.next_missing_deliverable.path if self.next_missing_deliverable is not None else ""

    def progress_hint(self) -> str:
        if self.next_missing_deliverable is None:
            return ""
        obligation = self.next_missing_deliverable
        if obligation.path:
            return f"当前缺失交付物：{obligation.path}。建议优先补齐该产物，但不限制模型选择工具。"
        return f"当前缺失交付物：{_obligation_label(obligation)}。建议优先补齐，但不限制模型选择工具。"


def next_missing_material_read(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> DeliverableObligation | None:
    if not goal_contract.requires_material_review:
        return None
    if not goal_contract.required_material_paths:
        return (
            None
            if tool_observation_ledger.has_read()
            else DeliverableObligation(
                obligation_id="read:any",
                kind="read_material",
                suggested_tool_names=("read_file", "read_structured_file", "search_files", "search_text"),
            )
        )
    for path in list(goal_contract.required_material_paths or []):
        normalized_path = str(path or "").strip().replace("\\", "/")
        if normalized_path and not tool_observation_ledger.has_read(normalized_path):
            return DeliverableObligation(
                obligation_id=f"read:{normalized_path}",
                kind="read_material",
                suggested_tool_names=("read_file", "read_structured_file"),
                path=normalized_path,
            )
    return None


def build_deliverable_progress(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> DeliverableProgress:
    obligations: list[DeliverableObligation] = []
    for path in list(goal_contract.required_output_paths or []):
        normalized_path = str(path or "").strip().replace("\\", "/")
        is_directory = normalized_path.endswith("/") or "." not in normalized_path.rsplit("/", 1)[-1]
        if is_directory:
            keep_path = normalized_path.strip("/") + "/.keep"
            satisfied = tool_observation_ledger.has_write(keep_path) or any(
                _path_matches(normalized_path, observed)
                for observed in tool_observation_ledger.observed_paths()
            )
            obligations.append(
                DeliverableObligation(
                    obligation_id=f"ensure_dir:{normalized_path.strip('/')}",
                    kind="ensure_dir",
                    suggested_tool_names=("write_file",),
                    path=keep_path,
                    satisfied=satisfied,
                    evidence_refs=_refs_for(tool_observation_ledger, "write_output"),
                )
            )
            continue
        evidence_refs = tuple(
            record.observation_ref
            for record in tool_observation_ledger.records
            if record.observation_ref and "write_output" in record.satisfies and tool_observation_ledger.has_write(normalized_path)
        )
        obligations.append(
            DeliverableObligation(
                obligation_id=f"write:{normalized_path}",
                kind="write_output",
                suggested_tool_names=("write_file",),
                path=normalized_path,
                satisfied=tool_observation_ledger.has_write(normalized_path),
                evidence_refs=evidence_refs,
            )
        )
    if goal_contract.requires_write_output and not goal_contract.required_output_paths:
        obligations.append(
            DeliverableObligation(
                obligation_id="write:any",
                kind="write_output",
                suggested_tool_names=("write_file", "edit_file"),
                satisfied=tool_observation_ledger.has_write(),
                evidence_refs=_refs_for(tool_observation_ledger, "write_output"),
            )
        )
    if goal_contract.requires_verification_command:
        writes_satisfied = all(obligation.satisfied for obligation in obligations if obligation.kind in {"write_output", "ensure_dir"})
        obligations.append(
            DeliverableObligation(
                obligation_id="verify:terminal",
                kind="verify_command",
                suggested_tool_names=("browser_control", "terminal"),
                satisfied=bool(writes_satisfied and tool_observation_ledger.verification_passed()),
                evidence_refs=_refs_for(tool_observation_ledger, "verify_command"),
            )
        )
    next_missing = next((obligation for obligation in obligations if not obligation.satisfied), None)
    return DeliverableProgress(obligations=tuple(obligations), next_missing_deliverable=next_missing)


def _refs_for(ledger: ToolObservationLedger, obligation_key: str) -> tuple[str, ...]:
    return tuple(
        record.observation_ref
        for record in ledger.records
        if obligation_key in record.satisfies and record.observation_ref
    )


def goal_contract_targets_code_edit(goal_contract: ProfessionalTaskGoalContract) -> bool:
    code_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
    candidate_paths = [
        *list(goal_contract.required_material_paths or []),
        *list(goal_contract.required_output_paths or []),
    ]
    if any(_normalize_path_for_match(path).endswith(code_suffixes) for path in candidate_paths):
        return True
    return any(
        str(kind or "").strip().lower() in {"code", "python", "typescript", "javascript"}
        for kind in goal_contract.material_types
    )


def required_writes_satisfied(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if not goal_contract.requires_write_output:
        return True
    if not goal_contract.required_output_paths:
        return tool_observation_ledger.has_write()
    deliverable_progress = build_deliverable_progress(
        goal_contract=goal_contract,
        tool_observation_ledger=tool_observation_ledger,
    )
    return all(
        obligation.satisfied
        for obligation in deliverable_progress.obligations
        if obligation.kind in {"write_output", "ensure_dir"}
    )


def material_review_satisfied(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if not goal_contract.requires_material_review:
        return True
    if not goal_contract.required_material_paths:
        return tool_observation_ledger.has_read()
    return all(tool_observation_ledger.has_read(path) for path in goal_contract.required_material_paths)


def observation_paths_for_satisfaction(
    tool_observation_ledger: ToolObservationLedger,
    satisfaction: str,
) -> list[str]:
    paths: list[str] = []
    for record in tool_observation_ledger.records:
        if satisfaction not in record.satisfies:
            continue
        paths.extend([str(path).strip() for path in list(record.observed_paths or []) if str(path).strip()])
        paths.extend([str(path).strip() for path in list(record.matched_paths or []) if str(path).strip()])
    return _dedupe_strings(paths)


def _obligation_label(obligation: DeliverableObligation) -> str:
    if obligation.kind == "write_output" and obligation.path:
        return f"write_output:{obligation.path}"
    if obligation.kind == "ensure_dir" and obligation.path:
        return f"ensure_dir:{obligation.path.rsplit('/', 1)[0]}"
    return obligation.kind


def _path_matches(target: str, candidate: str) -> bool:
    normalized_target = str(target or "").strip().strip("/").replace("\\", "/").lower()
    normalized_candidate = str(candidate or "").strip().strip("/").replace("\\", "/").lower()
    return bool(
        normalized_target
        and normalized_candidate
        and (
            normalized_candidate == normalized_target
            or normalized_candidate.startswith(normalized_target + "/")
            or normalized_target.startswith(normalized_candidate + "/")
        )
    )
