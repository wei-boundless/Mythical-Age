from __future__ import annotations

import json
from pathlib import Path

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry, default_agent_runtime_profiles
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.registry.worker_agent_factory import WorkerAgentFactory, default_worker_agent_blueprints
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest
from prompt_library import PromptAssemblyRequest, PromptAssemblyService, PromptLibraryRegistry
from prompt_library.worker_prompts import worker_prompt_ref_for_blueprint


def test_worker_prompt_resources_are_registered_and_agent_facing(tmp_path: Path) -> None:
    resources = {item.resource_id: item for item in PromptLibraryRegistry(tmp_path).list_resources()}

    assert not any(ref.startswith("worker.prompt.") and ref.endswith(".v1") for ref in resources)

    explorer = resources["worker.prompt.explorer"]
    web_research = resources["worker.prompt.web_research"]
    knowledge_search = resources["worker.prompt.knowledge_search"]
    memory_search = resources["worker.prompt.memory_search"]
    pdf_analysis = resources["worker.prompt.pdf_analysis"]
    structured_data = resources["worker.prompt.structured_data_analysis"]
    verifier = resources["worker.prompt.verification"]

    assert explorer.category == "agent"
    assert explorer.owner_layer == "agent"
    assert explorer.cache_scope == "session_stable"
    assert explorer.allowed_invocation_kinds == ("task_execution",)


def test_worker_blueprints_bind_prompt_refs_and_operation_boundaries() -> None:
    by_id = {item.blueprint_id: item for item in default_worker_agent_blueprints()}

    explorer = by_id["worker.explorer"]
    planner = by_id["worker.planner"]
    verifier = by_id["worker.verification"]
    executor = by_id["worker.code.executor"]

    assert explorer.prompt_ref == "worker.prompt.explorer"
    assert explorer.metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.explorer"]}
    assert "op.write_file" in explorer.blocked_operations
    assert "op.edit_file" in planner.blocked_operations
    assert verifier.prompt_ref == "worker.prompt.verification"
    assert "op.write_file" in verifier.blocked_operations
    assert "op.shell" in verifier.extra_allowed_operations
    assert executor.prompt_ref == "worker.prompt.code_executor"


def test_web_research_worker_prompt_binds_to_specialist_profile() -> None:
    profile = next(
        item
        for item in default_agent_runtime_profiles()
        if item.agent_profile_id == "web_research_agent"
    )
    metadata = dict(profile.metadata)

    assert metadata["worker_prompt_ref"] == "worker.prompt.web_research"
    assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.web_research"]}
    assert metadata["output_contract"]["recommended_fields"] == (
        "source_matrix",
        "source_urls",
        "open_questions",
        "source_strength",
        "recommended_parent_action",
    )


def test_builtin_specialist_worker_prompts_bind_to_profiles() -> None:
    profiles = {item.agent_profile_id: item for item in default_agent_runtime_profiles()}
    expected = {
        "knowledge_search_agent": "worker.prompt.knowledge_search",
        "memory_search_agent": "worker.prompt.memory_search",
        "pdf_analysis_agent": "worker.prompt.pdf_analysis",
        "structured_data_analysis_agent": "worker.prompt.structured_data_analysis",
    }

    for profile_id, prompt_ref in expected.items():
        metadata = dict(profiles[profile_id].metadata)
        assert metadata["worker_prompt_ref"] == prompt_ref
        assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": [prompt_ref]}


def test_builtin_specialist_worker_prompt_refs_are_resolved_from_blueprints() -> None:
    assert worker_prompt_ref_for_blueprint("runtime.template.knowledge_search") == "worker.prompt.knowledge_search"
    assert worker_prompt_ref_for_blueprint("builtin.specialist.memory_searcher") == "worker.prompt.memory_search"
    assert worker_prompt_ref_for_blueprint("builtin.specialist.pdf_reader") == "worker.prompt.pdf_analysis"
    assert worker_prompt_ref_for_blueprint("builtin.specialist.table_analyst") == "worker.prompt.structured_data_analysis"


def test_dynamic_worker_profile_uses_prompt_library_ref(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    result = WorkerAgentFactory(backend_dir).provision_worker_agent(
        request=WorkerAgentSpawnRequest(
            spawn_request_id="spawn:test",
            task_run_id="taskrun:test",
            parent_agent_run_ref="agrun:parent",
            blueprint_id="worker.review",
            requested_agent_name="审查 Agent 1",
            context_scope="subagent_scoped",
            requested_by_agent_id="agent:0",
            spawn_reason="review changed files",
        ),
        requested_agent_name="审查 Agent 1",
    )

    metadata = dict(result.runtime_profile.metadata)

    assert result.agent.description == "bug-first 审查 worker，复核变更、证据和缺失测试。"
    assert metadata["worker_prompt_ref"] == "worker.prompt.review"
    assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.review"]}


def test_completion_verifier_profile_uses_verification_worker_prompt() -> None:
    profile = next(
        item
        for item in default_agent_runtime_profiles()
        if item.agent_profile_id == "completion_verifier_agent"
    )
    metadata = dict(profile.metadata)

    assert metadata["worker_prompt_ref"] == "worker.prompt.verification"
    assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.verification"]}
    assert metadata["output_contract"]["verdict_values"] == ("PASS", "FAIL", "PARTIAL")
    assert "op.shell" in profile.allowed_operations
    assert "op.write_file" in profile.blocked_operations


def test_worker_prompt_ref_assembles_for_task_execution(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=("worker.prompt.verification",),
            agent_profile_ref="completion_verifier_agent",
        )
    )

    assert assembly.rejected_refs == ()
    assert "worker.prompt.verification" in assembly.manifest["stable_prompt_refs"]
    assert "worker.role" in assembly.manifest["prompt_rules"]["rule_kinds"]


