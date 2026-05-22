# Writing Writer Autonomous Memory Search Plan 2026-05-23

## Goal

Give the chapter writer a real, bounded ability to search the task memory database during generation. This must not become workspace file search, web search, or manual artifact leakage. The writer should be able to query approved writing memory by repository and collection, then cite the retrieved memory in its prewrite sourcing record before drafting.

## Problems Found

- The current writing graph already supplies `memory_snapshot` and `dynamic_memory_read_policy`, but the writer mainly receives a runtime-expanded memory pack before execution.
- `op.memory_read` exists as an operation permission, but there is no model-visible local tool that lets a task graph writer query the writing memory database by intent while it is running.
- The writing worker profile allows `op.memory_read`, yet metadata still frames memory side effects as fully orchestration-owned, which makes sense for commits but is too restrictive for read-only retrieval.
- The chapter writer prompt asks for a prewrite sourcing judgment, but that is not enough unless the runtime exposes an actual retrieval surface.

## Target Design

1. Add a read-only `memory_search` tool.
   - Operation: `op.memory_read`.
   - Inputs: `query`, `repositories`, `collections`, `limit`, `task_run_id`, `graph_id`.
   - Output: compact JSON text with matched memory refs, repository, collection, title, summary, canonical text preview, artifact refs and diagnostics.
   - Boundary: reads only formal task memory records; no filesystem traversal, no shell, no web.

2. Make memory search graph-configurable.
   - Nodes declare `tool_execution_policy` in runtime bindings.
   - `chapter_draft` exposes only `memory_search`.
   - Tool calls are capped for long writing tasks.
   - Dynamic memory read policy explicitly sets `allow_dynamic_read`.

3. Configure writing worker long-task profile.
   - Keep side-effect tools blocked.
   - Keep artifact creation owned by orchestration runtime.
   - Allow read-only memory search as an agent-side capability.
   - Increase output timeout and enable model thinking mode where supported.

4. Strengthen prompts without making them runtime instructions.
   - The writer is told to search memory when the provided pack is insufficient.
   - It must record what it searched and which returned memory refs informed the batch.
   - It must not treat unretrieved guesses as canon.

## Implementation Checklist

- Add `MemorySearchTool`.
- Register `memory_search` in tool definitions under `op.memory_read`.
- Add operation descriptor alias/metadata for database memory search.
- Add writing graph runtime tool policy for `chapter_draft`.
- Enable dynamic read in writing graph policy.
- Update writing worker profile configuration for long task + thinking mode.
- Add regression tests for tool registration, graph config, and profile permissions.
- Run focused tests and py_compile.
