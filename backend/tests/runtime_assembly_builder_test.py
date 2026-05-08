from __future__ import annotations

from pathlib import Path

from orchestration.agent_runtime_models import AgentRuntimeProfile
from orchestration.runtime_loop import (
    RuntimeContextManager,
    TaskRunLoop,
    build_node_runtime_assembly,
    build_single_agent_runtime_assembly,
)
from orchestration.runtime_loop.contract_compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledNodeContract,
    ContractManifest,
)
from orchestration.runtime_loop.stage_execution_request import StageExecutionRequest


def _manifest() -> ContractManifest:
    return ContractManifest(
        manifest_id="contract-manifest:test",
        manifest_kind="coordination",
        task_ref="coord.test",
        workflow_id="workflow.test",
        coordination_task_id="coord.test",
        graph_id="coordgraph:test",
        global_contracts=(
            CompiledGlobalContract(
                contract_id="contract.test.input",
                title_zh="输入契约",
                contract_kind="node_execution",
                source_ref="task.test.worker",
                input_fields=({"field_id": "goal", "required": True},),
                output_fields=(),
            ),
            CompiledGlobalContract(
                contract_id="contract.test.output",
                title_zh="输出契约",
                contract_kind="final_output",
                source_ref="task.test.worker",
                output_fields=({"field_id": "answer", "required": True},),
            ),
            CompiledGlobalContract(
                contract_id="contract.test.handoff",
                title_zh="交接契约",
                contract_kind="edge_handoff",
                source_ref="edge.test",
                output_fields=({"field_id": "payload", "required": True},),
            ),
        ),
        node_contracts=(
            CompiledNodeContract(
                node_id="worker",
                title="工作节点",
                node_type="subtask",
                task_id="task.test.worker",
                agent_id="agent:test",
                runtime_lane="test_lane",
                input_contract_id="contract.test.input",
                output_contract_id="contract.test.output",
                contract_refs=("contract.test.input", "contract.test.output"),
            ),
        ),
        edge_handoff_contracts=(
            CompiledEdgeHandoffContract(
                edge_id="coordinator_to_worker",
                source_node_id="coordinator",
                target_node_id="worker",
                message_type="message/send",
                contract_refs=("contract.test.handoff",),
                handoff_policy="filtered_handoff",
            ),
        ),
        acceptance_contracts=(
            CompiledAcceptanceContract(
                contract_id="contract.test.output",
                rule_count=1,
                rule_refs=("answer_present",),
            ),
        ),
    )


def test_single_agent_runtime_assembly_preserves_manifest_refs_and_output_contracts() -> None:
    profile = AgentRuntimeProfile(
        agent_profile_id="test_profile",
        agent_id="agent:test",
        allowed_runtime_lanes=("test_lane",),
    )

    assembly = build_single_agent_runtime_assembly(
        manifest=_manifest(),
        agent_profile=profile,
        explicit_inputs={"goal": "测试"},
        runtime_lane="test_lane",
    )

    payload = assembly.to_dict()
    assert payload["authority"] == "orchestration.single_agent_runtime_assembly"
    assert payload["manifest_ref"] == "contract-manifest:test"
    assert payload["agent_id"] == "agent:test"
    assert payload["diagnostics"]["full_history_included"] is False
    assert any(item["contract_id"] == "contract.test.output" for item in payload["output_contracts"])
    assert any(item["section_id"] == "task_inputs" for item in payload["context_sections"])


def test_node_runtime_assembly_hides_main_history_and_links_handoff_packet() -> None:
    profile = AgentRuntimeProfile(agent_profile_id="test_profile", agent_id="agent:test")

    assembly = build_node_runtime_assembly(
        manifest=_manifest(),
        node_id="worker",
        agent_profile=profile,
        explicit_inputs={"goal": "测试"},
    )
    payload = assembly.to_dict()

    assert payload["authority"] == "orchestration.node_runtime_assembly"
    assert payload["node_id"] == "worker"
    assert payload["diagnostics"]["full_main_session_history_included"] is False
    assert all(item["section_id"] != "main_session_history" for item in payload["context_sections"])
    assert payload["handoff_packets"][0]["a2a_trace"]["message_type"] == "message/send"
    assert payload["handoff_packets"][0]["contract_refs"] == ["contract.test.handoff"]


def test_runtime_context_manager_uses_assembly_visibility_to_hide_history() -> None:
    manager = RuntimeContextManager(lambda **_: "base prompt")
    history = [{"role": "user", "content": "old user"}, {"role": "assistant", "content": "old answer"}]

    default_snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="new",
        history=history,
    )
    node_assembly = build_node_runtime_assembly(
        manifest=_manifest(),
        node_id="worker",
        agent_profile=AgentRuntimeProfile(agent_profile_id="test_profile", agent_id="agent:test"),
    )
    assembly_snapshot = manager.prepare_model_context(
        session_id="session:test",
        task_id="task:test",
        user_message="new",
        history=history,
        runtime_assembly=node_assembly.to_dict(),
    )

    assert default_snapshot.history_message_count == 2
    assert assembly_snapshot.history_message_count == 0
    assert assembly_snapshot.diagnostics["runtime_assembly_context_applied"] is True
    assert "Runtime Assembly" in assembly_snapshot.model_messages[0]["content"]


def test_stage_execution_request_carries_runtime_assembly() -> None:
    assembly = build_node_runtime_assembly(
        manifest=_manifest(),
        node_id="worker",
        agent_profile=AgentRuntimeProfile(agent_profile_id="test_profile", agent_id="agent:test"),
    )

    request = StageExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="thread:test",
        root_task_run_id="taskrun:test",
        stage_id="stage.worker",
        node_id="worker",
        task_ref="task.test.worker",
        runtime_assembly=assembly.to_dict(),
    )
    restored = StageExecutionRequest.from_dict(request.to_dict())

    assert restored.runtime_assembly["assembly_id"] == assembly.assembly_id
    assert restored.to_dict()["runtime_assembly"]["node_id"] == "worker"


def test_task_run_loop_start_writes_runtime_assembly_refs_to_trace(tmp_path: Path) -> None:
    assembly = build_single_agent_runtime_assembly(
        manifest=_manifest(),
        agent_profile=AgentRuntimeProfile(agent_profile_id="test_profile", agent_id="agent:test"),
    )

    result = TaskRunLoop(tmp_path, backend_dir=Path("backend")).start(
        session_id="session:test",
        task_id="task:test",
        agent_id="agent:test",
        agent_profile_id="test_profile",
        runtime_assembly=assembly.to_dict(),
    )

    assert result.task_run.diagnostics["runtime_assembly_ref"] == assembly.assembly_id
    assert result.loop_state.diagnostics["contract_manifest_ref"] == assembly.manifest_ref
    started_event = result.events[0]
    assert started_event["refs"]["runtime_assembly_ref"] == assembly.assembly_id
