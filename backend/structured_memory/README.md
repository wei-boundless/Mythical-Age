# Python Agent Memory

This is a minimal Python implementation of the memory pattern used in this repo:

- durable memory stored as markdown files
- `MEMORY.md` as the memory index
- frontmatter-backed topic files
- per-session `process_state.json` runtime state
- per-session `views/agent_view.md` working-memory view
- `summary.md` as a compatibility mirror
- session-memory-driven context compaction
- prompt injection from both durable and session memory
- post-turn memory extraction
- extraction scheduling with simple coalescing
- team-memory scaffold under `memory/team/`

## Files

- `memory_manager.py`: durable memory CRUD
- `frontmatter.py`: frontmatter parse/format helpers
- `process_state.py`: authoritative runtime process-state schema and storage
- `session_memory.py`: rendered working-memory view storage
- `compact.py`: compresses long message history using session memory
- `extractor.py`: heuristic durable-memory extraction
- `extraction_scheduler.py`: throttles and coalesces extraction runs
- `team_memory.py`: shared-memory scaffold
- `prompt_builder.py`: injects memory into the system prompt
- `demo_agent.py`: tiny runnable example

## Run

```bash
python -m structured_memory.demo_agent
```

## Integrate With A Real Model

Replace `DemoAgent._mock_model_reply(...)` with your SDK call. The usual flow is:

1. append the new user message
2. update session memory
3. build the system prompt from persistent memory + session memory
4. compact long histories using session memory as the summary
5. call the model
6. append the assistant reply
7. refresh session memory
8. extract durable memories from the latest conversation

## Compression Model

The original TypeScript project does not only store memory; it also compresses
conversation state. The Python port now mirrors that at a minimal level:

- `process_state.json` acts as the runtime authority for the current session
- `views/agent_view.md` acts as the primary rendered working-memory view
- `summary.md` remains as a compatibility mirror during migration
- when the message list grows beyond a threshold, `ContextCompactor` replaces
  older history with one synthetic summary message
- the recent window is preserved verbatim

That gives you a simple version of:

```text
messages -> session summary -> compact older history -> build runtime prompt
```

## Suggested Directory Layout

```text
your-agent/
  context_profile/
    constitution/
      SOUL.md
      IDENTITY.md
    profile/
      USER.md
      AGENTS.md
  durable_memory/
    MEMORY.md
    *.md
    team/
      MEMORY.md
      *.md
  session-memory/
    process_state.json
    state.json
    summary.md
    views/
      agent_view.md
```

## Next Upgrade Ideas

- replace heuristic extraction with an LLM summarizer
- add selective retrieval instead of loading the first N notes
- add remote sync behind `TeamMemoryManager.sync_pull/sync_push`
- add agent-specific memory scopes like `user`, `project`, and `agent`
- add JSON or SQLite metadata cache if note count grows large
