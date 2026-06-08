from __future__ import annotations

from typing import Any


def build_configurator_write_contract(*, graph_id: str) -> dict[str, Any]:
    prototype_catalog = configuration_prototype_catalog()
    return {
        "contract_id": f"configurator-write:{graph_id}",
        "system_node_id": "__configurator__",
        "can_write": [
            "authoring_spec_draft",
            "node_seed_drafts",
            "resource_binding_drafts",
            "edge_prototype_selections",
            "node_contract_drafts",
            "resource_contract_drafts",
            "edge_contract_drafts",
            "graph_draft_patch",
        ],
        "can_apply_to": ["draft_graph_store"],
        "must_validate_with": ["graph_compiler"],
        "cannot_write": [
            "published_graph_contract",
            "runtime_graph_state",
            "credential_secret_value",
            "permission_grant",
        ],
        "prototype_catalog": prototype_catalog,
        "patch_contract": {
            "authority": "task_system.graph_draft_patch_contract",
            "required_fields": ["graph_id", "patch_id", "operations"],
            "operation_kinds": [
                "upsert_node",
                "upsert_resource",
                "upsert_edge",
                "upsert_node_contract_draft",
                "upsert_resource_contract_draft",
                "upsert_edge_contract_draft",
            ],
        },
        "output_contract": {
            "required_outputs": [
                "graph_draft_patch",
                "prototype_selection_report",
                "compiler_validation_request",
            ],
            "prototype_selection_report": {
                "required_fields": [
                    "selected_node_prototypes",
                    "selected_resource_prototypes",
                    "selected_edge_prototypes",
                    "rationale",
                ],
                "must_reference_catalog": True,
            },
            "compiler_validation_request": {
                "compiler": "graph_compiler",
                "expect_compile_report": True,
                "repair_loop": "revise_patch_until_compile_report_has_no_blocking_issues",
            },
            "authority": "task_system.configurator_output_contract",
        },
        "authoring_rules": [
            "优先使用 prototype_catalog 中的原型组合，不要求用户直接填写底层协议字段。",
            "高风险字段只能作为 draft 写入，并必须在 prototype_selection_report 中解释来源。",
            "每次输出 graph_draft_patch 后必须请求 graph_compiler 生成 compile_report。",
        ],
        "authority": "task_system.configurator_write_contract",
    }


def configuration_prototype_catalog() -> dict[str, Any]:
    return {
        "node_contract_prototypes": [
            {
                "prototype_id": "node.agent_worker",
                "node_class": "executable",
                "recommended_for": ["single_agent_step", "specialist_agent_step", "review_agent_step"],
            },
            {
                "prototype_id": "node.control_gate",
                "node_class": "control",
                "recommended_for": ["human_gate", "quality_gate", "manual_release"],
            },
            {
                "prototype_id": "node.resource_repository",
                "node_class": "resource",
                "recommended_for": ["memory_repository", "artifact_repository", "file_repository"],
            },
        ],
        "resource_contract_prototypes": [
            {
                "prototype_id": "resource.memory_repository",
                "resource_kind": "memory",
                "recommended_for": ["long_term_context", "project_memory", "cross_node_memory"],
            },
            {
                "prototype_id": "resource.artifact_repository",
                "resource_kind": "artifact",
                "recommended_for": ["files", "deliverables", "versioned_outputs"],
            },
            {
                "prototype_id": "resource.file_view",
                "resource_kind": "file",
                "recommended_for": ["workspace_files", "bounded_read_context"],
            },
        ],
        "edge_contract_prototypes": [
            {
                "prototype_id": "edge.node_handoff",
                "protocol_kind": "node_handoff",
                "interaction_pattern": "source_result_to_target_context",
            },
            {
                "prototype_id": "edge.resource_read",
                "protocol_kind": "resource_read",
                "interaction_pattern": "resource_context_projection",
            },
            {
                "prototype_id": "edge.resource_write_candidate",
                "protocol_kind": "resource_write_candidate",
                "interaction_pattern": "resource_write_candidate_projection",
            },
            {
                "prototype_id": "edge.resource_commit",
                "protocol_kind": "resource_commit",
                "interaction_pattern": "resource_commit_receipt_projection",
            },
            {
                "prototype_id": "edge.review_feedback",
                "protocol_kind": "review_feedback",
                "interaction_pattern": "review_feedback_to_revision_target",
            },
            {
                "prototype_id": "edge.conditional_route",
                "protocol_kind": "conditional_route",
                "interaction_pattern": "conditional_feedback_route",
            },
            {
                "prototype_id": "edge.event_signal",
                "protocol_kind": "event_signal",
                "interaction_pattern": "event_notification",
            },
            {
                "prototype_id": "edge.audit_observation",
                "protocol_kind": "audit_observation",
                "interaction_pattern": "audit_observation_record",
            },
            {
                "prototype_id": "edge.control_dependency",
                "protocol_kind": "control_dependency",
                "interaction_pattern": "state_dependency_only",
            },
            {
                "prototype_id": "edge.barrier_join",
                "protocol_kind": "barrier_join",
                "interaction_pattern": "state_join_only",
            },
            {
                "prototype_id": "edge.human_gate",
                "protocol_kind": "human_gate",
                "interaction_pattern": "manual_release_gate",
            },
            {
                "prototype_id": "edge.a2a_session",
                "protocol_kind": "a2a_session",
                "interaction_pattern": "agent_session_channel",
            },
        ],
        "authority": "task_system.configuration_prototype_catalog",
    }


def graph_draft_patch(
    *,
    graph_id: str,
    operations: list[dict[str, Any]],
    patch_id: str = "",
) -> dict[str, Any]:
    return {
        "patch_id": patch_id or f"gpatch:{graph_id}",
        "graph_id": graph_id,
        "operations": [dict(item) for item in operations],
        "status": "draft",
        "requires_compiler_validation": True,
        "authority": "task_system.graph_draft_patch",
    }
