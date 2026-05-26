# Task Graph Editor Authority Refactor Plan - 2026-05-27

## Goal

Restructure the task graph editor so it has one clear editing authority:

- Canonical `nodes` and `edges` are the only writable runtime graph.
- Editor focus describes where the user is looking.
- Canonical selection describes which writable object is being edited.
- Standard view is a compiled diagnostic projection with an explicit freshness state.
- Legacy timeline blocks and metadata overlay edges are not treated as active editor concepts.

This refactor targets structural correctness, not visual polish.

## Current Flow

- Entry point: `frontend/src/components/workspace/views/TaskSystemView.tsx`
- Workbench router: `frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx`
- Writable topology page: `frontend/src/components/workspace/views/task-system/TaskGraphTopologyPage.tsx`
- Compiled preview page: `frontend/src/components/workspace/views/task-system/TaskGraphComposableEditorPage.tsx`
- Preview canvas: `frontend/src/components/workspace/views/task-system/TaskGraphComposableCanvas.tsx`
- Focus helper: `frontend/src/components/workspace/views/task-system/taskGraphEditorFocus.ts`
- Save mapper: `frontend/src/components/workspace/views/task-system/taskGraphSaveMapper.ts`
- Backend standard view authority: `backend/task_system/graphs/task_graph_standard_models.py`

Current decision points:

- `TaskSystemView.tsx` stores `selectedGraphNodeId` and `selectedGraphEdgeId`.
- `TaskGraphWorkbench.tsx` stores `editorFocus` and also writes to canonical selection.
- `TaskGraphComposableEditorPage.tsx` stores `selectedSubject`, derived from `editorFocus`.
- Several pages infer fallback selections when no explicit edge or node is selected.
- `saveTaskGraphStack` maps editor state into backend `publish_state`, `enabled`, and `metadata.editor_publish_state`.

Recovery/fallback points to remove or rewrite:

- `repository_id` is written into `selectedGraphNodeId`.
- Responsibility page defaults to the first graph edge when no edge is selected.
- Modules/compiled preview can show stale standard view without a hard freshness boundary.
- Legacy timeline block and metadata overlay labels remain in primary editor navigation.

## Target Authority Chain

- observe: `TaskSystemView.tsx` receives API records and UI events.
- normalize: `taskGraphDraftV2.ts`, `taskGraphSaveMapper.ts`, and new selection utilities normalize records and IDs without guessing semantics.
- decide: `TaskGraphWorkbench.tsx` decides active layer/facet only; it must not silently choose a writable object.
- authorize: publish/save controls decide whether graph mutations are allowed based on `publish_state`.
- assemble: `taskGraphSaveMapper.ts` builds the backend upsert payload.
- execute: API functions in `frontend/src/lib/api` perform save, refresh, compile package, and publish actions.
- record: backend task graph registry stores canonical graph records.
- present: page components render selection, stale preview state, diagnostics, and actions.

## Authority Table

| File/module | Current responsibility | Hidden decision | Target layer | Action | Evidence |
| --- | --- | --- | --- | --- | --- |
| `TaskSystemView.tsx` | Owns draft, selected node, selected edge, save/refresh | Rehydrates draft and resets selection to first node; maps publish state through multiple fields | observe, normalize, assemble | Keep as top-level state owner, but replace loose node/edge state with a single typed editor selection and explicit standard view freshness | Selection lines around 672, 1167, 1935; save lines around 1761 |
| `TaskGraphWorkbench.tsx` | Routes layers, owns `editorFocus`, repairs preflight issues | Converts `repository_id` into `selectedGraphNodeId`; defaults edge in responsibility page | decide, present | Make focus and selection separate; remove implicit first-edge fallback | `applyEditorFocus` and responsibility props |
| `taskGraphEditorFocus.ts` | Maps preflight issues to target layer/facet | Encodes target IDs without distinguishing node, edge, repository, preview unit, issue | normalize | Replace or extend with typed focus targets | `TaskGraphEditorFocus` currently stores optional flat IDs |
| `TaskGraphComposableEditorPage.tsx` | Shows compiled standard view and local selected subject | Treats preview subject as if it can drive global selection | present | Keep preview subject local; only canonical node/edge focus may update writable selection | `selectedSubject` and `applySubject` |
| `TaskGraphComposableCanvas.tsx` | Renders units, port edges, graph modules, legacy stitching | Keeps legacy timeline block and overlay concepts visible in primary canvas | present | Remove legacy stitching from primary mode strip; show overlay as migration diagnostic only | Mode strip contains `legacy 来源`; overlay count shown |
| `taskGraphSaveMapper.ts` | Builds backend graph payload | Duplicates publish/editor metadata mapping | assemble | Centralize publish mapping into a single explicit helper with tests | `buildTaskGraphUpsertPayload` and `saveTaskGraphStack` jointly decide |
| `backend/task_system/graphs/task_graph_standard_models.py` | Produces standard view | Still supports standard view update path that can become second write authority | normalize, present | Keep build path; audit/update path should not be wired into frontend editor unless explicitly needed | `apply_task_graph_standard_view_update` |

