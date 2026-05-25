from __future__ import annotations

from pathlib import Path

import pytest

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from runtime import (
    RuntimeContextManager,
    TaskRunLoop,
    build_node_runtime_assembly,
)
from agent_system.assembly.runtime_chain import _memory_request_profile_for_context_assembly
from runtime.contracts.compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledNodeContract,
    ContractManifest,
)
from runtime.execution.node_execution_request import NodeExecutionRequest
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


def _manifest() -> ContractManifest:
    return ContractManifest(
        manifest_id="contract-manifest:test",
        manifest_kind="coordination",
        task_ref="graph.test",
        workflow_id="workflow.test",
        graph_id="graph.test",
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
                runtime_lane="readonly_exploration",
                projection_id="projection.test.node_worker",
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
    assert payload["projection_id"] == "projection.test.node_worker"
    assert payload["diagnostics"]["projection_resolution_source"] == "node"
    assert payload["diagnostics"]["projection_ref"] == "projection.test.node_worker"
    assert payload["diagnostics"]["agent_resolution_source"] == "node"
    assert payload["diagnostics"]["agent_profile_ref"] == "test_profile"
    assert payload["diagnostics"]["prompt_manifest_ref"] == "contract-manifest:test"
    assert payload["diagnostics"]["task_graph_node_ref"] == "graph.test:worker"
    assert payload["diagnostics"]["full_main_session_history_included"] is False
    assert all(item["section_id"] != "main_session_history" for item in payload["context_sections"])
    assert payload["handoff_packets"][0]["a2a_trace"]["message_type"] == "message/send"
    assert payload["handoff_packets"][0]["contract_refs"] == ["contract.test.handoff"]


def test_node_runtime_assembly_exposes_artifact_policy_as_runtime_contract_section() -> None:
    manifest = ContractManifest(
        manifest_id="contract-manifest:artifact-policy",
        manifest_kind="coordination",
        task_ref="graph.test",
        workflow_id="workflow.test",
        graph_id="graph.test",
        node_contracts=(
            CompiledNodeContract(
                node_id="writer",
                title="写作节点",
                node_type="agent",
                task_id="task.test.writer",
                agent_id="agent:test",
                artifact_bindings={
                    "artifact_policy": {
                        "enabled": True,
                        "required": True,
                        "default_artifact_root": "output/demo",
                        "artifacts": [
                            {
                                "path": "chapter.md",
                                "required": True,
                                "content_source": "final_content",
                                "fallback_to_full_content": True,
                            }
                        ],
                    }
                },
            ),
        ),
    )

    assembly = build_node_runtime_assembly(
        manifest=manifest,
        node_id="writer",
        agent_profile=AgentRuntimeProfile(
            agent_profile_id="test_profile",
            agent_id="agent:test",
            allowed_context_sections=("task", "runtime_contracts"),
        ),
    ).to_dict()

    policy_section = next(item for item in assembly["context_sections"] if item["section_id"] == "artifact_policy")
    assert policy_section["metadata"]["artifact_policy"]["target_paths"] == ["chapter.md"]
    assert policy_section["metadata"]["artifact_policy"]["runtime_rule"] == "required_final_content_materialized_to_configured_files"


def test_node_runtime_assembly_exposes_layered_context_sections() -> None:
    manifest = ContractManifest(
        manifest_id="contract-manifest:layered",
        manifest_kind="coordination",
        graph_id="graph.layered",
        graph_ref="graph.layered",
        node_contracts=(
            CompiledNodeContract(
                node_id="draft",
                title="起草",
                node_type="agent",
                task_id="task.draft",
                agent_id="agent:writer",
            ),
        ),
        metadata={
            "layered_graph": {
                "resource_nodes": [
                    {
                        "node_id": "memory.baseline",
                        "repository_id": "baseline",
                        "resource_type": "memory_repository",
                    }
                ],
                "memory_edges": [
                    {
                        "edge_id": "memory.baseline.read",
                        "source_node_id": "memory.baseline",
                        "target_node_id": "draft",
                        "memory_edge_type": "read",
                        "record_keys": ["project_rules"],
                        "version_selector": "latest_committed_before_stage_start",
                        "on_missing": "block",
                    }
                ],
                "artifact_context_edges": [
                    {
                        "edge_id": "plan.draft.artifact",
                        "source_node_id": "plan",
                        "target_node_id": "draft",
                        "context_mode": "expand_text_for_model",
                        "source_output_key": "plan_md",
                        "target_input_key": "plan_context",
                    }
                ],
                "revision_edges": [
                    {
                        "edge_id": "review.draft.revision",
                        "source_node_id": "review",
                        "target_node_id": "draft",
                        "carry": ["previous_candidate_ref", "review_result_ref"],
                    }
                ],
                "temporal_edges": [
                    {
                        "edge_id": "temporal:plan->draft",
                        "source_node_id": "plan",
                        "target_node_id": "draft",
                        "blocking": True,
                    }
                ],
            }
        },
    )

    assembly = build_node_runtime_assembly(
        manifest=manifest,
        node_id="draft",
        agent_profile=AgentRuntimeProfile(agent_profile_id="writer_profile", agent_id="agent:writer"),
    )
    payload = assembly.to_dict()

    section_ids = {item["section_id"] for item in payload["context_sections"]}
    assert {"memory_snapshot", "artifact_context", "revision_context"}.issubset(section_ids)
    layered = payload["metadata"]["layered_context"]
    assert layered["memory_snapshot"]["retrieval_mode"] == "directed_repository_edges"
    assert layered["memory_reads"][0]["repository"] == "baseline"
    assert layered["artifact_context_edges"][0]["source_output_key"] == "plan_md"
    assert layered["revision_edges"][0]["carry"] == ["previous_candidate_ref", "review_result_ref"]
    assert payload["diagnostics"]["layered_context"]["memory_read_edge_count"] == 1
    assert payload["diagnostics"]["layered_context"]["temporal_incoming_edge_count"] == 1


def test_node_runtime_assembly_carries_conversation_memory_suppression_policy() -> None:
    manifest = ContractManifest(
        manifest_id="contract-manifest:test",
        manifest_kind="coordination",
        graph_id="graph.test",
        node_contracts=(
            CompiledNodeContract(
                node_id="worker",
                title="工作节点",
                node_type="subtask",
                task_id="task.test.worker",
                agent_id="agent:test",
                metadata={
                    "context_visibility_policy": {
                        "conversation_memory": "hidden",
                        "suppress_conversation_memory": True,
                    },
                },
            ),
        ),
    )
    assembly = build_node_runtime_assembly(
        manifest=manifest,
        node_id="worker",
        agent_profile=AgentRuntimeProfile(agent_profile_id="test_profile", agent_id="agent:test"),
    )

    policy = assembly.to_dict()["diagnostics"]["context_assembly_policy"]

    assert policy["main_session_history"] == "hidden"
    assert policy["conversation_memory"] == "hidden"
    assert policy["suppress_conversation_memory"] is True


def test_context_assembly_policy_filters_conversation_memory_layer() -> None:
    profile = {
        "requested_memory_layers": ["conversation", "state", "long_term"],
        "allow_long_term_memory": True,
    }
    runtime_assembly = {
        "diagnostics": {
            "context_assembly_policy": {
                "suppress_conversation_memory": True,
            },
        },
    }

    filtered = _memory_request_profile_for_context_assembly(
        profile,
        runtime_assembly=runtime_assembly,
    )

    assert filtered["requested_memory_layers"] == ["state", "long_term"]
    assert filtered["allow_long_term_memory"] is False
    assert filtered["conversation_memory_suppressed"] is True


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
    assert "可用参考材料" in assembly_snapshot.model_messages[0]["content"]


def test_stage_execution_request_carries_runtime_assembly() -> None:
    assembly = build_node_runtime_assembly(
        manifest=_manifest(),
        node_id="worker",
        agent_profile=AgentRuntimeProfile(agent_profile_id="test_profile", agent_id="agent:test"),
    )

    request = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="thread:test",
        root_task_run_id="taskrun:test",
        stage_id="stage.worker",
        node_id="worker",
        task_ref="task.test.worker",
        runtime_assembly=assembly.to_dict(),
    )
    restored = NodeExecutionRequest.from_dict(request.to_dict())

    assert restored.runtime_assembly["assembly_id"] == assembly.assembly_id
    assert restored.to_dict()["runtime_assembly"]["node_id"] == "worker"
    assert restored.to_dict()["runtime_assembly"]["projection_id"] == "projection.test.node_worker"


