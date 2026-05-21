# Backend Root Directory Inventory - 2026-05-22

## Purpose

This inventory prevents the backend directory refactor from being reported as complete while root-level residue still exists.

## Canonical Source Packages

- `api/`
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

## Runtime/Data Residue Still Present Under Backend Root

These directories are not source packages and should not be treated as architecture branches:

- `artifact_repository/`
- `checkpoints/`
- `coordination_checkpoints/`
- `events/`
- `formal_memory/`
- `runtime_objects/`
- `runtime_state/`
- `runtime_views/`
- `state_index/`
- `timeline_ledgers/`
- `working_memory/`

Current handling:

- New memory service construction is centralized through `memory_system.runtime_services.MemoryRuntimeServices`.
- New background task writes now use `ProjectLayout.runtime_state_dir`, i.e. `storage/runtime_state/background_tasks`.
- Existing root-level runtime data has not been deleted in this slice because it may contain historical task traces, checkpoint state, and memory databases.

Cleanup rule:

- Delete or archive only after confirming the canonical `storage/` location contains the needed data or the data is disposable generated output.
- No new code should introduce a fresh backend-root runtime/data path.

## Temporary Or Legacy Source Packages Still Requiring Cutover

- `orchestration/`: still active and too large. It should be reduced to control-plane primitives or replaced by `agent_system`.
- `agents/`: legacy agent helper package. It must be absorbed into the future `agent_system` or deleted after import cutover.
- `capabilities/`: empty/legacy shell. It can be removed if no import path depends on it.
- `executions/`: empty/legacy shell. It can be removed if no import path depends on it.
- `knowledge/`: legacy or alternate knowledge surface. It requires comparison with `knowledge_system`.
- `maintenance/`: plan/audit location. It can remain as maintenance artifacts, but it is not runtime architecture.
- `operations/`: empty/legacy shell. It can be removed if no import path depends on it.
- `output/`: generated artifacts, not source architecture.
- `scripts/`: operational scripts. It can remain if scripts are current.
- `storage/`: should not be a source package under backend; canonical storage is project-root `storage/`.

## Completed In Current Recovery Work

- `structured_memory/` was folded into `memory_system/storage/`.
- Production and test imports were changed from `structured_memory` to `memory_system.storage`.
- Runtime-facing memory service construction was centralized in `memory_system.runtime_services.MemoryRuntimeServices`.
- Runtime and API direct construction of working/formal memory services was removed.
- Background task runtime state writes now go through `ProjectLayout.runtime_state_dir`.

## Remaining High-Priority Cutover

1. Create `agent_system/` and move agent registry/profile/assembly code out of `orchestration/`.
2. Thin `api/orchestration.py` into route modules and service calls.
3. Classify and archive/delete root-level runtime data directories after a storage migration check.
4. Remove empty legacy shells after import checks.
