from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .text_utils import normalize_storage_text

CandidateSourceKind = Literal["user_preference", "workflow_rule", "project_rule", "decision"]
CandidateStatus = Literal["candidate", "accepted", "session_only", "rejected"]
CandidateDecision = Literal["accept", "needs_confirmation", "session_only", "reject"]


@dataclass(slots=True)
class DurableCandidate:
    candidate_id: str
    source_kind: CandidateSourceKind
    title: str
    canonical_statement: str
    summary: str
    memory_type: str
    memory_class: str
    confidence: str
    rationale: str
    source_role: str
    source_excerpt: str
    retrieval_hints: list[str]
    status: CandidateStatus = "candidate"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "DurableCandidate":
        return cls(
            candidate_id=str(payload.get("candidate_id", "") or ""),
            source_kind=_normalize_source_kind(payload.get("source_kind", "decision")),
            title=str(payload.get("title", "") or ""),
            canonical_statement=str(payload.get("canonical_statement", "") or ""),
            summary=str(payload.get("summary", "") or ""),
            memory_type=str(payload.get("memory_type", "reference") or "reference"),
            memory_class=str(payload.get("memory_class", "work") or "work"),
            confidence=str(payload.get("confidence", "medium") or "medium"),
            rationale=str(payload.get("rationale", "") or ""),
            source_role=str(payload.get("source_role", "user") or "user"),
            source_excerpt=str(payload.get("source_excerpt", "") or ""),
            retrieval_hints=[
                str(item)
                for item in list(payload.get("retrieval_hints", []) or [])
                if str(item).strip()
            ],
            status=_normalize_status(payload.get("status", "candidate")),
        )


@dataclass(slots=True)
class DurableCandidateDecision:
    action: CandidateDecision
    reason: str
    memory_type: str
    memory_class: str
    confidence: str


PREFERENCE_MARKERS = (
    "喜欢",
    "偏好",
    "习惯",
    "默认",
    "先给结论",
    "风格",
    "用中文",
    "powershell",
    "prefer",
    "preference",
    "by default",
    "default to",
    "answer style",
    "reply style",
    "response style",
    "conclusion first",
    "give the conclusion first",
    "then explain",
)

WORKFLOW_MARKERS = (
    "工作流",
    "流程",
    "约定",
    "规范",
    "终端命令",
    "powershell",
    "以后",
    "默认用",
    "workflow",
    "convention",
    "rule",
    "terminal commands",
    "by default",
    "default to",
)

PROJECT_MARKERS = (
    "项目重点",
    "项目长期",
    "架构",
    "memory system",
    "记忆系统",
    "rag",
    "长期规则",
    "project focus",
    "project direction",
    "architecture",
    "long-term",
)

SESSION_ONLY_MARKERS = (
    "今天",
    "现在",
    "刚刚",
    "这次",
    "当前任务",
    "正在",
)

REJECT_MARKERS = (
    "你在干什么",
    "查的不对",
    "不对",
    "错了",
)


def evaluate_durable_candidate(candidate: DurableCandidate) -> DurableCandidateDecision:
    text = " ".join(
        [
            normalize_storage_text(candidate.title),
            normalize_storage_text(candidate.canonical_statement),
            normalize_storage_text(candidate.source_excerpt),
            normalize_storage_text(candidate.rationale),
        ]
    ).lower()

    if any(marker in text for marker in REJECT_MARKERS):
        return DurableCandidateDecision(
            action="reject",
            reason="meta_or_correction_noise",
            memory_type=candidate.memory_type,
            memory_class=candidate.memory_class,
            confidence="low",
        )

    if any(marker in text for marker in SESSION_ONLY_MARKERS):
        return DurableCandidateDecision(
            action="session_only",
            reason="short_lived_session_state",
            memory_type=candidate.memory_type,
            memory_class=candidate.memory_class,
            confidence="low",
        )

    if candidate.source_kind == "user_preference" and any(marker in text for marker in PREFERENCE_MARKERS):
        return DurableCandidateDecision(
            action="accept",
            reason="stable_user_preference",
            memory_type="preference",
            memory_class="preference",
            confidence="high",
        )

    if candidate.source_kind == "workflow_rule" and any(marker in text for marker in WORKFLOW_MARKERS):
        return DurableCandidateDecision(
            action="accept",
            reason="stable_workflow_rule",
            memory_type="workflow",
            memory_class="work",
            confidence="high",
        )

    if candidate.source_kind in {"project_rule", "decision"} and any(marker in text for marker in PROJECT_MARKERS):
        return DurableCandidateDecision(
            action="accept",
            reason="stable_project_rule",
            memory_type="project",
            memory_class="work",
            confidence="medium",
        )

    return DurableCandidateDecision(
        action="needs_confirmation",
        reason="candidate_needs_more_confirmation",
        memory_type=candidate.memory_type,
        memory_class=candidate.memory_class,
        confidence="medium",
    )


def _normalize_source_kind(value: object) -> CandidateSourceKind:
    normalized = str(value or "decision")
    if normalized in {"user_preference", "workflow_rule", "project_rule", "decision"}:
        return normalized
    return "decision"


def _normalize_status(value: object) -> CandidateStatus:
    normalized = str(value or "candidate")
    if normalized in {"candidate", "accepted", "session_only", "rejected"}:
        return normalized
    return "candidate"
