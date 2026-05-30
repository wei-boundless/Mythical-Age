from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.models import GraphNodeWorkOrder
from harness.runtime.compiler import RuntimeCompiler
from query.runtime import _graph_node_contract_from_work_order


def test_graph_node_task_packet_does_not_embed_full_graph_policy() -> None:
    read_rules = [
        {
            "edge_id": f"edge.memory.{index}",
            "source_node_id": "memory.global",
            "target_node_id": f"other_node_{index}",
            "repository": "memory.global",
            "collection": "huge",
            "metadata": {"noise": "x" * 500},
        }
        for index in range(80)
    ]
    input_package = {
        "package_id": "gin:test",
        "node_identity": {"node_id": "target_node", "title": "目标节点"},
        "prompt_contract": {"role_prompt": "你是一名测试执行员。"},
        "task_environment_id": "env.test",
        "initial_inputs": {"goal": "compact graph node prompt"},
        "memory_view": {"graph_memory_policy": {"read_rules": read_rules}},
        "artifact_view": {"graph_artifact_policy": {"context_edges": read_rules}},
        "file_view": {"graph_resource_policy": {"resource_nodes": read_rules}},
    }
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:test:target_node:1",
        work_kind="agent",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        node_id="target_node",
        config_id="ghcfg:test",
        config_hash="hash",
        task_ref="task.test.target_node",
        message="完成目标节点。",
        input_package=input_package,
        graph_slot={
            "authority": "harness.graph.node_execution_slot",
            "slot_id": "gslot:test:target_node",
            "graph_identity": {
                "graph_run_id": "grun:test",
                "root_task_run_id": "taskrun:test",
                "config_id": "ghcfg:test",
                "config_hash": "hash",
                "node_id": "target_node",
                "work_order_id": "gwork:test:target_node:1",
            },
            "node_contract": {
                "node_identity": {"node_id": "target_node", "title": "目标节点"},
                "prompt_contract": {"role_prompt": "你是一名测试执行员。"},
                "output_contract": {"output_contract_id": "contract.test.output"},
            },
            "edge_contracts": {},
            "memory_contract": {
                "read_protocols": read_rules,
                "resolved_snapshots": [],
            },
            "output_contract": {"expected_result_contract": {"output_contract_id": "contract.test.output"}},
            "state_refs": {"checkpoint_ref": "gchk:hidden"},
            "runtime_controls": {"retry_policy": {"max_attempts": 1}},
        },
        expected_result_contract={"output_contract_id": "contract.test.output"},
    )
    contract = _graph_node_contract_from_work_order(work_order).to_dict()
    task_run = {
        "task_run_id": "gtask:test",
        "session_id": "session-test",
        "task_id": "task.test.target_node",
        "task_contract_ref": "gcontract:test",
        "owner_agent_seat_id": "target_node",
        "agent_id": "agent:0",
        "agent_profile_id": "main_interactive_agent",
        "execution_runtime_kind": "single_agent_task",
        "status": "running",
        "diagnostics": {"contract": contract, "graph_run_id": "grun:test", "graph_node_id": "target_node"},
    }

    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-test",
        task_run=task_run,
        contract=contract,
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:test",
            "profile": {"mode": "professional", "interaction_mode": "task_execution"},
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": []},
        },
    ).packet

    stable_payload = json.loads(packet.model_messages[1]["content"].split("\n", 1)[1])

    assert len(packet.model_messages[1]["content"]) < 80000
    assert "contract" not in stable_payload["task_run"]["diagnostics"]
    assert "other_node_79" not in packet.model_messages[1]["content"]
    all_message_content = "".join(message["content"] for message in packet.model_messages)
    assert "graph_identity" not in all_message_content
    assert "state_refs" not in all_message_content
    assert "runtime_controls" not in all_message_content
    assert "gchk:hidden" not in all_message_content
    assert "gwork:test:target_node:1" not in all_message_content
    assert "grun:test" not in all_message_content