## Deletion / Rewrite Candidates

| Candidate | Why it lacks authority | What replaces it | Required test update |
| --- | --- | --- | --- |
| `repository_id -> selectedGraphNodeId` conversion | Repository is not always a writable graph node ID | Typed `TaskGraphEditorSelection` with separate `canonicalNodeId` and `resourceId` | Add selection tests for resource focus not mutating canonical node selection |
| Responsibility page first-edge fallback | UI guesses an editable edge without user intent | Empty edge state with explicit "select an edge" presentation | Add component/model test or focused regression for no implicit first edge |
| Primary "legacy stitching" mode | Old coordinate source should not be part of active editor model | Move to diagnostics only, or delete if no active runtime path requires it | Update terminology tests to reject "legacy 来源" in primary editor |
| `metadata.explicit_overlay` as active canvas concept | Overlay edge is not canonical write authority | Preflight issue and migration warning, no editor mode or primary metric | Update preflight/standard view tests to assert overlay is reported as issue |
| Dual publish state mapping scattered between caller and save mapper | Two layers decide saved/published meaning | One helper that maps editor intent to backend `publish_state`, `enabled`, metadata | Extend `taskGraphSaveMapper.test.ts` |

## Implementation Plan

### Slice 1 - Introduce Typed Editor Selection

Files:

- `frontend/src/components/workspace/views/task-system/taskGraphEditorSelection.ts` new
- `frontend/src/components/workspace/views/task-system/taskGraphEditorFocus.ts`
- `frontend/src/components/workspace/views/TaskSystemView.tsx`
- `frontend/src/components/workspace/views/task-system/TaskGraphWorkbench.tsx`
- `frontend/src/components/workspace/views/task-system/taskGraphTypes.ts`

Change:

- Add `TaskGraphEditorSelection`:
  - `canonicalNodeId`
  - `canonicalEdgeId`
  - `resourceId`
  - `previewUnitId`
  - `previewPortEdgeId`
  - `issueId`
- Add pure helpers:
  - `selectionFromFocus`
  - `focusFromSelection`
  - `clearCanonicalSelection`
  - `selectCanonicalNode`
  - `selectCanonicalEdge`
- Replace `selectedGraphNodeId` / `selectedGraphEdgeId` state with typed selection in `TaskSystemView`.
- Keep page props narrow by passing only canonical IDs where a page edits canonical graph.
- Do not map `repository_id` into canonical node selection.

Tests:

- Add `taskGraphEditorSelection.test.ts`.
- Update existing focus tests if they assert flat ID behavior.

Stop condition:

- No `repository_id` write reaches `selectedGraphNodeId` equivalent.
- Topology editing still selects and mutates canonical nodes/edges.

### Slice 2 - Remove Implicit Editable Fallbacks

Files:

- `TaskGraphWorkbench.tsx`
- `TaskGraphResponsibilityPage.tsx`
- `EdgeHandoffCard.tsx`
- `NodeResponsibilityCard.tsx`
- any tests covering responsibility / edge handoff behavior

Change:

- Remove first-edge fallback in responsibility layer.
- When no edge is selected, edge handoff panels render a non-mutating empty state.
- Node responsibility remains available when a canonical node is selected.
- Cross-layer links must explicitly select node or edge before showing mutation controls.

Tests:

- Add or update tests to prove no edge mutation is possible without explicit selected edge ID.

Stop condition:

- Searching for `activeGraphEdges[0]` in workbench responsibility routing finds no editable fallback.

### Slice 3 - Add Standard View Freshness Boundary

Files:

- `TaskSystemView.tsx`
- `TaskGraphWorkbench.tsx`
- `TaskGraphStudioShell.tsx`
- `TaskGraphComposableEditorPage.tsx`
- `TaskGraphPublishRunPage.tsx`
- possibly `taskGraphPreflight.ts`

