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
      message: "Request timed out after 15000ms: /sessions",
    });
    await vi.advanceTimersByTimeAsync(15000);

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
    await vi.advanceTimersByTimeAsync(90000);

    await pending;
  });

  it("gives edit-resend session truncation enough time to commit", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));

    const path = "/sessions/session-0079aa9a75bc43ff/messages/truncate?workspace_view=chat";
    const pending = expect(apiRequest(path, { method: "POST", body: "{}" })).rejects.toMatchObject({
      name: "RequestTimeoutError",
      message: `Request timed out after 60000ms: ${path}`,
    });
    await vi.advanceTimersByTimeAsync(60000);

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

describe("streamChat over WebSocket live", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
  });

  it("consumes typed WebSocket events and acks rendered offsets", async () => {
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", mockChatFetch({ run: { latest_event_offset: 9 } }));
    vi.stubGlobal("WebSocket", MockWebSocket);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:fixed" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await waitForWebSocketCount(1);
    await Promise.resolve();
    const socket = MockWebSocket.instances[0];
    expect(socket.url).toBe("ws://127.0.0.1:8003/api/chat/sessions/session%3Afixed/live");
    expect(JSON.parse(socket.sent[0]).subscriptions[0].after_offset).toBe(-1);

    socket.emit(eventEnvelope("assistant_text_delta", 1, { content: "你好", sequence: 1 }));
    socket.emit(eventEnvelope("turn_completed", 2, { status: "completed" }, true));
    const result = await pending;

    expect(result).toEqual({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: "strun:test",
      eventLogId: "chatrun:test",
      lastEventOffset: 2,
    });
    expect(events.map((item) => item.event)).toEqual(["assistant_text_delta", "turn_completed"]);
    expect(events[0]?.data.diagnostics).toEqual(expect.objectContaining({
      client_received_at: expect.any(Number),
    }));
    expect(socket.sent.map((item) => JSON.parse(item).type)).toEqual(["subscribe", "ack", "ack"]);
    expect(JSON.parse(socket.sent[2]).last_event_offset).toBe(2);
  });

  it("uses HTTP replay to patch a closed WebSocket before reconnecting", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", mockChatFetch({
      replayEvents: [
        eventEnvelope("assistant_text_delta", 2, { content: "好", sequence: 2 }),
        eventEnvelope("turn_completed", 3, { status: "completed" }, true),
      ],
    }));
    vi.stubGlobal("WebSocket", MockWebSocket);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:reconnect" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await waitForWebSocketCount(1);
    MockWebSocket.instances[0].emit(eventEnvelope("assistant_text_delta", 1, { content: "你", sequence: 1 }));
    MockWebSocket.instances[0].failClose();
    for (let index = 0; index < 5; index += 1) {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(500);
    }
    const result = await pending;

    expect(result.terminalEvent).toBe("turn_completed");
    expect(result.lastEventOffset).toBe(3);
    expect(events.map((item) => item.event)).toEqual([
      "assistant_text_delta",
      "stream_reconnecting",
      "stream_reconnected",
      "assistant_text_delta",
      "turn_completed",
    ]);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/runs/strun%3Atest/events/replay?after_offset=1"),
      expect.any(Object),
    );
  });

  it("fails a live stream after bounded reconnect attempts", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", mockChatFetch());
    vi.stubGlobal("WebSocket", MockWebSocket);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:reconnect-fails" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    const reconnectDelays = [500, 1000, 2000, 4000, 8000, 16000];
    for (let index = 0; index < reconnectDelays.length; index += 1) {
      await waitForWebSocketCount(index + 1);
      await Promise.resolve();
      MockWebSocket.instances[index].failClose();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(reconnectDelays[index]);
    }
    await waitForWebSocketCount(7);
    await Promise.resolve();
    MockWebSocket.instances[6].failClose();
    await Promise.resolve();

    await expect(pending).rejects.toMatchObject({
      name: "ChatStreamProtocolError",
      message: "stream_reconnect_attempts_exhausted",
    });
    expect(events.at(-1)).toMatchObject({
      event: "stream_reconnect_failed",
      data: {
        attempt: 6,
        max_attempts: 6,
        reason: "stream_reconnect_attempts_exhausted",
      },
    });
  });

  it("runs a final HTTP replay before declaring reconnect exhaustion", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", mockChatFetch({
      replayEventsByCall: [
        [],
        [],
        [],
        [],
        [],
        [],
        [
          eventEnvelope("assistant_text_delta", 1, { content: "最终输出", sequence: 1 }),
          eventEnvelope("turn_completed", 2, { status: "completed" }, true),
        ],
      ],
    }));
    vi.stubGlobal("WebSocket", MockWebSocket);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:final-replay" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    const reconnectDelays = [500, 1000, 2000, 4000, 8000, 16000];
    for (let index = 0; index < reconnectDelays.length; index += 1) {
      await waitForWebSocketCount(index + 1);
      MockWebSocket.instances[index].failClose();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(reconnectDelays[index]);
    }
    await waitForWebSocketCount(7);
    MockWebSocket.instances[6].failClose();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(0);
    const result = await pending;

    expect(result).toEqual({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: "strun:test",
      eventLogId: "chatrun:test",
      lastEventOffset: 2,
    });
    expect(events.map((item) => item.event)).toContain("assistant_text_delta");
    expect(events.map((item) => item.event)).toContain("turn_completed");
    expect(events.map((item) => item.event)).not.toContain("stream_reconnect_failed");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/runs/strun%3Atest/events/replay?after_offset=-1"),
      expect.any(Object),
    );
  });

  it("treats final replay output as recovery progress before reconnect exhaustion fails", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", mockChatFetch({
      replayEventsByCall: [
        [],
        [],
        [],
        [],
        [],
        [],
        [
          eventEnvelope("assistant_text_delta", 1, { content: "掉线前已生成", sequence: 1 }),
        ],
        [
          eventEnvelope("turn_completed", 2, { status: "completed" }, true),
        ],
      ],
    }));
    vi.stubGlobal("WebSocket", MockWebSocket);
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:partial-final-replay" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    const reconnectDelays = [500, 1000, 2000, 4000, 8000, 16000];
    for (let index = 0; index < reconnectDelays.length; index += 1) {
      await waitForWebSocketCount(index + 1);
      MockWebSocket.instances[index].failClose();
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(reconnectDelays[index]);
    }
    await waitForWebSocketCount(7);
    MockWebSocket.instances[6].failClose();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(0);

    await waitForWebSocketCount(8);
    MockWebSocket.instances[7].failClose();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(500);
    const result = await pending;

    expect(result).toEqual({
      terminalEvent: "turn_completed",
      terminalStatus: "completed",
      streamRunId: "strun:test",
      eventLogId: "chatrun:test",
      lastEventOffset: 2,
    });
    expect(events.some((item) =>
      item.event === "assistant_text_delta" && item.data.content === "掉线前已生成"
    )).toBe(true);
    expect(events.map((item) => item.event)).toContain("turn_completed");
    expect(events.map((item) => item.event)).not.toContain("stream_reconnect_failed");
  });

  it("does not replace an existing reconnect cursor when persistCursor is false", async () => {
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
    vi.stubGlobal("fetch", mockChatFetch());
    vi.stubGlobal("WebSocket", MockWebSocket);

    const pending = streamChat(
      { message: "补充要求", session_id: "session:steer", expected_active_turn_id: "turn:active" },
      { onEvent: () => undefined },
      { persistCursor: false },
    );
    await waitForWebSocketCount(1);
    MockWebSocket.instances[0].emit(eventEnvelope("turn_completed", 1, { status: "completed" }, true));
    const result = await pending;

    expect(result.terminalEvent).toBe("turn_completed");
    expect(localStorage.setItem).not.toHaveBeenCalled();
    expect(localStorage.removeItem).not.toHaveBeenCalled();
    expect(storage.get("chat.stream.cursor.session:steer")).toContain("strun:main");
  });
});

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.();
    });
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    if (this.readyState === MockWebSocket.CLOSED) return;
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  emit(envelope: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(envelope) });
  }

  failClose() {
    this.close();
  }
}

