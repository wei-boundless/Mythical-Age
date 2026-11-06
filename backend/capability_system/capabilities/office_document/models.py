from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class OfficePatchOperation:
    op_id: str
    op_type: str
    target_anchor: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    precondition: dict[str, Any] = field(default_factory=dict)
    expected_effect: dict[str, Any] = field(default_factory=dict)
    fallback_policy: str = "reject"

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "op_type": self.op_type,
            "target_anchor": dict(self.target_anchor),
            "payload": dict(self.payload),
            "precondition": dict(self.precondition),
            "expected_effect": dict(self.expected_effect),
            "fallback_policy": self.fallback_policy,
        }


@dataclass(frozen=True, slots=True)
class OfficePatchPlan:
    plan_id: str
    source_path: Path
    output_path: Path
    file_type: str
    operations: tuple[OfficePatchOperation | dict[str, Any], ...] = ()
    preconditions: tuple[dict[str, Any], ...] = ()
    preservation_policy: dict[str, Any] = field(default_factory=dict)
    verification_contract: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "source_path": str(self.source_path),
            "output_path": str(self.output_path),
            "file_type": self.file_type,
            "operations": [operation.to_dict() for operation in self.operations],
            "preconditions": [dict(item) for item in self.preconditions],
            "preservation_policy": dict(self.preservation_policy),
            "verification_contract": dict(self.verification_contract),
            "risk_level": self.risk_level,
        }


@dataclass(frozen=True, slots=True)
class OfficeExecutionReport:
    ok: bool
    output_path: Path
    applied_operations: tuple[str, ...] = ()
    skipped_operations: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output_path": str(self.output_path),
            "applied_operations": list(self.applied_operations),
            "skipped_operations": [dict(item) for item in self.skipped_operations],
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class OfficeVerificationReport:
    ok: bool
    level: str
    checks: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "level": self.level,
            "checks": [dict(item) for item in self.checks],
            "diagnostics": [dict(item) for item in self.diagnostics],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class OfficeDocumentRequest:
    action: str
    source_path: Path
    output_path: Path | None = None
    target_file_type: str = ""
    collection: str = "office_document"
    root_dir: Path | None = None
    read_scope: str = "document"
    max_blocks: int = 80
    operations: tuple[OfficePatchOperation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OfficeDocumentResult:
    ok: bool
    status: str
    action: str
    file_type: str
    source_path: str
    output_path: str = ""
    summary: str = ""
    extracted_content: tuple[dict[str, Any], ...] = ()
    artifact_refs: tuple[dict[str, Any], ...] = ()
    patch_plan_id: str = ""
    verification_report: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "action": self.action,
            "file_type": self.file_type,
            "source_path": self.source_path,
            "output_path": self.output_path,
            "summary": self.summary,
            "extracted_content": [dict(item) for item in self.extracted_content],
            "artifact_refs": [dict(item) for item in self.artifact_refs],
            "patch_plan_id": self.patch_plan_id,
            "verification_report": dict(self.verification_report),
            "diagnostics": [dict(item) for item in self.diagnostics],
            "limitations": list(self.limitations),
            "metadata": dict(self.metadata),
        }
