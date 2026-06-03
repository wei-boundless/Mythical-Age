# VS Code Project Binding and Sandbox Optimization Plan

## Goal

把当前的 VS Code/editor context 接入从“prompt 能看见项目”升级为“本地 session 的工具、sandbox、权限都绑定到同一个项目”。

核心目标：

- 对话和 session 权威仍在本地后端，不迁移到 VS Code。
- VS Code 只负责提供编辑器上下文和项目事实。
- 一个 session 首次绑定一个项目根目录后不可切换。
- 工具执行、shell、读写、diff、测试和 TaskRun sandbox 都从 session project binding 派生。
- 不需要打开两份项目，也不需要复制项目；后端只绑定并使用 VS Code 打开的同一个本地路径。

## Current Findings

当前已具备：

- `extensions/vscode` 可以采集 `workspace_roots`、`active_file`、`visible_files`、`diagnostics`。
- `/api/chat/runs` 已接收 `editor_context`。
- `editor_context` 已进入 dynamic prompt/context，agent 可以看到当前 VS Code 文件和选区。
- 前端已支持按 session 保存 opened-file context，避免跨 session 污染。

当前缺口：

- `editor_context.workspace_roots` 只作为 prompt 上下文，没有进入本地授权边界。
- `ToolUseContext.workspace_root` 默认仍来自 `tool_runtime.base_dir`，也就是 `langchain-agent` 项目根。
- `single_agent_turn` 和 `task_executor` 的 sandbox policy 仍回退到后端项目根。
- TaskRun 虽然能冻结 parent turn 的 editor context，但工具权限根不随之切换。
- VS Code extension 创建 session 时没有提交 project binding。
- 后端没有“打开 VS Code 并绑定项目”的本地入口。

## Target Authority Chain

```text
VS Code editor context
  observes workspace_root / active_file / diagnostics
        |
        v
SessionProjectBinding
  decides and freezes the project root for this session
        |
        v
RuntimeAssembly
  carries workspace_root into task_environment storage and sandbox policy
        |
        v
ToolControlPlane / SandboxPolicy
  authorizes actions inside the bound project root
        |
        v
ToolUseContext
  executes read/write/shell/test/diff against the bound root
```

Authority rules:

- `editor_context` is observation, not authorization.
- `SessionProjectBinding` is authorization scope source.
- `RuntimeAssembly` transports the already-decided root.
- Tool executors consume the root; they must not infer a new project from paths.
- If a session is already bound, a different workspace root is a conflict, not a silent switch.

## Session Project Binding Contract

Add `conversation_state.project_binding`:

```json
{
  "workspace_root": "D:/AI应用/langchain-mini",
  "source": "vscode",
  "bound_at": 1780520000.0,
  "last_seen_at": 1780520100.0,
  "immutable": true,
  "authority": "sessions.project_binding"
}
```

Rules:

- The root must exist and must be a directory.
- The root is normalized to an absolute resolved path.
- First bind wins.
- Rebinding to the same normalized root only updates `last_seen_at`.
- Rebinding to a different root raises a conflict.
- To work on another project, create a new session.

This keeps the user's desired model:

```text
one session = one project = one page/task context
```

## VS Code Role

VS Code is not the conversation authority.

VS Code responsibilities:

- Open the user's project folder.
- Send `workspace_roots`, active file, selection, dirty state and diagnostics.
- Remember the local `session_id` for that workspace as a convenience.

Local backend responsibilities:

- Own session history.
- Own project binding.
- Own permissions and sandbox.
- Own task/turn run state.
- Own traces, artifacts, diffs and test results.

No double opening is required:

```text
VS Code opens D:/AI应用/langchain-mini
Backend binds session.project_root = D:/AI应用/langchain-mini
Tools execute in D:/AI应用/langchain-mini
```

If the user starts from the local frontend, the frontend may call a backend convenience endpoint to run:

```powershell
code -r D:\AI应用\langchain-mini
```

That only opens the editor. It does not create a second project authority.

## API Changes

### 1. Session creation

Extend `POST /api/sessions` with optional `project_binding`:

```json
{
  "title": "VS Code Agent Session",
  "scope": { "workspace_view": "chat" },
  "project_binding": {
    "workspace_root": "D:/AI应用/langchain-mini",
    "source": "vscode"
  }
}
```

### 2. Explicit project binding

Add endpoint:

```text
PUT /api/sessions/{session_id}/project-binding
```

Behavior:

- Creates binding if missing.
- Accepts same root as idempotent refresh.
- Rejects different root with `409 session_project_binding_conflict`.

### 3. Open VS Code

Add endpoint:

```text
POST /api/sessions/{session_id}/project-binding/open-vscode
```

Behavior:

- Requires existing `project_binding`.
- Launches `code -r <workspace_root>` with hidden process window.
- Returns the command result and bound root.
- Does not mutate project binding.

### 4. Chat run auto-bind

Before creating a chat run:

- If `editor_context.workspace_roots` has one root and session has no binding, bind it.
- If session has a binding and editor context reports the same root, refresh `last_seen_at`.
- If session has a binding and editor context reports a different root, reject with conflict.
- If multiple workspace roots are present and no binding exists, require explicit binding to avoid guessing.

