import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest, getApiBase } from "./client";
import { streamChat } from "../api";

describe("api client base URL", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the fixed backend API in a plain browser session", () => {
    vi.stubGlobal("window", {});

    expect(getApiBase()).toBe("http://127.0.0.1:8003/api");
  });

  it("uses the host-injected API base when Electron provides one", () => {
    vi.stubGlobal("window", {
      mythicalAgentHost: {
        getConfig: () => ({ apiBase: "http://127.0.0.1:8003/api/" }),
      },
    });

    expect(getApiBase()).toBe("http://127.0.0.1:8003/api");
  });
});

describe("apiRequest", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("normalizes request timeouts instead of surfacing a raw AbortError", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));

    const pending = expect(apiRequest("/sessions", { method: "POST", body: "{}" })).rejects.toMatchObject({
      name: "RequestTimeoutError",
      message: "Request timed out after 5000ms: /sessions",
    });
    await vi.advanceTimersByTimeAsync(5000);

    await pending;
  });

  it("allows native project directory selection to wait for user input", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));

    const pending = expect(apiRequest("/sessions/session:pick/project-binding/select-directory", { method: "POST" })).rejects.toMatchObject({
      name: "RequestTimeoutError",
      message: "Request timed out after 90000ms: /sessions/session:pick/project-binding/select-directory",
    });
    await vi.advanceTimersByTimeAsync(89999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);

    await pending;
  });

  it("does not retry session timeline timeouts because session refresh has a history fallback", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));

    const pending = expect(apiRequest("/sessions/session:slow/timeline")).rejects.toMatchObject({
      name: "RequestTimeoutError",
      message: "Request timed out after 12000ms: /sessions/session:slow/timeline",
    });
    await vi.advanceTimersByTimeAsync(12000);

    await pending;
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("keeps one timeout retry for ordinary GET requests", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));

    const pending = expect(apiRequest("/files")).rejects.toMatchObject({
      name: "RequestTimeoutError",
      message: "Request timed out after 12000ms: /files",
    });
    await vi.advanceTimersByTimeAsync(12000);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(12000);

    await pending;
  });

  it("returns null for 204 no-content responses", async () => {
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 204,
      text: async () => "",
    })));

    await expect(apiRequest<null>("/chat/sessions/session:empty/latest-run?active_only=true")).resolves.toBeNull();
  });
});