def test_web_research_worker_prompt_assembles_for_task_execution(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=("worker.prompt.web_research",),
            agent_profile_ref="web_research_agent",
        )
    )

    assert assembly.rejected_refs == ()
    assert "worker.prompt.web_research" in assembly.manifest["stable_prompt_refs"]
    assert "worker.role" in assembly.manifest["prompt_rules"]["rule_kinds"]


def test_builtin_specialist_worker_prompts_assemble_for_task_execution(tmp_path: Path) -> None:
    expected = {
        "knowledge_search_agent": "worker.prompt.knowledge_search",
        "memory_search_agent": "worker.prompt.memory_search",
        "pdf_analysis_agent": "worker.prompt.pdf_analysis",
        "structured_data_analysis_agent": "worker.prompt.structured_data_analysis",
    }

    for profile_ref, prompt_ref in expected.items():
        assembly = PromptAssemblyService(tmp_path).assemble(
            PromptAssemblyRequest(
                invocation_kind="task_execution",
                prompt_refs=(prompt_ref,),
                agent_profile_ref=profile_ref,
            )
        )

        assert assembly.rejected_refs == ()
        assert prompt_ref in assembly.manifest["stable_prompt_refs"]
        assert "worker.role" in assembly.manifest["prompt_rules"]["rule_kinds"]


def test_worker_prompt_profile_roundtrip_from_registry(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    profile = AgentRuntimeRegistry(backend_dir).get_profile_by_profile_id("completion_verifier_agent")

    assert profile is not None
    assert profile.metadata["agent_prompt_refs_by_invocation"]["task_execution"] == ["worker.prompt.verification"]


def test_runtime_profile_registry_migrates_legacy_prompt_refs_on_load(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    AgentRegistry(backend_dir).upsert_agent(
        agent_id="agent:legacy_prompt",
        agent_name="Legacy Prompt Agent",
        description="Legacy prompt migration fixture.",
    )
    registry = AgentRuntimeRegistry(backend_dir)
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "agent_profile_id": "legacy_prompt_profile",
                        "agent_id": "agent:legacy_prompt",
                        "extra_allowed_operations": ["op.model_response"],
                        "metadata": {
                            "worker_prompt_ref": "worker.prompt.verification.v1",
                            "agent_prompt_refs": [
                                "agent.main_interactive_agent.task_execution.work_role.v1"
                            ],
                            "agent_prompt_refs_by_invocation": {
                                "task_execution": ["worker.prompt.review.v1"]
                            },
                            "prompt_pack_refs": ["runtime.pack.single_agent_turn.v1"],
                            "prompt_pack_refs_by_invocation": {
                                "task_execution": ["runtime.pack.task_execution.v1"]
                            },
                            "runtime_policy": {
                                "prompt_pack_refs_by_invocation": {
                                    "task_execution": ["runtime.pack.graph_node_execution.v1"]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profile = registry.get_profile("agent:legacy_prompt")

    assert profile is not None
    assert profile.metadata["worker_prompt_ref"] == "worker.prompt.verification"
    assert profile.metadata["agent_prompt_refs"] == [
        "agent.main_interactive_agent.task_execution.work_role"
    ]
    assert profile.metadata["agent_prompt_refs_by_invocation"] == {
        "task_execution": ["worker.prompt.review"]
    }
    assert profile.metadata["prompt_pack_refs"] == ["runtime.pack.single_agent_turn"]
    assert profile.metadata["prompt_pack_refs_by_invocation"] == {
        "task_execution": ["runtime.pack.task_execution"]
    }
    assert profile.metadata["runtime_policy"]["prompt_pack_refs_by_invocation"] == {
        "task_execution": ["runtime.pack.graph_node_execution"]
    }
    persisted_profiles = json.loads(registry.path.read_text(encoding="utf-8"))["profiles"]
    persisted_profile = next(item for item in persisted_profiles if item["agent_id"] == "agent:legacy_prompt")
    assert "worker.prompt.verification.v1" not in json.dumps(persisted_profile, ensure_ascii=False)
