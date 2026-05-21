# Backend Slimming Plan 2026-05-21 Round 6

## Scope

Backend only. Ignore stale `docs/` and frontend. This round targets `backend/orchestration/runtime_loop/langgraph_coordination_runtime.py`.

## Diagnosis

`LangGraphCoordinationRuntime` currently mixes the graph runtime entrypoints with several independent policy families:

- runtime graph/node payload lookup helpers;
- working-memory and formal-memory path/context/commit helpers;
- source output extraction and artifact-ref normalization;
- stage output/result-record construction;
- loop/revision retry policy helpers;
- human gate, rewind, scheduler, and contract payload deserialization helpers.

The class-level orchestration methods are already large, but a lot of file size is pure module-level helper logic. Moving those helpers behind named owner modules reduces the blast radius for future changes without changing the runtime API.

## Target Shape

Create focused modules under `backend/orchestration/runtime_loop/`:

- `coordination_memory_helpers.py`
  - runtime root path helpers
  - working-memory selection/context/read operation helpers
  - formal-memory commit request/write-record helpers
  - memory handoff/ref filtering helpers
- `coordination_result_helpers.py`
  - output bundle extraction
  - source output lookup and candidate conversion
  - artifact output satisfaction helpers
  - stage output collection and artifact-ref parsing
- `coordination_runtime_payloads.py`
  - runtime node payload/value helpers
  - runtime contract payload deserialization helpers
  - initial contract status/status mutation helpers

Keep `LangGraphCoordinationRuntime` as the orchestration owner: initialization, resume/rewind/human gate APIs, LangGraph app wiring, stage prepare/execute/accept, route transitions, and event emission.

## Implementation Steps

1. Extract memory/formal-memory helpers into `coordination_memory_helpers.py`.
2. Extract result/output/artifact helpers into `coordination_result_helpers.py`.
3. Extract runtime payload and contract deserialization helpers into `coordination_runtime_payloads.py`.
4. Replace local helper definitions in `langgraph_coordination_runtime.py` with imports.
5. Remove helper compatibility shells unless tests require them; migrate tests to the new owner when needed.
6. Validate with py_compile and targeted coordination/task graph/writing graph regression tests.

## Non-Goals

- Do not change coordination business behavior.
- Do not rewrite prompts or agent-facing task instructions.
- Do not touch frontend, docs, or generated runtime artifacts.
