from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from agents.a2a_cards import build_default_agent_cards, get_agent_card
from agents.a2a_extensions import EXT_RESULT_HANDLES
from agents.a2a_runtime import task_envelope_from_request, task_envelope_from_result
from query.worker_models import A2A_COMPATIBLE_PROTOCOL_VERSION, CanonicalResult, WorkerRequest, WorkerResult


def main() -> None:
    cards = build_default_agent_cards()
    retrieval_card = get_agent_card("agent:knowledge:retrieval")
    assert retrieval_card is not None
    assert retrieval_card.agent_id in cards
    assert retrieval_card.protocol_version == A2A_COMPATIBLE_PROTOCOL_VERSION
    assert retrieval_card.mcp_profile["protocol_version"] == "mcp-compatible.v1"
    assert retrieval_card.mcp_profile["tools"][0]["tool_name"] == "search_knowledge"
    assert retrieval_card.mcp_profile["tools"][0]["runtime_visibility"] == "agent_internal"

    request = WorkerRequest(
        request_id="req-1",
        session_id="session-1",
        query="缺货情况",
        worker_route="retrieval",
        extensions={"x-langchain-agent.dispatch_reason": "test"},
    )
    request_envelope = task_envelope_from_request(request)
    assert request_envelope.agent_id == "agent:knowledge:retrieval"
    assert request_envelope.status == "submitted"
    assert request_envelope.parts == [{"kind": "text", "text": "缺货情况"}]
    assert request_envelope.metadata["worker_route"] == "retrieval"
    assert request_envelope.metadata["agent_card"]["agent_id"] == "agent:knowledge:retrieval"

    canonical = CanonicalResult(
        result_kind="rag_answer",
        ok=True,
        answer="A 仓缺货最严重。",
        result_handle_ids=["result:rag_answer:shortage:primary"],
    )
    result_envelope = task_envelope_from_result(
        request=request,
        result=WorkerResult(worker_name="retrieval", status="ok", canonical_result=canonical),
    )
    assert result_envelope.status == "completed"
    assert result_envelope.stream_event_type == "task.completed"
    assert result_envelope.parts == [{"kind": "text", "text": "A 仓缺货最严重。"}]
    assert result_envelope.extensions[EXT_RESULT_HANDLES] == ["result:rag_answer:shortage:primary"]

    print("ALL PASSED (a2a protocol adapter regression)")


if __name__ == "__main__":
    main()
