from __future__ import annotations

from api import task_system as tasks_api


def test_contract_usage_index_scans_assignments_flows_graphs_nodes_edges_and_bindings() -> None:
    payload = tasks_api._contract_usage_index(  # type: ignore[attr-defined]
        task_assignments=[
            {
                "task_id": "task.story.review",
                "task_title": "Story Review",
                "input_contract_id": "contract.assignment.input",
                "output_contract_id": "contract.assignment.output",
            }
        ],
        task_flows=[
            {
                "flow_id": "flow.story.review",
                "title": "Story Review Flow",
                "input_contract_id": "contract.flow.input",
                "output_contract_id": "contract.flow.output",
            }
        ],
        task_graphs=[
            {
                "graph_id": "graph.story.review",
                "title": "Story Review Graph",
                "graph_contract_id": "contract.graph.root",
                "contract_bindings": {
                    "governance": {"contract_id": "contract.graph.governance"},
                    "runtime": {"runtime_contract_id": "contract.graph.runtime"},
                },
                "nodes": [
                    {
                        "node_id": "node.review",
                        "title": "Review",
                        "input_contract_id": "contract.node.input",
                        "output_contract_id": "contract.node.output",
                        "node_contract_id": "contract.node.execution",
                        "contract_bindings": {
                            "schema": {"input_contract_id": "contract.node.schema.input"},
                            "acceptance": {"acceptance_contract_id": "contract.node.acceptance"},
                        },
                    }
                ],
                "edges": [
                    {
                        "edge_id": "edge.review.final",
                        "payload_contract_id": "contract.edge.payload",
                        "contract_bindings": {
                            "handoff": {"contract_id": "contract.edge.handoff"},
                        },
                    }
                ],
            }
        ],
    )

    by_contract = payload["by_contract_id"]

    for contract_id in (
        "contract.assignment.input",
        "contract.assignment.output",
        "contract.flow.input",
        "contract.flow.output",
        "contract.graph.root",
        "contract.graph.governance",
        "contract.graph.runtime",
        "contract.node.input",
        "contract.node.output",
        "contract.node.execution",
        "contract.node.schema.input",
        "contract.node.acceptance",
        "contract.edge.payload",
        "contract.edge.handoff",
    ):
        assert contract_id in by_contract

    assert by_contract["contract.node.acceptance"][0]["field"] == "contract_bindings.acceptance.acceptance_contract_id"
    assert by_contract["contract.edge.handoff"][0]["source_kind"] == "task_graph_edge"
    assert payload["summary"]["usage_count"] == 14

