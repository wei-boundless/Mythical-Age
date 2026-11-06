import { apiRequest } from "./client";
import type { SessionScope } from "./types";

const inFlightGetRequests = new Map<string, Promise<unknown>>();

function getRequestKey(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers);
  const headerEntries = Array.from(headers.entries()).sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify({
    method: String(init?.method || "GET").toUpperCase(),
    path,
    headers: headerEntries,
  });
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = String(init?.method || "GET").toUpperCase();
  const hasBody = init?.body !== undefined && init?.body !== null;
  if (method === "GET" && !hasBody && !init?.signal) {
    const key = getRequestKey(path, init);
    const existing = inFlightGetRequests.get(key);
    if (existing) {
      return existing as Promise<T>;
    }
    const run = apiRequest<T>(path, init);
    inFlightGetRequests.set(key, run);
    run.then(
      () => inFlightGetRequests.delete(key),
      () => inFlightGetRequests.delete(key),
    );
    return run;
  }
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
