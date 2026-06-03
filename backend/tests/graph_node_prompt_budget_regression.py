from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.models import GraphNodeWorkOrder
from harness.runtime.compiler import RuntimeCompiler
from harness.graph.work_order_contract import _graph_node_contract_from_work_order


def _message_content_with_title(packet, title: str) -> str:
    for message in packet.model_messages:
        content = str(message.get("content") or "")
        if content.startswith(title):
            return content
    raise AssertionError(f"message title not found: {title}")


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
            "profile": {
                "profile_ref": "main_interactive_agent",
                "interaction_policy": {"style": "task_execution"},
                "context_policy": {"task_run_context": "disabled"},
                "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
                "operation_authorization_projection": {"model_visible": "summary_without_denials"},
            },
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": [], "denied_operations": ["op.write_file", "op.edit_file"]},
        },
    ).packet

    task_contract_content = _message_content_with_title(packet, "Task execution task contract")
    stable_payload = json.loads(task_contract_content.split("\n", 1)[1])

    assert len(task_contract_content) < 80000
    assert "task_run" not in stable_payload
    assert "other_node_79" not in task_contract_content
    all_message_content = "".join(message["content"] for message in packet.model_messages)
    assert "graph_identity" not in all_message_content
    assert "state_refs" not in all_message_content
    assert "runtime_controls" not in all_message_content
    assert "input_package" not in all_message_content
    assert "graph_slot" not in all_message_content
    assert "memory_contract" not in all_message_content
    assert "acceptance_policy" not in all_message_content
    assert "runtime.task_execution.v1" not in all_message_content
    assert "写入交付物时优先使用 write_file" not in all_message_content
    assert "write_file" not in all_message_content
    assert "edit_file" not in all_message_content
    assert "denied_operations" not in all_message_content
    assert "task_run_id" not in all_message_content
    assert packet.prompt_pack_refs == ("runtime.pack.graph_node_execution.v1",)
    manifest = packet.diagnostics["prompt_manifest"]
    assert "runtime.graph_node_execution.v1" in manifest["stable_prompt_refs"]
    assert "runtime.task_execution.v1" not in manifest["stable_prompt_refs"]
    assert not any(str(ref).startswith("task_prompt_contract:") for ref in manifest["stable_contract_refs"])
    assert any(str(ref).startswith("graph_node_prompt_contract:") for ref in manifest["stable_contract_refs"])
    assert "final_answer 必须是可被下游节点或系统物化的完整结果" in all_message_content
    assert "gchk:hidden" not in all_message_content
    assert "gwork:test:target_node:1" not in all_message_content
    assert "grun:test" not in all_message_content
    task_contract = stable_payload["task_contract"]
    assert "resource_requirements" not in task_contract
    assert "prompt_contract" not in task_contract
    assert "graph_slot" not in task_contract
    graph_context = task_contract["graph_node_context"]
    assert graph_context["node"]["role_prompt"] == "你是一名测试执行员。"
    assert "memory" not in graph_context


