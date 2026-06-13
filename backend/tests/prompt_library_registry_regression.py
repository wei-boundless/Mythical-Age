from __future__ import annotations

import json
from pathlib import Path

from prompt_library import (
    DEFAULT_PERSONALITY_PROMPT_REF,
    DURABLE_MEMORY_RECALL_SELECTOR_PROMPT,
    EVIDENCE_DISTILLER_PROMPT,
    FOUNDATION_PROMPT_REFS,
    ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS,
    ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT,
    HISTORY_SUMMARY_RECOVERY_PROMPT,
    MCP_SERVER_INSTRUCTIONS_PROMPT,
    PromptAssemblyRequest,
    PromptAssemblyService,
    PromptLibraryRegistry,
    PromptPack,
    PromptResource,
    RAG_FINALIZER_SYSTEM_PROMPT,
    SESSION_TITLE_GENERATION_PROMPT,
    SINGLE_AGENT_ADMISSION_REPAIR_PROMPT,
    SINGLE_AGENT_PROTOCOL_REPAIR_PROMPT,
    TASK_ACTION_JSON_REPAIR_PROMPT,
    build_runtime_prompt_manifest,
)


def test_prompt_library_registers_builtin_utility_prompts(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    resources = {item.resource_id: item for item in registry.list_active_resources()}

    expected = {
        "utility.finalizer.rag_answer": RAG_FINALIZER_SYSTEM_PROMPT,
        "utility.distiller.search_evidence": EVIDENCE_DISTILLER_PROMPT,
        "utility.memory.durable_recall_selector": DURABLE_MEMORY_RECALL_SELECTOR_PROMPT,
        "utility.title_generation.session": SESSION_TITLE_GENERATION_PROMPT,
        "utility.summarize_history.context_recovery": HISTORY_SUMMARY_RECOVERY_PROMPT,
        "utility.repair.single_agent_admission": SINGLE_AGENT_ADMISSION_REPAIR_PROMPT,
        "utility.repair.single_agent_protocol": SINGLE_AGENT_PROTOCOL_REPAIR_PROMPT,
        "utility.repair.task_action_json": TASK_ACTION_JSON_REPAIR_PROMPT,
        "mcp.prompt.server_instructions": MCP_SERVER_INSTRUCTIONS_PROMPT,
    }
    for prompt_id, content in expected.items():
        resource = resources[prompt_id]
        assert resource.owner_layer == "runtime"
        assert resource.cache_scope == "static"
        assert resource.source_ref.startswith("prompt_library.utility_prompts")
        assert resource.metadata["authority_scope"] == "utility_prompt"

    utility_resources = registry.list_active_resources(category="utility")
    mcp_resources = registry.list_active_resources(category="mcp")
    assert {item.resource_id for item in utility_resources} >= {
        "utility.finalizer.rag_answer",
        "utility.repair.single_agent_protocol",
        "utility.verifier.readonly_delivery",
    }
    assert {item.resource_id for item in mcp_resources} == {
        "mcp.prompt.server_instructions",
        "mcp.prompt.capability_usage",
    }


def test_prompt_library_lists_only_runtime_agent_and_environment_resources_by_default(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resources = registry.list_resources()
    resource_by_id = {item.resource_id: item for item in resources}
    pack_by_id = {item.pack_id: item for item in registry.list_packs()}
    required_runtime_control_refs = (
        "runtime.rule.subagent_delegation",
        "runtime.rule.subagent_invocation_protocol",
        "runtime.rule.plan_mode_boundary",
        "runtime.rule.lifecycle_control",
    )
    migrated_legacy_refs = {
        "runtime.single_agent_turn.v1",
        "runtime.task_execution.v1",
        "runtime.graph_node_execution.v1",
        "runtime.observation_followup.v1",
        "runtime.semantic_compaction.v1",
        "runtime.rule.system_call_protocol.v1",
        "runtime.rule.intent_feedback.v1",
        "runtime.rule.turn_decision_alignment.v1",
        "runtime.rule.tool_use.v1",
        "runtime.rule.output_boundary.v1",
        "runtime.rule.error_recovery.v1",
        "runtime.rule.context_memory.v1",
        "runtime.rule.permission_denial.v1",
        "runtime.rule.subagent_delegation.v1",
        "runtime.rule.subagent_invocation_protocol.v1",
        "runtime.rule.multi_tool_scheduling.v1",
        "runtime.rule.plan_mode_boundary.v1",
        "runtime.rule.lifecycle_control.v1",
        "graph.rule.node_boundary.v1",
        "graph.rule.node_output_contract.v1",
        "runtime.rule.file_management.generic.v1",
        "coding.rule.codebase_inspection.v1",
        "coding.rule.large_scope_exploration.v1",
        "coding.rule.editing.v1",
        "coding.rule.verification.v1",
        "coding.rule.debug_discipline.v1",
        "coding.rule.git_safety.v1",
        "coding.rule.windows_shell.v1",
        "coding.rule.task_progress.v1",
        "environment.rule.coding_workspace.v1",
        "environment.rule.coding_workspace.v1",
        "environment.rule.office_file_search.v1",
        "environment.rule.general_workspace.v1",
        "environment.resource.base_workspace.orientation.v1",
        "environment.resource.managed_project_workspace.orientation.v1",
        "environment.resource.sandbox_overlay.orientation.v1",
        "environment.resource.writing_manuscript.orientation.v1",
        "environment.resource.general_workspace.orientation.v1",
        "environment.coding.vibe_workspace.orientation.v1",
        "environment.coding.vibe_workspace.orientation.v1",
        "environment.office.file_search.orientation.v1",
        "environment.general.workspace.orientation.v1",
    }
    migrated_legacy_packs = {
        "runtime.pack.single_agent_turn.v1",
        "runtime.pack.task_execution.v1",
        "runtime.pack.graph_node_execution.v1",
        "runtime.pack.observation_followup.v1",
        "runtime.pack.semantic_compaction.v1",
    }
    assert migrated_legacy_refs.isdisjoint(resource_by_id)
    assert migrated_legacy_packs.isdisjoint(pack_by_id)

    for prompt_ref in FOUNDATION_PROMPT_REFS:
        resource = resource_by_id[prompt_ref]
        assert resource.category == "system"
        assert resource.owner_layer == "system"
        assert resource.cache_scope == "static"
        assert not resource.prompt_id.endswith(".v1")
        assert resource.allowed_invocation_kinds == (
            "single_agent_turn",
            "task_execution",
            "tool_observation_followup",
        )
        assert resource.source_ref.startswith("prompt_library.system_prompts")

    rag_finalizer = resource_by_id["utility.finalizer.rag_answer"].content
    assert "不要输出内部协议、工具名、字段名、JSON、canonical、evidence 等词" not in rag_finalizer
    assert "用自然语言说明来源边界和不确定性" in rag_finalizer
    mcp_usage_prompt = resource_by_id["mcp.prompt.capability_usage"].content
    assert "不要把内部路由当作用户可见结论" in mcp_usage_prompt

    assert resource_by_id["runtime.single_agent_turn"].category == "runtime"
    assert resource_by_id["runtime.task_execution"].category == "runtime"
    assert resource_by_id["runtime.rule.system_call_protocol"].category == "runtime"
    assert resource_by_id["runtime.rule.turn_decision_alignment"].category == "runtime"
    assert resource_by_id["runtime.rule.tool_use"].category == "runtime"
    assert resource_by_id["runtime.rule.subagent_invocation_protocol"].category == "runtime"
    system_call_protocol = resource_by_id["runtime.rule.system_call_protocol"].content
    assert "tool_calls 数组" in system_call_protocol
    assert (
        "如果本轮要求 JSON action，只输出一个合法 JSON 对象"
        not in resource_by_id["runtime.rule.output_boundary"].content
    )
    assert resource_by_id["runtime.rule.file_management.generic"].resource_type == "environment.file_management_rule"
    assert resource_by_id["coding.rule.large_scope_exploration"].resource_type == "environment.coding_rule"
    assert resource_by_id["coding.rule.large_scope_exploration"].cache_scope == "static_environment"
    for pack_id in ("runtime.pack.single_agent_turn", "runtime.pack.task_execution"):
        refs = pack_by_id[pack_id].ordered_prompt_refs
        assert all(prompt_ref in refs for prompt_ref in required_runtime_control_refs)
    managed_workspace_prompt = resource_by_id["environment.resource.managed_project_workspace.orientation"].content
    assert "项目相对路径" in managed_workspace_prompt
    assert "artifact 只用于交付证据" in managed_workspace_prompt
    sandbox_prompt = resource_by_id["environment.resource.sandbox_overlay.orientation"].content
    assert "不要求用户重复批准" in sandbox_prompt
    assert "下一步必须改变参数" in sandbox_prompt
    assert resource_by_id["agent.main_interactive_agent.single_agent_turn.work_role"].allowed_invocation_kinds == ("single_agent_turn",)
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role"].allowed_invocation_kinds == ("task_execution",)
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role"].source_ref.startswith("prompt_library.agent_prompts")
    assert resource_by_id["agent.main_interactive_agent.task_execution.work_role"].cache_scope == "session_stable"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].category == "personality"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].owner_layer == "personality"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].resource_type == "agent_personality"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].cache_scope == "session_stable"
    assert resource_by_id[DEFAULT_PERSONALITY_PROMPT_REF].metadata["authority_scope"] == "identity_and_style_only"
    assert resource_by_id["environment.general.workspace.orientation"].category == "environment"
    assert resource_by_id["environment.resource.general_workspace.orientation"].category == "environment"
    assert resource_by_id["environment.resource.general_workspace.orientation"].allowed_environment_refs == ()
    for environment_id, prompt_ids in ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT.items():
        for prompt_id in prompt_ids:
            resource = resource_by_id[prompt_id]
            assert resource.category == "environment"
            assert resource.owner_layer == "environment"
            assert resource.resource_type == "environment_prompt"
            assert resource.subtype.startswith("lifecycle_")
            assert resource.allowed_invocation_kinds == ("environment",)
            assert resource.allowed_environment_refs == (environment_id,)
            assert resource.cache_scope == "static_environment"
            assert resource.version == "2026-06-10"
            assert not resource.prompt_id.endswith(".v1")
    assert set(ALL_ENVIRONMENT_LIFECYCLE_PROMPT_IDS) == {
        prompt_id
        for prompt_ids in ENVIRONMENT_LIFECYCLE_PROMPT_IDS_BY_ENVIRONMENT.values()
        for prompt_id in prompt_ids
    }
    active_work_prompt = resource_by_id["environment.general.lifecycle.active_work_control"]
    assert resource_by_id["environment.general.lifecycle.memory_read_context"].resource_type == "environment_prompt"
    assert resource_by_id["environment.coding.lifecycle.memory_read_context"].allowed_environment_refs == (
        "env.coding.vibe_workspace",
    )
    assert resource_by_id["environment.office.lifecycle.memory_read_context"].allowed_environment_refs == (
        "env.office.file_search",
    )
    assert resource_by_id["environment.general.lifecycle.memory_write_handoff"].resource_type == "environment_prompt"
    assert resource_by_id["environment.general.lifecycle.verification_gate"].resource_type == "environment_prompt"
    assert not [item for item in resources if item.resource_id.startswith("prompt.default.")]
    assert not [item for item in resources if item.resource_type in {"task_goal_role", "stage_role", "understanding_policy"}]
    assert not (tmp_path / "storage" / "prompt_library" / "prompt_resources.json").exists()

    rules = registry.list_prompt_rules()
    rule_by_id = {item.rule_id: item for item in rules}
    assert rule_by_id["system.foundation.local_collaboration"].rule_kind == "system.foundation.local_collaboration"
    assert rule_by_id["system.foundation.local_collaboration"].cache_tier == "global_static"
    assert rule_by_id["system.foundation.current_request_authority"].rule_kind == "system.foundation.current_request_authority"
    assert rule_by_id["system.foundation.truth_and_verification"].rule_kind == "system.foundation.truth_and_verification"
    assert rule_by_id["runtime.task_execution"].rule_kind == "runtime.protocol"
    assert rule_by_id["runtime.task_execution"].requires == (
        "runtime.rule.system_call_protocol",
        "runtime.rule.turn_decision_alignment",
        "runtime.rule.lifecycle_control",
    )
    assert rule_by_id["runtime.graph_node_execution"].requires == ("runtime.rule.system_call_protocol",)
    assert rule_by_id["runtime.rule.system_call_protocol"].rule_kind == "runtime.system_call_protocol"
    assert rule_by_id["runtime.rule.turn_decision_alignment"].rule_kind == "runtime.turn_decision_alignment"
    assert rule_by_id["runtime.rule.lifecycle_control"].rule_kind == "runtime.lifecycle_control"
    assert rule_by_id["runtime.rule.lifecycle_control"].requires == (
        "runtime.rule.turn_decision_alignment",
        "runtime.rule.output_boundary",
    )
    assert rule_by_id["runtime.rule.tool_use"].rule_kind == "runtime.tool_use"
    assert rule_by_id["runtime.rule.subagent_invocation_protocol"].rule_kind == "runtime.subagent_invocation_protocol"
    assert rule_by_id["coding.rule.large_scope_exploration"].rule_kind == "coding.large_scope_exploration"
    assert rule_by_id["coding.rule.large_scope_exploration"].cache_tier == "static_environment"
    assert rule_by_id["agent.main_interactive_agent.task_execution.work_role"].cache_tier == "session_stable"
    assert rule_by_id[DEFAULT_PERSONALITY_PROMPT_REF].rule_kind == "personality.identity_style"
    assert rule_by_id[DEFAULT_PERSONALITY_PROMPT_REF].cache_tier == "session_stable"
    assert rule_by_id[DEFAULT_PERSONALITY_PROMPT_REF].owner_layer == "personality"
    assert rule_by_id["coding.rule.editing"].requires == ("runtime.rule.file_management.generic",)


