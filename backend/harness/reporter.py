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
        phase7_execution_contract_state_counts = result.details.get("runtime_phase7_execution_contract_state_counts")
        phase7_decommission_state_counts = result.details.get("runtime_phase7_decommission_state_counts")
        if not source_counts and not warning_counts and not fallback_turns and not entry_kind_counts and not entry_source_counts and not entry_strategy_counts and not entry_eligible_counts and not entry_blocker_counts and not entry_selection_state_counts and not primary_preview_state_counts and not primary_preview_mismatch_counts and not primary_takeover_state_counts and not phase7_readiness_state_counts and not phase7_readiness_blocker_counts and not phase7_intent_authority_state_counts and not phase7_execution_contract_state_counts and not phase7_decommission_state_counts:
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
                dict(phase7_execution_contract_state_counts or {}),
                dict(phase7_decommission_state_counts or {}),
            )
        )
    if runtime_rows:
        lines.extend(["", "## Runtime Control", ""])
        for name, source_counts, warning_counts, fallback_count, entry_kind_counts, entry_source_counts, entry_strategy_counts, entry_eligible_counts, entry_blocker_counts, entry_selection_state_counts, primary_preview_state_counts, primary_preview_mismatch_counts, primary_takeover_state_counts, phase7_readiness_state_counts, phase7_readiness_blocker_counts, phase7_intent_authority_state_counts, phase7_execution_contract_state_counts, phase7_decommission_state_counts in runtime_rows:
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
            phase7_execution_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_execution_contract_state_counts.items())) or "none"
            phase7_decommission_text = ", ".join(f"{key}:{value}" for key, value in sorted(phase7_decommission_state_counts.items())) or "none"
            lines.append(
                f"- `{name}`: sources `{source_text}`; fallback_turns `{fallback_count}`; warnings `{warning_text}`"
                f"; entries `{entry_kind_text}`; entry_sources `{entry_source_text}`; entry_strategy `{entry_strategy_text}`"
                f"; entry_eligible `{entry_eligible_text}`; entry_blockers `{entry_blocker_text}`"
                f"; entry_selection `{entry_selection_text}`"
                f"; primary_preview `{primary_preview_text}`; primary_preview_mismatches `{primary_preview_mismatch_text}`"
                f"; primary_takeover `{primary_takeover_text}`"
                f"; phase7_readiness `{phase7_readiness_text}`; phase7_blockers `{phase7_blockers_text}`"
                f"; phase7_intent `{phase7_intent_text}`"
                f"; phase7_execution `{phase7_execution_text}`"
                f"; phase7_decommission `{phase7_decommission_text}`"
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
