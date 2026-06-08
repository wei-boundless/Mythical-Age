from __future__ import annotations

from pathlib import Path

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry, default_agent_runtime_profiles
from agent_system.registry.worker_agent_factory import WorkerAgentFactory, default_worker_agent_blueprints
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest
from prompt_library import PromptAssemblyRequest, PromptAssemblyService, PromptLibraryRegistry
from prompt_library.worker_prompts import worker_prompt_ref_for_blueprint


def test_worker_prompt_resources_are_registered_and_agent_facing(tmp_path: Path) -> None:
    resources = {item.resource_id: item for item in PromptLibraryRegistry(tmp_path).list_resources()}

    explorer = resources["worker.prompt.explorer.v1"]
    web_research = resources["worker.prompt.web_research.v1"]
    knowledge_search = resources["worker.prompt.knowledge_search.v1"]
    memory_search = resources["worker.prompt.memory_search.v1"]
    pdf_analysis = resources["worker.prompt.pdf_analysis.v1"]
    structured_data = resources["worker.prompt.structured_data_analysis.v1"]
    verifier = resources["worker.prompt.verification.v1"]

    assert explorer.category == "agent"
    assert explorer.owner_layer == "agent"
    assert explorer.cache_scope == "session_stable"
    assert explorer.allowed_invocation_kinds == ("task_execution",)
    assert "你是一名只读探索员" in explorer.content
    assert "你不能写入项目文件" in explorer.content
    assert "你是一名网络研究子 Agent" in web_research.content
    assert "source_matrix" in web_research.content
    assert "prompt injection" in web_research.content
    assert "你是一名知识库检索子 Agent" in knowledge_search.content
    assert "RAG 文档块" in knowledge_search.content
    assert "你是一名记忆检索子 Agent" in memory_search.content
    assert "记忆不是当前事实来源" in memory_search.content
    assert "你是一名 PDF 阅读分析子 Agent" in pdf_analysis.content
    assert "page_refs" in pdf_analysis.content
    assert "你是一名结构化数据分析子 Agent" in structured_data.content
    assert "data_scope" in structured_data.content
    assert "这是 runtime 节点" not in explorer.content
    assert "这是 runtime 节点" not in web_research.content
    assert "这是 runtime 节点" not in knowledge_search.content
    assert "这是 runtime 节点" not in memory_search.content
    assert "这是 runtime 节点" not in pdf_analysis.content
    assert "这是 runtime 节点" not in structured_data.content
    assert "verdict" in verifier.content
    assert "PASS、FAIL 或 PARTIAL" in verifier.content


def test_worker_blueprints_bind_prompt_refs_and_operation_boundaries() -> None:
    by_id = {item.blueprint_id: item for item in default_worker_agent_blueprints()}

    explorer = by_id["worker.explorer"]
    planner = by_id["worker.planner"]
    verifier = by_id["worker.verification"]
    executor = by_id["worker.code.executor"]

    assert explorer.prompt_ref == "worker.prompt.explorer.v1"
    assert explorer.metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.explorer.v1"]}
    assert "op.write_file" in explorer.blocked_operations
    assert "op.edit_file" in planner.blocked_operations
    assert verifier.prompt_ref == "worker.prompt.verification.v1"
    assert "op.write_file" in verifier.blocked_operations
    assert "op.shell" in verifier.extra_allowed_operations
    assert executor.prompt_ref == "worker.prompt.code_executor.v1"


def test_web_research_worker_prompt_binds_to_specialist_profile() -> None:
    profile = next(
        item
        for item in default_agent_runtime_profiles()
        if item.agent_profile_id == "web_research_agent"
    )
    metadata = dict(profile.metadata)

    assert metadata["worker_prompt_ref"] == "worker.prompt.web_research.v1"
    assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.web_research.v1"]}
    assert metadata["output_contract"]["recommended_fields"] == (
        "source_matrix",
        "source_urls",
        "open_questions",
        "confidence",
        "recommended_parent_action",
    )


def test_builtin_specialist_worker_prompts_bind_to_profiles() -> None:
    profiles = {item.agent_profile_id: item for item in default_agent_runtime_profiles()}
    expected = {
        "knowledge_search_agent": "worker.prompt.knowledge_search.v1",
        "memory_search_agent": "worker.prompt.memory_search.v1",
        "pdf_analysis_agent": "worker.prompt.pdf_analysis.v1",
        "structured_data_analysis_agent": "worker.prompt.structured_data_analysis.v1",
    }

    for profile_id, prompt_ref in expected.items():
        metadata = dict(profiles[profile_id].metadata)
        assert metadata["worker_prompt_ref"] == prompt_ref
        assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": [prompt_ref]}


def test_builtin_specialist_worker_prompt_refs_are_resolved_from_blueprints() -> None:
    assert worker_prompt_ref_for_blueprint("runtime.template.knowledge_search") == "worker.prompt.knowledge_search.v1"
    assert worker_prompt_ref_for_blueprint("builtin.specialist.memory_searcher") == "worker.prompt.memory_search.v1"
    assert worker_prompt_ref_for_blueprint("builtin.specialist.pdf_reader") == "worker.prompt.pdf_analysis.v1"
    assert worker_prompt_ref_for_blueprint("builtin.specialist.table_analyst") == "worker.prompt.structured_data_analysis.v1"


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
    assert metadata["worker_prompt_ref"] == "worker.prompt.review.v1"
    assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.review.v1"]}


def test_completion_verifier_profile_uses_verification_worker_prompt() -> None:
    profile = next(
        item
        for item in default_agent_runtime_profiles()
        if item.agent_profile_id == "completion_verifier_agent"
    )
    metadata = dict(profile.metadata)

    assert metadata["worker_prompt_ref"] == "worker.prompt.verification.v1"
    assert metadata["agent_prompt_refs_by_invocation"] == {"task_execution": ["worker.prompt.verification.v1"]}
    assert metadata["output_contract"]["verdict_values"] == ("PASS", "FAIL", "PARTIAL")
    assert "op.shell" in profile.allowed_operations
    assert "op.write_file" in profile.blocked_operations


def test_worker_prompt_ref_assembles_for_task_execution(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=("worker.prompt.verification.v1",),
            agent_profile_ref="completion_verifier_agent",
        )
    )

    assert assembly.rejected_refs == ()
    assert "worker.prompt.verification.v1" in assembly.manifest["stable_prompt_refs"]
    assert "worker.role" in assembly.manifest["prompt_rules"]["rule_kinds"]


def test_web_research_worker_prompt_assembles_for_task_execution(tmp_path: Path) -> None:
    assembly = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_refs=("worker.prompt.web_research.v1",),
            agent_profile_ref="web_research_agent",
        )
    )

    assert assembly.rejected_refs == ()
    assert "worker.prompt.web_research.v1" in assembly.manifest["stable_prompt_refs"]
    assert "worker.role" in assembly.manifest["prompt_rules"]["rule_kinds"]


def test_builtin_specialist_worker_prompts_assemble_for_task_execution(tmp_path: Path) -> None:
    expected = {
        "knowledge_search_agent": "worker.prompt.knowledge_search.v1",
        "memory_search_agent": "worker.prompt.memory_search.v1",
        "pdf_analysis_agent": "worker.prompt.pdf_analysis.v1",
        "structured_data_analysis_agent": "worker.prompt.structured_data_analysis.v1",
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
    assert profile.metadata["agent_prompt_refs_by_invocation"]["task_execution"] == ["worker.prompt.verification.v1"]
