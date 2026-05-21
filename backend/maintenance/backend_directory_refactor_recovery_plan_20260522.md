# Backend Directory Refactor Recovery Plan - 2026-05-22

## Scope

This plan corrects the incomplete backend directory refactor. It is execution-oriented and must be validated against the actual source tree, not old documentation.

## Current Recovery Slice

Finish memory-system consolidation first.

Reason:

- The backend root exposed `memory_system`, `structured_memory`, and `runtime/memory` as three memory-related code surfaces.
- `structured_memory` was an implementation/storage layer, not an independent top-level system.
- Memory service ownership is still split across facade, runtime, and API.

## Slice 1: Fold Structured Memory Under Memory System

Target structure:

```text
backend/memory_system/
  storage/
    consolidation.py
    consolidation_scheduler.py
    exact_lookup.py
    flow_snapshots.py
    frontmatter.py
    memory_manager.py
    models.py
    process_engine.py
    process_state.py
    session_memory.py
    session_memory_view.py
    session_processor.py
    text_utils.py
    turn_understanding.py
    understanding_reconciliation.py
```

Rules:

- No production import may use `structured_memory`.
- Do not keep a root-level `structured_memory` compatibility package.
- Tests should import the new owner path.
- Runtime trace/index code may stay under `runtime/memory`; it is runtime ledger/state infrastructure, not durable memory storage.

Completion criteria:

- `backend/structured_memory/` no longer exists.
- `rg "from structured_memory|import memory_system.storage" backend` returns no production/test code hits.
- `python -m compileall -q backend/memory_system backend/context_system backend/bootstrap backend/capability_system backend/tests` passes.
- Focused memory/context tests pass.

## Slice 2: Centralize Memory Service Construction

Target:

- Add one construction/provider boundary for working memory, formal memory, task durable memory, and session memory.
- Runtime modules must not each resolve memory roots and construct memory services independently.
- API modules must not instantiate memory stores directly when a facade/provider is available.

Completion criteria:

- Direct production construction of `WorkingMemoryService` and `FormalMemoryService` outside the provider/facade is removed or explicitly justified.
- `MemoryFacade` or a dedicated `MemoryRuntimeServices` object becomes the single owner of memory service construction.
- Existing runtime and memory tests pass.

## Slice 3: Classify Root Runtime/Data Directories

Target:

- Source packages and runtime data must not be mixed conceptually.
- Root-level data residues under `backend/` must be either migrated to `storage/` or documented as generated runtime output pending cleanup.

Completion criteria:

- `working_memory/` and `formal_memory/` under `backend/` are not treated as source package branches.
- Runtime data roots have a single canonical path through `ProjectLayout`.
- No code writes new memory data directly under backend root unless a migration fallback explicitly requires it.

## Slice 4: Agent System Cutover

Target:

- Create `agent_system` as the owner of agent identity, registry, runtime profiles, groups, assembly, and worker blueprints.
- Shrink `orchestration` to control-plane primitives only, or delete it if it no longer owns live behavior.

Completion criteria:

- New production imports use `agent_system.*` for agent concepts.
- `orchestration` no longer contains agent registry/profile/assembly business logic.
- Compatibility shims, if any, contain no business logic and are deleted after import cutover.

## Slice 5: Final Backend Root Audit

Target:

- Every backend root directory is classified as canonical source, runtime data, temporary shim, or obsolete residue.

Completion criteria:

- The audit table is updated.
- Obsolete directories are removed.
- Compile and targeted regression tests pass.

