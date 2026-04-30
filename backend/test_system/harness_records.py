from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


IssueOrigin = Literal["conversation", "development", "skill", "runtime", "manual", "test_agent"]
IssueStatus = Literal["open", "triaged", "converted", "resolved", "archived"]
IssueSeverity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class TestHarnessIssue:
    issue_id: str
    title: str
    origin: IssueOrigin = "manual"
    owner_system: str = "test_system"
    severity: IssueSeverity = "medium"
    status: IssueStatus = "open"
    observed: str = ""
    expected: str = ""
    reproduce: str = ""
    related_run_id: str = ""
    related_turn_id: str = ""
    related_task_id: str = ""
    related_session_id: str = ""
    related_skill: str = ""
    problem_node_id: str = ""
    problem_node_label: str = ""
    tags: tuple[str, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class TestCaseDraft:
    draft_id: str
    title: str
    layer: str = "functional"
    owner_system: str = "test_system"
    source_issue_id: str = ""
    source_run_id: str = ""
    source_turn_id: str = ""
    trigger: str = ""
    expected: str = ""
    assertions: tuple[str, ...] = ()
    profile: str = "functional"
    status: str = "draft"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assertions"] = list(self.assertions)
        return payload


@dataclass(frozen=True, slots=True)
class HarnessRecordBook:
    issues: tuple[TestHarnessIssue, ...] = ()
    case_drafts: tuple[TestCaseDraft, ...] = ()
    authority: str = "test_system.harness_records"

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [item.to_dict() for item in self.issues],
            "case_drafts": [item.to_dict() for item in self.case_drafts],
            "summary": {
                "issue_count": len(self.issues),
                "open_issue_count": sum(1 for item in self.issues if item.status == "open"),
                "case_draft_count": len(self.case_drafts),
            },
            "authority": self.authority,
        }


