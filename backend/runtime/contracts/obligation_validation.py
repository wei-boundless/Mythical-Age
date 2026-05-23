from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.runtime_semantics.protocol_boundary import has_protocol_leak
from ..memory.tool_observation_ledger import ToolObservationLedger


@dataclass(frozen=True, slots=True)
class ObligationSatisfaction:
    obligation_key: str
    required: bool
    satisfied: bool
    evidence_refs: tuple[str, ...] = ()
    missing_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True, slots=True)
class ObligationValidation:
    passed: bool
    satisfactions: tuple[ObligationSatisfaction, ...] = ()
    missing_required_actions: tuple[str, ...] = ()
    missing_material_paths: tuple[str, ...] = ()
    missing_output_paths: tuple[str, ...] = ()
    missing_response_terms: tuple[str, ...] = ()
    missing_deliverables: tuple[str, ...] = ()
    unsupported_claims: tuple[str, ...] = ()
    protocol_leak_detected: bool = False
    checks: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.obligation_validation"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["satisfactions"] = [item.to_dict() for item in self.satisfactions]
        payload["missing_required_actions"] = list(self.missing_required_actions)
        payload["missing_material_paths"] = list(self.missing_material_paths)
        payload["missing_output_paths"] = list(self.missing_output_paths)
        payload["missing_response_terms"] = list(self.missing_response_terms)
        payload["missing_deliverables"] = list(self.missing_deliverables)
        payload["unsupported_claims"] = list(self.unsupported_claims)
        return payload


def validate_obligations(
    *,
    execution_obligation: dict[str, Any] | None,
    semantic_contract: dict[str, Any] | None,
    goal_contract: Any,
    tool_observation_ledger: ToolObservationLedger,
    final_content: str,
    deliverable_validation: dict[str, Any] | None = None,
    terminal_reason: str = "completed",
    tool_execution_enabled: bool = False,
    tool_call_count: int = 0,
    tool_observation_count: int = 0,
    delegation_enabled: bool = False,
    delegation_observation_count: int = 0,
    write_budget_reserved: bool = False,
    tool_budget_exhausted: bool = False,
    contract_gate_blocked: bool = False,
    protocol_leak_detected: bool = False,
) -> ObligationValidation:
    obligation = dict(execution_obligation or {})
    contract = dict(semantic_contract or {})
    deliverable = dict(deliverable_validation or {})
    text = str(final_content or "").strip()
    goal = goal_contract

    required_material_paths = _dedupe(
        [
            *[
                str(item.get("path") or "").strip()
                for item in list(obligation.get("required_reads") or [])
                if isinstance(item, dict) and str(item.get("path") or "").strip()
            ],
            *list(getattr(goal, "required_material_paths", []) or []),
        ]
    )
    required_output_paths = _dedupe(
        [
            *[
                str(item.get("path") or "").strip()
                for item in list(obligation.get("required_writes") or [])
                if isinstance(item, dict) and str(item.get("path") or "").strip()
            ],
            *list(getattr(goal, "required_output_paths", []) or []),
        ]
    )
    requires_material = bool(required_material_paths or getattr(goal, "requires_material_review", False))
    if requires_material and not required_material_paths:
        requires_material = False
    requires_write = bool(
        list(obligation.get("required_writes") or [])
        or getattr(goal, "requires_write_output", False)
    )
    requires_verify = bool(
        list(obligation.get("required_commands") or [])
        or list(obligation.get("required_verifications") or [])
        or getattr(goal, "requires_verification_command", False)
    )
    requires_delegate = bool(getattr(goal, "requires_delegation", False))

    missing_actions: list[str] = []
    missing_material_paths = [
        path for path in required_material_paths if not tool_observation_ledger.has_read(path)
    ]
    missing_output_paths = [
        path for path in required_output_paths if not tool_observation_ledger.has_write(path)
    ]
    satisfactions: list[ObligationSatisfaction] = []

    material_satisfied = not requires_material or (
        not missing_material_paths and tool_observation_ledger.has_read()
    )
    satisfactions.append(
        ObligationSatisfaction(
            "read_material",
            requires_material,
            material_satisfied,
            evidence_refs=_refs_for(tool_observation_ledger, "read_material"),
            missing_reason="missing_material_paths" if missing_material_paths else "",
        )
    )
    if requires_material and not material_satisfied:
        missing_actions.append("read_material")

    write_satisfied = not requires_write or (
        not missing_output_paths
        if required_output_paths
        else tool_observation_ledger.has_write()
    )
    satisfactions.append(
        ObligationSatisfaction(
            "write_output",
            requires_write,
            write_satisfied,
            evidence_refs=_refs_for(tool_observation_ledger, "write_output"),
            missing_reason=(
                "missing_output_paths"
                if requires_write and required_output_paths and missing_output_paths
                else "missing_write_observation"
                if requires_write and not write_satisfied
                else ""
            ),
        )
    )
    if requires_write and not write_satisfied:
        missing_actions.append("write_output")

    verify_satisfied = not requires_verify or tool_observation_ledger.verification_passed()
    satisfactions.append(
        ObligationSatisfaction(
            "verify_command",
            requires_verify,
            verify_satisfied,
            evidence_refs=_refs_for(tool_observation_ledger, "verify_command"),
            missing_reason="missing_passing_terminal_observation" if requires_verify and not verify_satisfied else "",
        )
    )
    if requires_verify and not verify_satisfied:
        missing_actions.append("verify_command")

    delegate_satisfied = not requires_delegate or delegation_observation_count > 0
    satisfactions.append(
        ObligationSatisfaction(
            "delegate_review",
            requires_delegate,
            delegate_satisfied,
            evidence_refs=_refs_for(tool_observation_ledger, "delegate_review"),
            missing_reason="missing_delegation_observation" if requires_delegate and not delegate_satisfied else "",
        )
    )
    if requires_delegate and not delegate_satisfied:
        missing_actions.append("delegate_review")

    response_terms = [
        str(item).strip()
        for item in list(getattr(goal, "response_must_include", []) or [])
        if str(item).strip()
    ]
    missing_response_terms = [term for term in response_terms if term.lower() not in text.lower()]
    missing_deliverables = [
        str(item).strip()
        for item in list(deliverable.get("missing_deliverables") or [])
        if str(item).strip()
    ]
    unsupported_claims = [
        str(item).strip()
        for item in list(deliverable.get("unsupported_claims") or [])
        if str(item).strip()
    ]
    protocol_leak = bool(
        protocol_leak_detected
        or deliverable.get("protocol_leak_detected") is True
        or has_protocol_leak(text)
    )
    if protocol_leak and "protocol_boundary" not in missing_deliverables:
        missing_deliverables.append("protocol_boundary")
    if bool(deliverable.get("passed") is True):
        missing_response_terms = [
            term
            for term in missing_response_terms
            if term not in _schema_response_terms(
                obligation=obligation,
                contract=contract,
            )
        ]

    passed = bool(
        text
        and terminal_reason == "completed"
        and not _dedupe(missing_actions)
        and not missing_response_terms
        and not _dedupe(missing_deliverables)
        and not unsupported_claims
        and not protocol_leak
        and bool(deliverable.get("passed") is not False)
    )
    return ObligationValidation(
        passed=passed,
        satisfactions=tuple(satisfactions),
        missing_required_actions=tuple(_dedupe(missing_actions)),
        missing_material_paths=tuple(_dedupe(missing_material_paths)),
        missing_output_paths=tuple(_dedupe(missing_output_paths)),
        missing_response_terms=tuple(_dedupe(missing_response_terms)),
        missing_deliverables=tuple(_dedupe(missing_deliverables)),
        unsupported_claims=tuple(_dedupe(unsupported_claims)),
        protocol_leak_detected=protocol_leak,
        checks={
            "has_final_content": bool(text),
            "terminal_reason": terminal_reason,
            "tool_execution_enabled": tool_execution_enabled,
            "tool_call_count": tool_call_count,
            "tool_observation_count": tool_observation_count,
            "delegation_enabled": delegation_enabled,
            "delegation_observation_count": delegation_observation_count,
            "write_output_required": requires_write,
            "write_observation_count": len(_refs_for(tool_observation_ledger, "write_output")),
            "required_output_paths": required_output_paths,
            "missing_output_paths": _dedupe(missing_output_paths),
            "artifact_observation_count": len(_refs_for(tool_observation_ledger, "write_output")),
            "verification_command_count": len(_refs_for(tool_observation_ledger, "verify_command")),
            "write_budget_reserved": bool(write_budget_reserved),
            "tool_budget_exhausted": bool(tool_budget_exhausted),
            "contract_gate_blocked": bool(contract_gate_blocked),
            "contract_passed": bool(not missing_actions and not missing_response_terms and not protocol_leak),
            "missing_required_actions": _dedupe(missing_actions),
            "missing_response_terms": _dedupe(missing_response_terms),
            "protocol_leak_detected": protocol_leak,
            "tool_claim_guard": "event_guarded" if tool_execution_enabled else "prompt_guarded",
            "summary_check_required": True,
            "tool_observation_ledger": tool_observation_ledger.summary(),
            "semantic_task_type": str(contract.get("task_goal_type") or ""),
        },
    )


