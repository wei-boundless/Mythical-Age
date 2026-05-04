from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import CommitCandidate, ExecutionGraph, ExecutionNode


def test_execution_graph_nodes_require_runtime_directive_authority() -> None:
    node = ExecutionNode(
        node_id="node-1",
        node_type="mcp",
        executor="mcp.pdf",
        directive_ref="directive-1",
    )
    graph = ExecutionGraph(graph_id="graph-1", task_id="task-1", nodes=(node,))

    assert graph.nodes[0].authority == "runtime_directive"
    assert graph.to_dict()["nodes"][0]["executor"] == "mcp.pdf"


def test_commit_candidate_is_denied_until_commit_gate_exists() -> None:
    candidate = CommitCandidate(
        candidate_id="commit-1",
        commit_type="session_message",
        producer="query.runtime",
        payload={"content": "answer"},
    )

    assert candidate.allowed is False
    assert candidate.reason == "pending_commit_gate"
