# Provider-Visible Context, Prefix Cache, and Fork Handoff Report

Date: 2026-06-26

## Current Main Chain

The runtime context chain is now:

```text
ContextSegmentPolicy
-> PhysicalContextPlan
-> ProviderPayloadManifest
-> ProviderRequestContextCommit
-> ProviderVisibleContextLedger
-> Session/Fork Boundary
```

The former standalone physical assembler is no longer a runtime module. Section, prefix, replay, and commit policy live in `context_segment_policy.py`. Physical ordering and cache-spine membership live in `physical_context_plan.py`.

## Authority Split

`ContextSegmentPolicy` owns semantic classification:

- `static_prefix`
- `context_memory_prefix`
- `context_append`
- `dynamic_tail`

`PhysicalContextPlan` owns physical lanes:

- `global_static_prefix`
- `active_context_prefix`
- `byte_replay_archive_prefix`
- `current_turn_tail`
- `never_replay_tail`

Only these lanes decide cache-spine membership:

```text
cache_spine = global_static_prefix + active_context_prefix + byte_replay_archive_prefix
request = cache_spine + current_turn_tail + never_replay_tail
```

There is no second physical segment/rank field in `ContextSegmentPolicy`. Semantic section remains useful for policy diagnostics, but physical order, cache-spine membership, and provider prefix hashes are derived from `physical_prefix_lane`.

## Prefix Cache Rule

Current-turn append content is not cache-spine content.

`context_append` now maps to `current_turn_tail`. It may become provider-visible, and it may be committed after provider success, but it cannot be counted as cache-readable prefix in the same request. On the next turn, confirmed ledger replay returns as `context_memory_prefix`, and only then can it enter `active_context_prefix` or `byte_replay_archive_prefix`.

This prevents the old failure mode:

```text
current append -> active prefix before provider success -> false cache-spine continuity
```

## Provider Payload Rule

Provider payload cache hashes now use the physical cache spine, not `cache_role/prefix_tier` alone.

The selected provider prefix hash is derived from:

```text
transport_contract_hash + physical cache-spine message segment hashes
```

Missing `physical_prefix_lane` is a violation. Provider payload does not guess a lane from old section fields.

## Ledger Rule

`provider_visible_context_ledger.py` is a confirmed-entry ledger. It does not decide whether a candidate is sealable. It receives candidates already accepted by policy and records them only after provider success.

Failure requests may create a provider request commit record, but they do not confirm provider-visible replay entries.

## Fork Handoff

Fork inheritance is anchored by confirmed context state:

- fork point context commit
- parent provider-visible ledger anchor
- cache spine hash
- compaction generation

Child sessions read parent confirmed entries up to the fork anchor and write subsequent entries only under the child scope.
The fork snapshot stores the fork-point compaction generation explicitly, and compiler inheritance carries it with the parent anchor metadata.

## Removed Old Runtime Entrypoints

Removed from runtime:

- the standalone physical assembler module
- provider-cache-policy physical-model switching
- provider-payload ordering diagnostics based on old section-order fields
- legacy physical segment/rank and prefix-state metadata emitted by context policy
- test fossils that protected the old fixed-package path
- metadata writes and fallback reads for the old assembly section field

## Remaining Boundaries

Tool context is now projected into provider request context commits as `tool_context_anchor` and `tool_context_projection`.

Further deepening still belongs in the tool-memory layer:

- large tool output should be stored by ref/summary before model entry
- fork child tool observations must write only to child scope
- provider-bound history must keep tool-use/tool-result pairing closed

These are not allowed to reintroduce another context assembly path; they must feed the same policy and physical plan chain.
