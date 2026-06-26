# Agent Context Main-Chain Architecture

Date: 2026-06-26

This document supersedes the older context assembly architecture note. The active runtime no longer has a separate physical assembler module or a provider-cache-policy switch that can decide message order.

## Main Chain

```text
ContextSegmentPolicy
-> PhysicalContextPlan
-> ProviderPayloadManifest
-> ProviderRequestContextCommit
-> ProviderVisibleContextLedger
-> Session/Fork Boundary
```

## Authority Boundaries

`ContextSegmentPolicy` owns semantic section, replay, commit, and cache eligibility:

- `static_prefix`
- `context_memory_prefix`
- `context_append`
- `dynamic_tail`

`PhysicalContextPlan` owns provider-visible physical lanes and cache-spine membership:

- `global_static_prefix`
- `active_context_prefix`
- `byte_replay_archive_prefix`
- `current_turn_tail`
- `never_replay_tail`

Provider payload construction consumes the physical lanes. It may report violations when a message lacks a lane or when a stable lane appears after a tail lane, but it must not infer a lane from old metadata fields.

## Cache Spine

Only these lanes are cache-spine lanes:

```text
global_static_prefix + active_context_prefix + byte_replay_archive_prefix
```

Current-turn append content is always outside the same-request cache spine:

```text
context_append -> current_turn_tail
provider success -> confirmed ledger entry
next turn replay -> context_memory_prefix -> active_context_prefix or byte_replay_archive_prefix
```

This makes cache hits depend on confirmed provider-visible bytes, not on optimistic current-turn appends.

## Fork Boundary

A fork inherits only confirmed context state:

- parent provider-visible ledger anchor
- fork-point context commit
- cache spine hash
- compaction generation

The child session reads parent confirmed entries up to the fork anchor and writes later entries under the child scope. Runtime control tails and unconfirmed append candidates do not become fork-inherited prefix memory.

## Prompt Quality Rule

Agent-facing prompts describe the agent's role, responsibility, input, output, decision criteria, and failure behavior. Runtime node descriptions and developer implementation notes are not agent prompts.

## Current Detailed Report

The implementation report lives at:

```text
docs/context_prefix_cache_fork_refactor_execution_report.md
```
