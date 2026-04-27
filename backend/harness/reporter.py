from __future__ import annotations

from collections import Counter

from .contracts import RunResult


def render_markdown(run_result: RunResult) -> str:
    results = run_result.results
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    by_category = Counter(result.category for result in results)

    lines = [
        f"# Test Run `{run_result.context.run_id}`",
        "",
        "## Summary",
        "",
        f"- profile: `{run_result.context.profile}`",
        f"- mode: `{run_result.context.mode}`",
        f"- total: `{total}`",
        f"- passed: `{passed}`",
        f"- failed: `{failed}`",
        f"- langsmith_enabled: `{run_result.context.langsmith_enabled}`",
        f"- trace_backend: `{run_result.context.trace_backend or 'disabled'}`",
        f"- trace_enabled: `{run_result.context.trace_enabled}`",
        "",
        "## Categories",
        "",
    ]

    for category, count in sorted(by_category.items()):
        lines.append(f"- `{category}`: `{count}`")

    runtime_rows = []
    for result in results:
        source_counts = result.details.get("runtime_control_source_counts")
        warning_counts = result.details.get("runtime_control_warning_counts")
        fallback_turns = result.details.get("runtime_control_fallback_turns")
        entry_kind_counts = result.details.get("runtime_entry_kind_counts")
        entry_source_counts = result.details.get("runtime_entry_source_counts")
        entry_strategy_counts = result.details.get("runtime_entry_strategy_counts")
        entry_eligible_counts = result.details.get("runtime_entry_eligible_counts")
        entry_blocker_counts = result.details.get("runtime_entry_blocker_counts")
        entry_selection_state_counts = result.details.get("runtime_entry_selection_state_counts")
        primary_preview_state_counts = result.details.get("runtime_primary_preview_state_counts")
        primary_preview_mismatch_counts = result.details.get("runtime_primary_preview_mismatch_counts")
        primary_takeover_state_counts = result.details.get("runtime_primary_takeover_state_counts")
        phase7_readiness_state_counts = result.details.get("runtime_phase7_readiness_state_counts")
        phase7_readiness_blocker_counts = result.details.get("runtime_phase7_readiness_blocker_counts")
        phase7_intent_authority_state_counts = result.details.get("runtime_phase7_intent_authority_state_counts")
        phase7_restore_authority_state_counts = result.details.get("runtime_phase7_restore_authority_state_counts")
        phase7_restore_authority_blocker_counts = result.details.get("runtime_phase7_restore_authority_blocker_counts")
        phase7_restore_candidate_type_counts = result.details.get("runtime_phase7_restore_candidate_type_counts")
        phase7_restore_adoption_state_counts = result.details.get("runtime_phase7_restore_adoption_state_counts")
        phase7_restore_adoption_gate_state_counts = result.details.get("runtime_phase7_restore_adoption_gate_state_counts")
        phase7_restore_adoption_gate_blocker_counts = result.details.get("runtime_phase7_restore_adoption_gate_blocker_counts")
        phase7_restore_adoption_decision_counts = result.details.get("runtime_phase7_restore_adoption_decision_counts")
        phase7_memory_context_validation_counts = result.details.get("runtime_phase7_memory_context_validation_counts")
        phase7_restore_cutover_state_counts = result.details.get("runtime_phase7_restore_cutover_state_counts")
        phase7_restore_cutover_blocker_counts = result.details.get("runtime_phase7_restore_cutover_blocker_counts")
        phase7_restore_dry_run_state_counts = result.details.get("runtime_phase7_restore_dry_run_state_counts")
        phase7_restore_dry_run_alignment_counts = result.details.get("runtime_phase7_restore_dry_run_alignment_counts")
        phase8_restore_formal_review_state_counts = result.details.get("runtime_phase8_restore_formal_review_state_counts")
        phase8_restore_formal_decision_counts = result.details.get("runtime_phase8_restore_formal_decision_counts")
        phase8_restore_legacy_alignment_counts = result.details.get("runtime_phase8_restore_legacy_alignment_counts")
        phase8_restore_trace_state_counts = result.details.get("runtime_phase8_restore_trace_state_counts")
        phase8_restore_trace_status_counts = result.details.get("runtime_phase8_restore_trace_status_counts")
        phase8_restore_trace_replacement_point_counts = result.details.get("runtime_phase8_restore_trace_replacement_point_counts")
        phase8_restore_trace_alignment_counts = result.details.get("runtime_phase8_restore_trace_alignment_counts")
        phase8_restore_shadow_state_counts = result.details.get("runtime_phase8_restore_shadow_state_counts")
        phase8_restore_shadow_status_counts = result.details.get("runtime_phase8_restore_shadow_status_counts")
        phase8_restore_shadow_replacement_point_counts = result.details.get("runtime_phase8_restore_shadow_replacement_point_counts")
        phase8_restore_shadow_compare_state_counts = result.details.get("runtime_phase8_restore_shadow_compare_state_counts")
        phase8_restore_shadow_compare_result_counts = result.details.get("runtime_phase8_restore_shadow_compare_result_counts")
        phase8_restore_shadow_observation_state_counts = result.details.get("runtime_phase8_restore_shadow_observation_state_counts")
        phase8_restore_real_shadow_gate_state_counts = result.details.get("runtime_phase8_restore_real_shadow_gate_state_counts")
        phase8_restore_real_shadow_gate_blocker_counts = result.details.get("runtime_phase8_restore_real_shadow_gate_blocker_counts")
        phase8_restore_real_shadow_design_status_counts = result.details.get("runtime_phase8_restore_real_shadow_design_status_counts")
        phase8_restore_real_shadow_interface_counts = result.details.get("runtime_phase8_restore_real_shadow_interface_counts")
        phase8_restore_shadow_contract_state_counts = result.details.get("runtime_phase8_restore_shadow_contract_state_counts")
        phase8_restore_shadow_contract_candidate_counts = result.details.get("runtime_phase8_restore_shadow_contract_candidate_counts")
        phase8_restore_shadow_consumer_control_state_counts = result.details.get("runtime_phase8_restore_shadow_consumer_control_state_counts")
        phase8_restore_shadow_consumer_control_mode_counts = result.details.get("runtime_phase8_restore_shadow_consumer_control_mode_counts")
        phase8_restore_shadow_consumer_observation_state_counts = result.details.get("runtime_phase8_restore_shadow_consumer_observation_state_counts")
        phase8_restore_shadow_consumer_observation_item_counts = result.details.get("runtime_phase8_restore_shadow_consumer_observation_item_counts")
        phase8_restore_legacy_decommission_state_counts = result.details.get("runtime_phase8_restore_legacy_decommission_state_counts")
        phase8_restore_legacy_decommission_target_counts = result.details.get("runtime_phase8_restore_legacy_decommission_target_counts")
        phase8_restore_authority_context_gate_state_counts = result.details.get("runtime_phase8_restore_authority_context_gate_state_counts")
        phase7_output_authority_state_counts = result.details.get("runtime_phase7_output_authority_state_counts")
        phase7_output_authority_blocker_counts = result.details.get("runtime_phase7_output_authority_blocker_counts")
        phase7_output_writeback_scope_counts = result.details.get("runtime_phase7_output_writeback_scope_counts")
        phase7_dispatch_authority_state_counts = result.details.get("runtime_phase7_dispatch_authority_state_counts")
        phase7_dispatch_authority_blocker_counts = result.details.get("runtime_phase7_dispatch_authority_blocker_counts")
        phase7_dispatch_target_counts = result.details.get("runtime_phase7_dispatch_target_counts")
        phase7_cutover_readiness_state_counts = result.details.get("runtime_phase7_cutover_readiness_state_counts")
        phase7_cutover_readiness_blocker_counts = result.details.get("runtime_phase7_cutover_readiness_blocker_counts")
        phase7_cutover_gate_blocker_counts = result.details.get("runtime_phase7_cutover_gate_blocker_counts")
        phase7_cutover_top_blocker_counts = result.details.get("runtime_phase7_cutover_top_blocker_counts")
        phase7_cutover_domain_state_counts = result.details.get("runtime_phase7_cutover_domain_state_counts")
        phase7_cutover_domain_blocker_counts = result.details.get("runtime_phase7_cutover_domain_blocker_counts")
        phase7_cutover_migration_task_counts = result.details.get("runtime_phase7_cutover_migration_task_counts")
        phase7_execution_contract_state_counts = result.details.get("runtime_phase7_execution_contract_state_counts")
        phase7_decommission_state_counts = result.details.get("runtime_phase7_decommission_state_counts")
        phase7_principle_alignment_state_counts = result.details.get("runtime_phase7_principle_alignment_state_counts")
        phase7_principle_alignment_blocker_counts = result.details.get("runtime_phase7_principle_alignment_blocker_counts")
        if not source_counts and not warning_counts and not fallback_turns and not entry_kind_counts and not entry_source_counts and not entry_strategy_counts and not entry_eligible_counts and not entry_blocker_counts and not entry_selection_state_counts and not primary_preview_state_counts and not primary_preview_mismatch_counts and not primary_takeover_state_counts and not phase7_readiness_state_counts and not phase7_readiness_blocker_counts and not phase7_intent_authority_state_counts and not phase7_restore_authority_state_counts and not phase7_restore_authority_blocker_counts and not phase7_restore_candidate_type_counts and not phase7_restore_adoption_state_counts and not phase7_restore_adoption_gate_state_counts and not phase7_restore_adoption_gate_blocker_counts and not phase7_restore_adoption_decision_counts and not phase7_memory_context_validation_counts and not phase7_restore_cutover_state_counts and not phase7_restore_cutover_blocker_counts and not phase7_restore_dry_run_state_counts and not phase7_restore_dry_run_alignment_counts and not phase8_restore_formal_review_state_counts and not phase8_restore_formal_decision_counts and not phase8_restore_legacy_alignment_counts and not phase8_restore_trace_state_counts and not phase8_restore_trace_status_counts and not phase8_restore_trace_replacement_point_counts and not phase8_restore_trace_alignment_counts and not phase8_restore_shadow_state_counts and not phase8_restore_shadow_status_counts and not phase8_restore_shadow_replacement_point_counts and not phase8_restore_shadow_compare_state_counts and not phase8_restore_shadow_compare_result_counts and not phase8_restore_shadow_observation_state_counts and not phase8_restore_real_shadow_gate_state_counts and not phase8_restore_real_shadow_gate_blocker_counts and not phase8_restore_real_shadow_design_status_counts and not phase8_restore_real_shadow_interface_counts and not phase8_restore_shadow_contract_state_counts and not phase8_restore_shadow_contract_candidate_counts and not phase8_restore_shadow_consumer_control_state_counts and not phase8_restore_shadow_consumer_control_mode_counts and not phase8_restore_shadow_consumer_observation_state_counts and not phase8_restore_shadow_consumer_observation_item_counts and not phase8_restore_legacy_decommission_state_counts and not phase8_restore_legacy_decommission_target_counts and not phase8_restore_authority_context_gate_state_counts and not phase7_output_authority_state_counts and not phase7_output_authority_blocker_counts and not phase7_output_writeback_scope_counts and not phase7_dispatch_authority_state_counts and not phase7_dispatch_authority_blocker_counts and not phase7_dispatch_target_counts and not phase7_cutover_readiness_state_counts and not phase7_cutover_readiness_blocker_counts and not phase7_cutover_gate_blocker_counts and not phase7_cutover_top_blocker_counts and not phase7_cutover_domain_state_counts and not phase7_cutover_domain_blocker_counts and not phase7_cutover_migration_task_counts and not phase7_execution_contract_state_counts and not phase7_decommission_state_counts and not phase7_principle_alignment_state_counts and not phase7_principle_alignment_blocker_counts:
            continue
        runtime_rows.append(
            (
                result.name,
                dict(source_counts or {}),
                dict(warning_counts or {}),
                len(list(fallback_turns or [])),
                dict(entry_kind_counts or {}),
                dict(entry_source_counts or {}),
                dict(entry_strategy_counts or {}),
                dict(entry_eligible_counts or {}),
                dict(entry_blocker_counts or {}),
                dict(entry_selection_state_counts or {}),
                dict(primary_preview_state_counts or {}),
                dict(primary_preview_mismatch_counts or {}),
                dict(primary_takeover_state_counts or {}),
                dict(phase7_readiness_state_counts or {}),
                dict(phase7_readiness_blocker_counts or {}),
                dict(phase7_intent_authority_state_counts or {}),
                dict(phase7_restore_authority_state_counts or {}),
                dict(phase7_restore_authority_blocker_counts or {}),
                dict(phase7_restore_candidate_type_counts or {}),
                dict(phase7_restore_adoption_state_counts or {}),
                dict(phase7_restore_adoption_gate_state_counts or {}),
                dict(phase7_restore_adoption_gate_blocker_counts or {}),
                dict(phase7_restore_adoption_decision_counts or {}),
                dict(phase7_memory_context_validation_counts or {}),
                dict(phase7_restore_cutover_state_counts or {}),
                dict(phase7_restore_cutover_blocker_counts or {}),
                dict(phase7_restore_dry_run_state_counts or {}),
                dict(phase7_restore_dry_run_alignment_counts or {}),
                dict(phase8_restore_formal_review_state_counts or {}),
                dict(phase8_restore_formal_decision_counts or {}),
                dict(phase8_restore_legacy_alignment_counts or {}),
                dict(phase8_restore_trace_state_counts or {}),
                dict(phase8_restore_trace_status_counts or {}),
                dict(phase8_restore_trace_replacement_point_counts or {}),
                dict(phase8_restore_trace_alignment_counts or {}),
                dict(phase8_restore_shadow_state_counts or {}),
                dict(phase8_restore_shadow_status_counts or {}),
                dict(phase8_restore_shadow_replacement_point_counts or {}),
                dict(phase8_restore_shadow_compare_state_counts or {}),
                dict(phase8_restore_shadow_compare_result_counts or {}),
                dict(phase8_restore_shadow_observation_state_counts or {}),
                dict(phase8_restore_real_shadow_gate_state_counts or {}),
                dict(phase8_restore_real_shadow_gate_blocker_counts or {}),
                dict(phase8_restore_real_shadow_design_status_counts or {}),
                dict(phase8_restore_real_shadow_interface_counts or {}),
                dict(phase8_restore_shadow_contract_state_counts or {}),
                dict(phase8_restore_shadow_contract_candidate_counts or {}),
                dict(phase8_restore_shadow_consumer_control_state_counts or {}),
                dict(phase8_restore_shadow_consumer_control_mode_counts or {}),
                dict(phase8_restore_shadow_consumer_observation_state_counts or {}),
                dict(phase8_restore_shadow_consumer_observation_item_counts or {}),
                dict(phase8_restore_legacy_decommission_state_counts or {}),
                dict(phase8_restore_legacy_decommission_target_counts or {}),
                dict(phase8_restore_authority_context_gate_state_counts or {}),
                dict(phase7_output_authority_state_counts or {}),
                dict(phase7_output_authority_blocker_counts or {}),
                dict(phase7_output_writeback_scope_counts or {}),
                dict(phase7_dispatch_authority_state_counts or {}),
                dict(phase7_dispatch_authority_blocker_counts or {}),
                dict(phase7_dispatch_target_counts or {}),
                dict(phase7_cutover_readiness_state_counts or {}),
                dict(phase7_cutover_readiness_blocker_counts or {}),
                dict(phase7_cutover_gate_blocker_counts or {}),
                dict(phase7_cutover_top_blocker_counts or {}),
                dict(phase7_cutover_domain_state_counts or {}),
                dict(phase7_cutover_domain_blocker_counts or {}),
                dict(phase7_cutover_migration_task_counts or {}),
                dict(phase7_execution_contract_state_counts or {}),
                dict(phase7_decommission_state_counts or {}),
                dict(phase7_principle_alignment_state_counts or {}),
                dict(phase7_principle_alignment_blocker_counts or {}),
            )
        )
    if runtime_rows:
        lines.extend(["", "## Runtime Control", ""])
        for name, source_counts, warning_counts, fallback_count, entry_kind_counts, entry_source_counts, entry_strategy_counts, entry_eligible_counts, entry_blocker_counts, entry_selection_state_counts, primary_preview_state_counts, primary_preview_mismatch_counts, primary_takeover_state_counts, phase7_readiness_state_counts, phase7_readiness_blocker_counts, phase7_intent_authority_state_counts, phase7_restore_authority_state_counts, phase7_restore_authority_blocker_counts, phase7_restore_candidate_type_counts, phase7_restore_adoption_state_counts, phase7_restore_adoption_gate_state_counts, phase7_restore_adoption_gate_blocker_counts, phase7_restore_adoption_decision_counts, phase7_memory_context_validation_counts, phase7_restore_cutover_state_counts, phase7_restore_cutover_blocker_counts, phase7_restore_dry_run_state_counts, phase7_restore_dry_run_alignment_counts, phase8_restore_formal_review_state_counts, phase8_restore_formal_decision_counts, phase8_restore_legacy_alignment_counts, phase8_restore_trace_state_counts, phase8_restore_trace_status_counts, phase8_restore_trace_replacement_point_counts, phase8_restore_trace_alignment_counts, phase8_restore_shadow_state_counts, phase8_restore_shadow_status_counts, phase8_restore_shadow_replacement_point_counts, phase8_restore_shadow_compare_state_counts, phase8_restore_shadow_compare_result_counts, phase8_restore_shadow_observation_state_counts, phase8_restore_real_shadow_gate_state_counts, phase8_restore_real_shadow_gate_blocker_counts, phase8_restore_real_shadow_design_status_counts, phase8_restore_real_shadow_interface_counts, phase8_restore_shadow_contract_state_counts, phase8_restore_shadow_contract_candidate_counts, phase8_restore_shadow_consumer_control_state_counts, phase8_restore_shadow_consumer_control_mode_counts, phase8_restore_shadow_consumer_observation_state_counts, phase8_restore_shadow_consumer_observation_item_counts, phase8_restore_legacy_decommission_state_counts, phase8_restore_legacy_decommission_target_counts, phase8_restore_authority_context_gate_state_counts, phase7_output_authority_state_counts, phase7_output_authority_blocker_counts, phase7_output_writeback_scope_counts, phase7_dispatch_authority_state_counts, phase7_dispatch_authority_blocker_counts, phase7_dispatch_target_counts, phase7_cutover_readiness_state_counts, phase7_cutover_readiness_blocker_counts, phase7_cutover_gate_blocker_counts, phase7_cutover_top_blocker_counts, phase7_cutover_domain_state_counts, phase7_cutover_domain_blocker_counts, phase7_cutover_migration_task_counts, phase7_execution_contract_state_counts, phase7_decommission_state_counts, phase7_principle_alignment_state_counts, phase7_principle_alignment_blocker_counts in runtime_rows:
            source_text = ", ".join(f"{key}:{value}" for key, value in sorted(source_counts.items())) or "none"
            warning_text = ", ".join(f"{key}:{value}" for key, value in sorted(warning_counts.items())) or "none"
            entry_kind_text = ", ".join(f"{key}:{value}" for key, value in sorted(entry_kind_counts.items())) or "none"
            entry_source_text = ", ".join(f"{key}:{value}" for key, value in sorted(entry_source_counts.items())) or "none"
            entry_strategy_text = ", ".join(f"{key}:{value}" for key, value in sorted(entry_strategy_counts.items())) or "none"
            entry_eligible_text = ", ".join(f"{key}:{value}" for key, value in sorted(entry_eligible_counts.items())) or "none"
            entry_blocker_text = ", ".join(f"{key}:{value}" for key, value in sorted(entry_blocker_counts.items())) or "none"
            entry_selection_text = ", ".join(f"{key}:{value}" for key, value in sorted(entry_selection_state_counts.items())) or "none"
            primary_preview_text = ", ".join(f"{key}:{value}" for key, value in sorted(primary_preview_state_counts.items())) or "none"
            primary_preview_mismatch_text = ", ".join(f"{key}:{value}" for key, value in sorted(primary_preview_mismatch_counts.items())) or "none"
            primary_takeover_text = ", ".join(f"{key}:{value}" for key, value in sorted(primary_takeover_state_counts.items())) or "none"
            phase7_readiness_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_readiness_state_counts.items())) or "none"
            phase7_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_readiness_blocker_counts.items())) or "none"
            phase7_intent_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_intent_authority_state_counts.items())) or "none"
            phase7_restore_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_authority_state_counts.items())) or "none"
            phase7_restore_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_authority_blocker_counts.items())) or "none"
            phase7_restore_types_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_candidate_type_counts.items())) or "none"
            phase7_restore_adoption_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_adoption_state_counts.items())) or "none"
            phase7_restore_gate_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_adoption_gate_state_counts.items())) or "none"
            phase7_restore_gate_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_adoption_gate_blocker_counts.items())) or "none"
            phase7_restore_decisions_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_adoption_decision_counts.items())) or "none"
            phase7_memory_context_validation_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_memory_context_validation_counts.items())) or "none"
            phase7_restore_cutover_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_cutover_state_counts.items())) or "none"
            phase7_restore_cutover_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_cutover_blocker_counts.items())) or "none"
            phase7_restore_dry_run_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_dry_run_state_counts.items())) or "none"
            phase7_restore_dry_run_alignments_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_restore_dry_run_alignment_counts.items())) or "none"
            phase8_restore_formal_review_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_formal_review_state_counts.items())) or "none"
            phase8_restore_formal_decisions_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_formal_decision_counts.items())) or "none"
            phase8_restore_legacy_alignment_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_legacy_alignment_counts.items())) or "none"
            phase8_restore_trace_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_trace_state_counts.items())) or "none"
            phase8_restore_trace_status_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_trace_status_counts.items())) or "none"
            phase8_restore_trace_replacement_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_trace_replacement_point_counts.items())) or "none"
            phase8_restore_trace_alignment_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_trace_alignment_counts.items())) or "none"
            phase8_restore_shadow_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_state_counts.items())) or "none"
            phase8_restore_shadow_status_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_status_counts.items())) or "none"
            phase8_restore_shadow_replacement_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_replacement_point_counts.items())) or "none"
            phase8_restore_shadow_compare_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_compare_state_counts.items())) or "none"
            phase8_restore_shadow_compare_result_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_compare_result_counts.items())) or "none"
            phase8_restore_shadow_observation_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_observation_state_counts.items())) or "none"
            phase8_restore_real_shadow_gate_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_real_shadow_gate_state_counts.items())) or "none"
            phase8_restore_real_shadow_gate_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_real_shadow_gate_blocker_counts.items())) or "none"
            phase8_restore_real_shadow_design_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_real_shadow_design_status_counts.items())) or "none"
            phase8_restore_real_shadow_interfaces_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_real_shadow_interface_counts.items())) or "none"
            phase8_restore_shadow_contract_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_contract_state_counts.items())) or "none"
            phase8_restore_shadow_contract_candidates_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_contract_candidate_counts.items())) or "none"
            phase8_restore_shadow_control_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_consumer_control_state_counts.items())) or "none"
            phase8_restore_shadow_control_modes_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_consumer_control_mode_counts.items())) or "none"
            phase8_restore_shadow_consumer_observation_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_consumer_observation_state_counts.items())) or "none"
            phase8_restore_shadow_consumer_observation_items_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_shadow_consumer_observation_item_counts.items())) or "none"
            phase8_restore_legacy_decommission_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_legacy_decommission_state_counts.items())) or "none"
            phase8_restore_legacy_decommission_targets_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_legacy_decommission_target_counts.items())) or "none"
            phase8_restore_authority_context_gate_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase8_restore_authority_context_gate_state_counts.items())) or "none"
            phase7_output_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_output_authority_state_counts.items())) or "none"
            phase7_output_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_output_authority_blocker_counts.items())) or "none"
            phase7_output_writeback_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_output_writeback_scope_counts.items())) or "none"
            phase7_dispatch_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_dispatch_authority_state_counts.items())) or "none"
            phase7_dispatch_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_dispatch_authority_blocker_counts.items())) or "none"
            phase7_dispatch_targets_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_dispatch_target_counts.items())) or "none"
            phase7_cutover_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_readiness_state_counts.items())) or "none"
            phase7_cutover_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_readiness_blocker_counts.items())) or "none"
            phase7_cutover_gate_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_gate_blocker_counts.items())) or "none"
            phase7_cutover_top_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_top_blocker_counts.items())) or "none"
            phase7_cutover_domains_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_domain_state_counts.items())) or "none"
            phase7_cutover_domain_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_domain_blocker_counts.items())) or "none"
            phase7_cutover_tasks_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_cutover_migration_task_counts.items())) or "none"
            phase7_execution_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_execution_contract_state_counts.items())) or "none"
            phase7_decommission_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_decommission_state_counts.items())) or "none"
            phase7_principle_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_principle_alignment_state_counts.items())) or "none"
            phase7_principle_blockers_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_principle_alignment_blocker_counts.items())) or "none"
            lines.append(
                f"- `{name}`: sources `{source_text}`; fallback_turns `{fallback_count}`; warnings `{warning_text}`"
                f"; entries `{entry_kind_text}`; entry_sources `{entry_source_text}`; entry_strategy `{entry_strategy_text}`"
                f"; entry_eligible `{entry_eligible_text}`; entry_blockers `{entry_blocker_text}`"
                f"; entry_selection `{entry_selection_text}`"
                f"; primary_preview `{primary_preview_text}`; primary_preview_mismatches `{primary_preview_mismatch_text}`"
                f"; primary_takeover `{primary_takeover_text}`"
                f"; phase7_readiness `{phase7_readiness_text}`; phase7_blockers `{phase7_blockers_text}`"
                f"; phase7_intent `{phase7_intent_text}`"
                f"; phase7_restore `{phase7_restore_text}`; phase7_restore_blockers `{phase7_restore_blockers_text}`"
                f"; phase7_restore_types `{phase7_restore_types_text}`; phase7_restore_adoption `{phase7_restore_adoption_text}`"
                f"; phase7_restore_gate `{phase7_restore_gate_text}`; phase7_restore_gate_blockers `{phase7_restore_gate_blockers_text}`"
                f"; phase7_restore_decisions `{phase7_restore_decisions_text}`"
                f"; phase7_memory_context_validation `{phase7_memory_context_validation_text}`"
                f"; phase7_restore_cutover `{phase7_restore_cutover_text}`; phase7_restore_cutover_blockers `{phase7_restore_cutover_blockers_text}`"
                f"; phase7_restore_dry_run `{phase7_restore_dry_run_text}`; phase7_restore_dry_run_alignments `{phase7_restore_dry_run_alignments_text}`"
                f"; phase8_restore_formal `{phase8_restore_formal_review_text}`; phase8_restore_decisions `{phase8_restore_formal_decisions_text}`"
                f"; phase8_restore_alignment `{phase8_restore_legacy_alignment_text}`"
                f"; phase8_restore_trace `{phase8_restore_trace_text}`; phase8_restore_trace_status `{phase8_restore_trace_status_text}`"
                f"; phase8_restore_trace_replacements `{phase8_restore_trace_replacement_text}`"
                f"; phase8_restore_trace_alignments `{phase8_restore_trace_alignment_text}`"
                f"; phase8_restore_shadow `{phase8_restore_shadow_text}`; phase8_restore_shadow_status `{phase8_restore_shadow_status_text}`"
                f"; phase8_restore_shadow_replacements `{phase8_restore_shadow_replacement_text}`"
                f"; phase8_restore_shadow_compare `{phase8_restore_shadow_compare_text}`"
                f"; phase8_restore_shadow_compare_results `{phase8_restore_shadow_compare_result_text}`"
                f"; phase8_restore_shadow_observations `{phase8_restore_shadow_observation_text}`"
                f"; phase8_restore_real_shadow_gate `{phase8_restore_real_shadow_gate_text}`"
                f"; phase8_restore_real_shadow_gate_blockers `{phase8_restore_real_shadow_gate_blockers_text}`"
                f"; phase8_restore_real_shadow_design `{phase8_restore_real_shadow_design_text}`"
                f"; phase8_restore_real_shadow_interfaces `{phase8_restore_real_shadow_interfaces_text}`"
                f"; phase8_restore_shadow_contract `{phase8_restore_shadow_contract_text}`"
                f"; phase8_restore_shadow_contract_candidates `{phase8_restore_shadow_contract_candidates_text}`"
                f"; phase8_restore_shadow_control `{phase8_restore_shadow_control_text}`"
                f"; phase8_restore_shadow_control_modes `{phase8_restore_shadow_control_modes_text}`"
                f"; phase8_restore_shadow_consumer_observation `{phase8_restore_shadow_consumer_observation_text}`"
                f"; phase8_restore_shadow_consumer_observation_items `{phase8_restore_shadow_consumer_observation_items_text}`"
                f"; phase8_restore_legacy_decommission `{phase8_restore_legacy_decommission_text}`"
                f"; phase8_restore_legacy_decommission_targets `{phase8_restore_legacy_decommission_targets_text}`"
                f"; phase8_restore_authority_context_gate `{phase8_restore_authority_context_gate_text}`"
                f"; phase7_output `{phase7_output_text}`; phase7_output_blockers `{phase7_output_blockers_text}`"
                f"; phase7_output_writeback `{phase7_output_writeback_text}`"
                f"; phase7_dispatch `{phase7_dispatch_text}`; phase7_dispatch_blockers `{phase7_dispatch_blockers_text}`"
                f"; phase7_dispatch_targets `{phase7_dispatch_targets_text}`"
                f"; phase7_cutover `{phase7_cutover_text}`; phase7_cutover_top `{phase7_cutover_top_blockers_text}`"
                f"; phase7_cutover_gate `{phase7_cutover_gate_blockers_text}`"
                f"; phase7_cutover_domains `{phase7_cutover_domains_text}`"
                f"; phase7_cutover_domain_blockers `{phase7_cutover_domain_blockers_text}`"
                f"; phase7_cutover_tasks `{phase7_cutover_tasks_text}`"
                f"; phase7_cutover_blockers_full `{phase7_cutover_blockers_text}`"
                f"; phase7_execution `{phase7_execution_text}`"
                f"; phase7_decommission `{phase7_decommission_text}`"
                f"; phase7_principles `{phase7_principle_text}`"
                f"; phase7_principle_blockers `{phase7_principle_blockers_text}`"
            )

    output_commit_rows = []
    for result in results:
        state_counts = result.details.get("runtime_phase8_output_commit_state_counts")
        candidate_counts = result.details.get("runtime_phase8_output_commit_candidate_type_counts")
        if not state_counts and not candidate_counts:
            continue
        output_commit_rows.append(
            (
                result.name,
                dict(state_counts or {}),
                dict(candidate_counts or {}),
            )
        )
    if output_commit_rows:
        lines.extend(["", "## Output Commit", ""])
        for name, state_counts, candidate_counts in output_commit_rows:
            state_text = ", ".join(f"{key}:{value}" for key, value in sorted(state_counts.items())) or "none"
            candidate_text = ", ".join(f"{key}:{value}" for key, value in sorted(candidate_counts.items())) or "none"
            lines.append(
                f"- `{name}`: phase8_output_commit `{state_text}`; commit_candidates `{candidate_text}`"
            )

    failing_results = [result for result in results if not result.passed]
    if failing_results:
        lines.extend(["", "## Failures", ""])
        for result in failing_results:
            lines.append(f"- `{result.category}` `{result.name}`: {result.summary}")
            trace_url = str(result.details.get("trace_url", "") or "")
            if trace_url:
                lines.append(f"  trace: {trace_url}")

    if run_result.issues:
        lines.extend(["", "## Issues", ""])
        for issue in run_result.issues:
            lines.append(
                f"- `{issue.severity}` `{issue.category}` `{issue.id}`: {issue.summary}"
            )
            if issue.trace_url:
                lines.append(f"  trace: {issue.trace_url}")

    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(run_result.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")

    return "\n".join(lines).strip() + "\n"