def test_task_run_loop_starts_task_graph_with_real_dispatch_plan(tmp_path: Path) -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.task_graph_run",
        title="测试任务图运行",
        graph_kind="multi_agent",
        publish_state="published",
        entry_node_id="collect",
        output_node_id="review",
        runtime_policy={"coordinator_agent_id": "agent:coordinator"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="collect",
                node_type="agent",
                title="资料整理",
                task_id="task.test.collect",
                agent_id="agent:collector",
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                task_id="task.test.review",
                agent_id="agent:reviewer",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="collect_to_review",
                source_node_id="collect",
                target_node_id="review",
                payload_contract_id="contract.collect.review",
            ),
        ),
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)

    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    result = loop.start_task_graph_run(
        session_id="session:test",
        graph=graph,
        runtime_spec=runtime_spec,
    )

    trace = loop.get_trace(result.task_run.task_run_id)
    checkpoint = loop.checkpoints.load_latest(result.task_run.task_run_id)
    indexed_task_run = loop.state_index.get_task_run(result.task_run.task_run_id)
    assert result.coordination_run is not None
    assert result.task_run.diagnostics["task_graph_run"] is True
    dispatch_plan_summary = result.task_run.diagnostics["agent_dispatch_plan_summary"]
    assert result.task_run.diagnostics["agent_dispatch_plan_ref"].startswith("rtobj:dispatch_plans:")
    assert dispatch_plan_summary["record_count"] == 2
    assert dispatch_plan_summary["ready_node_ids"] == ["collect"]
    assert dispatch_plan_summary["blocked_node_ids"] == ["review"]
    stage_request = result.loop_state.diagnostics["stage_execution_request"]
    assert stage_request["stage_id"] == "collect"
    assert stage_request["task_ref"] == "task.test.collect"
    assert stage_request["runtime_assembly"]["node_id"] == "collect"
    assert trace is not None
    assert trace["coordination_runs"][0]["graph_ref"] == graph.graph_id
    assert checkpoint is not None
    assert checkpoint.loop_state.runtime_lane == "task_graph_coordination"
    assert checkpoint.loop_state.diagnostics["langgraph_coordination_initialized"] is True
    assert indexed_task_run is not None
    assert indexed_task_run.latest_checkpoint_ref == checkpoint.checkpoint_id


