# Professional Required Action Queue Fix - 2026-05-24

## Problem

Professional mode already has a state machine and `agent_todo`, but they do not own execution progress. The runtime currently lets the model choose the next write from broad tool names such as `write_file` or `edit_file`. In long multi-file tasks this produces repeated stalls: `index.html` and `styles.css` can be written, then the model times out before `game.js`, `README.md`, `assets/`, and terminal verification.

## Root Cause

1. `ProfessionalRunState` tracks coarse states like `artifact_written`, not concrete required actions.
2. `agent_todo` is persisted as a tool observation, but it is not bound to required output paths.
3. `tool_contract_gate` computes missing paths but only exposes tool names to the model and driver.
4. Runtime recovery prompts say to write one file per round, which keeps multi-file completion dependent on another model call for each path.
5. Trace snapshots can show `unsatisfied_obligations: []` even when required output paths are missing, because the state is not recalculated from the ledger after each observation.

## Target Design

Create a deterministic required action queue derived from the goal contract and the tool observation ledger.

The queue must be the authority for:

- current required tool names;
- current required output path;
- missing output paths;
- missing verification;
- run state unsatisfied obligations;
- repair and recovery prompts.

The queue does not replace the model. The model still generates file content. The queue constrains what action must be completed next.

## Implementation Steps

1. Add `backend/runtime/professional_runtime/required_action_queue.py`.
   - Compile required output paths into ordered `write_file` actions.
   - Add terminal verification action after all writes when required.
   - Expose `current_action`, `missing_obligations`, `required_tool_names`, and `prompt_guidance`.

2. Wire queue into `tool_contract_gate.py`.
   - Gate decisions should use the queue instead of recomputing broad missing tool names.
   - Repair prompts must name the exact next path.
   - Remove the instruction that encourages slow per-file recovery as a loose model habit.

3. Wire queue into `driver.py`.
   - Build queue at each loop iteration from the current ledger.
   - Include queue diagnostics in state transitions and ledger events.
   - Store concrete `unsatisfied_obligations` on `ProfessionalRunState` after every observation.
   - Recovery prompts must receive queue-derived missing obligations.

4. Fix trace partial snapshot.
   - Read nested `task_run.task_run_id` when top-level `task_run_id` is absent.

5. Add focused regressions.
   - After `index.html` and `styles.css` are written, the next required action must be `write_file game.js`.
   - Run state must not report no unsatisfied obligations while required paths are missing.

## Non-Goals

- Do not rerun the long game scenario as the main proof.
- Do not add another prompt-only fallback.
- Do not make `agent_todo` a substitute for contract obligations.
