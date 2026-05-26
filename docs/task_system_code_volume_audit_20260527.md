# Task System Code Volume Audit - 2026-05-27

## Scope

Reviewed code under:

- `backend/task_system`
- `backend/runtime/graph_runtime`
- `backend/runtime/graph_task_runtime`
- `frontend/src/components/workspace/views/task-system`

This report explains why the task system code is large and which parts are legitimate complexity versus removable structural weight.

## Size Snapshot

| Area | Files | Lines |
| --- | ---: | ---: |
| frontend task-system workbench | 88 | 20,411 |
| backend task_system registry | 6 | 3,764 |
| backend runtime graph_runtime | 6 | 3,404 |
| backend task_system storage JSON | 2 | 2,508 |
| backend task_system graphs | 5 | 2,352 |
| backend task_system services | 7 | 2,291 |
| backend task_system runtime_semantics | 7 | 2,121 |
| backend task_system compiler | 4 | 2,090 |
| backend task_system planning | 7 | 1,832 |
| backend task_system orders | 9 | 1,393 |
| backend task_system contracts | 8 | 1,381 |
| backend task_system tasks | 8 | 1,141 |
| other task-system areas | 15 | 1,977 |

Total in this scope: about 47,151 lines across 176 files.

Important: the front-end editor is the single largest cost center. It is not just a visual page; it contains graph editing, compiled view inspection, memory/resource modeling, publish/run control, preflight repair, and library screens.

## Why It Is So Large

### 1. The system is doing too many product jobs under one name

`task_system` currently means all of these at once:

- task/domain/contract registries
- task graph canonical model
- graph compiler
- layered graph normalizer
- runtime semantics diagnostics
- graph scheduler and batch runtime
- task order and continuation recovery
- assembly/binding services
- graph editor frontend
- graph library frontend
- writing-specific task graph templates and storage

Some of this size is legitimate. A mature agent task graph system needs graph definitions, contracts, runtime specs, scheduling, monitoring, and editor surfaces.

The problem is that these layers are still coupled through shared metadata fields and repeated repair/preflight logic, so each new concern spreads across many files.

### 2. The frontend workbench carries too much authority

The frontend task-system folder is about 20.4k lines. Largest files include:

- `TaskGraphMemoryArtifactPage.tsx` - 1,314 lines
- `taskGraphTemplates.ts` - 994 lines
- `taskGraphPreflight.ts` - 768 lines
- `TaskGraphPublishRunPage.tsx` - 658 lines
- `TaskGraphTimelinePage.tsx` - 601 lines
- `TaskGraphWorkbench.tsx` - 583 lines

The workbench is not only presenting data. It also:

- derives memory models
- repairs graph issues
- builds preflight reports
- maps selected/focused objects
- manages publish and runtime package behavior
- exposes migration diagnostics
- edits multiple hierarchy levels

That is why the UI code volume feels unusually high. It is partly a console, partly a compiler explainer, partly a migration tool, and partly a runtime control panel.

### 3. There are multiple graph representations still alive

The active target representation is canonical `nodes` and `edges`.

But the code still contains or reads these parallel representations:

- `metadata.timeline_blocks`
- `metadata.composable_graph`
- `projection_overlay_id`
- legacy prompt migration metadata
- edge metadata used as semantic payload
- compiled standard view `units`, `interfaces`, `port_edges`
- runtime spec nodes/edges
- memory matrix/protocol views

Measured references in scope:

- `timeline_blocks`: 29
- `projection_overlay_id`: 19
- `legacy_`: 106
- `metadata.`: 428
- `contract_bindings`: 202
- `graph_module_runtime`: 121
- `preflight`: 258
- `repair`: 146

Not all are bad. But the high count shows the system is still paying a migration tax. Every compatibility representation creates more editor code, more diagnostics, and more tests.

### 4. Registry and storage code is large because it is doing persistence, migration, and model hydration together

`backend/task_system/registry/flow_registry.py` is 2,653 lines. It likely owns too many responsibilities:

- reading/writing JSON stores
- hydrating task records
- graph registry operations
- workflow registry wiring
- update/delete APIs
- storage compatibility

This file is a structural hotspot. It is large because persistence authority and domain authority are mixed.

Target shape should separate:

- storage adapter
- graph repository
- task repository
- workflow repository
- migration/import utilities
- service-facing registry facade

### 5. Compiler, normalizer, standard view, and runtime semantics overlap

Backend graph compilation is spread across:

- `compiler/coordination_graph_compiler.py`
- `compiler/layered_graph_normalizer.py`
- `graphs/task_graph_standard_models.py`
- `graphs/composable_graph_builder.py`
- `runtime_semantics/compiler.py`
- `runtime_semantics/quality_gates.py`
- `runtime/graph_runtime/scheduler.py`

This is where legitimate complexity becomes hard to reason about. Each layer has a sensible name, but authority boundaries are blurry:

- normalizer extracts layers from metadata and canonical fields
- compiler creates runtime spec
- standard view creates editor/debug projection
- composable builder creates units/ports
- runtime semantics emits diagnostics about legacy fields
- scheduler also interprets temporal metadata

The result is repeated interpretation of node/edge metadata in several places.

### 6. Writing graph requirements inflated the system

The writing task graph is ambitious: long-form modular novel creation, baseline/mutable/manuscript memories, chapter batching, volume loops, review/repair/commit gates, and graph modules.

That is real complexity. The writing graph added pressure in these areas:

- batch lifecycle planning
- long output length budgets
- memory commit protocols
- artifact policies
- review/repair packets
- graph module runtime
- prompt quality constraints

This is not inherently wrong. But it accelerated growth before the underlying task graph authority model was fully stable, so writing-specific needs left generic code paths with special-case concepts and compatibility residue.