def _refs_for(ledger: ToolObservationLedger, obligation_key: str) -> list[str]:
    return [
        record.observation_ref
        for record in ledger.records
        if obligation_key in record.satisfies and record.observation_ref
    ]


def _schema_response_terms(*, obligation: dict[str, Any], contract: dict[str, Any]) -> set[str]:
    deliverables = [
        *[
            str(item).strip()
            for item in list(contract.get("deliverables") or [])
            if str(item).strip()
        ],
        *[
            str(item).strip()
            for item in list(obligation.get("required_deliverables") or [])
            if str(item).strip()
        ],
    ]
    return {
        value
        for value in (_response_term_for_deliverable(item) for item in deliverables)
        if value
    }


def _response_term_for_deliverable(deliverable: str) -> str:
    mapping = {
        "change_summary": "修改",
        "changed_files": "文件",
        "verification_result_or_limitation": "验证",
        "failure_classification": "失败归类",
        "structural_root_causes": "结构性根因",
        "regression_test_plan": "回归测试",
        "evidence_limits": "证据边界",
        "artifact_refs": "产物",
        "completion_status": "完成状态",
        "limitations": "限制",
        "material_findings": "material_findings",
        "cross_material_conclusions": "cross_material_conclusions",
        "runnable_artifact_refs": "runnable_artifact_refs",
        "workflow_acceptance": "workflow_acceptance",
        "verification_evidence": "verification_evidence",
    }
    return mapping.get(str(deliverable or "").strip(), "")


def _dedupe(values: list[Any] | tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
