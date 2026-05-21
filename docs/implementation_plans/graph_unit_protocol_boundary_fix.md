# Graph Unit Protocol Boundary Fix

## Goal

Ensure graph unit stages behave as runtime communication shells for nested task graphs, not as model-visible agents. Parent graph unit protocol objects must remain internal orchestration metadata and must not be exposed to child graph agents as prompt material.

## Plan

1. Keep graph unit parent protocol payloads in diagnostics/runtime metadata only.
2. Start child graph runs with business inputs from the parent handle, not parent `stage_execution_request` or `standard_input_package`.
3. Add a model-visibility guard so internal protocol keys are filtered from standard node input packages if they ever leak into explicit inputs.
4. Add regression coverage for graph unit child starts and standard input rendering.
5. Run focused tests for graph unit scheduling and node handoff protocol.

## Completion Notes

- Added a shared protocol-boundary input key classifier.
- Kept graph unit parent protocol payloads in child run diagnostics/runtime metadata.
- Filtered internal protocol keys before child graph initial input persistence, pending input merge, artifact-context extraction, standard node input packaging, and model-visible standard input rendering.
- Added regression coverage for child graph start behavior, handoff package filtering, and renderer filtering.