def test_graph_node_task_packet_places_shared_stable_segments_before_node_contract() -> None:
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:test:cacheable-node:1",
        work_kind="agent",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        node_id="cacheable_node",
        config_id="ghcfg:test",
        config_hash="hash",
        task_ref="task.test.cacheable_node",
        message="完成目标节点。",
        input_package={"initial_inputs": {"goal": "cache prompt"}},
        graph_slot={
            "authority": "harness.graph.node_execution_slot",
            "slot_id": "gslot:test:cacheable_node",
            "node_contract": {
                "node_identity": {"node_id": "cacheable_node", "title": "可缓存节点", "node_type": "review_gate"},
                "prompt_contract": {"role_prompt": "你是一名测试执行员。"},
            },
            "edge_contracts": {},
            "memory_contract": {},
            "output_contract": {"expected_result_contract": {"output_contract_id": "contract.test.output"}},
        },
        expected_result_contract={"output_contract_id": "contract.test.output"},
    )
    contract = _graph_node_contract_from_work_order(work_order).to_dict()
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-test",
        task_run={
            "task_run_id": "gtask:test-cache",
            "session_id": "session-test",
            "task_id": "task.test.cacheable_node",
            "task_contract_ref": "gcontract:test-cache",
            "diagnostics": {"contract": contract, "graph_run_id": "grun:test", "graph_node_id": "cacheable_node"},
        },
        contract=contract,
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:test-cache",
            "profile": {
                "profile_ref": "main_interactive_agent",
                "context_policy": {"task_run_context": "disabled"},
                "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            },
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": []},
        },
    ).packet

    stable_kinds = [
        segment["kind"]
        for segment in packet.segment_plan["segments"]
        if segment.get("cache_role") in {"cacheable_prefix", "session_stable"}
    ]

    assert stable_kinds.index("artifact_scope_stable") < stable_kinds.index("agent_function_shared_stable")
    assert stable_kinds.index("tool_index_stable") < stable_kinds.index("agent_function_shared_stable")
    assert stable_kinds.index("agent_function_shared_stable") < stable_kinds.index("graph_task_shared_stable")
    if "active_skills" in stable_kinds:
        assert stable_kinds.index("active_skills") < stable_kinds.index("task_contract_stable")
    assert stable_kinds.index("graph_task_shared_stable") < stable_kinds.index("task_contract_stable")
    all_content = "".join(message["content"] for message in packet.model_messages)
    assert "Task execution agent function contract" in all_content
    function_content = next(
        message["content"]
        for message in packet.model_messages
        if message["content"].startswith("Task execution agent function contract")
    )
    function_payload = json.loads(function_content.split("\n", 1)[1])
    assert function_payload["agent_function_shared_context"]["role_family"] == "reviewer"
    assert "Task execution graph shared context" in all_content
    assert "Task execution task contract" in all_content
    assert "graph_node_context" in all_content


def test_graph_node_authorized_input_payload_does_not_duplicate_content_body() -> None:
    body = "上游交接正文" * 200
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:test:dedupe-input:1",
        work_kind="agent",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        node_id="review",
        config_id="ghcfg:test",
        config_hash="hash",
        task_ref="task.test.review",
        message="审核上游交接。",
        graph_slot={
            "authority": "harness.graph.node_execution_slot",
            "slot_id": "gslot:test:review",
            "node_contract": {
                "node_identity": {"node_id": "review", "title": "审核"},
                "prompt_contract": {"role_prompt": "你是一名审核员。"},
            },
            "edge_contracts": {
                "inbound_edge_contexts": [
                    {
                        "target_input_slot": "上游交接包",
                        "packet_type": "handoff",
                        "payload": {
                            "handoff_summary": body,
                            "content": body,
                            "summary": body,
                            "title": "交接包",
                        },
                    }
                ]
            },
            "memory_contract": {},
            "output_contract": {"expected_result_contract": {"output_contract_id": "contract.test.review"}},
        },
        expected_result_contract={"output_contract_id": "contract.test.review"},
    )
    contract = _graph_node_contract_from_work_order(work_order).to_dict()
    payload = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-test",
        task_run={
            "task_run_id": "gtask:test-dedupe",
            "session_id": "session-test",
            "task_id": "task.test.review",
            "task_contract_ref": "gcontract:test-dedupe",
            "diagnostics": {"contract": contract},
        },
        contract=contract,
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:test-dedupe",
            "profile": {
                "profile_ref": "main_interactive_agent",
                "context_policy": {"task_run_context": "disabled"},
                "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            },
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": []},
        },
    ).packet
    task_contract_content = next(
        message["content"]
        for message in payload.model_messages
        if message["content"].startswith("Task execution task contract")
    )
    stable_payload = json.loads(task_contract_content.split("\n", 1)[1])
    inbound = stable_payload["task_contract"]["graph_node_context"]["authorized_inputs"][0]

    assert inbound["content"] == body[:30000]
    assert "payload" not in inbound or len(json.dumps(inbound["payload"], ensure_ascii=False)) < 200
    assert "handoff_summary" not in json.dumps(inbound.get("payload") or {}, ensure_ascii=False)
    assert "content" not in (inbound.get("payload") or {})


