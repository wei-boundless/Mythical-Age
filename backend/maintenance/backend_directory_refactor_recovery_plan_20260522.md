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

Status: completed in this recovery pass.

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
- `rg "from structured_memory|import structured_memory" backend` returns no production/test code hits.
- `python -m compileall -q backend/memory_system backend/context_system backend/bootstrap backend/capability_system backend/tests` passes.
- Focused memory/context tests pass.

## Slice 2: Centralize Memory Service Construction

Status: completed for working/formal/task durable runtime services in this recovery pass.

Target:

- Add one construction/provider boundary for working memory, formal memory, task durable memory, and session memory.
- Runtime modules must not each resolve memory roots and construct memory services independently.
- API modules must not instantiate memory stores directly when a facade/provider is available.

Completion criteria:

- Direct production construction of `WorkingMemoryService` and `FormalMemoryService` outside the provider/facade is removed or explicitly justified.
- `MemoryFacade` or a dedicated `MemoryRuntimeServices` object becomes the single owner of memory service construction.
- Existing runtime and memory tests pass.

## Slice 3: Classify Root Runtime/Data Directories

Status: completed for backend-root runtime/data directories in this recovery pass.

Target:

- Source packages and runtime data must not be mixed conceptually.
- Root-level data residues under `backend/` must be either migrated to `storage/` or documented as generated runtime output pending cleanup.

Completion criteria:

- `working_memory/` and `formal_memory/` under `backend/` are not treated as source package branches.
- Runtime data roots have a single canonical path through `ProjectLayout`.
- No code writes new memory data directly under backend root unless a migration fallback explicitly requires it.

Additional completed items:

- `knowledge/` was migrated from `backend/knowledge` to project-root `storage/knowledge`.
- Retrieval collection configuration and PDF catalog lookup now use `ProjectLayout.knowledge_storage_dir`.
- `soul.activity_service` now reads runtime events and state index records through `ProjectLayout.runtime_state_dir`.
- Empty legacy root shells `capabilities/`, `operations/`, and `executions/` were removed after import checks.
- `memory_layout.py` was moved under `memory_system/layout.py`.
- `ProjectLayout.from_runtime_root()` now resolves `storage/runtime_state` back to the project layout instead of misclassifying it as a backend directory.
- `TaskRunLoop` now uses `ProjectLayout.from_runtime_root()` when no explicit backend directory is supplied.
- PDF OCR cache and local trace path helpers now resolve through `ProjectLayout` instead of hand-writing `../storage` or backend-relative output paths.
- Historical backend-root runtime/data directories were archived under `storage/legacy_backend_root_20260522_runtime_data/` with `archive_manifest.json`.

Remaining:

- `backend/api-server.log` remains under the backend root because it is held by an active writer. It was copied into the archive, but the live source file could not be removed safely while the process owns it.
- `__pycache__/` and `.pytest_cache/` are generated cache directories, not architecture surfaces.

## Slice 4: Agent System Cutover

Status: completed in this recovery pass.

Target:

- Create `agent_system` as the owner of agent identity, registry, runtime profiles, groups, assembly, and worker blueprints.
- Shrink `orchestration` to control-plane primitives only.

Implemented structure:

```text
backend/agent_system/
  identity.py
  assembly/
    runtime_bundle_builder.py
    runtime_chain.py
    runtime_spec_models.py
  groups/
    models.py
    registry.py
  models/
    agent_models.py
    model_profile_models.py
    model_profile_resolver.py
  profiles/
    body_models.py
    body_registry.py
    runtime_profile_models.py
    runtime_profile_registry.py
  registry/
    agent_registry.py
    worker_agent_blueprints.py
    worker_agent_factory.py
```

Completion criteria:

- New production imports use `agent_system.*` for agent concepts: completed.
- `orchestration` no longer contains agent registry/profile/assembly business logic: completed.
- Root `orchestration.__init__` no longer re-exports agent-system objects: completed.
- Deleted old source modules under `backend/orchestration/agent_*`, `body_*`, `assembly_*`, `worker_*`, and `model_profile_*`: completed.
- Validation passed:
  - `python -m compileall -q backend/agent_system backend/orchestration backend/runtime backend/task_system backend/api backend/query backend/health_system backend/bootstrap backend/tests`
  - `python -m pytest backend/tests/orchestration_agent_management_regression.py backend/tests/orchestration_runtime_spec_regression.py backend/tests/orchestration_model_profile_regression.py backend/tests/orchestration_cutover_regression.py backend/tests/runtime_assembly_builder_test.py backend/tests/agent_delegation_permission_regression.py backend/tests/memory_runtime_route_regression.py backend/tests/query_runtime_runtime_loop_regression.py backend/tests/langgraph_coordination_runtime_regression.py`

Notes:

- Existing serialized `authority` strings such as `orchestration.agent_runtime_spec` were intentionally left unchanged because they are protocol identifiers, not Python package paths. Renaming those should be a separate protocol migration with storage compatibility handling.
- `QueryRuntime` permission-mode wiring was corrected during validation: it now resolves through `permission_service.current_mode()` first, then `settings_service.get_permission_mode()`, then `default`.

## Slice 5: Final Backend Root Audit

Target:

- Every backend root directory is classified as canonical source, runtime data, temporary shim, or obsolete residue.

Completion criteria:

- The audit table is updated.
- Obsolete directories are removed.
- Compile and targeted regression tests pass.

Current status:

- Source-package residue is reduced.
- Backend-root runtime/data directories have been archived to `storage/legacy_backend_root_20260522_runtime_data/`.
- The only backend-root runtime residue observed after this pass is `api-server.log`, retained because it is actively written.
- Validation is still required before declaring this recovery pass closed.

