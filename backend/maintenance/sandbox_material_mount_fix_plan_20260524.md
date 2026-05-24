# Sandbox Material Mount Fix Plan - 2026-05-24

## Problem

Professional tasks can now express source material through `ModelTurnDecision.resource_contract.source_projects`, but the sandbox runtime does not expose those source projects as readable in-sandbox material.

The model sees an absolute source path and tries to read it. The filesystem and shell guards correctly reject this as path traversal or outside-sandbox access. The result is a loop of blocked reads instead of a clean material handoff.

## Principle

The model should own understanding. Runtime should own access topology.

`source_projects` must not be handed to the agent as raw absolute paths that tools cannot read. Runtime must import or mount them into a stable, read-only material namespace inside the sandbox and tell the model where to read them.

## Target Chain

```text
ModelTurnDecision.resource_contract.source_projects
-> sandbox material importer
-> sandbox_policy.material_mounts
-> model-visible sandbox guidance
-> read_file / terminal use relative material paths
-> target writes stay under requested output directory
```

## Implementation

1. Extend sandbox policy preparation:
   - Read `task_contract.task_requirement_contract.model_turn_decision.resource_contract`.
   - Import each `source_project.path` into:
     `.materials/source_projects/source_01/`
   - Copy directories recursively into the sandbox root.
   - Preserve file trees, including `assets/`.
   - Record `material_mounts` in `sandbox_policy`.

2. Expose material mounts to the model:
   - Add material mount summary to sandbox policy event/context.
   - Add prompt guidance in professional follow-up when material mounts exist:
     use `.materials/source_projects/source_01/...` instead of external absolute paths.

3. Safety boundary:
   - Imported materials are snapshots inside sandbox.
   - Writes still go to normal target output paths.
   - Do not allow writing back to original source path.

4. Regression:
   - Given a temp source project with files and assets, preparing sandbox creates `.materials/source_projects/source_01`.
   - Policy includes mount metadata.
   - Existing sandbox policy behavior remains unchanged when no resource contract exists.

