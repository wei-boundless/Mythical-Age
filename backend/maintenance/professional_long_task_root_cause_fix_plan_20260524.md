# Professional Long Task Root Cause Fix Plan - 2026-05-24

## Problem

Professional long-task runs can execute tools correctly but still finish as blocked because the request pipeline loses the concrete semantic task type. The model decision currently exposes coarse interaction/work mode fields, then runtime assembly derives `task_goal_type=planning`. That makes `test_report_triage` contracts validate as generic planning work.

A second failure appears in sandboxed professional runs: read tools execute inside the overlay workspace, while fixture/material paths may exist under the backend root. Copy-on-read only checks the project root path, so required materials can be missing in the sandbox even though the real backend material exists.

## Fix

1. Add concrete `task_goal_type` and `task_domain` to `ModelTurnDecision` and the sidecar schema.
2. Make runtime task-goal projection resolve authority in this order:
   - explicit authoritative `task_goal_spec`
   - model-declared concrete `task_goal_type`
   - explicit runtime `semantic_task_type`
   - coarse work-mode projection
3. Make task requirement resolution use the already projected `task_goal_spec` before coarse model work mode.
4. Make sandbox copy-on-read copy required files from the backend-root alternate path when tools resolve paths from the project root.
5. Verify the professional triage and repair long-task scenarios with real tool execution.
