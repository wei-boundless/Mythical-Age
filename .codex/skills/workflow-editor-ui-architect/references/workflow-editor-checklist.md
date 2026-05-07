# Workflow Editor Checklist

Use this checklist before and after implementing complex editor or console UI changes.

## Structure-first checks

- What is the primary object being edited?
- Which information belongs to global scope, page scope, selected-item scope, and edge/cell/detail scope?
- Are different hierarchy levels separated into distinct views or clearly switched panels?
- Is there a workbench layout when the task is inherently multi-panel?
- Are we solving a structural issue instead of masking it with extra fields or toggles?

## Layout checks

- Is the main page organized into clear regions such as navigation, canvas, inspector, and status/actions?
- Is the primary action area visually dominant?
- Are secondary settings moved into inspectors, drawers, or scoped panels rather than dumped into the main surface?
- Are repeated sections using a stable layout rather than ad hoc spacing?

## Repository-specific checks

- Different hierarchy levels must not be mixed into one page.
- Switching between hierarchy levels should use card-style buttons or equally explicit layer navigation.
- Large changes should have a plan document first.
- Dead or useless leftover code should be removed unless explicitly requested otherwise.

## Interaction checks

- Are selected states obvious?
- Are empty states, loading states, and error states present?
- Does each panel help the user act, not just read fields?
- Are destructive actions scoped and understandable?

## Visual quality checks

- Is the interface dense but readable?
- Is there unnecessary card nesting or decorative clutter?
- Is typography hierarchy clear?
- Are colors and emphasis supporting function rather than competing everywhere?

## Final verification

- Did we actually inspect the rendered UI after changes?
- Did we verify responsive behavior at practical widths?
- Did we keep implementation aligned with the chosen design system?
- Did we avoid one-off patches that should have been structural changes?
