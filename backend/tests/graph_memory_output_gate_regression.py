from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query import QueryRuntime
from task_system import TaskFlowRegistry
from task_system.compiler.graph_harness_config_publisher import publish_graph_harness_config_for_graph
from tests.support.runtime_stubs import (
    DefaultPermissionStub,
    EmptySkillRegistryStub,
    EmptyToolRuntimeStub,
    InMemorySessionManagerStub,
    PrimarySettingsStub,
    QueryRuntimeMemoryFacadeStub,
    isolated_backend_root,
)


class CompleteModelRuntimeStub:
    async def invoke_messages(self, _messages, **_kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "authority": "harness.loop.model_action_request",
                    "request_id": "model-action:graph-complete",
                    "action_type": "respond",
                    "public_progress_note": "图节点已完成当前职责，准备提交给图运行器。",
                    "public_action_state": {
                        "current_judgment": "当前节点结果可提交。",
                        "next_action": "提交结果给图运行器。",
                    },
                    "final_answer": "图节点输出正文。",
                    "diagnostics": {
                        "verification": "ok",
                        "final_action_diagnostics": {
                            "structured_output": {"review_verdict": "pass"}
                        },
                    },
                },
                ensure_ascii=False,
            )
        )


def _runtime(prefix: str) -> QueryRuntime:
    return QueryRuntime(
        base_dir=isolated_backend_root(prefix),
        settings_service=PrimarySettingsStub(),
        session_manager=InMemorySessionManagerStub(),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
        retrieval_service=SimpleNamespace(),
        tool_runtime=EmptyToolRuntimeStub(),
        skill_registry=EmptySkillRegistryStub(),
        permission_service=DefaultPermissionStub(),
        model_runtime=CompleteModelRuntimeStub(),
    )


def _runtime_object_payload(runtime: QueryRuntime, ref: str) -> dict:
    payload = runtime.single_agent_runtime_host.runtime_objects.get_object(ref)
    assert payload, f"runtime object not found: {ref}"
    return payload