def test_task_run_loop_restores_task_graph_initial_inputs_for_same_session_graph(tmp_path: Path) -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.restore_inputs",
        title="恢复初始输入",
        graph_kind="multi_agent",
        publish_state="published",
        entry_node_id="collect",
        output_node_id="review",
        runtime_policy={"coordinator_agent_id": "agent:coordinator"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="collect",
                node_type="agent",
                title="资料整理",
                task_id="task.test.collect",
                agent_id="agent:collector",
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                task_id="task.test.review",
                agent_id="agent:reviewer",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="collect_to_review",
                source_node_id="collect",
                target_node_id="review",
                payload_contract_id="contract.collect.review",
            ),
        ),
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))

    first = loop.start_task_graph_run(
        session_id="session:test",
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs={"project_brief": "洪荒时代", "title": "洪荒时代"},
    )
    second = loop.start_task_graph_run(
        session_id="session:test",
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs={},
    )

    restored_ref = str(second.task_run.diagnostics.get("task_graph_initial_inputs_ref") or "")
    restored_payload = loop.runtime_objects.get_object(restored_ref)
    assert first.task_run.diagnostics["task_graph_initial_input_keys"] == ["project_brief", "title"]
    assert second.task_run.diagnostics["task_graph_initial_input_keys"] == ["project_brief", "title"]
    assert restored_payload["initial_inputs"] == {"project_brief": "洪荒时代", "title": "洪荒时代"}


