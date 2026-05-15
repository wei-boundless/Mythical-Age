from __future__ import annotations


HEALTH_AGENT_ID = "agent:3"
HEALTH_AGENT_PROFILE_ID = "health_maintainer_agent"
HEALTH_SESSION_ID = "health-system"


HEALTH_TASK_ID_BY_MODE = {
    "issue_triage": "task.health.issue_triage",
    "trace_analysis": "task.health.trace_analysis",
    "case_draft": "task.health.case_draft",
    "fix_verification": "task.health.fix_verification",
}


def health_specific_task_id(task_mode: str) -> str:
    normalized = str(task_mode or "").strip()
    return HEALTH_TASK_ID_BY_MODE.get(normalized, f"task.health.{normalized or 'issue_triage'}")
