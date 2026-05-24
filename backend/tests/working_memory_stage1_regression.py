from __future__ import annotations

from memory_system import MemoryFacade, MemoryContextCandidate, WorkingMemoryPolicyProfile


def test_working_memory_item_is_node_run_scoped_and_idempotent(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    first = facade.create_working_memory_item(
        task_run_id="taskrun:novel",
        task_id="task.novel",
        graph_id="graph:novel",
        owner_node_id="chapter_writer",
        node_run_id="chapter_writer.chapter_001",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:writer",
        kind="chapter_draft",
        summary="第一章草稿片段",
        payload={"chapter": 1, "text": "..."}, 
        idempotency_key="chapter-001-attempt-01-draft",
    )
    duplicate = facade.create_working_memory_item(
        task_run_id="taskrun:novel",
        task_id="task.novel",
        graph_id="graph:novel",
        owner_node_id="chapter_writer",
        node_run_id="chapter_writer.chapter_001",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:writer",
        kind="chapter_draft",
        summary="第一章草稿片段",
        payload={"chapter": 1, "text": "..."}, 
        idempotency_key="chapter-001-attempt-01-draft",
    )
    second_run = facade.create_working_memory_item(
        task_run_id="taskrun:novel",
        task_id="task.novel",
        graph_id="graph:novel",
        owner_node_id="chapter_writer",
        node_run_id="chapter_writer.chapter_002",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:writer",
        kind="chapter_draft",
        summary="第二章草稿片段",
        payload={"chapter": 2, "text": "..."}, 
        idempotency_key="chapter-002-attempt-01-draft",
    )

    assert first.work_memory_id == duplicate.work_memory_id
    assert first.node_run_id == "chapter_writer.chapter_001"
    assert second_run.node_run_id == "chapter_writer.chapter_002"

    chapter_one = facade.query_working_memory_items(node_run_id="chapter_writer.chapter_001")
    chapter_two = facade.query_working_memory_items(node_run_id="chapter_writer.chapter_002")

    assert len(chapter_one) == 1
    assert len(chapter_two) == 1
    assert chapter_one[0].summary == "第一章草稿片段"
    assert chapter_two[0].summary == "第二章草稿片段"


def test_working_memory_status_transition_and_read_log_are_persisted(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    item = facade.create_working_memory_item(
        task_run_id="taskrun:coord",
        graph_id="graph:coord",
        owner_node_id="planner",
        node_run_id="planner.run.001",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:planner",
        kind="plan_fragment",
        summary="拆分三阶段执行计划",
    )

    accepted = facade.accept_working_memory_item(item.work_memory_id, actor_id="agent:main")
    log = facade.record_working_memory_read(
        task_run_id="taskrun:coord",
        graph_id="graph:coord",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        reader_agent_id="agent:writer",
        selected_item_ids=[item.work_memory_id],
        request={"requested_kind": "plan_fragment"},
    )

    assert accepted.status == "accepted"
    assert accepted.authority == "coordinator_adopted"
    assert log.selected_item_ids == (item.work_memory_id,)
    assert log.token_estimate > 0

    logs = facade.list_working_memory_read_logs("taskrun:coord")
    assert len(logs) == 1
    assert logs[0].reader_agent_id == "agent:writer"


def test_working_memory_handoff_transaction_and_temporal_edges_work(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    draft = facade.create_working_memory_item(
        task_run_id="taskrun:story",
        graph_id="graph:story",
        owner_node_id="scene_writer",
        node_run_id="scene_writer.scene_01",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:scene",
        kind="timeline_event_draft",
        summary="主角在夜里离开故乡",
    )
    result = facade.create_working_memory_item(
        task_run_id="taskrun:story",
        graph_id="graph:story",
        owner_node_id="scene_writer",
        node_run_id="scene_writer.scene_02",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:scene",
        kind="timeline_event_draft",
        summary="主角抵达都城",
    )

    transaction = facade.create_working_memory_handoff_transaction(
        task_run_id="taskrun:story",
        graph_id="graph:story",
        edge_id="scene_01_to_scene_02",
        handoff_id="handoff:scene:01:02",
        source_message_hash="hash:scene:01:02",
        candidate_work_memory_ids=[draft.work_memory_id],
    )
    committed = facade.commit_working_memory_handoff_transaction(
        transaction.transaction_id,
        adopted_work_memory_ids=[draft.work_memory_id],
        ephemeral_context_refs=["scene-summary:01"],
    )
    edge = facade.create_working_memory_temporal_edge(
        task_run_id="taskrun:story",
        graph_id="graph:story",
        source_item_id=draft.work_memory_id,
        target_item_id=result.work_memory_id,
        relation="before",
        source_node_id="scene_writer",
    )

    assert committed.transaction_status == "committed"
    assert committed.adopted_work_memory_ids == (draft.work_memory_id,)
    assert edge.relation == "before"
    assert facade.list_working_memory_temporal_edges("taskrun:story")[0].target_item_id == result.work_memory_id


def test_working_memory_controlled_read_respects_visibility_and_scope(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    shared = facade.create_working_memory_item(
        task_run_id="taskrun:visibility",
        graph_id="graph:visibility",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        writer_agent_id="agent:a",
        kind="plan_fragment",
        summary="可共享计划",
        status="accepted",
        visibility="shared_in_graph",
        scope="graph_scope",
    )
    facade.create_working_memory_item(
        task_run_id="taskrun:visibility",
        graph_id="graph:visibility",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        writer_agent_id="agent:a",
        kind="private_note",
        summary="A 的私有记录",
        status="accepted",
        visibility="private_to_agent",
        scope="node_scope",
    )

    selection = facade.select_working_memory_for_node(
        task_run_id="taskrun:visibility",
        graph_id="graph:visibility",
        owner_node_id="writer",
        node_run_id="writer.run.002",
        reader_agent_id="agent:b",
        memory_read_policy={"readable_kinds": ["plan_fragment", "private_note"], "readable_scopes": ["graph_scope", "node_scope"]},
        request={"requested_kinds": ["plan_fragment", "private_note"], "acceptable_scopes": ["graph_scope", "node_scope"]},
    )

    selected_ids = {item.work_memory_id for item in selection["required_items"]}
    assert selected_ids == {shared.work_memory_id}
    assert selection["read_log"].excluded_item_ids


def test_working_memory_dynamic_read_denial_is_logged(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    selection = facade.select_working_memory_for_node(
        task_run_id="taskrun:denied",
        graph_id="graph:denied",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        reader_agent_id="agent:writer",
        memory_read_policy={"readable_kinds": ["plan_fragment"], "readable_scopes": ["graph_scope"]},
        dynamic_read_policy={"allow_dynamic_read": True, "max_dynamic_reads_per_node_run": 1},
        request={"dynamic": True, "requested_kinds": ["secret_note"], "acceptable_scopes": ["graph_scope"]},
    )

    assert selection["denied_reason"] == "requested_kind_outside_policy"
    logs = facade.list_working_memory_read_logs("taskrun:denied")
    assert len(logs) == 1
    assert logs[0].denied_reason == "requested_kind_outside_policy"


def test_working_memory_temporal_expansion_respects_limit(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    first = facade.create_working_memory_item(
        task_run_id="taskrun:temporal",
        graph_id="graph:temporal",
        owner_node_id="writer",
        node_run_id="writer.chapter_001",
        kind="character_state_delta",
        summary="角色受伤",
        status="accepted",
        visibility="shared_in_graph",
        scope="graph_scope",
    )
    second = facade.create_working_memory_item(
        task_run_id="taskrun:temporal",
        graph_id="graph:temporal",
        owner_node_id="writer",
        node_run_id="writer.chapter_002",
        kind="character_state_delta",
        summary="角色恢复",
        status="accepted",
        visibility="shared_in_graph",
        scope="graph_scope",
    )
    facade.create_working_memory_temporal_edge(
        task_run_id="taskrun:temporal",
        graph_id="graph:temporal",
        source_item_id=first.work_memory_id,
        target_item_id=second.work_memory_id,
        relation="before",
    )

    selection = facade.select_working_memory_for_node(
        task_run_id="taskrun:temporal",
        graph_id="graph:temporal",
        owner_node_id="reviewer",
        node_run_id="reviewer.run.001",
        reader_agent_id="agent:reviewer",
        memory_read_policy={"readable_kinds": ["character_state_delta"], "readable_scopes": ["graph_scope"]},
        dynamic_read_policy={"allow_dynamic_read": True, "max_dynamic_reads_per_node_run": 2, "allow_temporal_expansion": True, "max_temporal_neighbors": 1},
        request={"dynamic": True, "requested_kinds": ["character_state_delta"], "acceptable_scopes": ["graph_scope"], "required_stage_ids": [], "include_temporal_neighbors": True, "max_items": 1},
    )

    selected_ids = [item.work_memory_id for item in selection["required_items"]]
    assert selected_ids == [first.work_memory_id, second.work_memory_id]


def test_working_memory_handoff_resolution_is_idempotent_and_adopts_refs(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    accepted = facade.create_working_memory_item(
        task_run_id="taskrun:handoff",
        graph_id="graph:handoff",
        owner_node_id="planner",
        node_run_id="planner.run.001",
        kind="plan_fragment",
        summary="已采纳计划",
        status="accepted",
        visibility="handoff_only",
        scope="edge_scope",
    )

    first = facade.resolve_working_memory_handoff(
        task_run_id="taskrun:handoff",
        graph_id="graph:handoff",
        edge_id="planner_to_writer",
        source_node_run_id="planner.run.001",
        target_node_run_id="writer.run.001",
        handoff_id="handoff:planner:writer:001",
        source_message_hash="hash:planner:writer:001",
        working_memory_refs=[accepted.work_memory_id],
        summary="计划摘要",
    )
    replay = facade.resolve_working_memory_handoff(
        task_run_id="taskrun:handoff",
        graph_id="graph:handoff",
        edge_id="planner_to_writer",
        source_node_run_id="planner.run.001",
        target_node_run_id="writer.run.001",
        handoff_id="handoff:planner:writer:001",
        source_message_hash="hash:planner:writer:001",
        working_memory_refs=[accepted.work_memory_id],
        summary="计划摘要",
    )

    assert replay.transaction_id == first.transaction_id
    assert first.transaction_status == "committed"
    assert first.adopted_work_memory_ids == (accepted.work_memory_id,)
    assert len(facade.list_working_memory_handoff_transactions("taskrun:handoff")) == 1


def test_working_memory_policy_profile_round_trip(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    profile = facade.save_working_memory_policy_profile(
        profile_id="wmprofile:novel",
        allowed_kinds=["chapter_draft", "character_state_delta", "continuity_conflict"],
        allowed_semantics=["draft_artifact", "working_fact", "conflict"],
        dynamic_read_rules={"allow_dynamic_read": True, "max_dynamic_reads_per_node_run": 3},
        temporal_rules={"enabled": True, "max_temporal_neighbors": 4},
        retry_memory_rules={"keep_failure_reflection": True},
    )

    loaded = facade.get_working_memory_policy_profile("wmprofile:novel")

    assert isinstance(profile, WorkingMemoryPolicyProfile)
    assert loaded is not None
    assert loaded.profile_id == "wmprofile:novel"
    assert "chapter_draft" in loaded.allowed_kinds
    assert loaded.dynamic_read_rules["allow_dynamic_read"] is True


def test_working_memory_context_candidates_remain_candidate_only(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    accepted = facade.create_working_memory_item(
        task_run_id="taskrun:ctx",
        task_id="task.ctx",
        graph_id="graph:ctx",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        writer_agent_id="agent:writer",
        kind="chapter_draft",
        summary="章节草稿候选",
        status="accepted",
    )
    proposed = facade.create_working_memory_item(
        task_run_id="taskrun:ctx",
        task_id="task.ctx",
        graph_id="graph:ctx",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        writer_agent_id="agent:writer",
        kind="failure_reflection",
        summary="本轮失败原因总结",
        status="proposed",
    )

    candidates = facade.build_working_memory_context_candidates(
        task_run_id="taskrun:ctx",
        node_run_id="writer.run.001",
    )

    assert len(candidates) == 2
    assert all(isinstance(item, MemoryContextCandidate) for item in candidates)
    assert all(item.memory_layer == "working" for item in candidates)
    assert all(item.authority == "candidate_only" for item in candidates)
    assert all(item.can_override_current_turn is False for item in candidates)
    accepted_candidate = next(item for item in candidates if item.content_ref == accepted.work_memory_id)
    proposed_candidate = next(item for item in candidates if item.content_ref == proposed.work_memory_id)
    assert accepted_candidate.requires_verification_before_use is False
    assert proposed_candidate.requires_verification_before_use is True


def test_memory_runtime_view_includes_working_memory_candidates_when_requested(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.create_working_memory_item(
        task_run_id="taskrun:view",
        task_id="task.view",
        graph_id="graph:view",
        owner_node_id="planner",
        node_run_id="planner.run.001",
        writer_agent_id="agent:planner",
        kind="plan_fragment",
        summary="按三阶段推进任务",
        status="accepted",
    )
    facade.create_working_memory_item(
        task_run_id="taskrun:view",
        task_id="task.view",
        graph_id="graph:view",
        owner_node_id="planner",
        node_run_id="planner.run.002",
        writer_agent_id="agent:planner",
        kind="plan_fragment",
        summary="这是另外一次运行的计划",
        status="accepted",
    )

    view = facade.build_memory_runtime_view(
        session_id="session-working-view",
        memory_request_profile={
            "requested_memory_layers": ["working"],
            "task_run_id": "taskrun:view",
            "graph_id": "graph:view",
            "node_run_id": "planner.run.001",
            "working_memory_kinds": ["plan_fragment"],
        },
    )

    assert view.context_candidates
    assert {item.memory_layer for item in view.context_candidates} == {"working"}
    assert len(view.context_candidates) == 1
    assert view.diagnostics["working_candidate_count"] == 1
    assert view.diagnostics["working_memory_task_run_id"] == "taskrun:view"
    assert view.context_candidates[0].metadata["node_run_id"] == "planner.run.001"


def test_memory_runtime_view_includes_task_durable_only_when_requested(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    item = facade.create_task_durable_memory_item(
        task_id="task.view",
        graph_id="graph:view",
        kind="project_rule",
        title="任务规则",
        canonical_statement="任务内读取任务长期记忆，不默认读取全局长期记忆。",
    )

    default_view = facade.build_memory_runtime_view(
        session_id="session-task-durable-view",
        memory_request_profile={
            "requested_memory_layers": ["working"],
            "task_id": "task.view",
            "graph_id": "graph:view",
        },
    )
    task_durable_view = facade.build_memory_runtime_view(
        session_id="session-task-durable-view",
        memory_request_profile={
            "requested_memory_layers": ["task_durable"],
            "task_id": "task.view",
            "graph_id": "graph:view",
        },
    )

    assert default_view.context_candidates == ()
    assert len(task_durable_view.context_candidates) == 1
    assert task_durable_view.context_candidates[0].memory_layer == "task_durable"
    assert task_durable_view.context_candidates[0].content_ref == item.task_memory_id
    assert task_durable_view.diagnostics["task_durable_candidate_count"] == 1


def test_memory_bundle_carries_working_memory_candidates_without_write_authority(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    facade.create_working_memory_item(
        task_run_id="taskrun:bundle",
        task_id="task.bundle",
        graph_id="graph:bundle",
        owner_node_id="reviewer",
        node_run_id="reviewer.run.001",
        writer_agent_id="agent:reviewer",
        kind="review_note",
        summary="需要补充连续性检查",
        status="accepted",
    )

    bundle = facade.build_memory_bundle(
        task_id="task.bundle",
        session_id="session-working-bundle",
        agent_id="agent:0",
        memory_request_profile={
            "requested_memory_layers": ["working"],
            "task_run_id": "taskrun:bundle",
            "graph_id": "graph:bundle",
            "node_run_id": "reviewer.run.001",
        },
    )

    assert bundle.runtime_view.read_only is True
    assert bundle.runtime_view.memory_write_allowed is False
    assert len(bundle.context_candidates) == 1
    assert bundle.context_candidates[0].memory_layer == "working"
    assert bundle.selected_layers == ("working",)


def test_working_memory_finalizer_splits_archive_promotion_conflict_and_discard(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    accepted_plan = facade.create_working_memory_item(
        task_run_id="taskrun:finalize",
        graph_id="graph:finalize",
        owner_node_id="planner",
        node_run_id="planner.run.001",
        writer_agent_id="agent:planner",
        kind="decision_record",
        summary="采用三阶段方案",
        status="accepted",
    )
    draft = facade.create_working_memory_item(
        task_run_id="taskrun:finalize",
        graph_id="graph:finalize",
        owner_node_id="writer",
        node_run_id="writer.run.001",
        writer_agent_id="agent:writer",
        kind="intermediate_result",
        summary="未采纳的中间草稿",
        status="draft",
    )
    conflict = facade.create_working_memory_item(
        task_run_id="taskrun:finalize",
        graph_id="graph:finalize",
        owner_node_id="reviewer",
        node_run_id="reviewer.run.001",
        writer_agent_id="agent:reviewer",
        kind="continuity_conflict",
        summary="存在连续性冲突",
        status="conflicted",
    )

    result = facade.finalize_working_memory_task_run(
        "taskrun:finalize",
        actor_id="agent:main",
        terminal_reason="completed",
    )

    loaded_plan = facade.get_working_memory_item(accepted_plan.work_memory_id)
    loaded_draft = facade.get_working_memory_item(draft.work_memory_id)
    loaded_conflict = facade.get_working_memory_item(conflict.work_memory_id)

    assert result.promotion_candidate_count == 1
    assert result.discarded_count == 1
    assert result.unresolved_conflict_count == 1
    assert loaded_plan is not None
    assert loaded_plan.status == "archived"
    assert loaded_plan.promotion_state == "needs_review"
    assert loaded_draft is not None
    assert loaded_draft.status == "discarded"
    assert loaded_conflict is not None
    assert loaded_conflict.status == "conflicted"
    assert loaded_conflict.promotion_state == "promoted_to_health_issue"


def test_working_memory_finalizer_retains_retry_memory_by_attempt(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    reflection = facade.create_working_memory_item(
        task_run_id="taskrun:retry",
        owner_node_id="writer",
        node_run_id="writer.chapter_01",
        run_attempt_id="attempt_01",
        kind="failure_reflection",
        summary="第一轮失败原因",
        status="proposed",
    )
    guidance = facade.create_working_memory_item(
        task_run_id="taskrun:retry",
        owner_node_id="writer",
        node_run_id="writer.chapter_01",
        run_attempt_id="attempt_02",
        kind="retry_guidance",
        summary="第二轮重试指导",
        status="proposed",
    )

    result = facade.finalize_working_memory_task_run(
        "taskrun:retry",
        actor_id="runloop",
        terminal_reason="completed",
        policy={"keep_failure_reflection": True},
    )

    assert result.archived_count == 2
    loaded_reflection = facade.get_working_memory_item(reflection.work_memory_id)
    loaded_guidance = facade.get_working_memory_item(guidance.work_memory_id)
    assert loaded_reflection.status == "archived"
    assert loaded_guidance.status == "archived"
    assert loaded_reflection.run_attempt_id == "attempt_01"
    assert loaded_guidance.run_attempt_id == "attempt_02"
