# Backend Root Directory Inventory - 2026-05-22

## Purpose

This inventory prevents the backend directory refactor from being reported as complete while root-level residue still exists.

## Canonical Source Packages

- `api/`
- `agent_system/`
- `artifact_system/`
- `bootstrap/`
- `capability_system/`
- `context_system/`
- `continuation/`
- `evidence/`
- `health_system/`
- `intent/`
- `knowledge_system/`
- `memory_system/`
- `observability/`
- `permissions/`
- `prompting/`
- `query/`
- `response_system/`
- `runtime/`
- `sessions/`
- `soul/`
- `task_system/`
- `understanding/`

## Canonical Runtime/Data Root

- `../storage/`

New runtime and memory writes should resolve through `ProjectLayout`, not by creating directories directly under `backend/`.

`knowledge/` has been moved out of `backend/` and is now stored at `../storage/knowledge/`.

## Runtime/Data Residue Still Present Under Backend Root

No backend-root runtime/data directories remain after the archive pass.

Archived directories:

- `.tmp/`
- `artifact_repository/`
- `checkpoints/`
- `coordination_checkpoints/`
- `events/`
- `formal_memory/`
- `output/`
- `runtime_objects/`
- `runtime_state/`
- `runtime_views/`
- `state_index/`
- `storage/`
- `timeline_ledgers/`
- `working_memory/`

Archive location:

- `../storage/legacy_backend_root_20260522_runtime_data/`
- Manifest: `../storage/legacy_backend_root_20260522_runtime_data/archive_manifest.json`

Residual live generated file:

- `api-server.log` remains in `backend/` because an active writer holds the file. It has been copied into the archive, but the live file was retained rather than force-deleted.

Current handling:

- New memory service construction is centralized through `memory_system.runtime_services.MemoryRuntimeServices`.
- New background task writes now use `ProjectLayout.runtime_state_dir`, i.e. `storage/runtime_state/background_tasks`.
- Soul activity reads runtime traces and state from `ProjectLayout.runtime_state_dir` instead of `backend/events` or `backend/state_index`.
- `TaskRunLoop` resolves backend ownership through `ProjectLayout.from_runtime_root()` when constructed from a runtime root.
- PDF OCR cache and local trace roots now resolve through `ProjectLayout` instead of manually building backend-relative storage/output paths.

Cleanup rule:

- No new code should introduce a fresh backend-root runtime/data path.
- If `api-server.log` is no longer actively written, move or delete it with the rest of generated logs.

## Temporary Or Legacy Source Packages Still Requiring Cutover

- `orchestration/`: active control-plane package. Agent registry/profile/assembly code has been moved out; remaining work is API thinning and deciding whether resource/commit/control primitives stay under this package or get narrower owners.
- `maintenance/`: plan/audit location. It can remain as maintenance artifacts, but it is not runtime architecture.
- `scripts/`: operational scripts. It can remain if scripts are current.

## Removed Or Migrated In Current Recovery Work

- `agents/` moved into `agent_system/a2a/`, then the root package was deleted.
- `capabilities/`, `operations/`, and `executions/` were empty legacy shells with no imports and were deleted.
- `knowledge/` was moved to `../storage/knowledge/`; retrieval and PDF catalog code now read through `ProjectLayout.knowledge_storage_dir`.
- `memory_layout.py` moved to `memory_system/layout.py`.

## Completed In Current Recovery Work

- `structured_memory/` was folded into `memory_system/storage/`.
- Production and test imports were changed from `structured_memory` to `memory_system.storage`.
- Runtime-facing memory service construction was centralized in `memory_system.runtime_services.MemoryRuntimeServices`.
- Runtime and API direct construction of working/formal memory services was removed.
- Background task runtime state writes now go through `ProjectLayout.runtime_state_dir`.
- `agent_system/` now owns agent identity, registry, groups, runtime profiles, body profiles, runtime assembly, runtime chain, worker blueprints, and A2A adapter/model helpers.
- `orchestration/__init__.py` no longer re-exports agent-system objects.
- Legacy root source/data surfaces removed or migrated: `agents/`, `capabilities/`, `executions/`, `operations/`, `knowledge/`, and `memory_layout.py`.
- Historical backend-root runtime/data directories archived to `../storage/legacy_backend_root_20260522_runtime_data/`.
- Six backend-root server logs were moved into the archive; `api-server.log` was copied but retained because it is still active.

## Remaining High-Priority Cutover

1. Thin `api/orchestration.py` into route modules and service calls.
2. Finish validation for the backend-root archive pass.
3. Remove or relocate `api-server.log` after the active writer stops.
4. Continue shrinking `orchestration/` control-plane/API surfaces.
