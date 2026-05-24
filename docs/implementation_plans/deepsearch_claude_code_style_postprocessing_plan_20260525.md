# DeepSearch Claude Code Style Postprocessing Plan (2026-05-25)

## Goal

Port the mature Claude Code style search/tool-result postprocessing pattern into the Python DeepSearch runtime.

The target design is not a one-off cleaner. It is a layered runtime path:

```text
search/fetch results
  -> clean and normalize readable text
  -> distill model-visible evidence
  -> persist oversized raw tool output
  -> replace large payload fields with previews and file refs
  -> build AgentEvidencePacket from distilled evidence
  -> return budgeted diagnostics to the main agent
```

## Source Reference

The implementation follows these Claude Code source-level ideas:

- `tools/WebFetchTool/WebFetchTool.ts`: fetch content, markdown-clean it, and apply a prompt/model step when raw content is not suitable.
- `tools/WebSearchTool/WebSearchTool.ts`: web search returns model text plus structured links, then maps them into a tool result block.
- `utils/toolResultStorage.ts`: persist large tool results, keep a preview, and apply result budget before model context.
- `query.ts`: apply tool-result budget before microcompact/autocompact and generate tool-use summaries after tool batches.

## Implementation Scope

### 1. Tool Result Storage

Add `backend/runtime/search_agent_runtime/result_storage.py`.

Responsibilities:

- Persist large text fields under `storage/search_agent_runtime/tool-results`.
- Return a compact preview with a persisted-output marker.
- Preserve metadata: path, original byte size, preview byte size, payload location.
- Apply a total payload budget to search/fetch result fields before diagnostics are returned to the main agent.

### 2. Evidence Distiller

Add `backend/runtime/search_agent_runtime/distiller.py`.

Responsibilities:

- Provide an agent-facing Chinese role prompt for future LLM distillation.
- Provide a deterministic default distiller so DeepSearch remains real and testable without fake model output.
- Produce structured claims with source URL, source type, confidence, excerpt, and artifact refs.
- Allow tests and future model gateway wiring to inject a stronger distiller.

### 3. Runtime Wiring

Modify `SearchAgentRuntime`:

- Distill evidence before payload budget replacement.
- Persist and preview large result fields after distillation.
- Attach `content_replacements`, `distillation`, and `artifact_refs` into diagnostics.
- Build `AgentEvidencePacket` from distilled claims first, falling back to ranked snippets.

### 4. Evidence Packet

Modify `evidence_builder.py`:

- Prefer `web_payload.deepsearch.distilled_claims`.
- Add artifact refs into evidence locators.
- Keep source ranking and confidence rules.
- Do not expose raw large HTML/text as model-visible evidence.

### 5. Verification

Add regression tests:

- Large fetched content is persisted and replaced by preview.
- Distilled evidence still appears in facts.
- Artifact refs are exposed in diagnostics and evidence locator.
- Existing DeepSearch behavior remains intact.