describe("streamChat", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("finishes as soon as a terminal SSE event arrives", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    vi.stubGlobal("fetch", mockChatRunFetch([
      streamReader(
        [
          'id: strun:test:chatrun:test:1\nevent: content_delta\ndata: {"content":"你好","event_offset":1}\n\n',
          'id: strun:test:chatrun:test:2\nevent: turn_completed\ndata: {"status":"completed","event_offset":2}\n\n',
        ],
        { cancel, openEnded: true },
      ),
    ]));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const result = await streamChat(
      { message: "你好", session_id: "session:fixed" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    expect(result).toEqual({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: "strun:test",
      eventLogId: "chatrun:test",
      lastEventOffset: 2,
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events.map((item) => item.event)).toEqual(["content_delta", "turn_completed"]);
  });

  it("parses CRLF-delimited SSE terminal events", async () => {
    vi.stubGlobal("window", {});
    const reader = streamReader(['id: strun:test:chatrun:test:1\r\nevent: turn_completed\r\ndata: {"status":"completed","event_offset":1}\r\n\r\n']);
    vi.stubGlobal("fetch", mockChatRunFetch([reader]));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const result = await streamChat(
      { message: "hi", session_id: "session:crlf" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.terminalStatus).toBe("completed");
    expect(reader.cancel).toHaveBeenCalledTimes(1);
    expect(events).toEqual([{ event: "turn_completed", data: { status: "completed", event_offset: 1 } }]);
  });

  it("can consume a short stream without replacing the session reconnect cursor", async () => {
    const storage = new Map<string, string>([[
      "chat.stream.cursor.session:steer",
      JSON.stringify({
        streamRunId: "strun:main",
        eventLogId: "chatrun:main",
        lastEventOffset: 8,
        lastEventId: "main:8",
      }),
    ]]);
    const localStorage = {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        storage.set(key, value);
      }),
      removeItem: vi.fn((key: string) => {
        storage.delete(key);
      }),
    };
    vi.stubGlobal("window", { localStorage });
    vi.stubGlobal("fetch", mockChatRunFetch([
      streamReader(['id: strun:test:chatrun:test:1\nevent: turn_completed\ndata: {"status":"completed","event_offset":1}\n\n']),
    ]));

    const result = await streamChat(
      { message: "补充要求", session_id: "session:steer", expected_active_turn_id: "turn:active" },
      { onEvent: () => undefined },
      { persistCursor: false },
    );

    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.terminalStatus).toBe("completed");
    expect(localStorage.setItem).not.toHaveBeenCalled();
    expect(localStorage.removeItem).not.toHaveBeenCalled();
    expect(storage.get("chat.stream.cursor.session:steer")).toContain("strun:main");
  });

  it("keeps reading after output_boundary until the backend sends done", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    vi.stubGlobal("fetch", mockChatRunFetch([
      streamReader(
        [
          'id: strun:test:chatrun:test:1\nevent: output_boundary\ndata: {"event_offset":1,"output":{"visible_text":"你好，我是四岳。","selected_channel":"answer_candidate","selected_source":"model_response"}}\n\n',
          'id: strun:test:chatrun:test:2\nevent: harness_loop_event\ndata: {"event_offset":2,"event":{"event_id":"rtevt:1","task_run_id":"taskrun:1","event_type":"agent_runtime_planning_phase_checked","payload":{"plan_coverage_review":{"passed":false}}}}\n\n',
          'id: strun:test:chatrun:test:3\nevent: turn_completed\ndata: {"event_offset":3,"status":"completed"}\n\n',
        ],
        { cancel, openEnded: true },
      ),
    ]));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:stable" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    const result = await pending;
    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.terminalStatus).toBe("completed");
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events.map((item) => item.event)).toEqual(["output_boundary", "harness_loop_event", "turn_completed"]);
  });

  it("reconnects from the last event offset when the stream closes without a terminal event", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    const fetch = mockChatRunFetch([
      streamReader(['id: strun:test:chatrun:test:1\nevent: content_delta\ndata: {"event_offset":1,"content":"你"}\n\n']),
      streamReader(['id: strun:test:chatrun:test:2\nevent: turn_completed\ndata: {"event_offset":2,"status":"completed"}\n\n']),
    ]);
    vi.stubGlobal("fetch", fetch);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:no-visible" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await vi.advanceTimersByTimeAsync(500);

    const result = await pending;
    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.terminalStatus).toBe("completed");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(String(fetch.mock.calls[2][0])).toContain("after_offset=1");
    expect(events.map((item) => item.event)).toEqual([
      "content_delta",
      "stream_reconnecting",
      "stream_reconnected",
      "turn_completed",
    ]);
    expect(events[1].data).toMatchObject({ attempt: 1, max_attempts: 5, event_offset: 1 });
  });

  it("reconnects after a transport error without replaying delivered offsets", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    let getCalls = 0;
    const doneReader = streamReader(['id: strun:test:chatrun:test:1\nevent: turn_completed\ndata: {"event_offset":1,"status":"completed"}\n\n']);
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const method = String(init?.method || "GET").toUpperCase();
      if (method === "POST" && String(url).endsWith("/chat/runs")) {
        return {
          ok: true,
          json: async () => ({
            stream_run_id: "strun:test",
            session_id: "session:test",
            event_log_id: "chatrun:test",
            root_request_ref: "chatreq:test",
            status: "running",
            latest_event_offset: -1,
            stream_url: "/api/chat/runs/strun:test/events",
          }),
        };
      }
      getCalls += 1;
      if (getCalls === 1) {
        throw new TypeError("network down");
      }
      return {
        ok: true,
        body: { getReader: () => doneReader },
      };
    });
    vi.stubGlobal("fetch", fetch);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "hi", session_id: "session:transport-error" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await vi.advanceTimersByTimeAsync(500);

    const result = await pending;
    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.terminalStatus).toBe("completed");
    expect(events.map((item) => item.event)).toEqual(["stream_reconnecting", "stream_reconnected", "turn_completed"]);
    expect(String(fetch.mock.calls[2][0])).toContain("after_offset=-1");
  });

  it("returns backend terminal events without frontend completion fields", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    vi.stubGlobal("fetch", mockChatRunFetch([
      streamReader(
        ['id: strun:test:chatrun:test:1\nevent: turn_completed\ndata: {"event_offset":1,"status":"failed","error_summary":"backend failed"}\n\n'],
        { cancel, openEnded: true },
      ),
    ]));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:backend-error" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    const result = await pending;

    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.terminalStatus).toBe("failed");
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events).toEqual([{ event: "turn_completed", data: { event_offset: 1, status: "failed", error_summary: "backend failed" } }]);
  });
});

function mockChatRunFetch(readers: Array<ReturnType<typeof streamReader>>) {
  let streamIndex = 0;
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = String(init?.method || "GET").toUpperCase();
    if (method === "POST" && String(url).endsWith("/chat/runs")) {
      return {
        ok: true,
        json: async () => ({
          stream_run_id: "strun:test",
          session_id: "session:test",
          event_log_id: "chatrun:test",
          root_request_ref: "chatreq:test",
          status: "running",
          latest_event_offset: -1,
          stream_url: "/api/chat/runs/strun:test/events",
        }),
      };
    }
    const reader = readers[streamIndex++];
    return {
      ok: true,
      body: { getReader: () => reader },
    };
  });
}

function streamReader(chunks: string[], options: { cancel?: () => Promise<void>; openEnded?: boolean } = {}) {
  const encoded = chunks.map((chunk) => new TextEncoder().encode(chunk));
  const read = vi.fn();
  for (const value of encoded) {
    read.mockResolvedValueOnce({ value, done: false });
  }
  if (options.openEnded) {
    read.mockImplementation(() => new Promise(() => undefined));
  } else {
    read.mockResolvedValue({ value: undefined, done: true });
  }
  return {
    read,
    cancel: options.cancel ?? vi.fn(async () => undefined),
  };
}