Change:

- Track standard view as `{ graphId, revisionKey, loadedAt, stale }`.
- Mark standard view stale after any canonical graph mutation.
- Modules/compiled preview must display stale status and block publish-preflight reliance on stale standard view.
- Refresh standard view clears stale only if it matches current graph ID and draft revision key.
- Execution package compile should require saved graph and warn when local draft is dirty/stale.

Tests:

- Add pure test for freshness reducer/helper.
- Update publish/preflight tests to assert stale compiled view is not treated as current.

Stop condition:

- Dirty topology changes cannot silently appear as current compiled preview.

### Slice 4 - Clean Legacy / Overlay Editor Surface

Files:

- `TaskGraphComposableCanvas.tsx`
- `TaskGraphComposableEditorPage.tsx`
- `TaskGraphGraphLayerRail.tsx`
- `taskGraphPreflight.ts`
- `taskGraphUiTerminology.test.ts`
- `taskGraphStandardView.test.ts` if needed

Change:

- Remove primary canvas mode for legacy stitching.
- Remove user-facing "legacy 来源" from primary editor.
- Keep timeline block information only in diagnostics if still emitted by backend.
- Convert `metadata.explicit_overlay` to a preflight/migration issue instead of a primary canvas metric.
- If no active runtime needs overlay edges, delete overlay-specific display filtering from canvas path.

Tests:

- Update terminology test to reject legacy wording in main editor.
- Add preflight assertion for overlay edge issue.

Stop condition:

- Primary editor no longer presents legacy timeline block or overlay edge as normal graph-editing concepts.

### Slice 5 - Centralize Publish State Mapping

Files:

- `taskGraphSaveMapper.ts`
- `taskGraphSaveMapper.test.ts`
- `TaskSystemView.tsx`
- `TaskGraphWorkbench.tsx`
- `TaskGraphPublishRunPage.tsx`

Change:

- Add one helper, for example `resolveTaskGraphPublishCommit`, that accepts explicit intent:
  - `save_draft`
  - `publish`
  - `mark_run_bound`
  - `archive`
- The helper returns:
  - editor publish state
  - backend publish state
  - `enabled`
  - metadata patch
- Remove scattered publish-state ternaries from `saveTaskGraphStack`.

Tests:

- Extend mapper tests for saved, published, run_bound, archive, dirty draft.

Stop condition:

- `enabled`, backend `publish_state`, and `metadata.editor_publish_state` are produced by one helper only.

### Slice 6 - Verification and Cleanup

Files:

- All changed frontend editor files.
- Obsolete tests or stale snapshots found during implementation.

Change:

- Remove obsolete helpers and tests protecting old flat selection or legacy surface.
- Run targeted tests.
- Start fixed frontend/backend ports only if UI verification is needed after implementation:
  - frontend `127.0.0.1:3000`
  - backend `127.0.0.1:8003`
- Use local Edge browser for rendered UI verification.

Verification commands:

```powershell
cd frontend
npm test -- taskGraphEditorSelection taskGraphEditorFocus taskGraphSaveMapper taskGraphUiTerminology taskGraphPreflight taskGraphStandardView
```

```powershell
cd backend
python -m pytest backend/tests/task_graph_standard_models_test.py backend/tests/task_graph_template_catalog_regression.py backend/tests/task_graph_runtime_semantics_manifest_test.py
```

Actual command names may be adjusted after inspecting `frontend/package.json` and existing test runner configuration.

Manual verification:

- Open task graph editor.
- Select a canonical node, switch layers, return to topology, confirm selection is stable.
- Focus a memory repository issue, confirm it does not masquerade as selected canonical node unless it is actually backed by a graph node.
- Enter responsibility layer without selecting an edge, confirm no first edge is editable.
- Modify topology, open compiled preview, confirm stale state is visible.
- Save/refresh, confirm standard view becomes current.
- Confirm no primary editor label says `legacy 来源`.

## Out of Scope

- Backend memory/runtime changes currently dirty in the worktree.
- Visual redesign beyond what is required to expose correct authority and stale states.
- New runtime scheduling semantics.
- Rewriting backend standard view generation unless frontend cleanup reveals an active second-write path.

## Approval Gate

This plan changes shared editor state and removes old editor surface concepts. Implementation should begin only after user review confirms the target structure.
