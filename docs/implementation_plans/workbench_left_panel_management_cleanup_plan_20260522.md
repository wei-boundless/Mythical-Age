# Workbench Left Panel Management Cleanup Plan

## Problem

The left workbench panel was treating `project`, `session`, and `file` as three parallel buckets. That model is wrong for this agent product.

The correct relationship is:

- Project is the workspace boundary.
- Session is the current conversation/task/runtime context inside that project.
- File is project material: inputs, memory, configuration, generated artifacts, and editable context.

When project is shown as a tab beside sessions and files, the interface hides the real hierarchy and makes every object look like a loose shortcut.

## Target Design

Keep the left panel as a low-noise project object manager:

- Fixed project context at the top: real project name/root from the backend, current workspace layer, active session, active file, and monitor stream state.
- Below the project context, switch only between project-owned objects:
  - `会话`: create, select, rename, search, and delete sessions. This is the agent's execution/conversation context.
  - `文件`: search, open, inspect, and save editable project resources. This is the agent's material and artifact surface.
- Do not make `项目` a tab. Project is the container, not a sibling of sessions/files.
- Do not use explanatory resource copy as interface content.

## Execution

1. Add a backend workspace context endpoint so the frontend does not guess project identity from the current view.
2. Store workspace context in the frontend runtime state.
3. Replace the old left panel with fixed project context plus `会话 / 文件` object switching.
4. Make sessions practical: current session title editor, new session, search, list, delete.
5. Make files practical: current file state, save action, search, grouped file rows.
6. Remove obsolete `project` tab, old pseudo-resource copy, and stale CSS selectors.
7. Run backend/frontend checks and inspect the rendered UI.

## Completion Criteria

- The left panel visibly communicates `project contains sessions and files`.
- Project context uses backend workspace data, not the current view name.
- There is no `项目` tab beside `会话 / 文件`.
- Session management and file management each expose real actions.
- No old misleading copy such as “会话资源 / 文件编辑 / 项目记忆 / 快捷文件” remains.
- `npm run build` passes.
