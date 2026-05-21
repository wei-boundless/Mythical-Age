# Task Run Completed Checkpoint Recovery

## Goal

When a task run has already reached a completed runtime checkpoint but the process stops before artifact materialization, agent result persistence, and coordination resume, recover through the same runtime closeout path instead of rerunning or fabricating outputs.

## Plan

1. Detect recoverable task runs where the latest checkpoint loop state is terminal but the state index is still running or missing closeout records.
2. Recover final content only from authoritative runtime events, preferring `output_boundary_applied` canonical output and falling back to committed assistant-session content.
3. Rebuild a minimal task result from the finalized task-run ledger recorded in events when the checkpoint has not yet persisted `commit_state.task_result`.
4. Re-enter `_upsert_finished_task_run` so artifact materialization, agent result records, and coordination continuation use the normal production path.
5. Expose the recovery through `continue-current-stage` so breakpoint continuation can repair half-finalized stage runs before replaying a node.
6. Add regression coverage for completed-checkpoint recovery and preserve the graph-unit protocol boundary tests.

## Verification

- Focused API/runtime regression tests must prove that a completed checkpoint with output-boundary content can materialize artifacts, mark the task run completed, create an agent result, and resume the parent coordination stage.
- Existing graph-unit protocol boundary regression tests must continue to pass.
