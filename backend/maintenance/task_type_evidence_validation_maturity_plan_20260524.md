# Task Type, Evidence, and Deliverable Validation Maturity Plan

## 1. Technical Source Report

Current failure mode:

- Task goal types are required in `ModelTurnDecision`, but the task type table is not yet authoritative. `TaskGoalProfile` exists, while `task_requirement_contracts.py`, `strategy_prototypes.py`, `interaction_mode_policy.py`, prompts, validators, and tests still encode their own boundary knowledge.
- `read_structured_file` parses JSON/YAML/TOML but returns only a structural text summary. `ToolResultEnvelope` has `structured_payload`, yet it cannot receive parsed tool data. `EvidencePacket` therefore reconstructs failures from text summary lines.
- `deliverable_validator.py` can block missing deliverables, but several checks still depend on final-answer words such as "失败归类", "结构性根因", "回归测试", and "证据边界".
- Professional mode has regression coverage for test-report triage and some write/verify paths, but the evidence and validator contract is not exercised across frontend/browser, multi-file artifact delivery, and long-context resume families.

Broken system property:

- The agent lacks a single typed contract chain for `task_goal_type -> obligation -> evidence -> deliverable validation`. The same semantic boundary is currently re-decided in several modules.

Correct end state:

- `TaskGoalProfile` is the authoritative registry for known task types, including conversational/light/inspection/tool tasks.
- Contract building only reads task-type policy from the registry plus explicit execution obligation; it does not maintain duplicate task maps.
- Structured tools return an envelope payload containing parsed data and structural summary separately.
- Evidence packets prefer typed tool payloads over text, and do not infer primary facts from presentation summaries.
- Deliverable validation checks required deliverables through structured evidence/deliverable coverage first, using text only for human-facing final-answer presence and protocol-leak detection.

## 2. Local Design Principles

Enforced constraints from current project plans and `AGENTS.md`:

- The main model owns current-turn intent and task type judgment; code owns resource registries, permissions, evidence, and validation.
- No compatibility fallback should silently change task goal type or make old paths authoritative.
- A task cannot be marked completed without a validated deliverable boundary.
- Prompt and output resources should consume structured contracts, not reverse-guess goals from raw text.
- Evidence must come from real observations, artifacts, tool results, or explicit limitations; classifications and plans are not completion evidence.

## 3. Recommended Design Direction

Use `TaskGoalProfile` as the registry instead of adding a second registry file. It is already the closest ownership point, and replacing it would create a new shell around an old shell.

Borrow from mature agent architectures:

- One request decision object from the model.
- One registry translating task type into runtime policy.
- One observation envelope preserving raw text and typed payload.
- One evidence packet summarizing execution facts.
- One validator judging deliverables against evidence and contract.

Do not borrow:

- A separate heuristic intent classifier in code.
- Keyword expansion as validation.
- Prompt-only enforcement for task boundaries.

## 4. Fixed Execution Flow

1. `ModelTurnDecision` declares `task_goal_type`.
2. `TaskGoalProfile` registry validates and describes the task type.
3. `TaskRequirementContract` compiles deliverables/actions/material policy from the profile and execution obligation.
4. Runtime executes tools and stores `ToolResultEnvelope`.
5. Structured tools place typed data in `structured_payload.tool_result`.
6. `EvidencePacket` consumes `structured_payload.tool_result` first, then generic envelope fields, then text only as a low-confidence observation preview.
7. `deliverable_validator` evaluates required deliverables from structured evidence dimensions and declared coverage.
8. Professional mode closes only when validator passes or returns explicit missing deliverables/unsupported claims.

## 5. Phased Execution Plan

### Phase 1 - Formalize Task Goal Registry

Goal:

- Make all currently used task types first-class `TaskGoalProfile` entries.

Files:

- `backend/task_system/goal_profiles/task_goal_profiles.py`
- `backend/task_system/goal_profiles/__init__.py`
- `backend/task_system/contracts/task_requirement_contracts.py`
- `backend/prompting/strategy_prototypes.py`
- `backend/orchestration/interaction_mode_policy.py`
- `backend/agent_runtime/understanding/model_turn_decision_invoker.py`

