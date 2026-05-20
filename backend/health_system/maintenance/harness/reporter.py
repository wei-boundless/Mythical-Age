from __future__ import annotations

from collections import Counter

from .contracts import RunResult


def _counts_text(counts: dict[str, object] | None) -> str:
    items = dict(counts or {})
    return ", ".join(f"{key}:{value}" for key, value in sorted(items.items())) or "none"


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
        details = result.details
        source_counts = details.get("runtime_control_source_counts")
        warning_counts = details.get("runtime_control_warning_counts")
        blocked_turns = details.get("runtime_control_blocked_turns")
        spec_kind_counts = details.get("runtime_execution_spec_kind_counts")
        spec_source_counts = details.get("runtime_execution_spec_source_counts")
        spec_action_counts = details.get("runtime_execution_spec_action_counts")
        spec_risk_counts = details.get("runtime_execution_spec_risk_counts")
        validation_counts = details.get("runtime_validation_status_counts")
        blocked_reason_counts = details.get("runtime_blocked_reason_counts")
        directive_source_counts = details.get("runtime_directive_source_counts")
        if not any(
            [
                source_counts,
                warning_counts,
                blocked_turns,
                spec_kind_counts,
                spec_source_counts,
                spec_action_counts,
                spec_risk_counts,
                validation_counts,
                blocked_reason_counts,
                directive_source_counts,
            ]
        ):
            continue
        runtime_rows.append(
            (
                result.name,
                dict(source_counts or {}),
                dict(warning_counts or {}),
                len(list(blocked_turns or [])),
                dict(spec_kind_counts or {}),
                dict(spec_source_counts or {}),
                dict(spec_action_counts or {}),
                dict(spec_risk_counts or {}),
                dict(validation_counts or {}),
                dict(blocked_reason_counts or {}),
                dict(directive_source_counts or {}),
            )
        )
    if runtime_rows:
        lines.extend(["", "## Runtime Control", ""])
        for (
            name,
            source_counts,
            warning_counts,
            blocked_count,
            spec_kind_counts,
            spec_source_counts,
            spec_action_counts,
            spec_risk_counts,
            validation_counts,
            blocked_reason_counts,
            directive_source_counts,
        ) in runtime_rows:
            lines.append(
                f"- `{name}`: sources `{_counts_text(source_counts)}`; blocked_turns `{blocked_count}`"
                f"; warnings `{_counts_text(warning_counts)}`"
                f"; execution_specs `{_counts_text(spec_kind_counts)}`"
                f"; spec_sources `{_counts_text(spec_source_counts)}`"
                f"; spec_actions `{_counts_text(spec_action_counts)}`"
                f"; spec_risks `{_counts_text(spec_risk_counts)}`"
                f"; validation `{_counts_text(validation_counts)}`"
                f"; blocked_reasons `{_counts_text(blocked_reason_counts)}`"
                f"; directive_sources `{_counts_text(directive_source_counts)}`"
            )

    output_commit_rows = []
    for result in results:
        state_counts = result.details.get("runtime_phase8_output_commit_state_counts")
        candidate_counts = result.details.get("runtime_phase8_output_commit_candidate_type_counts")
        if not state_counts and not candidate_counts:
            continue
        output_commit_rows.append((result.name, dict(state_counts or {}), dict(candidate_counts or {})))
    if output_commit_rows:
        lines.extend(["", "## Output Commit", ""])
        for name, state_counts, candidate_counts in output_commit_rows:
            lines.append(
                f"- `{name}`: phase8_output_commit `{_counts_text(state_counts)}`"
                f"; commit_candidates `{_counts_text(candidate_counts)}`"
            )

    failing_results = [result for result in results if not result.passed]
    if failing_results:
        lines.extend(["", "## Failures", ""])
        for result in failing_results:
            lines.append(f"- `{result.category}` `{result.name}`: {result.summary}")
            trace_url = str(result.details.get("trace_url", "") or "")
            if trace_url:
                lines.append(f"  trace: {trace_url}")
            evidence_refs = [
                str(item)
                for item in list(result.details.get("evidence_refs") or result.details.get("evidence_packet_refs") or [])
                if str(item).strip()
            ]
            if evidence_refs:
                lines.append(f"  evidence: {', '.join(f'`{item}`' for item in evidence_refs[:5])}")
            rerun = str(result.details.get("rerun_command") or result.command or "").strip()
            if rerun:
                lines.append(f"  rerun: `{rerun}`")
            recovery = str(result.details.get("recovery_suggestion") or "").strip()
            if recovery:
                lines.append(f"  recovery: {recovery}")

    if run_result.issues:
        lines.extend(["", "## Issues", ""])
        for issue in run_result.issues:
            lines.append(f"- `{issue.severity}` `{issue.category}` `{issue.id}`: {issue.summary}")
            if issue.trace_url:
                lines.append(f"  trace: {issue.trace_url}")

    harness_state = dict(run_result.metadata.get("harness_state") or {})
    if harness_state:
        lines.extend(["", "## Harness State", ""])
        lines.append(f"- status: `{harness_state.get('status') or 'unknown'}`")
        lines.append(f"- heartbeat_at: `{harness_state.get('heartbeat_at') or 0}`")
        lines.append(f"- last_progress_event_id: `{harness_state.get('last_progress_event_id') or ''}`")
        if harness_state.get("stale_reason"):
            lines.append(f"- stale_reason: {harness_state.get('stale_reason')}")

    evidence_packets = [
        dict(item)
        for item in list(run_result.metadata.get("evidence_packets") or [])
        if isinstance(item, dict)
    ]
    if evidence_packets:
        lines.extend(["", "## Useful Evidence", ""])
        for packet in evidence_packets[:5]:
            lines.append(
                f"- `{packet.get('packet_id') or 'evidence'}`: "
                f"{packet.get('summary') or packet.get('verdict') or ''}"
            )

    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(run_result.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")

    return "\n".join(lines).strip() + "\n"