class HarnessRecordStore:
    """Persistent issue and case-draft store for the test harness.

    This is intentionally small and file-backed. The goal is to make real
    problem capture durable before we introduce the future test-maintainer
    agent and richer task-system bindings.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.cwd() / "storage" / "test-system" / "harness_records.json"

    def load(self) -> HarnessRecordBook:
        payload = self._read()
        issues = tuple(self._issue_from_dict(item) for item in list(payload.get("issues") or []))
        drafts = tuple(self._draft_from_dict(item) for item in list(payload.get("case_drafts") or []))
        return HarnessRecordBook(issues=issues, case_drafts=drafts)

    def create_issue(self, payload: dict[str, Any]) -> TestHarnessIssue:
        book = self.load()
        now = time.time()
        issue = TestHarnessIssue(
            issue_id=str(payload.get("issue_id") or f"issue-{uuid4().hex[:10]}"),
            title=_required_text(payload, "title", "未命名测试问题"),
            origin=_choice(payload.get("origin"), {"conversation", "development", "skill", "runtime", "manual", "test_agent"}, "manual"),
            owner_system=str(payload.get("owner_system") or payload.get("system") or "test_system"),
            severity=_choice(payload.get("severity"), {"low", "medium", "high", "critical"}, "medium"),
            status=_choice(payload.get("status"), {"open", "triaged", "converted", "resolved", "archived"}, "open"),
            observed=str(payload.get("observed") or payload.get("summary") or ""),
            expected=str(payload.get("expected") or ""),
            reproduce=str(payload.get("reproduce") or ""),
            related_run_id=str(payload.get("related_run_id") or payload.get("relatedRun") or ""),
            related_turn_id=str(payload.get("related_turn_id") or ""),
            related_task_id=str(payload.get("related_task_id") or ""),
            related_session_id=str(payload.get("related_session_id") or ""),
            related_skill=str(payload.get("related_skill") or ""),
            problem_node_id=str(payload.get("problem_node_id") or ""),
            problem_node_label=str(payload.get("problem_node_label") or ""),
            tags=_string_tuple(payload.get("tags")),
            created_at=now,
            updated_at=now,
        )
        self._write(HarnessRecordBook(issues=(issue, *book.issues), case_drafts=book.case_drafts))
        return issue

    def create_case_draft(self, payload: dict[str, Any]) -> TestCaseDraft:
        book = self.load()
        now = time.time()
        layer = _choice(payload.get("layer"), {"chain", "functional", "system", "scenario"}, "functional")
        draft = TestCaseDraft(
            draft_id=str(payload.get("draft_id") or f"case-draft-{uuid4().hex[:10]}"),
            title=_required_text(payload, "title", "未命名测试用例草案"),
            layer=layer,
            owner_system=str(payload.get("owner_system") or payload.get("system") or "test_system"),
            source_issue_id=str(payload.get("source_issue_id") or payload.get("sourceIssue") or ""),
            source_run_id=str(payload.get("source_run_id") or ""),
            source_turn_id=str(payload.get("source_turn_id") or ""),
            trigger=str(payload.get("trigger") or ""),
            expected=str(payload.get("expected") or ""),
            assertions=_string_tuple(payload.get("assertions")),
            profile=str(payload.get("profile") or layer),
            status=str(payload.get("status") or "draft"),
            created_at=now,
            updated_at=now,
        )
        self._write(HarnessRecordBook(issues=book.issues, case_drafts=(draft, *book.case_drafts)))
        return draft

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"issues": [], "case_drafts": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"issues": [], "case_drafts": []}
        return payload if isinstance(payload, dict) else {"issues": [], "case_drafts": []}

    def _write(self, book: HarnessRecordBook) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(book.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _issue_from_dict(self, payload: Any) -> TestHarnessIssue:
        if not isinstance(payload, dict):
            payload = {}
        return TestHarnessIssue(
            issue_id=str(payload.get("issue_id") or f"issue-{uuid4().hex[:10]}"),
            title=str(payload.get("title") or "未命名测试问题"),
            origin=_choice(payload.get("origin"), {"conversation", "development", "skill", "runtime", "manual", "test_agent"}, "manual"),
            owner_system=str(payload.get("owner_system") or "test_system"),
            severity=_choice(payload.get("severity"), {"low", "medium", "high", "critical"}, "medium"),
            status=_choice(payload.get("status"), {"open", "triaged", "converted", "resolved", "archived"}, "open"),
            observed=str(payload.get("observed") or ""),
            expected=str(payload.get("expected") or ""),
            reproduce=str(payload.get("reproduce") or ""),
            related_run_id=str(payload.get("related_run_id") or ""),
            related_turn_id=str(payload.get("related_turn_id") or ""),
            related_task_id=str(payload.get("related_task_id") or ""),
            related_session_id=str(payload.get("related_session_id") or ""),
            related_skill=str(payload.get("related_skill") or ""),
            problem_node_id=str(payload.get("problem_node_id") or ""),
            problem_node_label=str(payload.get("problem_node_label") or ""),
            tags=_string_tuple(payload.get("tags")),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
        )

    def _draft_from_dict(self, payload: Any) -> TestCaseDraft:
        if not isinstance(payload, dict):
            payload = {}
        return TestCaseDraft(
            draft_id=str(payload.get("draft_id") or f"case-draft-{uuid4().hex[:10]}"),
            title=str(payload.get("title") or "未命名测试用例草案"),
            layer=str(payload.get("layer") or "functional"),
            owner_system=str(payload.get("owner_system") or "test_system"),
            source_issue_id=str(payload.get("source_issue_id") or ""),
            source_run_id=str(payload.get("source_run_id") or ""),
            source_turn_id=str(payload.get("source_turn_id") or ""),
            trigger=str(payload.get("trigger") or ""),
            expected=str(payload.get("expected") or ""),
            assertions=_string_tuple(payload.get("assertions")),
            profile=str(payload.get("profile") or payload.get("layer") or "functional"),
            status=str(payload.get("status") or "draft"),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
        )


def _choice(value: Any, allowed: set[str], default: str) -> Any:
    candidate = str(value or "").strip()
    return candidate if candidate in allowed else default


def _required_text(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = str(payload.get(key) or "").strip()
    return value or fallback


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.splitlines() if item.strip())
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


harness_record_store = HarnessRecordStore()
