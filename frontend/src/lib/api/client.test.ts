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
});

describe("streamChat", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("finishes as soon as a terminal SSE event arrives", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const chunks = [
      new TextEncoder().encode('event: content_delta\ndata: {"content":"你好"}\n\n'),
      new TextEncoder().encode('event: done\ndata: {"content":"你好"}\n\n'),
    ];
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: chunks[0], done: false })
        .mockResolvedValueOnce({ value: chunks[1], done: false })
        .mockImplementation(() => new Promise(() => undefined)),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const result = await streamChat(
      { message: "你好", session_id: "session:fixed" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    expect(result).toEqual({ terminalEvent: "done" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(reader.read).toHaveBeenCalledTimes(2);
    expect(events.map((item) => item.event)).toEqual(["content_delta", "done"]);
  });

  it("parses CRLF-delimited SSE terminal events", async () => {
    vi.stubGlobal("window", {});
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({
          value: new TextEncoder().encode('event: done\r\ndata: {"content":"ok"}\r\n\r\n'),
          done: true,
        }),
      cancel: vi.fn(),
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const result = await streamChat(
      { message: "hi", session_id: "session:crlf" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    expect(result).toEqual({ terminalEvent: "done" });
    expect(reader.cancel).not.toHaveBeenCalled();
    expect(events).toEqual([{ event: "done", data: { content: "ok" } }]);
  });

  it("keeps reading after output_boundary until the backend sends done", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const chunks = [
      new TextEncoder().encode(
        'event: output_boundary\ndata: {"output":{"visible_text":"你好，我是四岳。","selected_channel":"answer_candidate","selected_source":"model_response"}}\n\n'
      ),
      new TextEncoder().encode(
        'event: harness_loop_event\ndata: {"event":{"event_id":"rtevt:1","task_run_id":"taskrun:1","event_type":"agent_runtime_planning_phase_checked","payload":{"plan_coverage_review":{"passed":false}}}}\n\n'
      ),
      new TextEncoder().encode('event: done\ndata: {"content":"完成"}\n\n'),
    ];
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: chunks[0], done: false })
        .mockResolvedValueOnce({ value: chunks[1], done: false })
        .mockResolvedValueOnce({ value: chunks[2], done: false })
        .mockImplementation(() => new Promise(() => undefined)),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:stable" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    const result = await pending;
    expect(result).toEqual({ terminalEvent: "done" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events.map((item) => item.event)).toEqual(["output_boundary", "harness_loop_event", "done"]);
  });

  it("rejects when the stream closes without a terminal event", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: new TextEncoder().encode('event: content_delta\ndata: {"content":"你好"}\n\n'), done: false })
        .mockResolvedValueOnce({ value: undefined, done: true }),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    await expect(streamChat(
      { message: "你好", session_id: "session:no-visible" },
      { onEvent: (event, data) => events.push({ event, data }) },
    )).rejects.toThrow("Chat stream ended without a terminal event.");
    expect(cancel).not.toHaveBeenCalled();
    expect(events.map((item) => item.event)).toEqual(["content_delta"]);
  });

  it("returns backend terminal events without frontend completion fields", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: new TextEncoder().encode('event: error\ndata: {"error":"backend failed"}\n\n'), done: false }),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:backend-error" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    const result = await pending;

    expect(result).toEqual({ terminalEvent: "error" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events).toEqual([{ event: "error", data: { error: "backend failed" } }]);
  });
});
