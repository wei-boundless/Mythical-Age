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
class TestCaseTemplate:
    template_id: str
    title: str
    layer: str
    owner_system: str
    runner: str = "pytest"
    profiles: tuple[str, ...] = ()
    assertions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    description: str = ""
    pass_criteria: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profiles"] = list(self.profiles)
        payload["assertions"] = list(self.assertions)
        payload["tags"] = list(self.tags)
        payload["pass_criteria"] = list(self.pass_criteria)
        return payload


@dataclass(frozen=True, slots=True)
class ManagedTestCase:
    case_id: str
    title: str
    layer: str = "functional"
    path: str = ""
    owner_system: str = "test_system"
    runner: str = "pytest"
    status: str = "candidate"
    profiles: tuple[str, ...] = ()
    description: str = ""
    problem_statement: str = ""
    pass_criteria: tuple[str, ...] = ()
    scenario_turns: tuple[dict[str, str], ...] = ()
    assertions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    source_template_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profiles"] = list(self.profiles)
        payload["pass_criteria"] = list(self.pass_criteria)
        payload["scenario_turns"] = [dict(item) for item in self.scenario_turns]
        payload["assertions"] = list(self.assertions)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class HarnessRecordBook:
    issues: tuple[TestHarnessIssue, ...] = ()
    case_drafts: tuple[TestCaseDraft, ...] = ()
    managed_cases: tuple[ManagedTestCase, ...] = ()
    authority: str = "test_system.harness_records"

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [item.to_dict() for item in self.issues],
            "case_drafts": [item.to_dict() for item in self.case_drafts],
            "managed_cases": [item.to_dict() for item in self.managed_cases],
            "summary": {
                "issue_count": len(self.issues),
                "open_issue_count": sum(1 for item in self.issues if item.status == "open"),
                "case_draft_count": len(self.case_drafts),
                "managed_case_count": len(self.managed_cases),
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
        managed_cases = tuple(self._managed_case_from_dict(item) for item in list(payload.get("managed_cases") or []))
        return HarnessRecordBook(issues=issues, case_drafts=drafts, managed_cases=managed_cases)

    def templates(self) -> tuple[TestCaseTemplate, ...]:
        return DEFAULT_CASE_TEMPLATES

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
        self._write(HarnessRecordBook(issues=(issue, *book.issues), case_drafts=book.case_drafts, managed_cases=book.managed_cases))
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
        self._write(HarnessRecordBook(issues=book.issues, case_drafts=(draft, *book.case_drafts), managed_cases=book.managed_cases))
        return draft

    def create_managed_case(self, payload: dict[str, Any]) -> ManagedTestCase:
        book = self.load()
        now = time.time()
        template = self._template(str(payload.get("source_template_id") or payload.get("template_id") or ""))
        layer = _choice(payload.get("layer") or getattr(template, "layer", ""), {"chain", "functional", "system", "scenario"}, "functional")
        title = _required_text(payload, "title", getattr(template, "title", "未命名测试用例"))
        case_id = str(payload.get("case_id") or f"managed.{_slug(title)}.{uuid4().hex[:6]}")
        managed = ManagedTestCase(
            case_id=case_id,
            title=title,
            layer=layer,
            path=str(payload.get("path") or ""),
            owner_system=str(payload.get("owner_system") or getattr(template, "owner_system", "test_system")),
            runner=str(payload.get("runner") or getattr(template, "runner", "pytest")),
            status=str(payload.get("status") or "candidate"),
            profiles=_string_tuple(payload.get("profiles")) or tuple(getattr(template, "profiles", ()) or (layer,)),
            description=str(payload.get("description") or getattr(template, "description", "")),
            problem_statement=str(payload.get("problem_statement") or payload.get("reason") or ""),
            pass_criteria=_string_tuple(payload.get("pass_criteria")) or tuple(getattr(template, "pass_criteria", ()) or ()),
            scenario_turns=_scenario_turns_tuple(payload.get("scenario_turns")),
            assertions=_string_tuple(payload.get("assertions")) or tuple(getattr(template, "assertions", ()) or ()),
            tags=_string_tuple(payload.get("tags")) or tuple(getattr(template, "tags", ()) or ()),
            source_template_id=str(payload.get("source_template_id") or payload.get("template_id") or getattr(template, "template_id", "")),
            created_at=now,
            updated_at=now,
        )
        remaining = tuple(item for item in book.managed_cases if item.case_id != managed.case_id)
        self._write(HarnessRecordBook(issues=book.issues, case_drafts=book.case_drafts, managed_cases=(managed, *remaining)))
        return managed

    def delete_managed_case(self, case_id: str) -> bool:
        book = self.load()
        target = str(case_id or "").strip()
        remaining = tuple(item for item in book.managed_cases if item.case_id != target)
        if len(remaining) == len(book.managed_cases):
            return False
        self._write(HarnessRecordBook(issues=book.issues, case_drafts=book.case_drafts, managed_cases=remaining))
        return True

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"issues": [], "case_drafts": [], "managed_cases": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"issues": [], "case_drafts": [], "managed_cases": []}
        return payload if isinstance(payload, dict) else {"issues": [], "case_drafts": [], "managed_cases": []}

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

    def _managed_case_from_dict(self, payload: Any) -> ManagedTestCase:
        if not isinstance(payload, dict):
            payload = {}
        return ManagedTestCase(
            case_id=str(payload.get("case_id") or f"managed.{uuid4().hex[:10]}"),
            title=str(payload.get("title") or "未命名测试用例"),
            layer=str(payload.get("layer") or "functional"),
            path=str(payload.get("path") or ""),
            owner_system=str(payload.get("owner_system") or "test_system"),
            runner=str(payload.get("runner") or "pytest"),
            status=str(payload.get("status") or "candidate"),
            profiles=_string_tuple(payload.get("profiles")),
            description=str(payload.get("description") or ""),
            problem_statement=str(payload.get("problem_statement") or ""),
            pass_criteria=_string_tuple(payload.get("pass_criteria")),
            scenario_turns=_scenario_turns_tuple(payload.get("scenario_turns")),
            assertions=_string_tuple(payload.get("assertions")),
            tags=_string_tuple(payload.get("tags")),
            source_template_id=str(payload.get("source_template_id") or ""),
            created_at=float(payload.get("created_at") or 0.0),
            updated_at=float(payload.get("updated_at") or 0.0),
        )

    def _template(self, template_id: str) -> TestCaseTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in DEFAULT_CASE_TEMPLATES if item.template_id == target), None)