## Main Structural Causes

### Cause A - UI, compiler, and runtime all interpret metadata

When metadata is used as a broad extension bag, every layer becomes a parser. This explains the high `metadata.` count.

Target:

- canonical fields for runtime-critical concepts
- metadata only for display, provenance, or non-authoritative annotations
- one compiler-owned normalization pass from old metadata into canonical diagnostics

### Cause B - Migration diagnostics live too close to primary editing

Legacy fields, overlays, and timeline block diagnostics are valuable while migrating. But if they remain in the primary workbench, UI code grows because it must support both old and new editing mental models.

Target:

- primary editor edits canonical graph only
- migration diagnostics are read-only and grouped under one migration report
- no mutation controls for old representations

### Cause C - Preflight and repair logic are spread through the workbench

`TaskGraphWorkbench.tsx` currently includes repair functions for memory selectors, commit paths, revision packets, artifacts, human gates, and timeline issues.

This is convenient but scales poorly. Each preflight issue adds UI routing plus repair code plus edge/node metadata assumptions.

Target:

- pure preflight report builder
- pure repair command builder
- workbench only dispatches repair commands
- repair commands are tested without React

### Cause D - Registry is a god object

`flow_registry.py` is the biggest backend Python file. It should not own every persistence and hydration detail forever.

Target:

- `TaskGraphRepository`
- `TaskRecordRepository`
- `WorkflowRepository`
- `ContractRepository`
- `TaskSystemStorage`
- `TaskSystemRegistryFacade`

### Cause E - Standard view is both useful and expensive

The standard view is necessary for explaining compiled graph behavior. But if every editor page consumes it differently, it becomes another source of duplicated mapping code.

Target:

- one standard view view-model layer
- pages consume view-model slices instead of raw standard view
- stale/freshness status enforced at the shell level

## What Is Reasonable Complexity

These parts are likely justified:

- graph model definitions
- runtime spec compiler
- graph runtime scheduler
- batch lifecycle runtime
- memory/resource protocol modeling
- contract and quality gate models
- writing graph regression tests
- standard view generation for diagnostics

These are core to a mature agent task graph system.

## What Looks Like Reducible Complexity

### High-priority cleanup candidates

1. Split `flow_registry.py`.
   - It is the biggest backend source file and mixes storage, registry, and migration responsibilities.

2. Extract preflight repair commands out of `TaskGraphWorkbench.tsx`.
   - The workbench should route and present, not know how to repair every graph policy.

3. Collapse old timeline block editor paths.
   - After the recent graph-module refactor, timeline blocks should remain diagnostic only unless a current graph explicitly requires them.

4. Move frontend memory model pages into view-model modules.
   - `TaskGraphMemoryArtifactPage.tsx` is 1,314 lines and likely combines derivation, state, UI, and editor forms.

5. Create a canonical graph module model.
   - We just shifted backend compilation toward canonical `graph_module` nodes. The remaining standard/composable/timeline code should follow the same authority.

6. Reduce metadata parsing in scheduler/compiler/UI.
   - Make runtime-critical concepts first-class or normalize them once.

### Medium-priority cleanup candidates

1. Split `taskGraphTemplates.ts`.
   - Template catalog, builder helpers, and domain-specific template definitions should not live in one 994-line file.

2. Split `TaskGraphPublishRunPage.tsx`.
   - Separate publish preflight, package compile, run control, trace/monitor panels.

3. Move standard view adapters out of React components.
   - React components should receive prepared view models.

4. Separate migration tests from target-behavior tests.
   - Keep migration tests, but name them as migration tests so they do not protect old architecture forever.

## Recommended Refactor Sequence

1. Authority freeze.
   - Document canonical graph authority: `TaskGraphDefinition.nodes/edges` own runtime structure.
   - Mark `timeline_blocks`, `projection_overlay_id`, and `metadata.composable_graph` as migration/read-only unless explicitly promoted.

2. Extract frontend repair command layer.
   - New module: `taskGraphRepairCommands.ts`.
   - Input: issue + graph snapshot.
   - Output: typed patch command.
   - Workbench dispatches command only.

3. Split memory artifact page.
   - Move derived memory/resource models to pure modules.
   - Keep page as layout plus controls.

4. Split registry.
   - Extract JSON storage adapter first.
   - Then graph/task/workflow repositories.
   - Preserve public registry facade until callers are moved.

5. Normalize graph module runtime authority.
   - Continue replacing timeline-block plan authority with canonical `graph_module` nodes.
   - Keep timeline block support as read-only diagnostics with an explicit removal condition.

6. Standard view view-model.
   - Build a single frontend adapter for units, resources, timeline, memory protocol, graph modules.
   - Pages consume that adapter instead of repeatedly parsing `standardView`.

## Risk Notes

- Full cleanup is not a small patch. The system is already used by writing graph compilation and runtime tests.
- Avoid deleting compatibility fields blindly. Delete by authority: if a field no longer owns a decision, either migrate it or make it diagnostic-only.
- The current dirty worktree includes unrelated backend memory/runtime changes. Any broad refactor should isolate task-system files from those changes.

## Bottom Line

The task system is large because it became the convergence point for task authoring, graph compilation, runtime orchestration, memory protocols, quality gates, writing workflows, and a rich editor UI.

About half the size is legitimate product complexity. The reducible half comes from duplicated authority:

- canonical graph plus timeline blocks
- raw metadata plus first-class fields
- standard view plus frontend local derivations
- workbench repair code plus preflight diagnostics
- registry facade plus storage/migration logic

The best next cleanup is not deleting random files. It is cutting duplicated decision authority one layer at a time, starting with frontend repair commands and backend registry decomposition.
