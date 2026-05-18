from __future__ import annotations

from orchestration.runtime_loop.agent_delegation_executor import _delegation_request_counts_against_budget
from orchestration.runtime_loop.delegation_models import AgentDelegationRequest, AgentDelegationResult
from orchestration.runtime_loop.task_run_loop import _classify_delegation_goal_alignment


def _request(
    request_id: str,
    *,
    instruction: str,
    goal_alignment: str,
    input_payload: dict[str, object] | None = None,
) -> AgentDelegationRequest:
    return AgentDelegationRequest(
        request_id=request_id,
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:pdf_reader",
        delegation_kind="pdf_reading",
        instruction=instruction,
        input_payload=dict(input_payload or {}),
        diagnostics={"goal_alignment": goal_alignment},
    )


def test_goal_alignment_marks_pdf_followup_as_aligned() -> None:
    alignment = _classify_delegation_goal_alignment(
        user_message="继续沿着这份 PDF，只读第3页，告诉我它在全文里的作用。",
        instruction="打开 knowledge/AI Knowledge/report.pdf，只读第3页，判断它是目录页还是正文页。",
        input_payload={"file_path": "knowledge/AI Knowledge/report.pdf", "page_range": [3, 3]},
    )

    assert alignment == "aligned"


def test_goal_alignment_marks_unrelated_retrieval_as_offtopic() -> None:
    alignment = _classify_delegation_goal_alignment(
        user_message="继续沿着这份 PDF，只读第3页，告诉我它在全文里的作用。",
        instruction="在本地知识库中检索 AI 治理里最常见的三类风险。",
        input_payload={},
    )

    assert alignment == "offtopic"


def test_budget_counter_ignores_previous_offtopic_request() -> None:
    previous = _request(
        "req-1",
        instruction="在本地知识库中检索 AI 治理里最常见的三类风险。",
        goal_alignment="offtopic",
    )
    current = _request(
        "req-2",
        instruction="打开 knowledge/AI Knowledge/report.pdf，只读第3页。",
        goal_alignment="aligned",
        input_payload={"file_path": "knowledge/AI Knowledge/report.pdf"},
    )

    assert _delegation_request_counts_against_budget(previous, current_request=current, result=None) is False


def test_budget_counter_ignores_missing_handle_repair_retry() -> None:
    previous = _request(
        "req-1",
        instruction="读取第4页。",
        goal_alignment="aligned",
    )
    current = _request(
        "req-2",
        instruction="读取 knowledge/AI Knowledge/report.pdf 的第4页。",
        goal_alignment="aligned",
        input_payload={"file_path": "knowledge/AI Knowledge/report.pdf", "page": 4},
    )
    result = AgentDelegationResult(
        result_id="delegation:result:req-1",
        request_id="req-1",
        task_run_id="taskrun-1",
        parent_agent_run_ref="agrun:main",
        child_agent_run_ref="agrun:child",
        target_agent_id="agent:pdf_reader",
        status="failed",
        summary="需要先确认要阅读的 PDF 文件。",
        limitations=("missing_object_handle",),
    )

    assert _delegation_request_counts_against_budget(previous, current_request=current, result=result) is False


def test_budget_counter_ignores_missing_handle_repair_retry_with_file_paths() -> None:
    previous = _request(
        "req-1",
        instruction="读取两份 PDF。",
        goal_alignment="aligned",
    )
    current = _request(
        "req-2",
        instruction="读取两份 PDF。",
        goal_alignment="aligned",
        input_payload={"file_paths": ["knowledge/AI Knowledge/report.pdf"]},
    )
    result = AgentDelegationResult(
        result_id="delegation:result:req-1",
        request_id="req-1",
        task_run_id="taskrun-1",
        parent_agent_run_ref="agrun:main",
        child_agent_run_ref="agrun:child",
        target_agent_id="agent:pdf_reader",
        status="failed",
        summary="需要先确认要阅读的 PDF 文件。",
        limitations=("missing_object_handle",),
    )

    assert _delegation_request_counts_against_budget(previous, current_request=current, result=result) is False
