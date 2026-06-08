from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


GRAPH_COMPILATION_UNIT_AUTHORITY = "task_system.graph_compilation_unit"
GRAPH_COMPILE_REPORT_AUTHORITY = "task_system.graph_compile_report"


@dataclass(frozen=True, slots=True)
class GraphCompileIssue:
    code: str
    message: str
    severity: str = "error"
    node_id: str = ""
    edge_id: str = ""
    resource_id: str = ""
    authority: str = "task_system.graph_compile_issue"

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class GraphCompileReport:
    graph_id: str
    status: str
    issue_count: int
    blocking_issue_count: int
    summary: dict[str, Any] = field(default_factory=dict)
    issues: tuple[GraphCompileIssue, ...] = ()
    authority: str = GRAPH_COMPILE_REPORT_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [item.to_dict() for item in self.issues]
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class GraphCompilationUnit:
    unit_id: str
    graph_id: str
    compiler_version: str
    node_contract_index: dict[str, Any]
    resource_contract_index: dict[str, Any]
    edge_contract_index: dict[str, Any]
    configurator_write_contract: dict[str, Any]
    system_node_contract_index: dict[str, Any]
    maintenance_contract: dict[str, Any]
    graph_binding_contract: dict[str, Any]
    deployment_package: dict[str, Any]
    compile_report: GraphCompileReport
    authority: str = GRAPH_COMPILATION_UNIT_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["compile_report"] = self.compile_report.to_dict()
        return _drop_empty(payload)


def compile_status_from_issues(issues: list[GraphCompileIssue]) -> str:
    return "failed" if any(item.severity == "error" for item in issues) else "valid"


def compile_report(
    *,
    graph_id: str,
    summary: dict[str, Any],
    issues: list[GraphCompileIssue] | None = None,
) -> GraphCompileReport:
    issue_items = tuple(issues or ())
    blocking_count = sum(1 for item in issue_items if item.severity == "error")
    return GraphCompileReport(
        graph_id=graph_id,
        status="failed" if blocking_count else "valid",
        issue_count=len(issue_items),
        blocking_issue_count=blocking_count,
        summary=dict(summary or {}),
        issues=issue_items,
    )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
