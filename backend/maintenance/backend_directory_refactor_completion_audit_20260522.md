# Backend Directory Refactor Completion Audit - 2026-05-22

## Conclusion

The backend directory refactor was reported too broadly as completed. That report was inaccurate.

The current workspace shows that only part of the planned ownership migration landed. The task system and runtime packages were moved significantly, but the plan was not completed because several planned cleanup and ownership-cutover items remain active at the backend root.

## Evidence

The original plan lists these directories as targets to fold, migrate, or delete:

- `orchestration/`
- `agents/`
- `runtime_objects/`
- `runtime_state/`
- `runtime_views/`
- `executions/`
- `events/`
- `checkpoints/`
- `coordination_checkpoints/`
- `state_index/`
- `timeline_ledgers/`
- `working_memory/`
- `formal_memory/`

The current backend root still exposes multiple planned cleanup targets, including:

- `agents/`
- `orchestration/`
- `runtime_objects/`
- `runtime_state/`
- `runtime_views/`
- `events/`
- `checkpoints/`
- `coordination_checkpoints/`
- `state_index/`
- `timeline_ledgers/`
- `working_memory/`
- `formal_memory/`
- `structured_memory/`

The memory system is especially incomplete. It currently has three source-level ownership surfaces:

- `backend/memory_system/`
- `backend/structured_memory/`
- `backend/runtime/memory/`

It also has old runtime data directories still visible under `backend/`:

- `backend/working_memory/`
- `backend/formal_memory/`

## What Actually Landed

- `backend/task_system/` exists and contains task definitions, graph models, compiler, registry, planning, services, and contracts.
- `backend/runtime/` exists and contains unit runtime, graph runtime, coordination runtime, professional runtime, execution, contracts, shared, tool runtime, model gateway, and runtime memory.
- The old `backend/tasks/` package is no longer present in the current backend root.
- The old `orchestration/runtime_loop/` tree is no longer present.

## What Did Not Land

- `agent_system/` was not created as the planned owner for agent definitions, runtime profiles, registries, groups, and assembly.
- Many live production imports still point directly at `orchestration.*`.
- `orchestration/` remains a large active package, not a temporary compatibility layer.
- `structured_memory/` remains a live implementation package instead of being folded under `memory_system`.
- `memory_system` does not yet own all memory construction paths. Some runtime modules still instantiate memory services directly.
- The API layer still contains broad memory endpoints that construct memory-related services directly.
- Runtime data directories still leak into `backend/` instead of being fully normalized under project storage.

## Root Cause Of The Bad Completion Claim

The implementation confused package movement with ownership cutover.

Moving many files into `task_system/` and `runtime/` was real progress, but it was not the same as completing the full plan. The plan explicitly required cleanup of residual directories and removal of obsolete compatibility paths. Those completion criteria were not satisfied.

## Corrected Status

The backend directory refactor is partially complete.

Completed:

- Task system package creation and substantial migration.
- Runtime package creation and substantial migration.
- Removal of the old `tasks/` root package.
- Removal of the old `orchestration/runtime_loop/` subtree.

Incomplete:

- Agent system cutover.
- Orchestration shrink or deletion.
- Memory system consolidation.
- Root runtime artifact cleanup.
- API thinning for runtime, task, and memory control surfaces.
- Compatibility import removal.

## Required Correction Plan

1. Freeze completion claims until each planned directory has an explicit pass/fail status.
2. Build a backend root ownership checklist that treats every root directory as either:
   - canonical source package,
   - storage/runtime data,
   - temporary compatibility shim,
   - obsolete residue to delete.
3. Finish memory consolidation first because it currently has the clearest ownership split:
   - fold `structured_memory` into `memory_system/storage` or `memory_system/legacy_storage`,
   - centralize memory service creation,
   - move direct runtime memory service construction behind a provider,
   - split memory API by bounded route modules,
   - relocate old root data directories or mark them as archived runtime data.
4. Then finish `agent_system` cutover from `orchestration`.
5. Finally shrink `orchestration` to a small control-plane package or delete it if no longer justified.

## Audit Rule Going Forward

A refactor phase is not complete until:

- the target source package exists,
- production imports use the target package,
- old source paths contain no business logic,
- obsolete shims are deleted,
- root-level residue is either removed or explicitly classified as storage,
- compile and targeted regression tests pass.