async function waitForWebSocketCount(count: number) {
  for (let index = 0; index < 10; index += 1) {
    if (MockWebSocket.instances.length >= count) return;
    await Promise.resolve();
  }
  throw new Error(`Expected ${count} WebSocket connection(s).`);
}

function mockChatFetch(options: {
  replayEvents?: Record<string, unknown>[];
  replayEventsByCall?: Record<string, unknown>[][];
  run?: Record<string, unknown>;
} = {}) {
  let replayCallCount = 0;
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = String(init?.method || "GET").toUpperCase();
    if (method === "POST" && String(url).endsWith("/chat/runs")) {
      const body = JSON.parse(String(init?.body || "{}")) as { session_id?: string };
      const sessionId = String(body.session_id || "session:test");
      return jsonResponse({
        stream_run_id: "strun:test",
        session_id: sessionId,
        event_log_id: "chatrun:test",
        root_request_ref: "chatreq:test",
        status: "running",
        latest_event_offset: -1,
        replay_url: "/api/chat/runs/strun:test/events/replay",
        live_ws_url: `/api/chat/sessions/${encodeURIComponent(sessionId)}/live`,
        ...options.run,
      });
    }
    if (method === "GET" && String(url).includes("/events/replay")) {
      const replayEventsByCall = options.replayEventsByCall ?? [];
      const events = replayEventsByCall[replayCallCount] ?? options.replayEvents ?? [];
      replayCallCount += 1;
      return jsonResponse({
        stream_run_id: "strun:test",
        event_log_id: "chatrun:test",
        after_offset: 1,
        latest_event_offset: events.length ? Number(events[events.length - 1]?.event_offset ?? 1) : 1,
        terminal: events.some((event) => event.terminal === true),
        events,
        authority: "runtime.stream_replay",
      });
    }
    return jsonResponse({});
  });
}

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(payload),
  };
}

function eventEnvelope(event: string, offset: number, data: Record<string, unknown>, terminal = false) {
  return {
    type: "event",
    protocol: "agent-live.v1",
    stream_run_id: "strun:test",
    event_log_id: "chatrun:test",
    event_id: `strun:test:chatrun:test:${offset}`,
    event_offset: offset,
    public_event_type: event,
    terminal,
    data: {
      ...data,
      event_offset: offset,
      diagnostics: {
        server_event_created_at: 123,
        server_ws_sent_at: 124,
      },
    },
  };
}