## Runtime Changes

### HarnessRuntimeFacade

Before `assemble_runtime(...)`:

- Load `history_record.conversation_state.project_binding`.
- Resolve `bound_workspace_root`.
- Add it to runtime task selection or pass explicitly to `assemble_runtime`.
- Add a compact `project_binding` into `session_context` so the model sees the bound project root separately from volatile editor context.

### RuntimeAssembly

`assemble_runtime(...)` should accept `project_binding` or `workspace_root`.

It should inject the root into:

- `task_environment.storage_space.workspace_root`
- `task_environment.sandbox_policy.workspace_root`
- runtime diagnostics

Do not let environment defaults overwrite the session binding.

### single_agent_turn

`_single_turn_sandbox_policy(...)` and `_single_turn_workspace_root(...)` should use:

1. `task_environment.storage_space.workspace_root`
2. `task_environment.sandbox_policy.workspace_root`
3. fallback to backend project root only when no session project binding exists

### TaskRun executor

`_task_sandbox_policy(...)` must use the runtime assembly workspace root, not always `ProjectLayout.from_backend_dir(runtime_host.backend_dir).project_root`.

TaskRun inherits the parent turn's project binding through runtime assembly, not by re-reading editor context.

### Tool control and executor

Ensure `ToolInvocationRequest.requested_constraints.workspace_root` or sandbox policy carries the bound root.

`ToolUseContext.workspace_root` should be the bound project root unless the tool is intentionally running inside an enabled sandbox overlay.

No executor should infer permissions from absolute paths or editor context.

## Frontend Changes

Local frontend remains the main conversation surface.

Needed changes:

- Session page shows bound project root.
- If no binding exists, show “Bind Project” or “Open in VS Code” action.
- If bound, do not allow changing the root in the same session.
- If user wants another project, create a new session.
- Chat payload continues sending session-scoped editor context.

Optional later:

- Display VS Code connection status.
- Show current active file from last editor context snapshot.
- Provide “Open this bound project in VS Code” button.

## VS Code Extension Changes

Update extension flow:

- On session creation, include `project_binding.workspace_root` when exactly one workspace folder is open.
- If multiple workspace folders are open, ask the user to pick one before creating/binding.
- Before sending a chat run, call or rely on backend auto-bind validation.
- If backend returns binding conflict, show a clear message: create a new session for the other project.

Do not store conversation history in VS Code. Store only the local `session_id` reference.

## Permission Rules

Inside bound project:

- Read-only tools should run without artificial denial.
- `full_access` or authorized modes allow write/edit/shell inside the bound root.
- Dirty editor buffers remain a warning: disk reads may be stale.

Outside bound project:

- Absolute paths outside the bound root are denied.
- A different VS Code workspace root cannot silently expand permissions.
- Switching project requires a new session.

## Verification Plan

Focused backend tests:

1. Creating a session with `project_binding` persists normalized immutable binding.
2. Binding same root is idempotent and refreshes `last_seen_at`.
3. Binding a different root returns conflict.
4. Chat run with first VS Code `workspace_roots` auto-binds.
5. Chat run with conflicting `workspace_roots` is rejected.
6. Runtime assembly carries bound `workspace_root`.
7. Single-turn tool context reads from bound root.
8. TaskRun executor inherits bound root.
9. Bound `langchain-mini` session can read `backend/TOOLS_REGISTRY.json`.
10. Bound `langchain-mini` session cannot read `D:/AI应用/langchain-agent/backend/...`.

Extension tests:

- `npm run compile` under `extensions/vscode`.
- Create-session payload includes project binding.
- Multiple workspace folders require explicit pick.

Runtime smoke:

1. Start backend on `127.0.0.1:8003`.
2. Create local session bound to `D:/AI应用/langchain-mini`.
3. Send chat run asking to read `backend/TOOLS_REGISTRY.json`.
4. Confirm tool succeeds under `langchain-mini`, not `langchain-agent`.

## Non-Goals

- Do not move conversation storage into VS Code.
- Do not implement VS Code native agent session protocol in this slice.
- Do not support project switching inside one session.
- Do not add compatibility paths that silently fall back to the backend project when a session is bound.
- Do not let prompt-only editor context grant file permissions.

## Rollout Order

1. Add immutable session project binding model and API.
2. Update VS Code extension session creation payload.
3. Auto-bind/validate chat run editor workspace roots.
4. Inject binding into runtime assembly.
5. Route single-turn and TaskRun sandbox policies through assembly workspace root.
6. Add tests for binding, conflicts and tool root behavior.
7. Re-run vibe coding evaluation on `D:/AI应用/langchain-mini`.

## Expected Outcome

After implementation, the agent should be able to:

- Use our local frontend as the canonical conversation UI.
- Use VS Code as the project/editor context provider.
- Bind one session to one project permanently.
- Run tools inside the VS Code project's filesystem boundary.
- Reject accidental cross-project context pollution.
- Support real vibe coding workflows: inspect files, edit, diff, run tests and report results in the same session/project authority.
