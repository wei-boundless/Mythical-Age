# Two-stage skill activation refactor - 2026-05-24

## Problem
The current runtime still mixes candidate skills with activated skills. `skill_runtime_views` is a real registry-backed candidate list, but `TaskSpec.selected_skill_ids` is populated from every candidate, and prompt assembly only exposes IDs or scattered `skill_prompt` resources. That means the model does not get a clean card-first decision surface, and the runtime cannot prove that full skill instructions are expanded only after a model-owned selection.

## Target architecture
1. Candidate discovery is runtime-owned but non-decisive.
   - Runtime may expose model-visible candidate skill cards from `SkillRegistry`.
   - Candidate cards contain only `skill_id`, title, capability, use_when, not_for/forbidden_uses, and required operations.
   - Candidate cards do not include full `SKILL.md` body.
2. Skill activation is model-owned.
   - `ModelTurnDecision.selected_skill_ids` is the only current-turn activation signal.
   - Runtime validates selected IDs against visible candidates.
   - Unknown or non-visible IDs are rejected into diagnostics, not silently expanded.
3. Detail expansion is runtime-owned after selection.
   - Runtime reads the selected skill's canonical `SKILL.md` via registry `path`.
   - Full content is rendered in a separate skill detail section.
   - Candidate and detail sections are separate prompt sections with different source types.
4. No backend preselection.
   - `TaskSpec.selected_skill_ids` means activated IDs only, never candidate IDs.
   - `visible_skill_ids` remains candidate visibility metadata.
   - `workflow_section` may mention that skills are candidates, but must not say they are active.

## Execution plan

### Phase 1 - Contract cleanup
- Extend `ModelTurnDecision` with `selected_skill_ids`.
- Validate and dedupe selected skill IDs without requiring a selection.
- Update sidecar schema and role prompt to say the model may activate visible skill IDs, but cannot invent unavailable skills.
- Update test stubs to allow selected skill IDs.

Completion criteria: model decision payload can carry activated skills, and invalid behavioral intents remain rejected.

### Phase 2 - Prompt contract sections
- Add `skill_catalog_section` and `skill_detail_section` to `TaskPromptContract`/assembler output.
- Render candidate cards from `skill_runtime_views`.
- Resolve activated skills from `model_turn_decision.selected_skill_ids`, filtered by candidate IDs.
- Read canonical `SKILL.md` bodies for selected skills only.
- Put accepted/rejected selected IDs and visible skill cards into metadata.

Completion criteria: prompt contract distinguishes candidates from activated skill details.

### Phase 3 - Runtime section projection
- Add model-visible `skill_catalog_section` before workflow/output sections.
- Add model-visible `skill_detail_section` after catalog only when selections exist.
- Preserve `visible_skill_ids` as candidate metadata.
- Use `candidate_refs` for catalog and `source_refs` for expanded skill files.

Completion criteria: runtime view exposes cards always when candidates exist, and full bodies only after model activation.

### Phase 4 - TaskSpec semantics
- Change `TaskSpec.selected_skill_ids` population to accepted model-selected IDs only.
- Keep candidate skill views in `task_operation.skill_runtime_views`.
- Do not add fallback that auto-selects candidates.

Completion criteria: no candidate skill is reported as selected unless the model selected it.

### Phase 5 - Regression coverage
- Add tests proving candidate cards appear without full skill body.
- Add tests proving selected skill body appears after model activation.
- Add tests proving `TaskSpec.selected_skill_ids` is empty for candidate-only cases.
- Update existing expectations that incorrectly treated candidates as selected.

Completion criteria: targeted skill/runtime/prompt tests pass.

## Non-goals
- Do not rebuild the entire skill registry UI.
- Do not reintroduce `active_skill`.
- Do not preserve fake hardcoded `skill.*` prompt paths.
- Do not make the backend choose a skill from task type or modality.