def _choice(value: Any, allowed: set[str], default: str) -> Any:
    candidate = str(value or "").strip()
    return candidate if candidate in allowed else default


def _required_text(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = str(payload.get(key) or "").strip()
    return value or fallback


def _scenario_turns_tuple(value: Any) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        return ()
    turns: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        user_input = str(item.get("user") or item.get("input") or item.get("prompt") or "").strip()
        expectation = str(item.get("expected") or item.get("expectation") or item.get("assertion") or "").strip()
        assistant_hint = str(item.get("assistant") or item.get("assistant_hint") or item.get("notes") or "").strip()
        if not user_input and not expectation and not assistant_hint:
            continue
        turns.append(
            {
                "turn_id": str(item.get("turn_id") or f"turn-{index}"),
                "user": user_input,
                "expected": expectation,
                "assistant_hint": assistant_hint,
            }
        )
    return tuple(turns)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.splitlines() if item.strip())
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _slug(value: str) -> str:
    chars = []
    for char in str(value or "").lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("_")
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "case"


DEFAULT_CASE_TEMPLATES: tuple[TestCaseTemplate, ...] = (
    TestCaseTemplate(
        template_id="template.runtime_chain",
        title="运行链路合同用例",
        layer="chain",
        owner_system="orchestration_system",
        profiles=("chain", "system"),
        assertions=("loop.completed", "loop.has_checkpoint", "output.contract_ok"),
        tags=("runtime_loop", "trace", "contract"),
        description="用于验证一次用户任务是否被 RuntimeLoop 正确建模、推进、留痕和收口。",
        pass_criteria=(
            "RuntimeLoop 有 task_run_id、event log、checkpoint 和 terminal_reason。",
            "失败时能定位 problem_node 或 blocked reason。",
        ),
    ),
    TestCaseTemplate(
        template_id="template.semantic_answer",
        title="语义回答质量用例",
        layer="functional",
        owner_system="test_system",
        profiles=("functional",),
        assertions=("semantic.intent_matched", "semantic.no_unsupported_claims"),
        tags=("semantic", "answer_quality"),
        description="用于把真实对话问题转成可复测的语义质量用例。",
        pass_criteria=(
            "回答必须回应用户原始意图。",
            "回答不能遗漏显式约束，不能用无证据结论替代链路事实。",
        ),
    ),
    TestCaseTemplate(
        template_id="template.permission_boundary",
        title="权限边界用例",
        layer="functional",
        owner_system="operation_system",
        profiles=("functional", "system"),
        assertions=("operation_gate.checked", "blocked_operation.denied"),
        tags=("operation_gate", "resource_policy", "permission"),
        description="用于验证 Agent、任务流、工具和记忆范围没有越权。",
        pass_criteria=(
            "ResourcePolicy 与 AgentCapabilityProfile 必须一致。",
            "blocked operation 必须 fail-closed，并留下可读拒绝原因。",
        ),
    ),
)


harness_record_store = HarnessRecordStore()
