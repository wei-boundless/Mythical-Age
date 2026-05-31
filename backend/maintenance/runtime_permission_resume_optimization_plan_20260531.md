# Runtime Permission and Resume Optimization Plan - 2026-05-31

## Scope

This plan covers four runtime hardening changes found during the follow-up review:

1. Approval risk fingerprints for write/edit operations are under-bound.
2. Completed checkpoints can override new side-effect obligations.
3. Model streaming assumes stream support instead of degrading explicitly.
4. Tool preflight allows unresolved/unavailable tools to proceed to authorization.

The implementation touches runtime permission, resume, model response, and tool execution paths. It must be implemented as one coherent upgrade after review approval, not as isolated patches.

## Target Authority Chain

```text
Current obligation / model tool request
-> Runtime normalization
-> ActionPermit / OperationGate
-> Runtime execution
-> Recovery / resume decision
-> User-visible result
```

Authority ownership:

- `runtime.shared.approval_fingerprint`: normalizes the risk identity of a proposed side effect.
- `permissions.operation_gate`: decides whether an approval token matches the exact current risk identity.
- `runtime.shared.resume_decision`: decides whether an old checkpoint can be reused or whether current obligations require new execution.
- `runtime.model_gateway.model_response`: selects the available model invocation mode without inventing a hidden fallback after partial output.
- `runtime.tool_runtime.tool_executor`: proves a requested tool is executable before authorization proceeds.
- `runtime.tooling.supervisor`: treats preflight failures as repair/deny decisions before OperationGate.

## Planned Changes

### 1. Bind Approval Fingerprints to Content Hashes

Files:

- `backend/runtime/shared/approval_fingerprint.py`
- `backend/tests/capability_system_preview_regression.py` or a new focused approval fingerprint regression test

Change:

- Replace content length-only risk fields with stable hashes:
  - `content_sha256`
  - `old_text_sha256`
  - `new_text_sha256`
- Keep length fields only as diagnostics if useful, not as the authority-bearing identity.
- Add tests proving same path + same length + different content produces different fingerprints.
- Add tests proving `edit_file` old/new text differences also change the fingerprint.

Deletion/cleanup:

- Do not keep a compatibility branch that accepts old length-only fingerprints for new approvals.
- Existing stored approval tokens with old fingerprints may no longer match. This is acceptable because approvals are for side effects and should fail closed when the risk identity format changes.

### 2. Make Resume Decisions Honor New Side-Effect Obligations

Files:

- `backend/runtime/shared/resume_decision.py`
- `backend/tests/professional_run_resume_regression.py`
- `backend/tests/agent_runtime_professional_foundation_regression.py` if needed

Change:

- Move `_obligation_requires_new_side_effect()` before the completed-checkpoint reuse branch, while preserving explicit `restart` and human gate precedence.
- A completed checkpoint with empty current obligations still returns `reuse_completed`.
- A completed checkpoint with `required_writes` or `required_commands` returns `continue` with reason `current_obligation_requires_unsatisfied_side_effects`.

Deletion/cleanup:

- Do not add a separate completed-with-obligation compatibility decision.
- Keep the existing reason string for the side-effect path so traces remain easy to compare.

### 3. Add Explicit Non-Stream Fallback When Stream Support Is Missing

Files:

- `backend/runtime/model_gateway/model_response.py`
- `backend/tests/model_response_runtime_regression.py`

Change:

- Before the plain streaming branch, check whether `model_runtime.astream_messages` is callable.
- If streaming is enabled but the runtime has no stream method, use the normal non-stream `invoke_messages` path.
- Emit no fake stream recovery event; this is capability degradation before a stream starts, not recovery after a stream failure.
- Preserve existing partial-output timeout behavior and stream recovery behavior.

Deletion/cleanup:

- Remove the implicit AttributeError path as a behavior source.
- Do not silently retry after partial output; the existing partial-output guard remains.

### 4. Make Tool Preflight Fail Closed for Unresolved Tools

Files:

- `backend/runtime/tool_runtime/tool_executor.py`
- `backend/runtime/tooling/supervisor.py` if the current repair path needs clearer diagnostics
- `backend/tests/sandbox_tool_runtime_regression.py`
- `backend/tests/tool_supervisor_regression.py`

Change:

- `preflight_validate()` should return `allowed=False` for:
  - missing tool definition
  - missing runtime tool instance when no native tool or adapter can be built
- The returned observation/diagnostics should be model-repair visible and clearly state:
  - `tool_not_available`
  - `tool_runtime_unavailable`
  - the requested `tool_name`
- `ToolSupervisor` should keep treating `allowed=False` preflight as a repair decision before OperationGate.
- Add tests proving authorization is not requested for unknown or unavailable tools.

Deletion/cleanup:

- Remove fail-open preflight returns for unresolved tools.
- Do not add an execution-time compatibility fallback that converts unavailable tools into generic execution failures after approval.

## Verification Plan

Focused tests:

```powershell
python -m pytest backend/tests/capability_system_preview_regression.py backend/tests/professional_run_resume_regression.py backend/tests/model_response_runtime_regression.py backend/tests/sandbox_tool_runtime_regression.py backend/tests/tool_supervisor_regression.py -q
```

Runtime-adjacent regression tests:

```powershell
python -m pytest backend/tests/agent_runtime_professional_foundation_regression.py backend/tests/file_gateway_regression.py backend/tests/file_operation_receipt_regression.py backend/tests/formal_memory_run_scope_regression.py -q
```

Static checks:

```powershell
rg -n "content_chars|old_text_chars|new_text_chars|return \\{\"allowed\": True\\}" backend/runtime backend/permissions backend/tests
git diff --check
```

Expected outcomes:

- Write/edit approval fingerprints differ when content differs.
- Completed checkpoints are reused only when the current turn has no new side-effect obligation.
- Stream-enabled non-stream runtimes still produce a normal model response.
- Unknown/unavailable tools are blocked before OperationGate approval.
- No old fail-open approval or tool execution branch remains in the modified paths.

## Risks

- Existing approval tokens created before the fingerprint change should fail to match. This is safer than accepting stale approvals for side effects.
- Moving obligation precedence can cause more completed tasks to continue execution when the current turn explicitly requires writes or commands. That is intended; empty-obligation status checks still reuse completed checkpoints.
- Tool preflight fail-closed may expose previously hidden assembly bugs. These should be fixed at assembly/capability-table level rather than masked in the executor.