def test_task_run_loop_rejects_legacy_task_graph_fallback_when_langgraph_support_missing(tmp_path: Path, monkeypatch) -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.no_legacy_fallback",
        title="禁止旧续推回退",
        graph_kind="multi_agent",
        publish_state="published",
        entry_node_id="collect",
        output_node_id="review",
        runtime_policy={"coordinator_agent_id": "agent:coordinator"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="collect",
                node_type="agent",
                title="资料整理",
                task_id="task.test.collect",
                agent_id="agent:collector",
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                task_id="task.test.review",
                agent_id="agent:reviewer",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="collect_to_review",
                source_node_id="collect",
                target_node_id="review",
                payload_contract_id="contract.collect.review",
            ),
        ),
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    monkeypatch.setattr(loop.langgraph_coordination_runtime, "supports", lambda coordination_run: False)

    with pytest.raises(RuntimeError, match="legacy initialization fallback was removed"):
        loop.start_task_graph_run(
            session_id="session:test",
            graph=graph,
            runtime_spec=runtime_spec,
        )


def test_stage_execution_request_carries_working_memory_refs() -> None:
    request = NodeExecutionRequest(
        request_id="",
        coordination_run_id="coordrun:test",
        thread_id="thread:test",
        root_task_run_id="taskrun:test",
        stage_id="stage.writer",
        node_id="writer",
        task_ref="task.writer",
        working_memory_refs=("wm:1", "wm:2"),
    )

    restored = NodeExecutionRequest.from_dict(request.to_dict())

    assert restored.working_memory_refs == ("wm:1", "wm:2")


def test_runtime_checkpoint_carries_working_memory_refs(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))

    started = loop.start(
        session_id="session:wm-checkpoint",
        task_id="task:wm-checkpoint",
        runtime_assembly={
            "context_sections": [
                {"section_id": "working_memory.required", "metadata": {"refs": ["wm:accepted"]}},
                {"section_id": "working_memory.preferred", "metadata": {"refs": ["wm:proposed"]}},
            ],
        },
    )

    loaded = loop.checkpoints.load_latest(started.task_run.task_run_id)

    assert loaded is not None
    assert loaded.working_memory_refs == ("wm:accepted", "wm:proposed")


def test_task_run_loop_can_submit_working_memory_candidates(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))

    stored = loop.submit_working_memory_candidates(
        task_run_id="taskrun:test",
        node_id="writer",
        node_run_id="writer.run.001",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:test",
        candidates=(
            {
                "kind": "chapter_draft",
                "summary": "第一章草稿",
                "status": "draft",
            },
            {
                "kind": "review_note",
                "summary": "需要补连续性检查",
                "status": "proposed",
            },
        ),
    )

    assert len(stored) == 2
    assert stored[0].owner_node_id == "writer"
    assert stored[0].node_run_id == "writer.run.001"
    assert stored[1].writer_agent_id == "agent:test"


def test_task_run_loop_can_finalize_working_memory_without_durable_promotion(tmp_path: Path) -> None:
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    stored = loop.submit_working_memory_candidates(
        task_run_id="taskrun:test-finalize",
        node_id="writer",
        node_run_id="writer.run.001",
        writer_agent_id="agent:test",
        candidates=(
            {
                "kind": "chapter_draft",
                "summary": "章节草稿",
                "status": "accepted",
                "artifact_refs": ["artifact:chapter-1"],
            },
            {
                "kind": "review_note",
                "summary": "未采纳审查意见",
                "status": "proposed",
            },
        ),
    )

    finalized = loop.finalize_working_memory(
        task_run_id="taskrun:test-finalize",
        actor_id="agent:main",
        terminal_reason="completed",
    )

    result = finalized["result"]
    assert result["artifact_candidate_count"] == 1
    assert result["discarded_count"] == 1
    assert finalized["event"]["event_type"] == "working_memory_finalized"
    assert loop.working_memory.get_item(stored[0].work_memory_id).status == "archived"
    assert loop.working_memory.get_item(stored[0].work_memory_id).promotion_state == "promoted_to_artifact_store"
    assert loop.working_memory.get_item(stored[1].work_memory_id).status == "discarded"