Changes:

- Add task types: `light_qa`, `role_conversation`, `inspection`, `bounded_tool_task`, `blocked`, `external_research`, `implementation`, `verification`, `pdf_analysis`.
- Add registry helpers for allowed task types and profile-derived strategy data.
- Remove duplicate deliverable/reasoning/action/domain maps where a profile can answer directly.
- Make mode policy derive professional/standard/role buckets from profile capabilities and deliverables instead of local task-type sets.

Completion criteria:

- There is one authoritative list of known task types.
- Contract building no longer contains duplicate default deliverable or reasoning maps for registered task types.

### Phase 2 - Upgrade Structured Tool Result Protocol

Goal:

- Stop reconstructing structured facts from `read_structured_file` text summaries.

Files:

- `backend/capability_system/units/tools/structured_file_tool.py`
- `backend/runtime/tool_runtime/tool_result_envelope.py`
- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/shared/action_request.py`
- `backend/runtime/memory/evidence_packet.py`

Changes:

- Introduce a small `StructuredToolResult` object or dict convention with `text` plus `structured_payload`.
- `read_structured_file` returns parsed payload, format, root type, path, and compact summary.
- `ToolRuntimeExecutor` preserves structured payload before string truncation.
- `ToolResultEnvelope` stores `structured_payload["tool_result"]` for typed tool output.
- `EvidencePacket` reads parsed payload from the envelope first.

Completion criteria:

- A JSON failure report read through `read_structured_file` yields evidence facts from structured payload, not from summary text.

### Phase 3 - Make Deliverable Validation Evidence-Led

Goal:

- Replace keyword-led validation with structured deliverable coverage and evidence dimensions.

Files:

- `backend/runtime/contracts/deliverable_validator.py`
- `backend/runtime/memory/evidence_packet.py`

Changes:

- Add evidence-derived `deliverable_coverage` for triage and profile-driven tasks.
- Validate `test_report_triage` by facts/classifications/coverage, not Chinese section labels.
- Validate artifact/frontend/game families by envelope facts: artifact refs, command receipts, browser/runtime observations, asset refs, and limitations.
- Keep protocol-leak detection and empty-answer checks.

Completion criteria:

- A triage answer with correct evidence but different wording passes.
- A polished answer with no facts still fails.

### Phase 4 - Expand Professional Mode Verification Matrix

Goal:

- Prove the new contracts across more task families without faking output.

Files:

- `backend/tests/professional_mode_runtime_regression.py`
- `backend/tests/professional_runtime_foundation_regression.py`
- focused new/updated tests where necessary.

Scenarios:

- Structured triage through `read_structured_file` envelope.
- Frontend delivery requires write evidence plus browser/workflow evidence.
- Game delivery requires write, asset, browser, gameplay evidence.
- Multi-file artifact delivery requires all required output paths.
- Resume keeps current obligation and evidence boundaries.

Completion criteria:

- Focused professional/evidence/validator tests pass.
- Existing professional long-task tests remain passing.

## 6. Cutover Rules

- No old fallback may infer task type from `work_mode`.
- Unknown task types are allowed only as explicit model outputs and compile to minimal `final_answer` contract; they do not get invented professional behavior.
- Text-summary parsing in evidence packet may remain only as low-confidence support for non-structured observations, not as the primary path for `read_structured_file`.
- If a phase exposes an old test stub with hard-coded task types, update it to use registry helpers rather than adding another list.

## 7. Validation Commands

Run focused checks after implementation:

```powershell
python -m compileall backend\task_system backend\runtime backend\capability_system backend\agent_runtime backend\prompting backend\orchestration
pytest -q backend\tests\professional_mode_runtime_regression.py backend\tests\professional_runtime_foundation_regression.py backend\tests\professional_run_resume_regression.py
pytest -q backend\tests\professional_task_run_regression.py -k "test_report_triage or artifact_delivery or code_fix_execution or frontend or game"
```
