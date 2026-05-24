# Context Compactor Agent Configuration Plan

## Goal

Move context compaction that uses an LLM into the existing orchestration system instead of treating it as a hard-coded runtime service.

## Principles

- LLM-backed behavior must be represented as an Agent with RuntimeProfile, model profile, projection/prompt, permissions, and runtime_config.
- Non-LLM runtime capabilities may remain code executors, but their switches and policy must be stored under orchestration-managed runtime_config.
- The context compactor is a builtin Agent capability, not a TaskGraph node by default.

## Implementation

1. Register a builtin context compactor Agent.
2. Register a matching AgentRuntimeProfile with only `op.model_response` and read-only context sections.
3. Add a system-only runtime lane for context compaction.
4. Extend the orchestration runtime_config editor with `runtime.template.context_compactor`.
5. Rename the LLM compactor class/export so it is not presented as an independent runtime type.
6. Add regression tests for builtin registration and frontend template parsing.

