# Vibe Coding Runtime Stabilization Plan

## Problem

The professional runtime can now mount source projects, derive read/write/verify obligations, and force the next tool stage through the action gate. The real smoke run still stalled after the action gate forced `write_file`.

The broken system property is not model intelligence. The runtime does not fully enforce per-stage model deadlines at the provider boundary. In a coding-agent loop, a forced action round must be bounded, observable, and recoverable.

## Target

- Material review must use real file observations.
- Required writes must happen in the sandbox overlay, not the source project.
- When the action gate forces `write_file`, `edit_file`, `terminal`, or browser verification, the model call must inherit the same short deadline at the underlying model spec.
- Forced action rounds should not spend long provider retries before the runtime can recover.
- A timeout must become a structured observation, then the loop should continue with the remaining required action.

## Implementation Steps

1. Propagate round stream policy into the model spec before model invocation.
   - Cap `timeout_seconds` and `long_output_timeout_seconds` to the current round deadline.
   - For action-gated forced rounds, set provider retries to zero for that round.

2. Keep the action gate as the action authority.
   - Do not add keyword permission hacks.
   - Continue to derive permissions from `resource_contract`, `sandbox_policy`, operation gate, and tool preflight.

3. Add regression coverage.
   - Verify `ModelResponseRuntimeExecutor` passes a bounded model spec to the model runtime.
   - Verify professional action-gate recovery observes the shortened model spec.

4. Re-run focused regression tests.

5. Restart the fixed backend on `127.0.0.1:8003` and re-run the real sandbox smoke test against `langchain-mini-clean`.

## Acceptance

- Focused tests pass without faking outputs.
- The real smoke creates `output/vibe-code-smoke/langchain-mini-chat-api-review.md` under `output/sandbox_runs/<workspace-key>/workspace`.
- `D:\AI应用\agent-vibe-sandboxes\langchain-mini-clean` remains clean.

## Follow-up Correction: Verification Evidence and Permission Authority

The real smoke showed the agent successfully read required materials, wrote the sandbox report, and ran a passing terminal command, but the run stayed blocked because the terminal ledger record had `side_effect_kind=verification` and `command_receipt.passed=true` while `satisfies=[]`.

### Design Decision

- `verify_output` action-gate intent is the canonical source that a terminal/browser call is meant to satisfy `verify_command`.
- Terminal keyword matching remains only a secondary recognizer for explicit test commands such as pytest/build/browser checks.
- Plain terminal exploration must not become verification just because it exits with zero.
- Natural-language write markers are intent signals only. Hard write authority belongs to operation dispatch, sandbox policy, and tool permission checks.

### Implementation Steps

1. Add structured `verification_intent` to terminal/browser observations emitted during forced `verify_output`.
2. Make `ToolObservationLedger` accept `verify_command` when a structured envelope carries that intent and the command receipt passes.
3. Add regressions for the exact `Get-Item output/...md` verification shape.
4. Mark boundary/obligation natural-language write bans as intent-level diagnostics, not filesystem permission authority.
5. Re-run focused tests, restart backend on `127.0.0.1:8003`, and re-run the real sandbox smoke.

## Follow-up Correction: Write Permission Authority

The permission audit found a structural drift: natural-language markers such as
`不要改代码` were still converted into hard `forbidden_actions` in the
understanding and obligation layers, even though diagnostics said those markers
were only intent signals. That makes sandboxed coding tasks fragile because
`不要修改源项目，但写入 sandbox 产物` can be misread as a global write ban.

### Design Decision

- Natural-language write-ban markers are diagnostic intent signals only.
- Hard write denial must come from structured authority:
  - `ModelTurnDecision.forbidden_actions`
  - explicit `current_turn_context.forbidden_actions`
  - task/goal structured forbidden actions
  - resource policy, operation gate, sandbox policy, and tool preflight
- Scoped source read-only remains a write-scope constraint, not a global ban.
- The action permit must evaluate model-turn forbidden actions directly, so the
  model-owned understanding remains the authority for read-only turns.

### Implementation Steps

1. Remove keyword-derived write denial from `BoundaryPolicy`; keep marker
   diagnostics and explicit structured forbidden actions.
2. Make `ActionPermit` deny write operations from either boundary policy or
   model-turn structured forbidden actions.
3. Make `ExecutionObligation` derive hard `forbidden_actions` only from
   structured context, while keeping natural-language markers in extraction
   evidence.
4. Update regressions so they prove keyword markers do not silently become
   filesystem permission authority.
5. Re-run focused tests and the sandbox smoke.

## Follow-up Correction: Forced Tool Rounds and Drift Recovery

