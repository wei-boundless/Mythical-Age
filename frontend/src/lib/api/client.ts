export function getApiBase() {
  const hostBase = (
    globalThis.__MYTHICAL_AGENT_HOST__?.apiBase
    || (typeof window !== "undefined" ? window.mythicalAgentHost?.getConfig().apiBase : "")
  )?.trim();
  if (hostBase) {
    return hostBase.replace(/\/$/, "");
  }

  const explicitBase = process.env.NEXT_PUBLIC_API_BASE?.trim();
  if (explicitBase) {
    return explicitBase.replace(/\/$/, "");
  }

  return "http://127.0.0.1:8003/api";
}

export function getRuntimeMonitorEventStreamUrl(limit = 40) {
  return `${getApiBase()}/orchestration/runtime-monitor/events?limit=${encodeURIComponent(String(limit))}`;
}

function requestTimeoutMs(path: string) {
  if (path === "/sessions") {
    return 5000;
  }
  if (
    path === "/tasks/overview"
    || path === "/soul/projections"
    || path === "/orchestration/agents"
    || path.startsWith("/orchestration/harness/")
    || path.startsWith("/orchestration/runtime-monitor/")
  ) {
    return 30000;
  }
  return 12000;
}

export function isRequestAbortError(error: unknown) {
  if (!error || typeof error !== "object") {
    return false;
  }
  const name = String((error as { name?: unknown }).name ?? "");
  return name === "AbortError" || name === "TimeoutError";
}

function requestTimeoutError(path: string, timeoutMs: number, cause?: unknown) {
  const error = new Error(`Request timed out after ${timeoutMs}ms: ${path}`);
  error.name = "RequestTimeoutError";
  if (cause !== undefined) {
    (error as Error & { cause?: unknown }).cause = cause;
  }
  return error;
}

function requestTimeoutReason(path: string, timeoutMs: number) {
  return new DOMException(`Request timed out after ${timeoutMs}ms: ${path}`, "TimeoutError");
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const hasBody = init?.body !== undefined && init?.body !== null;
  if (hasBody && !(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (init?.method || "GET").toUpperCase();
  const timeoutMs = requestTimeoutMs(path);
  const runFetch = async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(requestTimeoutReason(path, timeoutMs)), timeoutMs);
    try {
      return await fetch(`${getApiBase()}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  };
  let response: Response;
  try {
    response = await runFetch();
  } catch (error) {
    if (method === "GET" && isRequestAbortError(error)) {
      try {
        response = await runFetch();
      } catch (retryError) {
        if (isRequestAbortError(retryError)) {
          throw requestTimeoutError(path, timeoutMs, retryError);
        }
        throw retryError;
      }
    } else if (isRequestAbortError(error)) {
      throw requestTimeoutError(path, timeoutMs, error);
    } else {
      throw error;
    }
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}
