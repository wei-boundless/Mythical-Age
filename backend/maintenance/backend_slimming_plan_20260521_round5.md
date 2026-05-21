# Backend Slimming Plan 2026-05-21 Round 5

## Scope

Backend only. Ignore `docs/` and frontend. This round targets `backend/orchestration/runtime_loop/professional_task_run_driver.py`, which still mixes orchestration, goal contract parsing, tool gating, prompt shaping, evidence closeout, and artifact auto-write fallback in one file.

## Diagnosis

`ProfessionalTaskRunDriver` should be the professional-mode run orchestrator, but the file also owns several independent policy families:

- goal contract extraction from semantic contracts and user text;
- semantic control plan construction;
- professional prompt/directive shaping;
- contract-gated tool selection and repair instructions;
- evidence-packet closeout generation;
- artifact-delivery auto-write fallback;
- small protocol and observation helpers.

That coupling makes the runtime hard to slim because tests and later fixes reach into private helpers on the driver file. The business behavior can remain intact while the policy code moves behind named module boundaries.

## Target Shape

Create focused modules under `backend/orchestration/runtime_loop/`:

- `professional_goal_contract.py`
  - `ProfessionalTaskGoalContract`
  - goal/material/output path extraction
  - semantic control plan generation
  - contract summaries and response term extraction
- `professional_tool_contract_gate.py`
  - `ProfessionalTaskContractGateDecision`
  - tool request gate, repair guidance, next-tool selection, recovery message compacting
- `professional_runtime_policy.py`
  - directive shaping, prompt insertion, runtime policy extraction, allowed tool names, tool-call binding options
- `professional_evidence_closeout.py`
  - final-content sanitization and evidence-based closeout decisions/content
  - artifact delivery auto-write fallback
  - observation ref/artifact ref helpers

`professional_task_run_driver.py` should import these policies and keep run orchestration plus ledger step transitions.

## Implementation Steps

1. Move dataclasses and pure goal-contract helpers into `professional_goal_contract.py`.
2. Move tool-gate helpers into `professional_tool_contract_gate.py`, importing goal-contract helpers instead of duplicating path logic.
3. Move prompt/directive/runtime policy helpers into `professional_runtime_policy.py`.
4. Move evidence closeout and artifact auto-write helpers into `professional_evidence_closeout.py`.
5. Replace local helper definitions in `professional_task_run_driver.py` with imports.
6. Keep public helper compatibility only where tests still import them, then migrate those tests to the new owner modules and remove compatibility aliases when safe.
7. Validate with targeted py_compile and professional/query runtime regression tests.

## Non-Goals

- No prompt semantic rewrite beyond preserving existing content in new modules.
- No changes to frontend or stale docs.
- No generated runtime artifacts cleanup in this round.