The sandbox smoke reached `write_output` with only `write_file` visible, but the
real provider still did not complete the write. The runtime must treat a forced
coding-agent round as a provider contract, not only as a prompt preference.

### Design Decision

- The action gate remains the delivery authority for missing read/write/verify
  obligations.
- A forced single-tool round must pass a provider-compatible model spec to the
  gateway. For DeepSeek, that means disabling thinking mode for that round so
  `tool_choice` can be honored.
- The gateway's provider compatibility check must use the effective thinking
  mode, not an empty override that accidentally differs from runtime settings.
- Repeated wrong-tool calls during a forced stage are runtime drift, not useful
  evidence. After policy rejection, the next model turn should be rebuilt from
  a compact stage summary and the current action gate instead of replaying an
  ever-growing context full of stale read attempts.

### Implementation Steps

1. When `action_gate_timeout_applied` and a forced `tool_choice` exist, derive an
   effective model spec that caps timeouts, disables retries, and disables
   DeepSeek thinking for the forced round.
2. Make DeepSeek tool-choice filtering look at the effective spec's thinking
   mode, defaulting empty values to disabled.
3. Add regressions proving forced `write_file` keeps provider-native
   `tool_choice` under an otherwise thinking-enabled runtime.
4. Add a compact action-gate drift recovery message after wrong-tool policy
   rejection, carrying only task, pending obligations, latest evidence summary,
   target path, allowed tools, and the repair instruction.
5. Re-run focused tests and the real sandbox smoke.

## Follow-up Correction: Budget Closeout Verification

The real sandbox smoke showed a mature coding-agent failure mode: the agent read
materials and wrote the sandbox report, but repeated provider errors and wrong
tool attempts consumed the model round budget before the runtime could enter a
normal `verify_output` round.

### Design Decision

- Read, write, and verify are delivery obligations, not ordinary chat turns.
- When all required writes are satisfied and the only remaining obligation is
  verification, budget closeout may run one deterministic sandbox-local
  verification command.
- The deterministic verification must use the same structured terminal
  observation path as action-gate verification, so the ledger remains the single
  source of truth.
- This is not a fake pass: the runtime runs `Test-Path`/`Get-Item` from the
  sandbox workspace and records the real command receipt.

### Implementation Steps

1. Reuse `_auto_verify_output_observation` at the round-budget boundary before
   declaring `professional_task_tool_round_budget_exceeded`.
2. Record the auto verification as a normal `terminal` tool observation with
   `verify_command`, `command_receipt.passed`, and artifact path evidence.
3. Add a regression where the model writes the output, drifts during
   verification, hits the round budget, and still closes as completed only after
   the real auto verification passes.
4. Ensure code-fix evidence closeout includes the material paths it actually
   read, so response-term validation does not fail after ledger evidence is
   complete.

## Follow-up Correction: Policy Rejection Semantics

The final real smoke revealed another important distinction: a policy rejection
can be model-visible as a tool result, but it must not be interpreted as the
requested tool failing. A blocked duplicate `read_file` request is not evidence
that `README.md` could not be read.

### Design Decision

- `tool_policy_rejection` means the runtime blocked a requested tool call before
  execution.
- The observation must explicitly tell the model that no tool side effect
  occurred and that it must not treat the rejection as a file, command, or
  resource failure.
- Actual file read/write/terminal failures remain separate executor/tool
  observations.

### Implementation Steps

1. Add `tool_executed=false`, `is_tool_execution_failure=false`, requested tool
   metadata, and explicit evidence semantics to policy rejection observations.
2. Change the model-visible rejection text to say the request was rejected
   before execution and produced no tool side effect.
3. Add regression coverage proving native tool permission rejection exposes this
   distinction to the model.
4. Re-run focused regressions and a real sandbox smoke against
   `langchain-mini-clean`.

## Current Acceptance Snapshot

- Focused regression suite: `74 passed, 1 warning`.
- Real sandbox smoke:
  - session `vibe_smoke_20260525_114139_semanticverify`
  - workspace `vibe-smoke-langchain-mini-review-20260525_114139-semanticverify`
  - API status `200`
  - professional verification `passed=true`
  - loop terminal reason `completed`
  - terminal observation satisfies `verify_command`
  - terminal `command_receipt.passed=true`
  - sandbox report exists at
    `output/sandbox_runs/vibe-smoke-langchain-mini-review-20260525_114139-semanticverify/workspace/output/vibe-code-smoke/langchain-mini-chat-api-review.md`
  - source project `D:\AI应用\agent-vibe-sandboxes\langchain-mini-clean`
    remains git-clean.
