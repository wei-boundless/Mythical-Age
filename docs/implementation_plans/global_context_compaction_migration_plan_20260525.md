# Global Context Compaction Migration Plan (2026-05-25)

## Goal

Move from Search-only result budgeting to a reusable global context compaction layer.

The target is Claude Code style context hygiene:

```text
large tool/child output
  -> persisted raw artifact
  -> model-visible preview
  -> evidence/summary first
  -> compact parent observation
  -> later RuntimeContextManager can compact old history before model calls
```

## Current Facts

- DeepSearch already has search-local result persistence and previews.
- `AgentEvidencePacket.visible_summary()` already provides model-safe evidence summaries.
- `AgentDelegationExecutor.build_parent_observation()` currently returns `summary` and `answer_candidate` directly.
- `RuntimeContextManager.prepare_model_context()` assembles model messages, but has no compaction stage.

## Implementation Scope

### Phase 1: Shared Context Management Package

Add:

```text
backend/runtime/context_management/__init__.py
backend/runtime/context_management/budget.py
backend/runtime/context_management/tool_result_storage.py
backend/runtime/context_management/child_result_compaction.py
```

Responsibilities:

- Estimate JSON/text size consistently.
- Persist large result fields under `storage/runtime_context/tool-results`.
- Replace oversized fields with `<persisted-output>` previews.
- Build compact child-agent observations from evidence packets, summaries, limitations, and refs.

### Phase 2: Reuse From DeepSearch

Make `backend/runtime/search_agent_runtime/result_storage.py` a compatibility wrapper around the shared storage implementation.

No duplicate old logic should remain.

### Phase 3: Parent Observation Boundary

Modify `AgentDelegationExecutor.build_parent_observation()`:

- Preserve exact `summary`, refs, confidence, limitations.
- Replace oversized `answer_candidate` with a compact observation summary.
- Include `context_compaction` diagnostics with replacement refs.
- Prefer `visible_packet_summary` / `agent_evidence_packet.visible_summary` as model-visible content.

### Phase 4: Tests

Add regression coverage:

- Large child answer is persisted and previewed.
- Evidence packet summary is preserved in parent observation.
- Existing shadow readiness behavior remains unchanged.
- DeepSearch storage compatibility remains intact.

## Out of Scope For This Pass

- Full history autocompact before every model call.
- Long-term memory summarization.
- UI controls for compaction policy.

Those will build on this shared package after the output boundary is stable.

