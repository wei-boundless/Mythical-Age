# Electron Dev Host Plan

## Goal

Provide a local desktop host for development that keeps the existing Next.js hot reload and FastAPI development loop, while moving service startup, port selection, API base injection, health checks, and cleanup into one owner process.

## Non-goals

- Do not redesign the workbench UI.
- Do not package a production installer in this step.
- Do not remove the existing `scripts/project_stack.ps1` flow.
- Do not rely on Next.js `/api` rewrites for the app shell.

## Runtime Shape

1. Electron main process starts first.
2. It finds available frontend and backend ports, preferring `3000` and `8002`.
3. It starts the backend with `uvicorn app:app --reload`.
4. It starts the frontend with `next dev -p <frontendPort>`.
5. It waits for backend `/health` and frontend `/`.
6. It opens a desktop window to the frontend URL.
7. It injects host config through preload:
   - `apiBase`
   - `frontendUrl`
   - `backendHealthUrl`
   - selected ports
8. The renderer uses the injected `apiBase` instead of hardcoded `/api`.
9. When the desktop app exits, child processes are stopped.

## Recovery Rules

- If the preferred port is occupied by a non-project process, use the next free port.
- If a child process exits while the app is still open, mark service state unhealthy.
- Initial version reports failures through a minimal desktop error page and logs.
- A later iteration can add visible restart controls.

## Implementation Checklist

- Add Electron main process under `frontend/electron/main.cjs`.
- Add preload bridge under `frontend/electron/preload.cjs`.
- Add a tiny TypeScript global declaration for injected host config.
- Update `frontend/src/lib/api.ts` to prefer injected `apiBase`.
- Add npm scripts:
  - `dev:host`
  - `electron:host`
- Add `electron` as a frontend dev dependency.
- Verify:
  - `npm run electron:host -- --help` or a syntax-level load check.
  - `npm run dev:host` starts backend, frontend, and opens the shell.
  - `GET /health` succeeds on injected backend port.

