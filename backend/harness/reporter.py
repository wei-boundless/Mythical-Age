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

    failing_results = [result for result in results if not result.passed]
    if failing_results:
        lines.extend(["", "## Failures", ""])
        for result in failing_results:
            lines.append(f"- `{result.category}` `{result.name}`: {result.summary}")
            trace_url = str(result.details.get("trace_url", "") or "")
            if trace_url:
                lines.append(f"  trace: {trace_url}")

    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(run_result.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")

    return "\n".join(lines).strip() + "\n"