def test_graph_memory_read_protocol_resolves_snapshot_into_graph_slot() -> None:
    runtime = _runtime("graph-memory-snapshot-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.memory_snapshot_slot",
        title="Memory Snapshot Slot",
        graph_kind="multi_agent",
        entry_node_id="reader",
        output_node_id="reader",
        nodes=(
            {
                "node_id": "memory.repo",
                "node_type": "memory_repository",
                "title": "正式记忆",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.repo",
                        "collections": [{"collection_id": "world"}],
                    }
                },
            },
            {"node_id": "reader", "node_type": "agent", "title": "读取者", "agent_id": "agent:0"},
        ),
        edges=(
            {
                "edge_id": "edge.memory.reader",
                "source_node_id": "memory.repo",
                "target_node_id": "reader",
                "edge_type": "memory_read",
                "metadata": {
                    "repository": "memory.repo",
                    "collection": "world",
                    "selector": {"record_key": "world.current"},
                    "on_missing": "block",
                    "model_visible_label": "世界观基准",
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(
        session_id="session:test",
        task_id="",
        graph_config=graph_config,
        dispatch_ready=False,
    )
    formal_memory = runtime.graph_harness._services.formal_memory_service
    read_edge = {
        "edge_id": "edge.memory.reader",
        "repository": "memory.repo",
        "collection": "world",
        "selector": {"record_key": "world.current"},
    }
    candidate, _txn = formal_memory.write_candidate_from_edge(
        edge=read_edge,
        candidate={"record_key": "world.current", "canonical_text": "洪荒世界基准设定", "summary": "洪荒世界基准设定"},
        task_run_id=start.task_run.task_run_id,
        node_run_id="seed",
        source_node_id="seed",
        source_clock_seq=0,
        runtime_scope=start.envelope.memory_scope["runtime_scope"],
    )
    formal_memory.commit_from_edge(
        edge=read_edge,
        candidate_version_id=candidate.version_id,
        node_run_id="seed.commit",
        source_clock_seq=0,
    )

    dispatched = runtime.graph_harness.graph_loop.dispatch_ready_and_checkpoint(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
    )
    graph_slot = dispatched.node_work_orders[0].graph_slot
    snapshot = graph_slot["memory_contract"]["resolved_snapshots"][0]

    assert snapshot["logical_repository_id"] == "memory.repo"
    assert snapshot["collection_id"] == "world"
    assert snapshot["records"][0]["canonical_text"] == "洪荒世界基准设定"
    assert graph_slot["memory_contract"]["memory_receipt_refs"][0]["read_log_id"]


def test_graph_output_policy_materializes_to_environment_artifact_area() -> None:
    runtime = _runtime("graph-output-policy-env-artifact-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.output_policy_environment_artifact",
        title="Output Policy Environment Artifact",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="draft",
        nodes=(
            {
                "node_id": "draft",
                "node_type": "agent",
                "title": "起草",
                "task_id": "task.test.draft",
                "agent_id": "agent:0",
                "contract_bindings": {
                    "output": {
                        "primary_content_key": "final_answer",
                        "artifact_materialization_policy": {
                            "required": True,
                            "target_repository_id": "repo.writing.artifact_repository",
                            "target_collection_id": "chapter_drafts",
                            "artifact_targets": [
                                {"path": "chapters/chapter_001.md", "required": True, "content_source": "final_answer"}
                            ],
                        },
                    }
                },
            },
        ),
        runtime_policy={"coordinator_agent_id": "agent:0", "task_environment_id": "env.creation.writing"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)
    node_result = _runtime_object_payload(runtime, state["result_index"]["draft"]["result_ref"])
    expected_path = runtime.base_dir.parent / "storage" / "task_environments" / "creation" / "writing" / "artifacts" / "chapters" / "chapter_001.md"
    overview = runtime.graph_harness._services.artifact_repository_service.overview(
        task_run_id=start.task_run.task_run_id,
        graph_run_id=start.graph_run.graph_run_id,
        repository_id="repo.writing.artifact_repository",
    )

    assert result.status == "completed"
    assert expected_path.exists()
    assert "图节点输出正文" in expected_path.read_text(encoding="utf-8")
    assert node_result["artifact_refs"] == ["storage/task_environments/creation/writing/artifacts/chapters/chapter_001.md"]
    assert overview["artifact_count"] == 1
    assert overview["artifacts"][0]["collection_id"] == "chapter_drafts"


def test_post_node_review_gate_waits_before_outbound_edges_and_can_continue() -> None:
    runtime = _runtime("graph-post-node-gate-")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.upsert_task_graph(
        graph_id="graph.test.post_node_gate",
        title="Post Node Gate",
        graph_kind="multi_agent",
        entry_node_id="review",
        output_node_id="next",
        nodes=(
            {
                "node_id": "review",
                "node_type": "agent",
                "title": "审核",
                "task_id": "task.test.review",
                "agent_id": "agent:0",
                "metadata": {
                    "post_node_gate_policy": {
                        "gate_id": "gate.review.after",
                        "mode": "wait_human_after_review_any_result",
                        "review_result_policy": "wait_always",
                    }
                },
            },
            {"node_id": "next", "node_type": "agent", "title": "下游", "task_id": "task.test.next", "agent_id": "agent:0"},
        ),
        edges=(
            {"edge_id": "edge.review.next", "source_node_id": "review", "target_node_id": "next", "edge_type": "handoff"},
        ),
        runtime_policy={"coordinator_agent_id": "agent:0"},
        publish_state="published",
        enabled=True,
    )
    graph_config = publish_graph_harness_config_for_graph(base_dir=runtime.base_dir, graph_id=graph.graph_id)
    start = runtime.graph_harness.start_run(session_id="session:test", task_id="", graph_config=graph_config)

    result = asyncio.run(
        runtime.graph_harness.run_until_idle(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            max_node_executions=1,
            max_node_steps=1,
        )
    )
    waiting_state = runtime.graph_harness.get_checkpoint_state(start.graph_run.graph_run_id)

    assert result.status == "waiting_human_gate"
    assert waiting_state["node_states"]["review"]["status"] == "waiting_human_gate"
    assert waiting_state["node_states"]["next"]["status"] == "pending"
    assert waiting_state["edge_states"]["edge.review.next"]["status"] == "pending"
    assert waiting_state["active_work_orders"] == {}

    advance = runtime.graph_harness.apply_human_gate_decision(
        graph_config=graph_config,
        graph_run_id=start.graph_run.graph_run_id,
        decision={"node_id": "review", "human_action": "approve_continue", "reason": "人工确认继续"},
    )

    assert advance.loop_state.node_states["review"]["status"] == "completed"
    assert advance.loop_state.edge_states["edge.review.next"]["status"] == "ready"
    assert advance.node_work_orders[0].node_id == "next"
