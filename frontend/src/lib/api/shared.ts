import { apiRequest } from "./client";
import type { SessionScope } from "./types";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init);
}

export function sessionScopeQuery(scope?: Partial<SessionScope>) {
  const params = new URLSearchParams();
  if (scope?.workspace_view) params.set("workspace_view", scope.workspace_view);
  if (scope?.task_environment_id) params.set("task_environment_id", scope.task_environment_id);
  if (scope?.project_id) params.set("project_id", scope.project_id);
  return params;
}

export function withSessionScopeQuery(path: string, scope?: Partial<SessionScope>) {
  const params = sessionScopeQuery(scope);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
