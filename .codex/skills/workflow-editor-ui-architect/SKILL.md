---
name: workflow-editor-ui-architect
description: Orchestrate structure-first and high-fidelity frontend work for workflow editors, task builders, topology canvases, inspector layouts, and complex console UIs. Use when redesigning multi-panel workbenches, layered task systems, or editor-like products that need both information architecture and polished implementation.
---

# workflow-editor-ui-architect

Use this skill for complex product UIs where the problem is not just "make it prettier", but "design the right structure, then implement it well".

Typical triggers:

- workflow editors
- task builders
- topology / node-edge configuration UIs
- inspector + canvas + sidebar workbenches
- admin consoles with multiple information layers
- redesigns where navigation, hierarchy, and action flow are unclear

## Required workflow

### 1. Classify the interface before designing

Identify:

- product type
- user role
- primary object being edited
- page hierarchy
- whether this is a workbench, editor, dashboard, or detail form

If multiple information layers are currently mixed into one page, treat that as a structural problem first.

Before implementing, read [workflow-editor-checklist.md](references/workflow-editor-checklist.md).

### 2. Generate a structure-first design system

Use the local `ui-ux-pro-max` skill as the design-system and IA engine.

Read:

- [../ui-ux-pro-max/SKILL.md](../ui-ux-pro-max/SKILL.md)

Then run its search flow first, especially `--design-system`, to decide:

- workbench layout
- hierarchy split
- visual density
- color / typography direction
- anti-patterns to avoid
- stack-specific implementation guidance

For project-level redesigns, persist or summarize the resulting design rules before coding so later page work stays consistent.

### 3. Implement with high-fidelity frontend judgment

After the structure is clear, use the installed `frontend-design` skill for execution quality.

Read:

- `C:/Users/admin/.codex/skills/frontend-design/SKILL.md`

Apply it to:

- choose a deliberate aesthetic direction that matches the product
- refine typography, spacing, emphasis, and interaction feedback
- ensure empty/loading/error states exist
- avoid generic AI-looking layouts and over-carded noise

Do not let visual styling undo the structure decided in step 2.

### 4. Enforce project constraints during implementation

This repository has non-optional product constraints:

- prefer structural fixes over patch fixes
- remove dead legacy code unless the user explicitly wants it kept
- separate different hierarchy levels into distinct views
- use card-style buttons for switching between different hierarchy levels
- do not mix different hierarchy layers into a single page
- actually inspect the result after frontend changes
- for larger structural work, write a plan first and then execute it through

If the request implies significant UI or structure changes, produce or update a plan document before editing production code.

## Deliverable shape

For substantial UI work, aim to produce this chain:

1. structure diagnosis
2. design-system decision
3. page/workbench layout decision
4. implementation
5. actual verification

## Notes

- Keep the structure stable across pages before polishing visual detail.
- For builder/editor products, favor workbench layouts over marketing-style compositions.
- Prefer explicit page and panel responsibilities over dumping all controls into one screen.
- Use references only as needed; do not duplicate large chunks of other skills into this one.