def test_builtin_model_visible_prompts_use_agent_runtime_situation_language(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    forbidden_markers = (
        "关键词分类器",
        "环境切换器",
        "系统装配",
        "系统已经为",
        "runtime payload",
        "personality prompt",
        "当前内容只约束",
        "该环境用于",
        "这个任务环境是当前",
        "runtime 权限",
        "当前 runtime 明确",
        "runtime 曾经省略",
        "不授予工具",
        "被系统选中",
        "这个环境不是任务分类器",
        "runtime packet",
        "这个 prompt",
        "该 prompt",
        "prompt 用于",
        "本段只",
        "本段告诉",
    )

    violations = []
    for resource in registry.list_resources():
        if not resource.model_visible:
            continue
        content = str(resource.content or "")
        hits = [marker for marker in forbidden_markers if marker in content]
        if hits:
            violations.append((resource.prompt_id, hits))

    assert violations == []

    runtime_protocol = registry.get_resource("runtime.task_execution")
    assert runtime_protocol is not None


def test_graph_node_runtime_protocol_includes_respond_action_json_shape(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resource = registry.get_resource("runtime.graph_node_execution")

    assert resource is not None


def test_runtime_protocol_prompts_include_active_work_control_action(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    single_turn = registry.get_resource("runtime.single_agent_turn")
    observation_followup = registry.get_resource("runtime.observation_followup")

    assert single_turn is not None
    assert observation_followup is not None
    assert "active_work_control" in single_turn.content
    assert "用户可见反馈意图" in single_turn.content
    assert "控制动作脱节" in single_turn.content
    assert "用户可见反馈" in observation_followup.content
    assert "不等同暂停或停止" in observation_followup.content
    assert "质疑" in observation_followup.content
    assert "纠错" in observation_followup.content


def test_environment_lifecycle_prompts_keep_action_control_boundaries(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    for prompt_id in (
        "environment.coding.lifecycle.active_work_control",
        "environment.office.lifecycle.active_work_control",
        "environment.general.lifecycle.active_work_control",
    ):
        resource = registry.get_resource(prompt_id)

        assert resource is not None
        assert "turn_response_policy=" not in resource.content
        assert "answer_obligation=" not in resource.content
        assert "先用一句" not in resource.content
        assert "轻反馈" not in resource.content
        assert "用户可见反馈意图" in resource.content
        assert "系统投影" in resource.content
        assert "控制动作脱节" in resource.content
        assert "这不是自动暂停或停止" in resource.content
        assert "回答后继续" in resource.content

    coding_capability = registry.get_resource("environment.coding.lifecycle.environment_capability_alignment")
    assert coding_capability is not None
    assert "前后端" not in coding_capability.content
    assert "SSE" not in coding_capability.content
    assert "Electron" not in coding_capability.content
    assert "服务进程" in coding_capability.content
    assert "网络端点" in coding_capability.content

    general_context = registry.get_resource("environment.general.lifecycle.context_intake")
    general_control = registry.get_resource("environment.general.lifecycle.active_work_control")
    general_recovery = registry.get_resource("environment.general.lifecycle.tool_observation_recovery")
    general_subagent = registry.get_resource("environment.general.lifecycle.subagent_result_integration")
    general_verification = registry.get_resource("environment.general.lifecycle.verification_gate")
    general_finalization = registry.get_resource("environment.general.lifecycle.finalization")
    assert general_context is not None
    assert general_control is not None
    assert general_recovery is not None
    assert general_subagent is not None
    assert general_verification is not None
    assert general_finalization is not None
    assert "权威顺序" in general_context.content
    assert "pause" in general_control.content
    assert "replan" in general_control.content
    for failure_class in ("参数", "路径", "权限", "工具", "环境", "合同"):
        assert failure_class in general_recovery.content
    assert "行动建议" in general_subagent.content
    assert "能力限制" in general_verification.content
    assert "强制暂停" in general_finalization.content


def test_environment_action_selection_prompts_define_operational_minimal_action(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    for prompt_id in (
        "environment.coding.lifecycle.action_selection",
        "environment.office.lifecycle.action_selection",
        "environment.general.lifecycle.action_selection",
    ):
        resource = registry.get_resource(prompt_id)

        assert resource is not None
        assert "最小充分动作" in resource.content
        assert "判断骨架" in resource.content
        assert "目标" in resource.content
        assert "事实" in resource.content
        assert "裁决" in resource.content
        assert "阻塞" in resource.content


def test_environment_prompts_define_chat_vs_task_run_judgment(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    for prompt_id in (
        "environment.coding.lifecycle.request_judgment",
        "environment.office.lifecycle.request_judgment",
        "environment.general.lifecycle.request_judgment",
        "environment.coding.lifecycle.task_run_handoff",
        "environment.office.lifecycle.task_run_handoff",
        "environment.general.lifecycle.task_run_handoff",
    ):
        resource = registry.get_resource(prompt_id)

        assert resource is not None
        assert "聊天" in resource.content
        assert "开启任务" in resource.content or "开启持续任务" in resource.content
        assert "不要开启任务" in resource.content or "才开启持续任务" in resource.content


def test_prompt_library_upsert_does_not_persist_all_default_resources(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            resource_id="prompt.user.custom.output",
            resource_type="output_boundary",
            title="用户自定义输出边界",
            content="你需要用用户指定的格式收口。",
            source_ref="test",
        )
    )

    storage_path = tmp_path / "storage" / "prompt_library" / "prompt_resources.json"
    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    stored_ids = {str(item.get("resource_id") or "") for item in list(payload.get("resources") or [])}

    assert "prompt.user.custom.output" in stored_ids
    assert "system.foundation.local_collaboration" not in stored_ids
    assert "runtime.single_agent_turn" not in stored_ids
    assert len(stored_ids) == 1
    assert registry.get_resource("runtime.single_agent_turn") is not None


def test_prompt_assembly_enforces_authority_precedence_over_requested_order(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    for resource in (
        PromptResource(
            prompt_id="test.project.boundary",
            resource_id="test.project.boundary",
            category="project",
            subtype="instruction",
            owner_layer="project",
            resource_type="project.instruction",
            title="Project boundary",
            content="project layer",
            allowed_invocation_kinds=("single_agent_turn",),
            cache_scope="task_stable",
        ),
        PromptResource(
            prompt_id="test.runtime.protocol",
            resource_id="test.runtime.protocol",
            category="runtime",
            subtype="protocol",
            owner_layer="runtime",
            resource_type="runtime.rule",
            title="Runtime protocol",
            content="runtime layer",
            allowed_invocation_kinds=("single_agent_turn",),
            cache_scope="static",
        ),
        PromptResource(
            prompt_id="test.system.foundation",
            resource_id="test.system.foundation",
            category="system",
            subtype="foundation",
            owner_layer="system",
            resource_type="system.foundation",
            title="System foundation",
            content="system layer",
            allowed_invocation_kinds=("single_agent_turn",),
            cache_scope="static",
        ),
    ):
        registry.upsert_resource(resource)

    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="single_agent_turn",
            prompt_refs=(
                "test.project.boundary",
                "test.runtime.protocol",
                "test.system.foundation",
            ),
        )
    )
    refs = [section.prompt_ref for section in assembly.sections]
    prompt_manifest = build_runtime_prompt_manifest(
        invocation_kind="single_agent_turn",
        assembly=assembly,
        packet_id="packet:test:prompt-authority",
    ).to_dict()
    authority_manifest = prompt_manifest["diagnostics"]["prompt_authority"]

    assert refs == [
        "test.system.foundation",
        "test.runtime.protocol",
        "test.project.boundary",
    ]
    assert assembly.manifest["prompt_precedence"]["behavior"] == "enforced_precedence_order"
    assert authority_manifest["authority"] == "prompt_library.prompt_authority_manifest"
    assert authority_manifest["segment_order"] == refs
    assert [item["requested_order"] for item in authority_manifest["entries"]] == [3, 2, 1]


def test_prompt_library_stored_resource_overrides_default_resource(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            prompt_id="runtime.single_agent_turn",
            resource_id="runtime.single_agent_turn",
            category="runtime",
            subtype="single_agent_turn",
            resource_type="runtime.single_agent_turn",
            title="覆盖后的 single agent turn",
            content="这是用户覆盖后的 single agent turn prompt。",
            allowed_invocation_kinds=("single_agent_turn",),
            source_ref="test.override",
            priority=1,
        )
    )

    resource = registry.get_resource("runtime.single_agent_turn")

    assert resource is not None
    assert resource.title == "覆盖后的 single agent turn"
    assert resource.source_ref == "test.override"


def test_prompt_library_storage_migrates_deprecated_prompt_refs_without_runtime_alias(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage" / "prompt_library"
    storage_dir.mkdir(parents=True)
    resources_path = storage_dir / "prompt_resources.json"
    packs_path = storage_dir / "prompt_packs.json"
    resources_path.write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "prompt_id": "runtime.single_agent_turn.v1",
                        "resource_id": "runtime.single_agent_turn.v1",
                        "category": "runtime",
                        "subtype": "single_agent_turn",
                        "resource_type": "runtime.single_agent_turn",
                        "title": "Legacy override",
                        "content": "这是迁移后的 single agent turn 覆盖 prompt。",
                        "allowed_invocation_kinds": ["single_agent_turn"],
                        "metadata": {
                            "prompt_rule": {
                                "rule_id": "runtime.single_agent_turn.v1",
                                "prompt_ref": "runtime.single_agent_turn.v1",
                                "rule_kind": "runtime.protocol",
                                "requires": ["runtime.rule.system_call_protocol.v1"],
                            }
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    packs_path.write_text(
        json.dumps(
            {
                "packs": [
                    {
                        "pack_id": "runtime.pack.task_execution.v1",
                        "invocation_kind": "task_execution",
                        "ordered_prompt_refs": ["runtime.task_execution.v1", "tool.guidance.git.v1"],
                        "title": "Legacy task execution pack",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    registry = PromptLibraryRegistry(tmp_path)
    resource = registry.get_resource("runtime.single_agent_turn")
    pack = registry.get_pack("runtime.pack.task_execution")

    assert resource is not None
    assert resource.metadata["prompt_rule"]["rule_id"] == "runtime.single_agent_turn"
    assert resource.metadata["prompt_rule"]["requires"] == ["runtime.rule.system_call_protocol"]
    assert registry.get_resource("runtime.single_agent_turn.v1") is None
    assert pack is not None
    assert pack.ordered_prompt_refs == (
        "runtime.task_execution",
        "tool.guidance.git_read",
        "tool.guidance.git_write",
    )
    persisted_resources = json.loads(resources_path.read_text(encoding="utf-8"))["resources"]
    persisted_packs = json.loads(packs_path.read_text(encoding="utf-8"))["packs"]
    assert persisted_resources[0]["prompt_id"] == "runtime.single_agent_turn"
    assert persisted_resources[0]["resource_id"] == "runtime.single_agent_turn"
    assert persisted_packs[0]["pack_id"] == "runtime.pack.task_execution"
    assert persisted_packs[0]["ordered_prompt_refs"] == [
        "runtime.task_execution",
        "tool.guidance.git_read",
        "tool.guidance.git_write",
    ]

    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=("runtime.task_execution.v1",),
        )
    )
    assert assembly.sections == ()
    assert assembly.rejected_refs == (
        {"ref": "runtime.task_execution.v1", "reason": "prompt_not_found_or_inactive"},
    )

    saved_resource = registry.upsert_resource(
        PromptResource(
            prompt_id="worker.prompt.review.v1",
            resource_id="worker.prompt.review.v1",
            category="agent",
            subtype="worker.role",
            resource_type="work_role",
            title="Legacy review prompt",
            content="你是一名审查员。",
            allowed_invocation_kinds=("task_execution",),
        )
    )
    saved_pack = registry.upsert_pack(
        PromptPack(
            pack_id="runtime.pack.observation_followup.v1",
            invocation_kind="tool_observation_followup",
            ordered_prompt_refs=("runtime.observation_followup.v1",),
        )
    )

    assert saved_resource.resource_id == "worker.prompt.review"
    assert saved_pack.pack_id == "runtime.pack.observation_followup"
    assert saved_pack.ordered_prompt_refs == ("runtime.observation_followup",)


def test_task_graph_node_role_prompt_writes_graph_node_role_resource(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)

    resource = registry.upsert_task_graph_node_role_prompt(
        graph_id="graph.demo",
        graph_title="Demo graph",
        domain_id="domain.demo",
        node={
            "node_id": "review",
            "task_id": "task.demo.review",
            "workflow_id": "workflow.demo.node.review",
            "title": "Review",
        },
        prompt="你是一名审核员，只负责裁决是否通过。",
    )

    payload = resource.to_dict()

    assert resource.category == "graph_node"
    assert resource.subtype == "role"
    assert resource.resource_type == "graph_node.role"
    assert resource.allowed_invocation_kinds == ()
    assert "applies_to_task_goal_types" not in payload
    assert "applies_to_domains" not in payload
    assert "applies_to_modes" not in payload
    assert "stage_role" not in resource.resource_id
