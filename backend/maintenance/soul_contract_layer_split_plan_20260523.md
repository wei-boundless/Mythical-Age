# Soul Contract Layer Split Plan

## Goal

Separate protected system prohibitions from user-editable shared contracts. The protected layer must keep AGENTS.md-like authority in runtime prompts, while user-authored long-term preferences stay in a separate catalog bucket and cannot be confused with prohibitions.

## Steps

1. Keep `soul/agent_core/CORE.md` as the protected system contract and remove it from the normal user shared-contract catalog.
2. Treat `soul/common_contracts/catalog.json` as the user-editable shared contract catalog.
3. Assemble runtime prompts with two distinct sections:
   - protected system rules: always visible to the model.
   - shared common contract: visible only when `use_shared_contract` is enabled.
4. Reflect the split in soul catalog, mode preview, prompt section ordering, API metadata, and frontend fallback/types.
5. Add regression coverage proving hard prohibitions stay out of the editable common contract and still enter runtime prompts.