def test_graph_node_authorized_input_payload_omits_duplicate_artifact_body() -> None:
    body = "重复正文" * 500
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:test:dedupe-artifact-input:1",
        work_kind="agent",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        node_id="review",
        config_id="ghcfg:test",
        config_hash="hash",
        task_ref="task.test.review",
        message="审核上游交接。",
        graph_slot={
            "authority": "harness.graph.node_execution_slot",
            "slot_id": "gslot:test:review",
            "node_contract": {
                "node_identity": {"node_id": "review", "title": "审核"},
                "prompt_contract": {"role_prompt": "你是一名审核员。"},
            },
            "edge_contracts": {
                "inbound_edge_contexts": [
                    {
                        "target_input_slot": "上游交接包",
                        "packet_type": "handoff",
                        "payload": {
                            "content": body,
                            "artifact_payloads": [
                                {
                                    "artifact_ref": "artifact://draft.md",
                                    "content": body,
                                    "truncated": False,
                                }
                            ],
                        },
                    }
                ]
            },
            "memory_contract": {},
            "output_contract": {"expected_result_contract": {"output_contract_id": "contract.test.review"}},
        },
        expected_result_contract={"output_contract_id": "contract.test.review"},
    )
    contract = _graph_node_contract_from_work_order(work_order).to_dict()
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-test",
        task_run={
            "task_run_id": "gtask:test-dedupe-artifact",
            "session_id": "session-test",
            "task_id": "task.test.review",
            "task_contract_ref": "gcontract:test-dedupe-artifact",
            "diagnostics": {"contract": contract},
        },
        contract=contract,
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:test-dedupe-artifact",
            "profile": {
                "profile_ref": "main_interactive_agent",
                "context_policy": {"task_run_context": "disabled"},
                "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            },
            "task_environment": {"environment_id": "env.test"},
            "operation_authorization": {"allowed_operations": []},
        },
    ).packet
    task_contract_content = next(
        message["content"]
        for message in packet.model_messages
        if message["content"].startswith("Task execution task contract")
    )
    stable_payload = json.loads(task_contract_content.split("\n", 1)[1])
    inbound = stable_payload["task_contract"]["graph_node_context"]["authorized_inputs"][0]
    artifact_payload = inbound["payload"]["artifact_payloads"][0]

    assert inbound["content"] == body[:30000]
    assert artifact_payload["artifact_ref"] == "artifact://draft.md"
    assert "content" not in artifact_payload
    assert artifact_payload["content_omitted_reason"] == "duplicate_of_authorized_input_content"


def test_task_execution_packet_ignores_engagement_shared_prompt_contract() -> None:
    packet = RuntimeCompiler().compile_task_execution_packet(
        session_id="session-shared-prompt",
        task_run={
            "task_run_id": "taskrun:shared-prompt",
            "session_id": "session-shared-prompt",
            "task_id": "task.shared_prompt",
            "agent_profile_id": "main_interactive_agent",
        },
        contract={
            "contract_id": "contract.shared_prompt",
            "user_visible_goal": "验证 engagement 级共享 prompt 不会进入运行包",
            "completion_criteria": ["只保留任务自身合同和环节约束"],
        },
        observations=[],
        runtime_assembly={
            "assembly_id": "rtasm:shared-prompt",
            "profile": {
                "profile_ref": "main_interactive_agent",
                "interaction_policy": {"style": "task_execution"},
                "context_policy": {"task_run_context": "enabled"},
                "operation_authorization_projection": {"model_visible": "summary_without_denials"},
            },
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": [], "denied_operations": []},
            "engagement_contract": {
                "contract_id": "engagement.shared_prompt",
                "prompt_contract": {
                    "role_prompt": "共同契约残留：所有环节都必须遵守这段话。",
                    "task_instruction": "这段共同约束不应该进入任何执行包。",
                },
            },
        },
    ).packet

    all_message_content = "".join(str(message.get("content") or "") for message in packet.model_messages)
    manifest = packet.diagnostics["prompt_manifest"]

    assert "共同契约残留" not in all_message_content
    assert "这段共同约束不应该进入任何执行包" not in all_message_content
    assert not any(str(ref).startswith("task_prompt_contract:") for ref in manifest["stable_contract_refs"])
